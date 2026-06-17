"""
File-based DMS key import for the /prepare "Datei-Upload" pane.

The user uploads a spreadsheet with document keys (Documenttype / Documentversion /
Documentpart / Documentnumber). Those keys are looked up in HANA ``DIL.DRAD`` using the
SAME per-DOKOB status-exclusion rules as the "DMS Objekte" load step
(:func:`app.routes_dms.load_dms_objects_stream`). The resulting object links are collected
and written to the shared ``userdata/dms_objects.db`` cache. The frontend then re-uses the
existing ``/api/dms/create-batch-stream`` endpoint to create the migration batch -- i.e.
"continue exactly where DMS Objekte continues once the keys are collected".

IMPORTANT
---------
This module *intentionally duplicates* the per-DOKOB DRAD query templates from
``routes_dms.py`` (only the WHERE filter differs: document keys instead of plant/WERK) so
that ``routes_dms.py`` and the protected "DMS Objekte" pane remain completely untouched.
If the status-exclusion rules in ``routes_dms.py`` ever change, mirror them here.
"""

import io
import os
import re
import json
import sqlite3

import pandas as pd
from flask import request, jsonify
from sqlalchemy import text

from app.blueprint import migrate_bp, allowed_file, df_to_json_safe


# ── Column-name resolution ────────────────────────────────────────────────────
# Maps a normalized (lower-case, stripped of separators) header to the canonical
# document-key part. Tolerant towards English/German variants.
_COLUMN_ALIASES = {
    'dokar': 'dokar', 'documenttype': 'dokar', 'doctype': 'dokar', 'type': 'dokar', 'typ': 'dokar',
    'dokvr': 'dokvr', 'documentversion': 'dokvr', 'docversion': 'dokvr', 'version': 'dokvr', 'ver': 'dokvr',
    'doktl': 'doktl', 'documentpart': 'doktl', 'docpart': 'doktl', 'part': 'doktl', 'teil': 'doktl',
    'doknr': 'doknr', 'documentnumber': 'doknr', 'docnumber': 'doknr', 'number': 'doknr',
    'nummer': 'doknr', 'quelldok': 'doknr', 'sourcedoc': 'doknr', 'sourcedocument': 'doknr',
}

# Embedded line breaks inside a single cell. Excel stores hard line breaks as the
# OOXML escape "_x000D_" (CR) / "_x000A_" (LF); CSV/openpyxl may also yield real \r\n.
# Such cells contain several keys mashed together, so we split them back apart.
_LINEBREAK_RE = re.compile(r'_x000[ad]_|\r\n|\r|\n', re.IGNORECASE)

# A full key embedded as a space-separated fragment, e.g. "IY1 02 000 Y_PM_DMS_000002"
# or "IY1 00 000 #2 AIR COMPRESSOR VESSEL" (the document number itself may contain spaces).
_SPACE_KEY_RE = re.compile(r'^(\S{1,4})\s+(\d{1,3})\s+(\d{1,3})\s+(.+)$')

# Sanity guard: SAP DRAD fields are short (DOKAR=3, DOKVR=2, DOKTL=3, DOKNR=25).
# Anything far beyond that is genuinely malformed input, not a real key.
_MAX_DOKNR_LEN = 50

# How many key tuples to send per DRAD query (keeps the generated SQL bounded).
_CHUNK_SIZE = 800

# Scalar subquery: does the document have a file in the Content Repository?
# (Identical to routes_dms.load_dms_objects_stream._has_file_sql.)
_HAS_FILE_SQL = """CASE WHEN EXISTS (
            SELECT 1 FROM DIL.DMS_DOC_FILES df
            WHERE df.DOKNR = drad.DOKNR AND df.DOKAR = drad.DOKAR
            AND df.DOKVR = drad.DOKVR AND df.DOKTL = drad.DOKTL
            AND df.MANDT = '100'
        ) THEN 1 ELSE 0 END as HAS_FILE"""


def _normalize_header(col):
    """Reduce a header to a comparable token (lower-case, no separators)."""
    return re.sub(r'[\s._\-]', '', str(col).strip().lower())


def _resolve_columns(df):
    """Return a {canonical_part: original_column} mapping for the uploaded sheet."""
    mapping = {}
    for col in df.columns:
        canonical = _COLUMN_ALIASES.get(_normalize_header(col))
        if canonical and canonical not in mapping:
            mapping[canonical] = col
    return mapping


def _norm_part(value, default='', zfill=0, numeric_only=False):
    """Normalize a single key part. Empty -> default; optionally zero-pad."""
    if value is None:
        s = ''
    else:
        s = str(value).strip()
    # pandas may read empty cells as the literal 'nan'
    if s.lower() == 'nan':
        s = ''
    if not s:
        s = default
    if zfill and s and (s.isdigit() or not numeric_only):
        if s.isdigit() and len(s) < zfill:
            s = s.zfill(zfill)
    return s


def _norm_doknr(value):
    """Normalize the document number. Pure-numeric internal numbers are zero-padded
    to 25 chars (SAP storage); external/alphanumeric numbers are kept as-is (upper)."""
    if value is None:
        return ''
    s = str(value).strip()
    if s.lower() == 'nan':
        return ''
    s = s.upper()
    if s.isdigit() and len(s) < 25:
        s = s.zfill(25)
    return s


def _make_key(dokar, dokvr, doktl, doknr):
    """Normalize the four parts into a key dict (or None if structurally unusable)."""
    dokar = _norm_part(dokar, default='').upper()
    dokvr = _norm_part(dokvr, default='00', zfill=2)
    doktl = _norm_part(doktl, default='000', zfill=3)
    doknr = _norm_doknr(doknr)
    if not dokar and not doknr:
        return None  # empty row
    display = f"{dokar}/{dokvr}/{doktl}/{doknr}"
    # Structurally invalid: missing type/number, or absurdly long (malformed cell).
    if not dokar or not doknr or len(doknr) > _MAX_DOKNR_LEN or len(dokar) > 4:
        return {'valid': False, 'display': display}
    return {'valid': True, 'dokar': dokar, 'dokvr': dokvr, 'doktl': doktl,
            'doknr': doknr, 'display': display}


def _parse_fragment(fragment, dokar, dokvr, doktl):
    """Interpret one line of a multi-line cell.

    A fragment may itself be a full key (``TYPE/VER/PART/NR`` or ``TYPE VER PART NR``);
    otherwise it is treated as a document number under the row's type/version/part.
    """
    frag = fragment.strip()
    if not frag:
        return None
    # Slash form: TYPE/VER/PART/NR
    if '/' in frag:
        bits = frag.split('/', 3)
        if len(bits) == 4 and bits[0].strip():
            return _make_key(bits[0], bits[1], bits[2], bits[3])
    # Space form: TYPE VER PART NR (number may contain spaces)
    m = _SPACE_KEY_RE.match(frag)
    if m:
        return _make_key(m.group(1), m.group(2), m.group(3), m.group(4))
    # Plain document number under the current row's type/version/part
    return _make_key(dokar, dokvr, doktl, frag)


def _build_key_queries(key_filter):
    """Per-DOKOB DRAD queries filtered by document keys (NOT by plant).

    ``key_filter`` is the SQL predicate, e.g.::

        (drad.DOKAR, drad.DOKVR, drad.DOKTL, drad.DOKNR) IN (('I71','00','000','...'), ...)

    Exclusion rules are identical to routes_dms.load_dms_objects_stream.
    """
    hf = _HAS_FILE_SQL
    return {
        'EQUI': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   equz.IWERK as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231'
            JOIN DIL.EQUI equi ON drad.OBJKY = equi.EQUNR
            WHERE drad.DOKOB = 'EQUI' AND {key_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j
                  WHERE j.OBJNR = equi.OBJNR
                  AND j.STAT IN ('I0320', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
        """,
        'IFLOT': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   iflot.IWERK as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR
            WHERE drad.DOKOB = 'IFLOT' AND {key_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j
                  WHERE j.OBJNR = iflot.OBJNR
                  AND j.STAT IN ('I0320', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
        """,
        'MPLA': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
            LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
            WHERE drad.DOKOB = 'MPLA' AND {key_filter}
        """,
        'PMPLKO': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   plko.WERKS as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.PLKO plko ON
                drad.OBJKY = plko.PLNTY || plko.PLNNR || plko.PLNAL
            WHERE drad.DOKOB = 'PMPLKO' AND {key_filter}
              AND (plko.LOEKZ IS NULL OR plko.LOEKZ = '')
        """,
        'PMAUFK': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   aufk.WERKS as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR
            WHERE drad.DOKOB = 'PMAUFK' AND {key_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j
                  WHERE j.OBJNR = aufk.OBJNR
                  AND j.STAT IN ('I0045', 'I0046', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
        """,
        'PMAFVC': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   afvc.WERKS as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.AFVC afvc ON
                SUBSTRING(drad.OBJKY, 3, 10) = afvc.AUFPL AND
                SUBSTRING(drad.OBJKY, 13, 8) = afvc.APLZL
            JOIN DIL.AFKO afko ON afvc.AUFPL = afko.AUFPL
            JOIN DIL.AUFK aufk ON afko.AUFNR = aufk.AUFNR
            WHERE drad.DOKOB = 'PMAFVC' AND {key_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j
                  WHERE j.OBJNR = aufk.OBJNR
                  AND j.STAT IN ('I0045', 'I0046', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
        """,
        'PMQMEL': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   qmih.IWERK as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
            JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
            WHERE drad.DOKOB = 'PMQMEL' AND {key_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j
                  WHERE j.OBJNR = qmel.OBJNR
                  AND j.STAT IN ('I0072', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
        """,
        'SMQMEL': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   qmih.IWERK as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
            JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
            WHERE drad.DOKOB = 'SMQMEL' AND {key_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j
                  WHERE j.OBJNR = qmel.OBJNR
                  AND j.STAT IN ('I0072', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
        """,
        'STKO_DOC': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   stko.WRKAN as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
            WHERE drad.DOKOB = 'STKO_DOC' AND {key_filter}
              AND (stko.LOEKZ IS NULL OR stko.LOEKZ = '')
        """,
        'STPO_DOC': f"""
            SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                   stko.WRKAN as WERK,
                   {hf}
            FROM DIL.DRAD drad
            JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX)
            JOIN DIL.STKO stko ON stpo.STLNR = stko.STLNR AND stpo.STLTY = stko.STLTY
            WHERE drad.DOKOB = 'STPO_DOC' AND {key_filter}
              AND (stpo.LKENZ IS NULL OR stpo.LKENZ = '')
        """,
    }


def _read_upload(file_storage):
    """Read the uploaded spreadsheet into a string DataFrame (preserves leading zeros)."""
    ext = file_storage.filename.rsplit('.', 1)[1].lower()
    raw = file_storage.read()
    if ext == 'csv':
        return pd.read_csv(io.BytesIO(raw), dtype=str, sep=None, engine='python')
    return pd.read_excel(io.BytesIO(raw), dtype=str)


def _parse_keys(df):
    """Turn the uploaded DataFrame into normalized key dicts.

    Returns ``(keys, invalid, error)``. Each key is
    ``{'dokar','dokvr','doktl','doknr','display'}``; ``display`` is the slash form.

    Document-number cells may contain several keys separated by hard line breaks
    (Excel ``_x000D_`` escapes or real newlines). Such cells are split: the first
    line is the row's own number, any further lines are parsed as additional keys.
    """
    colmap = _resolve_columns(df)
    missing = [p for p in ('dokar', 'doknr') if p not in colmap]
    if missing:
        return None, None, (
            "Pflichtspalten fehlen: Documenttype und Documentnumber. "
            "Bitte das bereitgestellte Template verwenden."
        )

    keys = []
    invalid = []
    seen = set()

    def _add(result):
        if result is None:
            return
        if not result.get('valid'):
            if result['display'] not in invalid:
                invalid.append(result['display'])
            return
        composite = (result['dokar'], result['dokvr'], result['doktl'], result['doknr'])
        if composite in seen:
            return
        seen.add(composite)
        keys.append({k: result[k] for k in ('dokar', 'dokvr', 'doktl', 'doknr', 'display')})

    for _, row in df.iterrows():
        dokar_raw = _norm_part(row.get(colmap['dokar']), default='').upper()
        dokvr_raw = _norm_part(row.get(colmap.get('dokvr')) if 'dokvr' in colmap else '', default='00', zfill=2)
        doktl_raw = _norm_part(row.get(colmap.get('doktl')) if 'doktl' in colmap else '', default='000', zfill=3)
        doknr_cell = row.get(colmap['doknr'])
        doknr_str = '' if doknr_cell is None else str(doknr_cell)

        # Split the document-number cell on any embedded line breaks.
        fragments = [f for f in _LINEBREAK_RE.split(doknr_str) if f and f.strip()]

        if not fragments:
            # No number at all - still record empty rows that carry a type (as invalid).
            if dokar_raw:
                _add(_make_key(dokar_raw, dokvr_raw, doktl_raw, ''))
            continue

        # First fragment = this row's own document number (uses the row's columns).
        _add(_make_key(dokar_raw, dokvr_raw, doktl_raw, fragments[0]))
        # Further fragments = additional keys mashed into the same cell.
        for extra in fragments[1:]:
            _add(_parse_fragment(extra, dokar_raw, dokvr_raw, doktl_raw))

    return keys, invalid, None


def _sql_tuple(key):
    """Build a single SQL tuple literal for a key.

    Values are wrapped as HANA string literals with single quotes doubled, which is
    the only escape character in standard-SQL/HANA literals -> safe against injection.
    """
    def esc(v):
        return v.replace("'", "''")
    return f"('{esc(key['dokar'])}', '{esc(key['dokvr'])}', '{esc(key['doktl'])}', '{esc(key['doknr'])}')"


@migrate_bp.route('/api/dms/import-keys', methods=['POST'])
def import_dms_keys():
    """Parse an uploaded DMS-key list, resolve object links via HANA DRAD (same
    exclusion rules as DMS Objekte) and write the result to ``userdata/dms_objects.db``.

    The frontend afterwards re-uses ``/api/dms/create-batch-stream``.
    """
    from app_config import DilEngine

    if 'file' not in request.files or not request.files['file'].filename:
        return jsonify({'success': False, 'error': 'Keine Datei hochgeladen'}), 400

    file = request.files['file']
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Ungültiger Dateityp (erlaubt: .xlsx, .xls, .csv)'}), 400

    # 1) Read + parse the uploaded keys
    try:
        df = _read_upload(file)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Datei konnte nicht gelesen werden: {e}'}), 400

    keys, invalid, err = _parse_keys(df)
    if err:
        return jsonify({'success': False, 'error': err}), 400
    if not keys:
        return jsonify({'success': False, 'error': 'Keine gültigen DMS-Keys in der Datei gefunden'}), 400

    # 2) Connect to HANA / DIL
    dil_db = DilEngine.load()
    if dil_db.engine is None:
        return jsonify({'success': False, 'error': 'DIL-Datenbank nicht verbunden'}), 503

    # 3) Run the per-DOKOB DRAD lookups (chunked) and collect all object links
    frames = []
    try:
        with dil_db.engine.begin() as con:
            for start in range(0, len(keys), _CHUNK_SIZE):
                chunk = keys[start:start + _CHUNK_SIZE]
                tuples_sql = ', '.join(_sql_tuple(k) for k in chunk)
                key_filter = f"(drad.DOKAR, drad.DOKVR, drad.DOKTL, drad.DOKNR) IN ({tuples_sql})"
                for dokob, query in _build_key_queries(key_filter).items():
                    try:
                        part = pd.read_sql(text(query), con)
                        if not part.empty:
                            part.columns = [c.lower() for c in part.columns]
                            frames.append(part)
                    except Exception as q_err:
                        print(f"[Key Import] {dokob} query failed: {q_err}")
    except Exception as e:
        return jsonify({'success': False, 'error': f'DRAD-Abfrage fehlgeschlagen: {e}'}), 500

    # 4) Combine + map HAS_FILE -> ablage, dedup per document, build object_links JSON
    dokob_summary = {}
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        if 'has_file' in combined.columns:
            combined['ablage'] = combined['has_file'].map({1: 'KPRO', 0: 'DB'}).fillna('DB')
            combined = combined.drop(columns=['has_file'])
        else:
            combined['ablage'] = 'KPRO'

        # per-DOKOB link counts (before dedup) for the UI summary
        if 'dokob' in combined.columns:
            dokob_summary = {str(k): int(v) for k, v in combined['dokob'].value_counts().items()}

        doc_key_cols = ['doknr', 'dokar', 'dokvr', 'doktl']

        def _doc_key(row):
            return (
                str(row.get('doknr', '') or ''),
                str(row.get('dokar', '') or ''),
                str(row.get('dokvr', '00') or '00'),
                str(row.get('doktl', '000') or '000'),
            )

        object_links_map = {}
        for _, row in combined.iterrows():
            k = _doc_key(row)
            object_links_map.setdefault(k, [])
            dokob, objky = row.get('dokob'), row.get('objky')
            if pd.notnull(dokob) and pd.notnull(objky):
                pair = (str(dokob).strip(), str(objky).strip())
                if pair not in object_links_map[k]:
                    object_links_map[k].append(pair)

        combined = combined.drop_duplicates(
            subset=[c for c in doc_key_cols if c in combined.columns], keep='first'
        ).copy()
        combined['object_links'] = combined.apply(
            lambda r: json.dumps([{'dokob': d, 'objky': o} for d, o in object_links_map.get(_doc_key(r), [])])
            if object_links_map.get(_doc_key(r)) else None, axis=1)
        combined['link_count'] = combined.apply(lambda r: len(object_links_map.get(_doc_key(r), [])), axis=1)

        found_keys = set(
            (str(r['dokar']), str(r['dokvr']), str(r['doktl']), str(r['doknr']))
            for _, r in combined.iterrows()
        )
        data_list = combined.to_dict(orient='records')
    else:
        found_keys = set()
        data_list = []

    # 5) Determine which uploaded keys produced no (surviving) DRAD link
    not_found = [
        k['display'] for k in keys
        if (k['dokar'], k['dokvr'], k['doktl'], k['doknr']) not in found_keys
    ]

    # 6) Persist to the shared SQLite cache (same table the create-batch-stream reads)
    saved = False
    try:
        os.makedirs('userdata', exist_ok=True)
        db_path = 'userdata/dms_objects.db'
        conn = sqlite3.connect(db_path)
        if data_list:
            pd.DataFrame(data_list).to_sql('dms_objects', conn, if_exists='replace', index=False)
        else:
            conn.execute("DROP TABLE IF EXISTS dms_objects")
            conn.commit()
        conn.close()
        saved = True
        print(f"[Key Import] Saved {len(data_list)} documents to {db_path}")
    except Exception as e:
        return jsonify({'success': False, 'error': f'Speichern fehlgeschlagen: {e}'}), 500

    return jsonify({
        'success': True,
        'uploaded_keys': len(keys),
        'found_documents': len(data_list),
        'total_links': sum(dokob_summary.values()),
        'dokob_summary': dokob_summary,
        'not_found_count': len(not_found),
        'not_found_keys': not_found[:2000],
        'invalid_count': len(invalid),
        'invalid_keys': invalid[:2000],
        'data': df_to_json_safe(combined) if data_list else [],
        'saved': saved,
    })
