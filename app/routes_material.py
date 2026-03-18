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
                if dir_path:
                    rows = con.execute(text("""
                        SELECT id, target_dokar, target_dokvr, target_doktl, target_description,
                               target_doknr, source_file, material, vendor, cocd, plnt, sloc, status,
                               ISNULL(file_uploaded, 0) AS file_uploaded,
                               qinf_material, qinf_zaehl
                        FROM dbo.qm_material_staging
                        WHERE batch_id = :bid AND (status = 'pending' OR (status = 'done' AND source_file IS NOT NULL AND ISNULL(file_uploaded, 0) = 0))
                        ORDER BY id
                    """), {'bid': batch_id}).fetchall()
                else:
                    rows = con.execute(text("""
                        SELECT id, target_dokar, target_dokvr, target_doktl, target_description,
                               target_doknr, source_file, material, vendor, cocd, plnt, sloc, status,
                               qinf_material, qinf_zaehl
                        FROM dbo.qm_material_staging
                        WHERE batch_id = :bid AND status = 'pending'
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
