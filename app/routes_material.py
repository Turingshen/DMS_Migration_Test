"""Routes for QM Material and TECH Material workflows."""

import re
import os
import threading
import requests
import time
from datetime import datetime
from flask import render_template, request, jsonify, session, Response
from sqlalchemy import text
from werkzeug.utils import secure_filename

from app_config import Config
from app.blueprint import (
    migrate_bp, misc_engine, get_template_context, UPLOAD_FOLDER,
    _is_authenticated, _build_session_snapshot,
)
from app.process import prepare_session_headers, is_csrf_error, force_csrf_renewal, MAX_DESC_LEN
from app.execute import _get_mime_type, _sanitize_slug
from app.logger import get_logger

logger = get_logger('qm_material')
cfg = Config.load()

# Background execution state for QM migration
_qm_bg_results = {}   # batch_id -> {status, done, failed, total, errors, ...}
_qm_bg_lock = threading.Lock()


# ── Column mapping: XLS field name → DB column ───────────────────────
QM_COLUMN_MAP = {
    'LineNumber': 'line_number',
    'Doc':        'doc',
    'Material':   'material',
    'Vendor':     'vendor',
    'CoCd':       'cocd',
    'Plnt':       'plnt',
    'Sloc':       'sloc',
    'B.Unit':     'bunit',
    'TradeName':  'trade_name',
    'Hand/Prod':  'hand_prod',
    'V/M/D/S':    'vmds',
    'Spec.Nr.':   'spec_nr',
    'Revision':   'revision',
    'Sp.Agr.Dt':  'sp_agr_dt',
    'Approv.Dt':  'approv_dt',
    'Q.Crit.Ind': 'q_crit_ind',
    'Q-Nr':       'q_nr',
    'FlagBGA':    'flag_bga',
    'FlagFDA':    'flag_fda',
    'Restr.Use':  'restr_use',
    'Archivnr.':  'archivnr',
    'Inactive':   'inactive',
    'ArchiveId':  'archive_id',
}

# Reverse map for quick lookup
_DB_TO_XLS = {v: k for k, v in QM_COLUMN_MAP.items()}


def _parse_sap_alv_xls(raw_bytes):
    """Parse SAP ALV binary export XLS format.

    Returns (columns, records) where records is a list of dicts.
    """
    data_start = raw_bytes.index(0x0d)
    header_bytes = raw_bytes[:data_start]

    field_defs = []
    for m in re.finditer(
        rb'([\x20-\x7e]{2,}?)\x00+([CN])\x00{4}([\x01-\xff])',
        header_bytes,
    ):
        name = m.group(1).decode('latin-1').strip()
        ftype = m.group(2).decode('latin-1')
        width = m.group(3)[0]
        field_defs.append((name, ftype, width))

    calc_width = sum(w for _, _, w in field_defs)
    record_width = calc_width + 1  # +1 padding byte

    data = raw_bytes[data_start + 1:]
    data = data.rstrip(b'\x1a')
    num_records = len(data) // record_width

    columns = [f[0] for f in field_defs]
    records = []
    for i in range(num_records):
        start = i * record_width
        rec_text = data[start + 1 : start + record_width].decode('latin-1')
        pos = 0
        row = {}
        for fname, _, fwidth in field_defs:
            row[fname] = rec_text[pos:pos + fwidth].strip()
            pos += fwidth
        records.append(row)

    return columns, records


# ── Page routes ──────────────────────────────────────────────────────

@migrate_bp.route('/qm-material')
def qm_material():
    """QM Material workflow page."""
    return render_template('qm_material.html', **get_template_context())


@migrate_bp.route('/tech-material')
def tech_material():
    """TECH Material workflow page."""
    return render_template('tech_material.html', **get_template_context())


# ── QM Material API ──────────────────────────────────────────────────

@migrate_bp.route('/api/qm-material/parse', methods=['POST'])
def qm_material_parse():
    """Parse uploaded XLS file and return columns + preview (no DB write yet)."""
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'Keine Datei hochgeladen'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'Leerer Dateiname'}), 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    safe_name = secure_filename(f.filename)
    filepath = os.path.join(UPLOAD_FOLDER, safe_name)
    f.save(filepath)

    try:
        with open(filepath, 'rb') as fh:
            raw = fh.read()

        columns, records = _parse_sap_alv_xls(raw)

        # Preview: first 50 rows
        preview = []
        for rec in records[:50]:
            row = {}
            for c in columns:
                row[c] = rec.get(c, '')
            preview.append(row)

        return jsonify({
            'ok': True,
            'filename': safe_name,
            'columns': columns,
            'preview': preview,
            'total': len(records),
        })

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@migrate_bp.route('/api/qm-material/save', methods=['POST'])
def qm_material_save():
    """Save parsed data to staging table with user-selected columns."""
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'Kein JSON-Body'}), 400

    filename = body.get('filename')
    selected_columns = body.get('columns', [])

    if not filename:
        return jsonify({'ok': False, 'error': 'Dateiname fehlt'}), 400
    if not selected_columns:
        return jsonify({'ok': False, 'error': 'Keine Spalten ausgewählt'}), 400

    # Validate selected columns against known mapping
    valid_xls_cols = set(QM_COLUMN_MAP.keys())
    selected_columns = [c for c in selected_columns if c in valid_xls_cols]
    if not selected_columns:
        return jsonify({'ok': False, 'error': 'Keine gültigen Spalten ausgewählt'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(filename))
    if not os.path.isfile(filepath):
        return jsonify({'ok': False, 'error': 'Datei nicht gefunden'}), 404

    try:
        with open(filepath, 'rb') as fh:
            raw = fh.read()

        columns, records = _parse_sap_alv_xls(raw)

        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        batch_id = f'QM_{ts}'
        created_by = session.get('au_name', 'unknown')

        # Build INSERT with only selected columns + target columns
        db_cols = [QM_COLUMN_MAP[c] for c in selected_columns]
        all_insert_cols = db_cols + ['target_dokar', 'target_dokvr', 'target_doktl', 'target_description']
        placeholders = ', '.join(f':{c}' for c in all_insert_cols)
        col_names = ', '.join(all_insert_cols)
        insert_sql = text(f"""
            INSERT INTO dbo.qm_material_staging
                (batch_id, created_by, {col_names})
            VALUES
                (:batch_id, :created_by, {placeholders})
        """)

        def _build_target_description(rec):
            """Material-Vendor-CoCd-Plnt-Sloc with leading zeros stripped from Material & Vendor."""
            mat = rec.get('Material', '').strip().lstrip('0') or '0'
            ven = rec.get('Vendor', '').strip().lstrip('0') or '0'
            cocd = rec.get('CoCd', '').strip()
            plnt = rec.get('Plnt', '').strip()
            sloc = rec.get('Sloc', '').strip()
            return '-'.join([mat, ven, cocd, plnt, sloc])

        inserted = 0
        with misc_engine.begin() as con:
            for rec in records:
                params = {'batch_id': batch_id, 'created_by': created_by}
                for xls_col in selected_columns:
                    db_col = QM_COLUMN_MAP[xls_col]
                    val = rec.get(xls_col, '').strip()
                    params[db_col] = val if val else None
                params['target_dokar'] = 'Q01'
                params['target_dokvr'] = '00'
                params['target_doktl'] = '000'
                params['target_description'] = _build_target_description(rec)
                con.execute(insert_sql, params)
                inserted += 1

        # Return preview with selected columns + target columns
        preview = []
        for rec in records[:200]:
            row = {}
            for c in selected_columns:
                row[c] = rec.get(c, '')
            row['Ziel DOKAR'] = 'Q01'
            row['Ziel DOKVR'] = '00'
            row['Ziel DOKTL'] = '000'
            row['Ziel Beschreibung'] = _build_target_description(rec)
            preview.append(row)

        return jsonify({
            'ok': True,
            'batch_id': batch_id,
            'columns': selected_columns + ['Ziel DOKAR', 'Ziel DOKVR', 'Ziel DOKTL', 'Ziel Beschreibung'],
            'data': preview,
            'total': len(records),
            'inserted': inserted,
        })

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@migrate_bp.route('/api/qm-material/batches', methods=['GET'])
def qm_material_batches():
    """List QM material staging batches."""
    with misc_engine.connect() as con:
        rows = con.execute(text("""
            SELECT batch_id,
                   MIN(created_at) as created_at,
                   MAX(created_by) as created_by,
                   COUNT(*) as total,
                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                   COUNT(DISTINCT material) as materials,
                   COUNT(DISTINCT vendor) as vendors,
                   COUNT(DISTINCT plnt) as plants
            FROM dbo.qm_material_staging
            GROUP BY batch_id
            ORDER BY MIN(created_at) DESC
        """)).fetchall()

    batches = []
    for r in rows:
        batches.append({
            'batch_id': r.batch_id,
            'created_at': r.created_at.isoformat() if r.created_at else None,
            'created_by': r.created_by,
            'total': r.total,
            'pending': r.pending,
            'done': r.done,
            'errors': r.errors,
            'materials': r.materials,
            'vendors': r.vendors,
            'plants': r.plants,
        })
    return jsonify({'ok': True, 'batches': batches})


@migrate_bp.route('/api/qm-material/data/<batch_id>', methods=['GET'])
def qm_material_data(batch_id):
    """Get staging data for a QM material batch (paginated)."""
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(2000, max(10, int(request.args.get('per_page', 500))))
    offset = (page - 1) * per_page

    columns = [
        'id', 'line_number', 'doc', 'source_file', 'material', 'vendor', 'cocd', 'plnt', 'sloc',
        'trade_name', 'hand_prod', 'vmds', 'spec_nr', 'revision',
        'sp_agr_dt', 'approv_dt', 'archivnr', 'target_dokar', 'target_dokvr', 'target_doktl',
        'target_description', 'target_doknr', 'file_uploaded',
        'qinf_material', 'qinf_zaehl',
        'status', 'error_message',
    ]

    with misc_engine.connect() as con:
        total = con.execute(text(
            "SELECT COUNT(*) FROM dbo.qm_material_staging WHERE batch_id = :bid"
        ), {'bid': batch_id}).scalar()

        rows = con.execute(text("""
            SELECT * FROM dbo.qm_material_staging
            WHERE batch_id = :bid
            ORDER BY line_number
            OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
        """), {'bid': batch_id, 'off': offset, 'lim': per_page}).fetchall()

    data = []
    for r in rows:
        row = {}
        for c in columns:
            val = getattr(r, c, None)
            row[c] = str(val) if val is not None else ''
        data.append(row)

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    return jsonify({
        'ok': True, 'columns': columns, 'data': data,
        'total': total, 'page': page, 'per_page': per_page, 'total_pages': total_pages,
    })


# ── QM Material File Scan ──────────────────────────────────────────

@migrate_bp.route('/api/qm-material/scan-files', methods=['POST'])
def qm_material_scan_files():
    """Scan a local directory and match files to staging records via description prefix.

    Files are named like Material-Vendor-CoCd-Plnt-Sloc-.... The first 5
    dash-separated parts form the same key as target_description.

    Body: { batch_id, dir_path }
    Returns matched count and updates a file_path column if present,
    or just returns the match summary.
    """
    body = request.get_json(silent=True) or {}
    batch_id = body.get('batch_id', '').strip()
    dir_path = body.get('dir_path', '').strip()

    if not batch_id:
        return jsonify({'ok': False, 'error': 'batch_id fehlt'}), 400
    if not dir_path:
        return jsonify({'ok': False, 'error': 'dir_path fehlt'}), 400

    # Validate path exists and is a directory
    norm_path = os.path.normpath(dir_path)
    if not os.path.isdir(norm_path):
        return jsonify({'ok': False, 'error': f'Verzeichnis nicht gefunden: {dir_path}'}), 400

    # Build lookup: prefix -> list of filenames
    file_map = {}  # "mat-ven-cocd-plnt-sloc" -> [filename, ...]
    try:
        for fname in os.listdir(norm_path):
            fpath = os.path.join(norm_path, fname)
            if not os.path.isfile(fpath):
                continue
            parts = fname.split('-', 5)
            if len(parts) >= 5:
                prefix = '-'.join(parts[:5])
                file_map.setdefault(prefix, []).append(fname)
    except PermissionError:
        return jsonify({'ok': False, 'error': 'Zugriff verweigert auf ' + dir_path}), 403

    # Load staging descriptions for this batch
    with misc_engine.connect() as con:
        rows = con.execute(text("""
            SELECT id, target_description FROM dbo.qm_material_staging
            WHERE batch_id = :bid
        """), {'bid': batch_id}).fetchall()

    matched = 0
    unmatched = 0
    matches = []
    for r in rows:
        desc = (r.target_description or '').strip()
        flist = file_map.get(desc, [])
        if flist:
            matched += 1
            matches.append({'id': r.id, 'description': desc, 'files': flist})
        else:
            unmatched += 1

    # Write first matching filename into source_file column
    with misc_engine.begin() as con:
        for r in rows:
            desc = (r.target_description or '').strip()
            flist = file_map.get(desc, [])
            fname = flist[0] if flist else None
            con.execute(text("""
                UPDATE dbo.qm_material_staging
                SET source_file = :sf
                WHERE id = :rid
            """), {'sf': fname, 'rid': r.id})

    return jsonify({
        'ok': True,
        'dir_path': dir_path,
        'total_files': sum(len(v) for v in file_map.values()),
        'total_records': len(rows),
        'matched': matched,
        'unmatched': unmatched,
        'matches': matches[:200],  # cap preview
    })


# ── QM Material Execution ───────────────────────────────────────────

@migrate_bp.route('/api/qm-material/execute', methods=['POST'])
def qm_material_execute():
    """Execute QM material migration: create Q01 document containers in ZVF.

    Accepts JSON body with:
      - batch_id (str): the staging batch
      - record_ids (list[int], optional): specific record IDs to migrate; if omitted, all pending
      - dir_path (str, optional): directory containing source files to upload
    """
    if not _is_authenticated():
        return jsonify({'ok': False, 'error': 'Nicht authentifiziert. Bitte zuerst anmelden.'}), 401

    body = request.get_json(silent=True) or {}
    batch_id = body.get('batch_id')
    record_ids = body.get('record_ids')  # optional list of staging IDs
    dir_path = body.get('dir_path', '').strip()  # optional file directory

    if not batch_id:
        return jsonify({'ok': False, 'error': 'batch_id fehlt'}), 400

    # Validate dir_path if provided
    if dir_path:
        norm_path = os.path.normpath(dir_path)
        if not os.path.isdir(norm_path):
            return jsonify({'ok': False, 'error': f'Verzeichnis nicht gefunden: {dir_path}'}), 400
        dir_path = norm_path

    # Check not already running
    with _qm_bg_lock:
        prev = _qm_bg_results.get(batch_id, {})
        if prev.get('status') == 'running':
            return jsonify({'ok': False, 'error': 'Migration läuft bereits für diesen Batch'}), 409

    snapshot = _build_session_snapshot()

    # Start background thread
    t = threading.Thread(
        target=_qm_execute_background,
        args=(batch_id, snapshot, record_ids, dir_path),
        daemon=True,
    )
    t.start()

    return jsonify({'ok': True, 'message': 'Migration gestartet', 'batch_id': batch_id})


@migrate_bp.route('/api/qm-material/execute/progress/<batch_id>', methods=['GET'])
def qm_material_progress(batch_id):
    """Poll execution progress for QM material batch."""
    with _qm_bg_lock:
        result = _qm_bg_results.get(batch_id)
    if not result:
        return jsonify({'ok': False, 'error': 'Keine laufende Migration für diesen Batch'}), 404
    return jsonify({'ok': True, **result})


def _qm_execute_background(batch_id, session_snapshot, record_ids=None, dir_path=''):
    """Background worker: create Q01 containers and optionally upload files."""
    target_system = session_snapshot.get('target_system', 'zvfr3')

    # Init progress
    with _qm_bg_lock:
        _qm_bg_results[batch_id] = {
            'status': 'running', 'total': 0, 'done': 0, 'failed': 0,
            'current': 0, 'errors': [],
        }

    try:
        # Load records to process
        with misc_engine.connect() as con:
            if record_ids:
                placeholders = ','.join(str(int(rid)) for rid in record_ids)
                rows = con.execute(text(f"""
                    SELECT id, target_dokar, target_dokvr, target_doktl, target_description,
                           target_doknr, source_file, material, vendor, cocd, plnt, sloc, status,
                           qinf_material, qinf_zaehl
                    FROM dbo.qm_material_staging
                    WHERE batch_id = :bid AND id IN ({placeholders})
                    ORDER BY id
                """), {'bid': batch_id}).fetchall()
            else:
                # Include 'done' records that have a source_file but need upload (when dir_path given)
                # Also include 'error' records where container was created but upload failed
                if dir_path:
                    rows = con.execute(text("""
                        SELECT id, target_dokar, target_dokvr, target_doktl, target_description,
                               target_doknr, source_file, material, vendor, cocd, plnt, sloc, status,
                               ISNULL(file_uploaded, 0) AS file_uploaded,
                               qinf_material, qinf_zaehl
                        FROM dbo.qm_material_staging
                        WHERE batch_id = :bid AND (
                            status = 'pending'
                            OR (status = 'done' AND source_file IS NOT NULL AND ISNULL(file_uploaded, 0) = 0)
                            OR (status = 'error' AND target_doknr IS NOT NULL AND target_doknr <> '' AND source_file IS NOT NULL AND ISNULL(file_uploaded, 0) = 0)
                        )
                        ORDER BY id
                    """), {'bid': batch_id}).fetchall()
                else:
                    rows = con.execute(text("""
                        SELECT id, target_dokar, target_dokvr, target_doktl, target_description,
                               target_doknr, source_file, material, vendor, cocd, plnt, sloc, status,
                               qinf_material, qinf_zaehl
                        FROM dbo.qm_material_staging
                        WHERE batch_id = :bid AND (
                            status = 'pending'
                            OR (status = 'error' AND target_doknr IS NOT NULL AND target_doknr <> '')
                        )
                        ORDER BY id
                    """), {'bid': batch_id}).fetchall()

        total = len(rows)
        logger.info(f"[QM_EXEC] Batch {batch_id}: {total} records to process, dir_path='{dir_path}'", category="QM_EXEC")
        with _qm_bg_lock:
            _qm_bg_results[batch_id]['total'] = total

        if total == 0:
            with _qm_bg_lock:
                _qm_bg_results[batch_id]['status'] = 'completed'
            return

        # Prepare SAP session
        server_session = requests.Session()
        prepare_session_headers(server_session, session_snapshot, target_system)
        doc_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
        create_url = f"{doc_base_url}/A_DocumentInfoRecord"

        done_count = 0
        fail_count = 0

        for rec in rows:
            rec_id = rec.id
            description = (rec.target_description or '').strip()
            if not description:
                description = f"{rec.material}-{rec.vendor}-{rec.cocd}"
            if len(description) > MAX_DESC_LEN:
                description = description[:MAX_DESC_LEN]

            existing_doknr = (rec.target_doknr or '').strip()
            source_file = (rec.source_file or '').strip()
            doc_version = rec.target_dokvr or '00'
            doc_part = rec.target_doktl or '000'
            rec_status = (rec.status or '').strip()

            logger.info(f"[QM_EXEC] Record {rec_id}: doknr='{existing_doknr}', source_file='{source_file}', status='{rec_status}', dir_path='{dir_path}'", category="QM_EXEC")

            try:
                # ── Step A: Create container if needed ──────────────────
                if existing_doknr:
                    target_doknr = existing_doknr
                    logger.info(f"[QM_EXEC] Record {rec_id}: container exists ({target_doknr}), skipping create", category="QM_EXEC")
                else:
                    payload = {
                        'DocumentInfoRecordDocType': 'Q01',
                        'DocumentInfoRecordDocVersion': doc_version,
                        'DocumentInfoRecordDocPart': doc_part,
                        'to_DocDesc': [
                            {'Language': 'DE', 'DocumentDescription': description},
                            {'Language': 'EN', 'DocumentDescription': description},
                        ]
                    }

                    # Add QINF object link via Deep Insert if mapping exists
                    qinf_mat = (getattr(rec, 'qinf_material', None) or '').strip()
                    qinf_z = (getattr(rec, 'qinf_zaehl', None) or '').strip()
                    if qinf_mat and qinf_z:
                        objky = qinf_mat.zfill(18) + ' ' * 22 + qinf_z.zfill(6)
                        payload['to_ProductObj'] = [{
                            'LinkedSAPObject': 'QINF',
                            'LinkedSAPObjectKey': objky,
                            'DocObjectLinkCounter': '001',
                        }]
                        logger.info(f"[QM_EXEC] Record {rec_id}: QINF link → OBJKY='{objky}'", category="QM_EXEC")

                    server_session.headers.update({'Content-Type': 'application/json'})
                    resp = server_session.post(create_url, json=payload, timeout=30)

                    # CSRF retry
                    if is_csrf_error(resp):
                        logger.warning(f"CSRF expired for record {rec_id}, refreshing", category="QM_CREATE")
                        force_csrf_renewal(session_snapshot, target_system)
                        prepare_session_headers(server_session, session_snapshot, target_system)
                        server_session.headers.update({'Content-Type': 'application/json'})
                        resp = server_session.post(create_url, json=payload, timeout=30)

                    # Fallback: if QINF link fails (26/285 = only one doc link allowed),
                    # retry without the QINF link so the container is still created
                    if resp.status_code == 400 and 'to_ProductObj' in payload:
                        try:
                            err_body = resp.json()
                            err_code = err_body.get('error', {}).get('code', '')
                        except Exception:
                            err_code = ''
                        if '26/285' in err_code or 'nur eine Dokumentverknüpfung' in resp.text:
                            logger.warning(f"[QM_EXEC] Record {rec_id}: QINF already linked, retrying without QINF link", category="QM_CREATE")
                            payload_no_qinf = {k: v for k, v in payload.items() if k != 'to_ProductObj'}
                            server_session.headers.update({'Content-Type': 'application/json'})
                            resp = server_session.post(create_url, json=payload_no_qinf, timeout=30)
                            if is_csrf_error(resp):
                                force_csrf_renewal(session_snapshot, target_system)
                                prepare_session_headers(server_session, session_snapshot, target_system)
                                server_session.headers.update({'Content-Type': 'application/json'})
                                resp = server_session.post(create_url, json=payload_no_qinf, timeout=30)

                    if resp.status_code not in (200, 201):
                        err_text = resp.text[:500] if resp.text else resp.reason
                        raise RuntimeError(f"Container-Erstellung HTTP {resp.status_code}: {err_text}")

                    try:
                        rdata = resp.json()
                        target_doknr = rdata.get('d', {}).get('DocumentInfoRecordDocNumber', '')
                    except Exception:
                        target_doknr = ''

                # ── Step B: Upload file if available ───────────────────
                # IMPORTANT: Use the SAME server_session for upload (not _upload_one_file).
                # SAP requires the same session (cookies/CSRF) from container creation.
                upload_ok = True
                upload_err = ''
                if source_file and dir_path:
                    fpath = os.path.join(dir_path, source_file)
                    logger.info(f"[QM_EXEC] Record {rec_id}: uploading '{source_file}' to {target_doknr}, path='{fpath}'", category="QM_UPLOAD")
                    if os.path.isfile(fpath):
                        with open(fpath, 'rb') as fh:
                            file_data = fh.read()
                        mime_type = _get_mime_type(source_file)
                        slug_filename = _sanitize_slug(source_file)

                        try:
                            attachment_base_url = cfg.get(target_system, 'api_list', 'attachment', 'base_url')
                        except Exception:
                            attachment_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')

                        attachment_url = (
                            f"{attachment_base_url}/A_DocumentInfoRecordAttch"
                            f"(DocumentInfoRecordDocType='Q01',"
                            f"DocumentInfoRecordDocNumber='{target_doknr}',"
                            f"DocumentInfoRecordDocVersion='{doc_version}',"
                            f"DocumentInfoRecordDocPart='{doc_part}'"
                            f")/DocumentInfoRecordToAttachmentNavigation"
                        )

                        server_session.headers.update({'Content-Type': mime_type, 'Slug': slug_filename})
                        file_size_mb = len(file_data) / 1024 / 1024
                        upload_timeout = max(60, 60 + int(file_size_mb * 10))

                        logger.info(f"[QM_EXEC] Record {rec_id}: POST {attachment_url}", category="QM_UPLOAD")
                        upload_resp = server_session.post(attachment_url, data=file_data, timeout=upload_timeout)

                        # CSRF retry
                        if is_csrf_error(upload_resp):
                            logger.warning(f"[QM_EXEC] Record {rec_id}: CSRF expired, refreshing", category="QM_UPLOAD")
                            force_csrf_renewal(session_snapshot, target_system)
                            prepare_session_headers(server_session, session_snapshot, target_system)
                            server_session.headers.update({'Content-Type': mime_type, 'Slug': slug_filename})
                            upload_resp = server_session.post(attachment_url, data=file_data, timeout=upload_timeout)

                        if upload_resp.status_code in (200, 201):
                            logger.info(f"[QM_EXEC] Record {rec_id}: upload OK (HTTP {upload_resp.status_code})", category="QM_UPLOAD")
                        else:
                            upload_ok = False
                            upload_err = f" | Upload HTTP {upload_resp.status_code}: {upload_resp.text[:300]}"
                            logger.error(f"[QM_EXEC] Record {rec_id}: upload FAILED: {upload_err}", category="QM_UPLOAD")

                        # Restore Content-Type to JSON for next container creation
                        server_session.headers.update({'Content-Type': 'application/json'})
                        server_session.headers.pop('Slug', None)
                    else:
                        upload_ok = False
                        upload_err = f" | Datei nicht gefunden: {fpath}"
                        logger.warning(f"[QM_EXEC] Record {rec_id}: file not found at {fpath}", category="QM_UPLOAD")
                elif source_file and not dir_path:
                    logger.info(f"[QM_EXEC] Record {rec_id}: source_file='{source_file}' but no dir_path provided, skipping upload", category="QM_UPLOAD")

                # ── Step C: Update DB ──────────────────────────────────
                # Determine file_uploaded flag
                file_uploaded = 1 if (upload_ok and source_file and dir_path) else 0

                if upload_ok:
                    with misc_engine.begin() as con:
                        con.execute(text("""
                            UPDATE dbo.qm_material_staging
                            SET status = 'done',
                                target_doknr = :doknr,
                                file_uploaded = :fu,
                                error_message = NULL,
                                migrated_at = GETUTCDATE()
                            WHERE id = :rid
                        """), {'doknr': target_doknr, 'fu': file_uploaded, 'rid': rec_id})
                    done_count += 1
                else:
                    err_msg = f"Container {target_doknr} erstellt{upload_err}"
                    with misc_engine.begin() as con:
                        con.execute(text("""
                            UPDATE dbo.qm_material_staging
                            SET status = 'error',
                                target_doknr = :doknr,
                                file_uploaded = 0,
                                error_message = :err,
                                migrated_at = GETUTCDATE()
                            WHERE id = :rid
                        """), {'doknr': target_doknr, 'err': err_msg, 'rid': rec_id})
                    fail_count += 1
                    with _qm_bg_lock:
                        _qm_bg_results[batch_id]['errors'].append({
                            'id': rec_id, 'error': err_msg[:200]
                        })

            except Exception as e:
                err_msg = str(e)[:500]
                with misc_engine.begin() as con:
                    con.execute(text("""
                        UPDATE dbo.qm_material_staging
                        SET status = 'error',
                            error_message = :err,
                            migrated_at = GETUTCDATE()
                        WHERE id = :rid
                    """), {'err': err_msg, 'rid': rec_id})
                fail_count += 1
                with _qm_bg_lock:
                    _qm_bg_results[batch_id]['errors'].append({
                        'id': rec_id, 'error': err_msg[:200]
                    })

            # Update progress
            with _qm_bg_lock:
                _qm_bg_results[batch_id].update({
                    'current': done_count + fail_count,
                    'done': done_count,
                    'failed': fail_count,
                })

        # Done
        with _qm_bg_lock:
            _qm_bg_results[batch_id]['status'] = 'completed'

    except Exception as e:
        with _qm_bg_lock:
            _qm_bg_results[batch_id].update({
                'status': 'error',
                'errors': [{'id': 0, 'error': str(e)[:500]}],
            })


# ── QINF Mapping (Excel download / upload) ──────────────────────────

@migrate_bp.route('/api/qm-material/qinf-mapping/download/<batch_id>', methods=['GET'])
def qinf_mapping_download(batch_id):
    """Download QINF mapping template as Excel for a QM material batch.

    Columns: id, material, vendor, cocd, plnt, sloc, qinf_material, qinf_zaehl
    """
    import pandas as pd
    from io import BytesIO

    with misc_engine.connect() as con:
        df = pd.read_sql(text("""
            SELECT id, material, vendor, cocd, plnt, sloc,
                   ISNULL(qinf_material, '') AS qinf_material,
                   ISNULL(qinf_zaehl, '') AS qinf_zaehl
            FROM dbo.qm_material_staging
            WHERE batch_id = :bid
            ORDER BY id
        """), con, params={'bid': batch_id})

    if df.empty:
        return jsonify({'ok': False, 'error': 'Keine Daten für diesen Batch'}), 404

    # Rename columns for the Excel template
    df.rename(columns={
        'id': 'ID',
        'material': 'Material',
        'vendor': 'Vendor',
        'cocd': 'CoCd',
        'plnt': 'Plnt',
        'sloc': 'SLoc',
        'qinf_material': 'Map to Material',
        'qinf_zaehl': 'Zähler',
    }, inplace=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='QINF Mapping', index=False)

        # Auto-width columns
        ws = writer.sheets['QINF Mapping']
        for col_cells in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col_cells) + 2
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len, 30)

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename=QINF_Mapping_{batch_id}.xlsx'},
    )


@migrate_bp.route('/api/qm-material/qinf-mapping/upload/<batch_id>', methods=['POST'])
def qinf_mapping_upload(batch_id):
    """Upload QINF mapping Excel and update staging table.

    Expects columns: ID, Map to Material, Zähler
    """
    import pandas as pd

    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'Keine Datei hochgeladen'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'Leerer Dateiname'}), 400

    try:
        df = pd.read_excel(f, sheet_name=0, dtype=str)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Excel-Fehler: {e}'}), 400

    # Normalise column names
    col_map = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl == 'id':
            col_map[c] = 'id'
        elif cl in ('map to material', 'qinf_material', 'material_map'):
            col_map[c] = 'qinf_material'
        elif cl in ('zähler', 'zaehler', 'zaehl', 'qinf_zaehl', 'counter'):
            col_map[c] = 'qinf_zaehl'
    df.rename(columns=col_map, inplace=True)

    if 'id' not in df.columns:
        return jsonify({'ok': False, 'error': 'Spalte "ID" fehlt in der Datei'}), 400

    updated = 0
    skipped = 0
    with misc_engine.begin() as con:
        for _, row in df.iterrows():
            rid = str(row.get('id', '')).strip()
            if not rid or not rid.isdigit():
                skipped += 1
                continue

            mat = str(row.get('qinf_material', '') or '').strip()
            zaehl = str(row.get('qinf_zaehl', '') or '').strip()

            if not mat and not zaehl:
                skipped += 1
                continue

            # Pad zaehl to 6 digits if numeric
            if zaehl and zaehl.isdigit():
                zaehl = zaehl.zfill(6)

            con.execute(text("""
                UPDATE dbo.qm_material_staging
                SET qinf_material = :mat, qinf_zaehl = :zaehl
                WHERE id = :rid AND batch_id = :bid
            """), {'mat': mat or None, 'zaehl': zaehl or None, 'rid': int(rid), 'bid': batch_id})
            updated += 1

    return jsonify({
        'ok': True,
        'updated': updated,
        'skipped': skipped,
        'message': f'{updated} Zuordnungen aktualisiert, {skipped} übersprungen',
    })


# ═══════════════════════════════════════════════════════════════════════
# TECH Material API — Excel Upload → DIL Enrichment → Staging
# ═══════════════════════════════════════════════════════════════════════

TECH_EXPECTED_COLS = ['DOKAR', 'DOKNR', 'DOKVR', 'DOKTL', 'DOKOB', 'OBZAE', 'OBJKY']

tech_logger = get_logger('tech_material')


@migrate_bp.route('/api/tech-material/upload', methods=['POST'])
def tech_material_upload():
    """Upload Excel/CSV with TECH material document list.

    Expected columns: DOKAR, DOKNR, DOKVR, DOKTL, DOKOB, OBZAE, OBJKY.
    Saves to staging, then enriches from DIL in a second step.
    """
    import pandas as pd

    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'Keine Datei hochgeladen'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'Leerer Dateiname'}), 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    safe_name = secure_filename(f.filename)
    filepath = os.path.join(UPLOAD_FOLDER, safe_name)
    f.save(filepath)

    try:
        ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
        if ext in ('xlsx', 'xls'):
            df = pd.read_excel(filepath, dtype=str)
        elif ext == 'csv':
            df = pd.read_csv(filepath, dtype=str, sep=None, engine='python')
        else:
            return jsonify({'ok': False, 'error': f'Ungültiges Format: .{ext}'}), 400

        df.columns = [c.strip() for c in df.columns]

        # Validate required columns
        missing = [c for c in TECH_EXPECTED_COLS if c not in df.columns]
        if missing:
            return jsonify({
                'ok': False,
                'error': f'Fehlende Spalten: {", ".join(missing)}. Erwartet: {", ".join(TECH_EXPECTED_COLS)}'
            }), 400

        # Strip whitespace
        for c in TECH_EXPECTED_COLS:
            df[c] = df[c].fillna('').astype(str).str.strip()

        # Preview
        records = df[TECH_EXPECTED_COLS].to_dict(orient='records')
        preview = records[:200]

        return jsonify({
            'ok': True,
            'filename': safe_name,
            'columns': TECH_EXPECTED_COLS,
            'preview': preview,
            'total': len(records),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@migrate_bp.route('/api/tech-material/save', methods=['POST'])
def tech_material_save():
    """Save uploaded data to tech_material_staging and trigger DIL enrichment.

    Body: { filename }
    """
    import pandas as pd
    from app_config import DilEngine

    body = request.get_json(silent=True) or {}
    filename = body.get('filename', '').strip()
    if not filename:
        return jsonify({'ok': False, 'error': 'Dateiname fehlt'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(filename))
    if not os.path.isfile(filepath):
        return jsonify({'ok': False, 'error': 'Datei nicht gefunden'}), 404

    try:
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext in ('xlsx', 'xls'):
            df = pd.read_excel(filepath, dtype=str)
        else:
            df = pd.read_csv(filepath, dtype=str, sep=None, engine='python')

        df.columns = [c.strip() for c in df.columns]
        for c in TECH_EXPECTED_COLS:
            df[c] = df[c].fillna('').astype(str).str.strip()

        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        batch_id = f'TECH_{ts}'
        created_by = session.get('au_name', 'unknown')

        # ── 1) Insert raw records into staging (BULK optimized) ────────
        # Prepare data for bulk insert
        records = []
        for _, row in df.iterrows():
            records.append({
                'bid': batch_id, 'cb': created_by,
                'dokar': row['DOKAR'], 'doknr': row['DOKNR'],
                'dokvr': row['DOKVR'], 'doktl': row['DOKTL'],
                'dokob': row['DOKOB'], 'obzae': row['OBZAE'],
                'objky': row['OBJKY'],
            })
        
        # Bulk insert in chunks of 1000 for optimal performance
        CHUNK_SIZE = 1000
        inserted = 0
        with misc_engine.begin() as con:
            for i in range(0, len(records), CHUNK_SIZE):
                chunk = records[i:i + CHUNK_SIZE]
                con.execute(text("""
                    INSERT INTO dbo.tech_material_staging
                        (batch_id, created_by,
                         source_dokar, source_doknr, source_dokvr, source_doktl,
                         source_dokob, source_obzae, source_objky)
                    VALUES
                        (:bid, :cb,
                         :dokar, :doknr, :dokvr, :doktl,
                         :dokob, :obzae, :objky)
                """), chunk)
                inserted += len(chunk)
                tech_logger.info(f"[TECH] Inserted {inserted}/{len(records)} records...", category='TECH_UPLOAD')

        tech_logger.info(
            f"[TECH] Batch {batch_id}: {inserted} records inserted from '{filename}'",
            category='TECH_UPLOAD',
        )

        # ── 2) DIL enrichment ────────────────────────────────────────
        enrich_errors = []
        try:
            dil_db = DilEngine.load()
            if dil_db.engine is not None:
                _tech_enrich_from_dil(batch_id, dil_db.engine)
            else:
                enrich_errors.append('DIL nicht verbunden — Anreicherung übersprungen')
        except Exception as e:
            enrich_errors.append(f'DIL-Anreicherung fehlgeschlagen: {str(e)[:300]}')
            tech_logger.error(f"[TECH] DIL enrichment error: {e}", category='TECH_ENRICH')

        # ── 3) Read back enriched data for preview ───────────────────
        with misc_engine.connect() as con:
            rows = con.execute(text("""
                SELECT id, source_dokar, source_doknr, source_dokvr, source_doktl,
                       source_dokob, source_obzae, source_objky,
                       source_description, filename, file_size_bytes, has_file, ablage,
                       source_object_links, source_link_count, status
                FROM dbo.tech_material_staging
                WHERE batch_id = :bid
                ORDER BY id
            """), {'bid': batch_id}).fetchall()

        columns = [
            'id', 'DOKAR', 'DOKNR', 'DOKVR', 'DOKTL',
            'DOKOB', 'OBZAE', 'OBJKY',
            'Beschreibung', 'Dateiname', 'Größe (Bytes)', 'Datei?', 'Ablage',
            'Objektlinks', 'Linkanzahl', 'Status',
        ]
        data = []
        for r in rows:
            data.append({
                'id': r.id,
                'DOKAR': r.source_dokar or '',
                'DOKNR': r.source_doknr or '',
                'DOKVR': r.source_dokvr or '',
                'DOKTL': r.source_doktl or '',
                'DOKOB': r.source_dokob or '',
                'OBZAE': str(r.source_obzae or ''),
                'OBJKY': r.source_objky or '',
                'Beschreibung': r.source_description or '',
                'Dateiname': r.filename or '',
                'Größe (Bytes)': str(r.file_size_bytes or ''),
                'Datei?': 'Ja' if r.has_file else 'Nein',
                'Ablage': r.ablage or '',
                'Objektlinks': r.source_object_links or '',
                'Linkanzahl': str(r.source_link_count or 0),
                'Status': r.status or 'pending',
            })

        return jsonify({
            'ok': True,
            'batch_id': batch_id,
            'columns': columns,
            'data': data[:500],
            'total': len(data),
            'inserted': inserted,
            'enrich_errors': enrich_errors,
        })
    except Exception as e:
        import traceback
        tech_logger.error(f"[TECH] Save error: {traceback.format_exc()}", category='TECH_SAVE')
        return jsonify({'ok': False, 'error': str(e)}), 500


def _tech_enrich_from_dil(batch_id, dil_engine):
    """Enrich tech_material_staging records with data from DIL.
    
    FULLY VECTORIZED - no iterrows() loops for maximum performance.
    Uses pandas merge operations instead of dict lookups.

    For each unique document (DOKAR/DOKNR/DOKVR/DOKTL):
      - Description from DIL.DRAT
      - Filename from DIL.DRAW
      - File existence from DIL.DMS_DOC_FILES
      - LOIO ID from DIL.DMS_DOC2LOIO
      - File size from DIL.DMS_FILE_SIZE
      - All object links from DIL.DRAD (aggregated as JSON)
    """
    import pandas as pd
    import json
    import time

    t_total = time.time()
    
    # Load staging records
    t0 = time.time()
    with misc_engine.connect() as con:
        staging = pd.read_sql(text("""
            SELECT id, source_dokar, source_doknr, source_dokvr, source_doktl,
                   source_dokob, source_objky
            FROM dbo.tech_material_staging
            WHERE batch_id = :bid
        """), con, params={'bid': batch_id})

    if staging.empty:
        return

    tech_logger.info(f"[TECH_ENRICH] ▶ START: {len(staging)} rows loaded in {time.time()-t0:.1f}s", category='TECH_ENRICH')

    # ── VECTORIZED: Build join keys and SQL conditions ────────────────
    # Prepare padded/escaped columns for merging (VECTORIZED - no iterrows!)
    staging['_dokvr'] = staging['source_dokvr'].astype(str).str.zfill(2)
    staging['_doktl'] = staging['source_doktl'].astype(str).str.zfill(3)
    staging['_doknr'] = staging['source_doknr'].astype(str)
    staging['_dokar'] = staging['source_dokar'].astype(str)
    
    # Unique documents for DIL queries
    doc_keys = staging[['_doknr', '_dokar', '_dokvr', '_doktl']].drop_duplicates().copy()
    doc_keys['_doknr_esc'] = doc_keys['_doknr'].str.replace("'", "''", regex=False)
    doc_keys['_dokar_esc'] = doc_keys['_dokar'].str.replace("'", "''", regex=False)
    
    # Build SQL conditions VECTORIZED (no loop!)
    conditions = (
        "(DOKNR='" + doc_keys['_doknr_esc'] +
        "' AND DOKAR='" + doc_keys['_dokar_esc'] +
        "' AND DOKVR='" + doc_keys['_dokvr'] +
        "' AND DOKTL='" + doc_keys['_doktl'] + "')"
    ).tolist()
    
    chunk_size = 1000
    total_chunks = (len(conditions) + chunk_size - 1) // chunk_size
    tech_logger.info(f"[TECH_ENRICH] {len(doc_keys)} unique docs → {total_chunks} chunks per table", category='TECH_ENRICH')

    # ── A) Descriptions from DIL.DRAT (VECTORIZED) ────────────────────
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 📖 Phase 1/6: Loading DRAT (descriptions)...", category='TECH_ENRICH')
    drat_df = pd.DataFrame()
    try:
        all_descs = []
        for i in range(0, len(conditions), chunk_size):
            chunk = conditions[i:i + chunk_size]
            q = f"""
                SELECT DOKNR, DOKAR, DOKVR, DOKTL, LANGU, DKTXT
                FROM DIL.DRAT
                WHERE MANDT = '100' AND ({' OR '.join(chunk)})
            """
            with dil_engine.begin() as con:
                all_descs.append(pd.read_sql(q, con))

        if all_descs:
            drat_df = pd.concat(all_descs, ignore_index=True)
            drat_df.columns = [c.lower() for c in drat_df.columns]
            # Priority: English (E) > German (D) > any - VECTORIZED
            drat_df['_lang_prio'] = drat_df['langu'].map({'E': 0, 'D': 1}).fillna(2).astype(int)
            drat_df = drat_df.sort_values('_lang_prio').drop_duplicates(
                subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first'
            )[['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt']].copy()
            drat_df['dktxt'] = drat_df['dktxt'].fillna('').str.strip()
        tech_logger.info(f"[TECH_ENRICH] ✓ Phase 1/6: DRAT: {len(drat_df)} descriptions in {time.time()-t0:.1f}s", category='TECH_ENRICH')
    except Exception as e:
        tech_logger.error(f"[TECH_ENRICH] ✗ Phase 1/6: DRAT error: {e}", category='TECH_ENRICH')

    # ── B) Filenames from DIL.DRAW (VECTORIZED) ───────────────────────
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 📁 Phase 2/6: Loading DRAW (filenames)...", category='TECH_ENRICH')
    draw_df = pd.DataFrame()
    try:
        all_draws = []
        for i in range(0, len(conditions), chunk_size):
            chunk = conditions[i:i + chunk_size]
            q = f"""
                SELECT DOKNR, DOKAR, DOKVR, DOKTL, FILEP
                FROM DIL.DRAW
                WHERE MANDT = '100' AND ({' OR '.join(chunk)})
            """
            with dil_engine.begin() as con:
                all_draws.append(pd.read_sql(q, con))

        if all_draws:
            draw_df = pd.concat(all_draws, ignore_index=True)
            draw_df.columns = [c.lower() for c in draw_df.columns]
            draw_df['filep'] = draw_df['filep'].fillna('').str.strip()
            draw_df = draw_df[draw_df['filep'] != ''].drop_duplicates(
                subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first'
            )
        tech_logger.info(f"[TECH_ENRICH] ✓ Phase 2/6: DRAW: {len(draw_df)} filenames in {time.time()-t0:.1f}s", category='TECH_ENRICH')
    except Exception as e:
        tech_logger.error(f"[TECH_ENRICH] ✗ Phase 2/6: DRAW error: {e}", category='TECH_ENRICH')

    # ── C) File existence from DIL.DMS_DOC_FILES (VECTORIZED) ─────────
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 💾 Phase 3/6: Loading DMS_DOC_FILES (file existence)...", category='TECH_ENRICH')
    files_df = pd.DataFrame()
    try:
        all_files = []
        for i in range(0, len(conditions), chunk_size):
            chunk = conditions[i:i + chunk_size]
            q = f"""
                SELECT DISTINCT DOKNR, DOKAR, DOKVR, DOKTL
                FROM DIL.DMS_DOC_FILES
                WHERE MANDT = '100' AND ({' OR '.join(chunk)})
            """
            with dil_engine.begin() as con:
                all_files.append(pd.read_sql(q, con))

        if all_files:
            files_df = pd.concat(all_files, ignore_index=True)
            files_df.columns = [c.lower() for c in files_df.columns]
            files_df = files_df.drop_duplicates()
            files_df['_has_file'] = 1  # Marker for merge
        tech_logger.info(f"[TECH_ENRICH] ✓ Phase 3/6: DMS_DOC_FILES: {len(files_df)} with files in {time.time()-t0:.1f}s", category='TECH_ENRICH')
    except Exception as e:
        tech_logger.error(f"[TECH_ENRICH] ✗ Phase 3/6: DMS_DOC_FILES error: {e}", category='TECH_ENRICH')

    # ── D) LOIO IDs from DIL.DMS_DOC2LOIO (VECTORIZED) ────────────────
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 🔑 Phase 4/6: Loading DMS_DOC2LOIO (LOIO IDs)...", category='TECH_ENRICH')
    loio_df = pd.DataFrame()
    try:
        all_loios = []
        for i in range(0, len(conditions), chunk_size):
            chunk = conditions[i:i + chunk_size]
            q = f"""
                SELECT DOKNR, DOKAR, DOKVR, DOKTL, LO_OBJID
                FROM DIL.DMS_DOC2LOIO
                WHERE MANDT = '100' AND ({' OR '.join(chunk)})
            """
            with dil_engine.begin() as con:
                all_loios.append(pd.read_sql(q, con))

        if all_loios:
            loio_df = pd.concat(all_loios, ignore_index=True)
            loio_df.columns = [c.lower() for c in loio_df.columns]
            loio_df = loio_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')
        tech_logger.info(f"[TECH_ENRICH] ✓ Phase 4/6: DMS_DOC2LOIO: {len(loio_df)} LOIOs in {time.time()-t0:.1f}s", category='TECH_ENRICH')
    except Exception as e:
        tech_logger.error(f"[TECH_ENRICH] ✗ Phase 4/6: DMS_DOC2LOIO error: {e}", category='TECH_ENRICH')

    # ── E) File sizes from DIL.DMS_FILE_SIZE (VECTORIZED) ─────────────
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 📏 Phase 5/6: Loading DMS_FILE_SIZE (file sizes)...", category='TECH_ENRICH')
    size_df = pd.DataFrame()
    if len(loio_df) > 0:
        try:
            unique_loios = loio_df['lo_objid'].dropna().unique().tolist()
            all_sizes = []
            for i in range(0, len(unique_loios), 2000):
                chunk = unique_loios[i:i + 2000]
                placeholders = ",".join(f"'{lid}'" for lid in chunk)
                q = f"SELECT LOIO_ID, FILE_SIZE FROM DIL.DMS_FILE_SIZE WHERE LOIO_ID IN ({placeholders})"
                with dil_engine.begin() as con:
                    all_sizes.append(pd.read_sql(q, con))

            if all_sizes:
                size_df = pd.concat(all_sizes, ignore_index=True)
                size_df.columns = [c.lower() for c in size_df.columns]
                size_df = size_df.drop_duplicates(subset=['loio_id'], keep='first')
            tech_logger.info(f"[TECH_ENRICH] ✓ Phase 5/6: DMS_FILE_SIZE: {len(size_df)} sizes in {time.time()-t0:.1f}s", category='TECH_ENRICH')
        except Exception as e:
            tech_logger.error(f"[TECH_ENRICH] ✗ Phase 5/6: DMS_FILE_SIZE error: {e}", category='TECH_ENRICH')
    else:
        tech_logger.info(f"[TECH_ENRICH] ✓ Phase 5/6: DMS_FILE_SIZE: skipped (no LOIOs) in {time.time()-t0:.1f}s", category='TECH_ENRICH')

    # ── F) Object links from DIL.DRAD - aggregate as JSON (VECTORIZED) ─
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 🔗 Phase 6/6: Loading DRAD (object links)...", category='TECH_ENRICH')
    drad_agg = pd.DataFrame()
    try:
        all_drad = []
        for i in range(0, len(conditions), chunk_size):
            chunk = conditions[i:i + chunk_size]
            q = f"""
                SELECT DOKNR, DOKAR, DOKVR, DOKTL, DOKOB, OBJKY
                FROM DIL.DRAD
                WHERE MANDT = '100' AND ({' OR '.join(chunk)})
            """
            with dil_engine.begin() as con:
                all_drad.append(pd.read_sql(q, con))

        if all_drad:
            drad = pd.concat(all_drad, ignore_index=True)
            drad.columns = [c.lower() for c in drad.columns]
            drad['dokob'] = drad['dokob'].fillna('').str.strip()
            drad['objky'] = drad['objky'].fillna('').str.strip()
            # Deduplicate links per document
            drad_unique = drad.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl', 'dokob', 'objky'])
            # Build JSON string per document VECTORIZED (no iterrows!)
            drad_unique['_link'] = '{"dokob":"' + drad_unique['dokob'] + '","objky":"' + drad_unique['objky'] + '"}'
            drad_agg = drad_unique.groupby(['doknr', 'dokar', 'dokvr', 'doktl']).agg(
                source_object_links=('_link', lambda x: '[' + ','.join(x) + ']'),
                source_link_count=('_link', 'count')
            ).reset_index()
        tech_logger.info(f"[TECH_ENRICH] ✓ Phase 6/6: DRAD: {len(drad_agg)} docs with links in {time.time()-t0:.1f}s", category='TECH_ENRICH')
    except Exception as e:
        tech_logger.error(f"[TECH_ENRICH] ✗ Phase 6/6: DRAD error: {e}", category='TECH_ENRICH')

    # ── G) MERGE all DIL data into staging (VECTORIZED - no dict lookups!) ────
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 🔀 Merging DIL data via pandas...", category='TECH_ENRICH')
    
    # Start with staging, merge each DIL result
    result = staging[['id', '_doknr', '_dokar', '_dokvr', '_doktl']].copy()
    
    # Merge DRAT (descriptions)
    if len(drat_df) > 0:
        drat_df['doknr'] = drat_df['doknr'].astype(str)
        drat_df['dokar'] = drat_df['dokar'].astype(str)
        drat_df['dokvr'] = drat_df['dokvr'].astype(str)
        drat_df['doktl'] = drat_df['doktl'].astype(str)
        result = result.merge(
            drat_df[['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt']].rename(columns={'dktxt': 'source_description'}),
            how='left', left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
            right_on=['doknr', 'dokar', 'dokvr', 'doktl']
        ).drop(columns=['doknr', 'dokar', 'dokvr', 'doktl'], errors='ignore')
    else:
        result['source_description'] = None
    
    # Merge DRAW (filenames)
    if len(draw_df) > 0:
        draw_df['doknr'] = draw_df['doknr'].astype(str)
        draw_df['dokar'] = draw_df['dokar'].astype(str)
        draw_df['dokvr'] = draw_df['dokvr'].astype(str)
        draw_df['doktl'] = draw_df['doktl'].astype(str)
        result = result.merge(
            draw_df[['doknr', 'dokar', 'dokvr', 'doktl', 'filep']].rename(columns={'filep': 'filename'}),
            how='left', left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
            right_on=['doknr', 'dokar', 'dokvr', 'doktl']
        ).drop(columns=['doknr', 'dokar', 'dokvr', 'doktl'], errors='ignore')
    else:
        result['filename'] = None
    
    # Merge DMS_DOC_FILES (has_file flag)
    if len(files_df) > 0:
        files_df['doknr'] = files_df['doknr'].astype(str)
        files_df['dokar'] = files_df['dokar'].astype(str)
        files_df['dokvr'] = files_df['dokvr'].astype(str)
        files_df['doktl'] = files_df['doktl'].astype(str)
        result = result.merge(
            files_df[['doknr', 'dokar', 'dokvr', 'doktl', '_has_file']].rename(columns={'_has_file': 'has_file'}),
            how='left', left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
            right_on=['doknr', 'dokar', 'dokvr', 'doktl']
        ).drop(columns=['doknr', 'dokar', 'dokvr', 'doktl'], errors='ignore')
    else:
        result['has_file'] = None
    result['has_file'] = result['has_file'].fillna(0).astype(int)
    result['ablage'] = result['has_file'].apply(lambda x: 'KPRO' if x == 1 else 'DB')
    
    # Merge LOIO IDs
    if len(loio_df) > 0:
        loio_df['doknr'] = loio_df['doknr'].astype(str)
        loio_df['dokar'] = loio_df['dokar'].astype(str)
        loio_df['dokvr'] = loio_df['dokvr'].astype(str)
        loio_df['doktl'] = loio_df['doktl'].astype(str)
        result = result.merge(
            loio_df[['doknr', 'dokar', 'dokvr', 'doktl', 'lo_objid']].rename(columns={'lo_objid': 'loio_id'}),
            how='left', left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
            right_on=['doknr', 'dokar', 'dokvr', 'doktl']
        ).drop(columns=['doknr', 'dokar', 'dokvr', 'doktl'], errors='ignore')
    else:
        result['loio_id'] = None
    
    # Merge file sizes via LOIO
    if len(size_df) > 0:
        size_df['loio_id'] = size_df['loio_id'].astype(str)
        result['loio_id'] = result['loio_id'].astype(str)
        result = result.merge(
            size_df[['loio_id', 'file_size']].rename(columns={'file_size': 'file_size_bytes'}),
            how='left', on='loio_id'
        )
    else:
        result['file_size_bytes'] = None
    
    # Merge DRAD aggregated links
    if len(drad_agg) > 0:
        drad_agg['doknr'] = drad_agg['doknr'].astype(str)
        drad_agg['dokar'] = drad_agg['dokar'].astype(str)
        drad_agg['dokvr'] = drad_agg['dokvr'].astype(str)
        drad_agg['doktl'] = drad_agg['doktl'].astype(str)
        result = result.merge(
            drad_agg,
            how='left', left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
            right_on=['doknr', 'dokar', 'dokvr', 'doktl']
        ).drop(columns=['doknr', 'dokar', 'dokvr', 'doktl'], errors='ignore')
    else:
        result['source_object_links'] = None
        result['source_link_count'] = 0
    result['source_link_count'] = result['source_link_count'].fillna(0).astype(int)
    
    tech_logger.info(f"[TECH_ENRICH] ✓ Merging completed in {time.time()-t0:.1f}s", category='TECH_ENRICH')
    
    # Prepare final update DataFrame
    result = result.rename(columns={'id': 'staging_id'})
    update_cols = ['staging_id', 'source_description', 'filename', 'file_size_bytes', 
                   'loio_id', 'has_file', 'ablage', 'source_object_links', 'source_link_count']
    update_df = result[[c for c in update_cols if c in result.columns]].copy()
    update_df = update_df.where(pd.notnull(update_df), None)
    
    t0 = time.time()
    tech_logger.info(f"[TECH_ENRICH] 💾 Bulk updating {len(update_df)} rows via temp table...", category='TECH_ENRICH')

    # ── H) Bulk update via TEMP TABLE + JOIN ────────────────────────────
    with misc_engine.begin() as con:
        # 1. Create temp table
        con.execute(text("""
            IF OBJECT_ID('tempdb..#tech_enrich_update') IS NOT NULL DROP TABLE #tech_enrich_update;
            CREATE TABLE #tech_enrich_update (
                staging_id INT PRIMARY KEY,
                source_description NVARCHAR(500),
                filename NVARCHAR(500),
                file_size_bytes BIGINT,
                loio_id NVARCHAR(100),
                has_file INT,
                ablage NVARCHAR(20),
                source_object_links NVARCHAR(MAX),
                source_link_count INT
            );
        """))
        
        # 2. Bulk insert into temp table
        CHUNK_SIZE = 900
        for i in range(0, len(update_df), CHUNK_SIZE):
            chunk = update_df.iloc[i:i + CHUNK_SIZE]
            chunk.to_sql('#tech_enrich_update', con, if_exists='append', index=False, method='multi')
            if len(update_df) > 10000 and i % 10000 == 0 and i > 0:
                tech_logger.info(f"[TECH_ENRICH] Temp table: {i}/{len(update_df)} rows...", category='TECH_ENRICH')
        
        # 3. Single UPDATE with JOIN (replaces 125k individual UPDATEs!)
        result = con.execute(text("""
            UPDATE s
            SET s.source_description = t.source_description,
                s.filename = t.filename,
                s.file_size_bytes = t.file_size_bytes,
                s.loio_id = t.loio_id,
                s.has_file = t.has_file,
                s.ablage = t.ablage,
                s.source_object_links = t.source_object_links,
                s.source_link_count = t.source_link_count
            FROM dbo.tech_material_staging s
            INNER JOIN #tech_enrich_update t ON s.id = t.staging_id
        """))
        updated = result.rowcount
        
        # 4. Cleanup
        con.execute(text("DROP TABLE #tech_enrich_update"))

    tech_logger.info(f"[TECH_ENRICH] ✓ Updated {updated} rows in {time.time()-t0:.1f}s", category='TECH_ENRICH')
    tech_logger.info(f"[TECH_ENRICH] ■ DONE: Total enrichment time: {time.time()-t_total:.1f}s", category='TECH_ENRICH')


@migrate_bp.route('/api/tech-material/batches', methods=['GET'])
def tech_material_batches():
    """List TECH material staging batches."""
    with misc_engine.connect() as con:
        rows = con.execute(text("""
            SELECT batch_id,
                   MIN(created_at) as created_at,
                   MAX(created_by) as created_by,
                   COUNT(*) as total,
                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                   COUNT(DISTINCT source_doknr) as documents,
                   COUNT(DISTINCT source_dokob) as dokob_types,
                   SUM(CASE WHEN has_file = 1 THEN 1 ELSE 0 END) as with_file
            FROM dbo.tech_material_staging
            GROUP BY batch_id
            ORDER BY MIN(created_at) DESC
        """)).fetchall()

    batches = []
    for r in rows:
        batches.append({
            'batch_id': r.batch_id,
            'created_at': r.created_at.isoformat() if r.created_at else None,
            'created_by': r.created_by,
            'total': r.total,
            'pending': r.pending,
            'done': r.done,
            'errors': r.errors,
            'documents': r.documents,
            'dokob_types': r.dokob_types,
            'with_file': r.with_file,
        })
    return jsonify({'ok': True, 'batches': batches})


@migrate_bp.route('/api/tech-material/data/<batch_id>', methods=['GET'])
def tech_material_data(batch_id):
    """Get staging data for a TECH material batch."""
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(2000, max(10, int(request.args.get('per_page', 500))))
    offset = (page - 1) * per_page

    with misc_engine.connect() as con:
        total = con.execute(text(
            "SELECT COUNT(*) FROM dbo.tech_material_staging WHERE batch_id = :bid"
        ), {'bid': batch_id}).scalar()

        rows = con.execute(text("""
            SELECT id, source_dokar, source_doknr, source_dokvr, source_doktl,
                   source_dokob, source_obzae, source_objky,
                   source_description, filename, file_size_bytes, has_file, ablage,
                   source_object_links, source_link_count, status, error_message
            FROM dbo.tech_material_staging
            WHERE batch_id = :bid
            ORDER BY id
            OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
        """), {'bid': batch_id, 'off': offset, 'lim': per_page}).fetchall()

    data = []
    for r in rows:
        data.append({
            'id': r.id,
            'DOKAR': r.source_dokar or '',
            'DOKNR': r.source_doknr or '',
            'DOKVR': r.source_dokvr or '',
            'DOKTL': r.source_doktl or '',
            'DOKOB': r.source_dokob or '',
            'OBZAE': str(r.source_obzae or ''),
            'OBJKY': r.source_objky or '',
            'Beschreibung': r.source_description or '',
            'Dateiname': r.filename or '',
            'Größe (Bytes)': str(r.file_size_bytes or ''),
            'Datei?': 'Ja' if r.has_file else 'Nein',
            'Ablage': r.ablage or '',
            'Objektlinks': r.source_object_links or '',
            'Linkanzahl': str(r.source_link_count or 0),
            'Status': r.status or 'pending',
            'Fehler': r.error_message or '',
        })

    columns = [
        'id', 'DOKAR', 'DOKNR', 'DOKVR', 'DOKTL',
        'DOKOB', 'OBZAE', 'OBJKY',
        'Beschreibung', 'Dateiname', 'Größe (Bytes)', 'Datei?', 'Ablage',
        'Objektlinks', 'Linkanzahl', 'Status', 'Fehler',
    ]

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    return jsonify({
        'ok': True, 'columns': columns, 'data': data,
        'total': total, 'page': page, 'per_page': per_page, 'total_pages': total_pages,
    })


# ═══════════════════════════════════════════════════════════════════════
# TECH Material — Download Execution
# ═══════════════════════════════════════════════════════════════════════

_tech_bg_results = {}   # batch_id -> progress dict
_tech_bg_lock = threading.Lock()


@migrate_bp.route('/api/tech-material/execute', methods=['POST'])
def tech_material_execute():
    """Start background download of all files for a TECH material batch."""
    body = request.get_json(silent=True) or {}
    batch_id = body.get('batch_id', '').strip()
    download_path = body.get('download_path', '').strip()

    if not batch_id:
        return jsonify({'ok': False, 'error': 'batch_id fehlt'}), 400
    if not download_path:
        return jsonify({'ok': False, 'error': 'Speicherpfad fehlt'}), 400

    norm_path = os.path.normpath(download_path)
    if not os.path.isdir(norm_path):
        return jsonify({'ok': False, 'error': f'Verzeichnis nicht gefunden: {download_path}'}), 400

    with _tech_bg_lock:
        prev = _tech_bg_results.get(batch_id, {})
        if prev.get('status') == 'running':
            return jsonify({'ok': False, 'error': 'Download läuft bereits für diesen Batch'}), 409

    snapshot = _build_session_snapshot()

    t = threading.Thread(
        target=_tech_download_background,
        args=(batch_id, snapshot, norm_path),
        daemon=True,
    )
    t.start()

    return jsonify({'ok': True, 'message': 'Download gestartet', 'batch_id': batch_id})


@migrate_bp.route('/api/tech-material/execute/progress/<batch_id>', methods=['GET'])
def tech_material_progress(batch_id):
    """Poll download execution progress for TECH material batch."""
    with _tech_bg_lock:
        result = _tech_bg_results.get(batch_id)
    if not result:
        return jsonify({'ok': False, 'error': 'Kein laufender Download für diesen Batch'}), 404
    return jsonify({'ok': True, **result})


def _extract_cd_filename(cd_header):
    """Extract filename from a Content-Disposition header value.

    Handles both ``filename="name.ext"`` and ``filename=name.ext`` forms.
    Returns empty string when nothing useful is found.
    """
    if not cd_header:
        return ''
    m = re.search(r'filename\*?=["\']?([^"\';]+)', cd_header)
    if m:
        name = m.group(1).strip().rstrip('"').rstrip("'")
        # Sometimes the value is URL-encoded (UTF-8''name.ext)
        if "''" in name:
            name = name.split("''", 1)[-1]
        # Only keep the basename (strip any path parts)
        name = name.replace('\\', '/').split('/')[-1]
        return name
    return ''


def _tech_download_background(batch_id, session_snapshot, base_download_path):
    """Background worker: download all files from source SAP and write mapping Excel."""
    import json as _json
    import traceback as _tb
    from app.process import _sanitize_filename

    source_system = session_snapshot.get('source_system', 'zhl')

    # Init progress
    with _tech_bg_lock:
        _tech_bg_results[batch_id] = {
            'status': 'running', 'total': 0, 'done': 0, 'failed': 0, 'skipped': 0,
            'current_doc': '', 'errors': [], 'download_path': '',
        }

    try:
        # ── 1) Load all staging records for this batch ────────────────
        with misc_engine.connect() as con:
            rows = con.execute(text("""
                SELECT id, source_dokar, source_doknr, source_dokvr, source_doktl,
                       source_dokob, source_obzae, source_objky,
                       source_description, filename, file_size_bytes, loio_id,
                       has_file, ablage, source_object_links, source_link_count
                FROM dbo.tech_material_staging
                WHERE batch_id = :bid
                ORDER BY id
            """), {'bid': batch_id}).fetchall()

        if not rows:
            with _tech_bg_lock:
                _tech_bg_results[batch_id] = {
                    'status': 'done', 'total': 0, 'done': 0, 'failed': 0, 'skipped': 0,
                    'errors': ['Keine Datensätze im Batch'], 'download_path': '',
                }
            return

        # ── 2) Build unique documents (deduplicate by DOKAR/DOKNR/DOKVR/DOKTL) ──
        # Folder structure: batch_folder / DOKAR / DOKNR
        # Each document is downloaded exactly once regardless of how many objects reference it.
        doc_map = {}
        all_records = []
        for r in rows:
            rec = {
                'id': r.id,
                'dokar': (r.source_dokar or '').strip(),
                'doknr': (r.source_doknr or '').strip(),
                'dokvr': (r.source_dokvr or '').strip(),
                'doktl': (r.source_doktl or '').strip(),
                'dokob': (r.source_dokob or '').strip(),
                'obzae': str(r.source_obzae or '').strip(),
                'objky': (r.source_objky or '').strip(),
                'description': (r.source_description or '').strip(),
                'filename': (r.filename or '').strip(),
                'file_size': r.file_size_bytes,
                'loio_id': (r.loio_id or '').strip(),
                'has_file': bool(r.has_file),
                'ablage': (r.ablage or '').strip(),
                'object_links': r.source_object_links or '[]',
                'link_count': r.source_link_count or 0,
            }
            all_records.append(rec)
            key = (rec['dokar'], rec['doknr'], rec['dokvr'], rec['doktl'])
            if key not in doc_map:
                doc_map[key] = rec

        # Sort by DOKAR then DOKNR for consistent folder ordering
        unique_docs = sorted(doc_map.values(), key=lambda d: (d['dokar'], d['doknr']))
        docs_with_file = [d for d in unique_docs if d['has_file']]

        with _tech_bg_lock:
            _tech_bg_results[batch_id]['total'] = len(docs_with_file)

        tech_logger.info(
            f"[TECH_DL] Batch {batch_id}: {len(all_records)} records, "
            f"{len(unique_docs)} unique docs, {len(docs_with_file)} with files",
            category='TECH_DOWNLOAD',
        )

        # ── 3) Create batch folder ──────────────────────────────────
        batch_folder = os.path.join(base_download_path, batch_id)
        os.makedirs(batch_folder, exist_ok=True)

        # ── 4) Download files per unique document ────────────────────
        from app.process import get_info

        dl_session = requests.Session()
        prepare_session_headers(dl_session, session_snapshot, source_system)
        dl_session.headers.pop('Slug', None)

        base_read_url = cfg.get(source_system, 'api_list', 'document', 'base_url')
        file_log = []
        doc_log = []
        done_count = 0
        failed_count = 0
        skipped_count = 0

        for doc in unique_docs:
            safe_dokar = _sanitize_filename(doc['dokar'])
            safe_doknr = _sanitize_filename(doc['doknr'] or 'UNKNOWN')
            doc_folder = os.path.join(batch_folder, safe_dokar, safe_doknr)

            with _tech_bg_lock:
                _tech_bg_results[batch_id]['current_doc'] = (
                    f"{doc['dokar']}/{doc['doknr']}"
                )

            if not doc['has_file']:
                doc_log.append({
                    'DOKAR': doc['dokar'], 'DOKNR': doc['doknr'],
                    'DOKVR': doc['dokvr'], 'DOKTL': doc['doktl'],
                    'Beschreibung': doc['description'],
                    'Dateiname_Staging': doc['filename'],
                    'LOIO_ID': '',
                    'Dateien_Heruntergeladen': 0,
                    'Gesamtgroesse_Bytes': 0,
                    'Status': 'skipped_no_file',
                    'Ordnerpfad': '', 'Fehler': '',
                })
                skipped_count += 1
                with _tech_bg_lock:
                    _tech_bg_results[batch_id]['skipped'] = skipped_count
                continue

            os.makedirs(doc_folder, exist_ok=True)

            # ── 4a) Query API to discover ALL files for this document ──
            status_code, reason, api_files = get_info(
                dl_session, source_system,
                doc['doknr'], doc['doktl'], doc['dokar'], doc['dokvr'],
            )

            if status_code != 200 or not api_files:
                dl_error = f'READ_FAILED {status_code}: {reason}'
                failed_count += 1
                doc_log.append({
                    'DOKAR': doc['dokar'], 'DOKNR': doc['doknr'],
                    'DOKVR': doc['dokvr'], 'DOKTL': doc['doktl'],
                    'Beschreibung': doc['description'],
                    'Dateiname_Staging': doc['filename'],
                    'LOIO_ID': doc['loio_id'],
                    'Dateien_Heruntergeladen': 0,
                    'Gesamtgroesse_Bytes': 0,
                    'Status': 'error',
                    'Ordnerpfad': '', 'Fehler': dl_error,
                })
                with misc_engine.begin() as con:
                    con.execute(text("""
                        UPDATE dbo.tech_material_staging
                        SET status = 'error', error_message = :err
                        WHERE batch_id = :bid
                          AND source_dokar = :dokar AND source_doknr = :doknr
                          AND source_dokvr = :dokvr AND source_doktl = :doktl
                    """), {
                        'err': dl_error, 'bid': batch_id,
                        'dokar': doc['dokar'], 'doknr': doc['doknr'],
                        'dokvr': doc['dokvr'], 'doktl': doc['doktl'],
                    })
                with _tech_bg_lock:
                    p = _tech_bg_results[batch_id]
                    p['failed'] = failed_count
                    p['errors'].append(
                        f"{doc['dokar']}/{doc['doknr']}: {dl_error[:150]}"
                    )
                continue

            tech_logger.info(
                f"[TECH_DL] {doc['dokar']}/{doc['doknr']}: "
                f"API returned {len(api_files)} file(s)",
                category='TECH_DOWNLOAD',
            )

            # Create folder only now that we know files exist
            os.makedirs(doc_folder, exist_ok=True)

            # ── 4b) Download each file with its own LOIOID ────────────
            saved_files = []
            dl_errors = []

            for fi, api_file in enumerate(api_files):
                loio = api_file.get('LOIOID', '') or ''
                # Original filename from API Docpath
                docpath = (api_file.get('Docpath', '') or '').replace('\\', '/')
                api_fname = docpath.split('/')[-1] if docpath else ''

                formatted_args = (
                    f"Documentnumber='{api_file.get('Documentnumber', doc['doknr'])}',"
                    f"Documentpart='{api_file.get('Documentpart', doc['doktl'])}',"
                    f"Documenttype='{api_file.get('Documenttype', doc['dokar'])}',"
                    f"Documentversion='{api_file.get('Documentversion', doc['dokvr'])}',"
                    f"LOIOID='{loio}'"
                )
                request_url = (
                    f"{base_read_url}/DocumentfilesSet({formatted_args})/$value"
                )

                try:
                    resp = dl_session.get(request_url, timeout=300)
                    if resp.status_code == 200 and resp.content:
                        # Filename priority: API Docpath > Content-Disposition > staging
                        fname = api_fname
                        if not fname:
                            fname = _extract_cd_filename(
                                resp.headers.get('Content-Disposition', '')
                            )
                        if not fname:
                            fname = doc['filename']
                        if not fname:
                            fname = f"file_{fi}_{doc['dokar']}_{doc['doknr']}"
                        fname = _sanitize_filename(fname)

                        out_path = os.path.join(doc_folder, fname)
                        # Handle name collision within same folder
                        if os.path.exists(out_path):
                            root, ext = os.path.splitext(fname)
                            counter = 2
                            while os.path.exists(out_path):
                                out_path = os.path.join(
                                    doc_folder,
                                    f"{root}_{counter:03d}{ext}",
                                )
                                counter += 1

                        with open(out_path, 'wb') as fh:
                            fh.write(resp.content)

                        saved_files.append({
                            'filename': os.path.basename(out_path),
                            'size': len(resp.content),
                            'path': out_path,
                            'loio': loio,
                        })
                    elif resp.status_code == 200 and not resp.content:
                        dl_errors.append(
                            f"File {fi} LOIO={loio}: Leere Antwort"
                        )
                    else:
                        dl_errors.append(
                            f"File {fi} LOIO={loio}: HTTP {resp.status_code}"
                        )
                except Exception as e:
                    dl_errors.append(
                        f"File {fi} LOIO={loio}: {str(e)[:200]}"
                    )

            # Determine overall status for this document
            if saved_files and not dl_errors:
                dl_status = 'success'
                done_count += 1
            elif saved_files and dl_errors:
                dl_status = 'partial'
                done_count += 1   # partial counts as done
            else:
                dl_status = 'error'
                failed_count += 1

            dl_error_str = '; '.join(dl_errors)[:500] if dl_errors else ''

            doc_log.append({
                'DOKAR': doc['dokar'], 'DOKNR': doc['doknr'],
                'DOKVR': doc['dokvr'], 'DOKTL': doc['doktl'],
                'Beschreibung': doc['description'],
                'Dateiname_Staging': doc['filename'],
                'LOIO_ID': doc['loio_id'],
                'Dateien_Heruntergeladen': len(saved_files),
                'Gesamtgroesse_Bytes': sum(f['size'] for f in saved_files),
                'Status': dl_status,
                'Ordnerpfad': doc_folder,
                'Fehler': dl_error_str,
            })

            for sf in saved_files:
                file_log.append({
                    'DOKAR': doc['dokar'], 'DOKNR': doc['doknr'],
                    'DOKVR': doc['dokvr'], 'DOKTL': doc['doktl'],
                    'Dateiname': sf['filename'],
                    'Groesse_Bytes': sf['size'],
                    'Lokaler_Pfad': sf['path'],
                    'LOIO_ID': sf['loio'],
                    'Status': 'ok',
                })

            # Update staging status for all rows matching this document key
            new_status = 'done' if dl_status in ('success', 'partial') else 'error'
            with misc_engine.begin() as con:
                con.execute(text("""
                    UPDATE dbo.tech_material_staging
                    SET status = :st, error_message = :err
                    WHERE batch_id = :bid
                      AND source_dokar = :dokar AND source_doknr = :doknr
                      AND source_dokvr = :dokvr AND source_doktl = :doktl
                """), {
                    'st': new_status, 'err': dl_error_str or None,
                    'bid': batch_id,
                    'dokar': doc['dokar'], 'doknr': doc['doknr'],
                    'dokvr': doc['dokvr'], 'doktl': doc['doktl'],
                })

            with _tech_bg_lock:
                p = _tech_bg_results[batch_id]
                p['done'] = done_count
                p['failed'] = failed_count
                p['skipped'] = skipped_count
                if dl_error_str:
                    p['errors'].append(
                        f"{doc['dokar']}/{doc['doknr']}: {dl_error_str[:150]}"
                    )
                    if len(p['errors']) > 50:
                        p['errors'] = p['errors'][:50]

        # ── 5) Write mapping Excel ───────────────────────────────────
        excel_path = os.path.join(batch_folder, f'{batch_id}_mapping.xlsx')
        _tech_write_mapping_excel(
            excel_path, batch_id, all_records,
            doc_log, file_log, done_count, failed_count, skipped_count,
        )

        tech_logger.info(
            f"[TECH_DL] Batch {batch_id} complete: {done_count} ok, "
            f"{failed_count} failed, {skipped_count} skipped. Excel: {excel_path}",
            category='TECH_DOWNLOAD',
        )

        with _tech_bg_lock:
            _tech_bg_results[batch_id].update({
                'status': 'done',
                'done': done_count, 'failed': failed_count,
                'skipped': skipped_count,
                'download_path': batch_folder,
                'excel_path': excel_path,
                'current_doc': '',
            })

    except Exception as e:
        tech_logger.error(
            f"[TECH_DL] Fatal error: {_tb.format_exc()}",
            category='TECH_DOWNLOAD',
        )
        with _tech_bg_lock:
            _tech_bg_results[batch_id] = {
                'status': 'error', 'total': 0, 'done': 0, 'failed': 0,
                'skipped': 0,
                'errors': [f'Fataler Fehler: {str(e)[:300]}'],
                'download_path': '', 'current_doc': '',
            }


def _tech_write_mapping_excel(path, batch_id, all_records, doc_log, file_log,
                               done_count, failed_count, skipped_count):
    """Write the mapping Excel with 4 sheets."""
    import json as _json
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()

    # ── Sheet 1: Zusammenfassung ─────────────────────────────────────
    ws1 = wb.active
    ws1.title = 'Zusammenfassung'
    ws1.append(['TECH Material Download — Zusammenfassung'])
    ws1['A1'].font = Font(bold=True, size=14)
    ws1.append([])

    unique_docs = {(r['dokar'], r['doknr'], r['dokvr'], r['doktl'])
                   for r in all_records}
    unique_dokar = {r['dokar'] for r in all_records}
    unique_dokob = {r['dokob'] for r in all_records}
    total_size = sum(d.get('Gesamtgroesse_Bytes', 0) for d in doc_log)

    stats = [
        ('Batch-ID', batch_id),
        ('Erstellt am', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')),
        ('', ''),
        ('Staging-Zeilen gesamt', len(all_records)),
        ('Einzigartige Dokumente', len(unique_docs)),
        ('Einzigartige Dokumentarten (DOKAR)', len(unique_dokar)),
        ('Einzigartige Objekttypen (DOKOB)', len(unique_dokob)),
        ('', ''),
        ('Dokumente heruntergeladen', done_count),
        ('Fehler', failed_count),
        ('Übersprungen (keine Datei)', skipped_count),
        ('Gesamtgröße Downloads',
         f'{total_size / 1024 / 1024:.2f} MB' if total_size else '0'),
        ('', ''),
        ('Dateien gesamt im Download', len(file_log)),
    ]
    for label, value in stats:
        ws1.append([label, value])
        if label:
            ws1.cell(row=ws1.max_row, column=1).font = Font(bold=True)

    ws1.column_dimensions['A'].width = 35
    ws1.column_dimensions['B'].width = 40

    hdr_fill = PatternFill(start_color='6F42C1', end_color='6F42C1',
                           fill_type='solid')
    hdr_font = Font(bold=True, color='FFFFFF')

    # ── Sheet 2: Info Record ─────────────────────────────────────────
    # One row per unique document (DOKAR/DOKNR/DOKVR/DOKTL), deduplicated.
    ws2 = wb.create_sheet('Info Record')
    doc_headers = [
        'DOKAR', 'DOKNR', 'DOKVR', 'DOKTL', 'Beschreibung',
        'LOIO_ID', 'Dateien heruntergeladen', 'Gesamtgröße (Bytes)',
        'Status', 'Fehler', 'Duplikat',
    ]
    ws2.append(doc_headers)
    for col_idx in range(1, len(doc_headers) + 1):
        c = ws2.cell(row=1, column=col_idx)
        c.fill = hdr_fill
        c.font = hdr_font

    # Deduplicate doc_log by (DOKAR, DOKNR, DOKVR, DOKTL):
    # merge status (worst-case: error > partial > success) and collect errors.
    _status_rank = {'error': 2, 'partial': 1, 'success': 0, '': 0}
    ir_map = {}  # key -> dict
    for d in doc_log:
        key = (d.get('DOKAR', ''), d.get('DOKNR', ''), d.get('DOKVR', ''), d.get('DOKTL', ''))
        if key not in ir_map:
            ir_map[key] = {
                'DOKAR': d.get('DOKAR', ''), 'DOKNR': d.get('DOKNR', ''),
                'DOKVR': d.get('DOKVR', ''), 'DOKTL': d.get('DOKTL', ''),
                'Beschreibung': d.get('Beschreibung', ''),
                'LOIO_ID': d.get('LOIO_ID', ''),
                'Dateien_Heruntergeladen': d.get('Dateien_Heruntergeladen', 0),
                'Gesamtgroesse_Bytes': d.get('Gesamtgroesse_Bytes', 0),
                'Status': d.get('Status', ''),
                'Fehler': d.get('Fehler', ''),
            }
        else:
            existing = ir_map[key]
            # Keep worst status
            if _status_rank.get(d.get('Status', ''), 0) > _status_rank.get(existing['Status'], 0):
                existing['Status'] = d.get('Status', '')
            # Append non-empty errors
            if d.get('Fehler', ''):
                existing['Fehler'] = (existing['Fehler'] + '; ' + d['Fehler']).strip('; ')

    err_fill = PatternFill(start_color='FFCCCC', end_color='FFCCCC', fill_type='solid')
    dup_fill = PatternFill(start_color='FFEB9C', end_color='FFEB9C', fill_type='solid')

    # Find which (DOKAR, DOKNR, DOKTL) appear with more than one DOKVR → potential duplicates
    base_key_counts = {}
    for k in ir_map:
        base = (k[0], k[1], k[3])  # DOKAR, DOKNR, DOKTL (no DOKVR)
        base_key_counts[base] = base_key_counts.get(base, 0) + 1

    for k, ir in ir_map.items():
        base = (k[0], k[1], k[3])
        is_dup = base_key_counts[base] > 1
        ws2.append([
            ir['DOKAR'], ir['DOKNR'], ir['DOKVR'], ir['DOKTL'],
            ir['Beschreibung'], ir['LOIO_ID'],
            ir['Dateien_Heruntergeladen'], ir['Gesamtgroesse_Bytes'],
            ir['Status'], ir['Fehler'],
            'Ja' if is_dup else 'Nein',
        ])
        if ir['Status'] == 'error':
            for col_idx in range(1, len(doc_headers) + 1):
                ws2.cell(row=ws2.max_row, column=col_idx).fill = err_fill
        elif is_dup:
            for col_idx in range(1, len(doc_headers) + 1):
                ws2.cell(row=ws2.max_row, column=col_idx).fill = dup_fill

    # ── Sheet 3: Dateien ─────────────────────────────────────────────
    # One row per file — each document is downloaded only once (OBJKY is irrelevant here).
    # Duplikat = same file (DOKAR/DOKNR/DOKTL/Dateiname/Größe) in a different version (DOKVR).
    ws3 = wb.create_sheet('Dateien')
    file_headers = [
        'DOKAR', 'DOKNR', 'DOKVR', 'DOKTL', 'Dateiname',
        'Größe (Bytes)', 'LOIO_ID', 'Status', 'Duplikat',
    ]
    ws3.append(file_headers)
    for col_idx in range(1, len(file_headers) + 1):
        c = ws3.cell(row=1, column=col_idx)
        c.fill = hdr_fill
        c.font = hdr_font

    seen_files = set()
    for f in file_log:
        fkey = (
            f.get('DOKAR', ''), f.get('DOKNR', ''), f.get('DOKTL', ''),
            f.get('Dateiname', ''), f.get('Groesse_Bytes', 0),
        )
        is_dup = fkey in seen_files
        seen_files.add(fkey)
        ws3.append([
            f.get('DOKAR', ''), f.get('DOKNR', ''), f.get('DOKVR', ''),
            f.get('DOKTL', ''), f.get('Dateiname', ''),
            f.get('Groesse_Bytes', 0), f.get('LOIO_ID', ''),
            f.get('Status', ''), 'Ja' if is_dup else 'Nein',
        ])
        if is_dup:
            for col_idx in range(1, len(file_headers) + 1):
                ws3.cell(row=ws3.max_row, column=col_idx).fill = dup_fill

    # ── Sheet 4: Objektlinks ─────────────────────────────────────────
    ws4 = wb.create_sheet('Objektlinks')
    link_headers = [
        'DOKAR', 'DOKNR', 'DOKVR', 'DOKTL', 'DOKOB', 'OBJKY',
        'OBZAE (Quelle)', 'Beschreibung',
    ]
    ws4.append(link_headers)
    for col_idx in range(1, len(link_headers) + 1):
        c = ws4.cell(row=1, column=col_idx)
        c.fill = hdr_fill
        c.font = hdr_font

    for rec in all_records:
        ws4.append([
            rec['dokar'], rec['doknr'], rec['dokvr'], rec['doktl'],
            rec['dokob'], rec['objky'], rec['obzae'], rec['description'],
        ])
        try:
            links = _json.loads(rec.get('object_links', '[]') or '[]')
            for lnk in links:
                dokob = lnk.get('dokob', '')
                objky = lnk.get('objky', '')
                if dokob == rec['dokob'] and objky == rec['objky']:
                    continue
                ws4.append([
                    rec['dokar'], rec['doknr'], rec['dokvr'], rec['doktl'],
                    dokob, objky, '', rec['description'],
                ])
        except (ValueError, TypeError):
            pass

    # Auto-column-width
    for ws in [ws2, ws3, ws4]:
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val = str(cell.value or '')
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = min(max_len + 2, 50)

    wb.save(path)
