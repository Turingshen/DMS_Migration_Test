# INFO: async integration of reading from SAP R3 Systems and writing to SAP S/4HANA systems
# from flask import redirect, session, url_for, Response, request
# from urllib.parse import urlencode
import requests
import copy
import mimetypes
import pandas as pd
import json, time
import asyncio
import os
import yaml
import datetime as dt
import time
import authentication as auth  # only used in main thread (snapshot); avoid inside workers
from flask import session as http_session
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')

from app_config import Config
cfg = Config.load()

from app_config import MiscEngine
misc_db = MiscEngine.load()
misc_engine = misc_db.engine

from app_config import DilEngine
dil_db = DilEngine.load()
dil_engine = dil_db.engine

MAX_API_WORKERS = 2
ADD_UP_TO = 5 # each execution should take at least X seconds

MAX_DESC_LEN = 40
MAX_FILENAME_LEN = 80  # Maximum length for stored/uploaded filenames (extension preserved when truncating)
FORBIDDEN_FILENAME_CHARS = ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '\n', '\r', '\t']  # replaced with '_'

read_sap_system = "zhl"
write_sap_system = "zbq"

# API calls are limited. Right now it is about 1.5 seconds per document.
# Each document gets 3 seconds to process. If the process takes less, the worker will wait for the remaining time.
# If the process takes longer, the worker will finish normally. But here you lose efficiency.

# If it happens that the add_up_to are exceeded often, you don't get all out of the API.
# In this case it is recommended to increase the MAX_API_WORKERS variable and the add_up_to variable.
# Calculate the add_up_to time divided by the number of workers. This should always be 1.5 to get the most out of the API.
# You can go with MAX_API_WORKERS to about 50. But then you have to increase the add_up_to time as well to 75.


dokument_query =  f"""
    SELECT
        drad.doknr,
        drad.dokob,
        drad.objky,
        drad.dokar,
        drad.dokvr,
        drad.doktl,
        drad.longtext_id,
        iflos.strno
    FROM dil.drad
    LEFT JOIN iflos ON drad.objky = iflos.strno
    WHERE iflos.tplnr IS NOT NULL;
    """

authgroup_query = """
    SELECT
        draw.doknr,
        draw.dokar,
        draw.dokvr,
        draw.doktl,
        draw.begru
    FROM dil.draw
    WHERE draw.begru IS NOT NULL AND draw.begru <> '';
    """

_authgroup_cache = {}

def _get_auth_group(doknr, dokar, dokvr, doktl):
    """Return cached Authorization Group (BEGRU) only.

    No live database queries here (batch prefetch must have populated `_authgroup_cache`).
    If absent, returns None. This avoids per-document SELECT overhead entirely.
    """
    return _authgroup_cache.get((doknr, dokar, dokvr, doktl))

def _prefetch_auth_groups(base_data):
    """Batch load Authorization Groups (BEGRU) for all documents in the incoming workload.

    This reduces per-document lookup overhead by issuing at most one query per batch.
    Fills the global _authgroup_cache keyed by (doknr,dokar,dokvr,doktl). Safe if called multiple times.
    If the batch is large, the query is split to avoid exceeding parameter limits.
    """
    try:
        # Collect unique keys
        keys = set()
        for _, row in base_data.items():
            # Input rows originate from drad select -> field names may differ
            doknr = row.get('doknr') or row.get('Documentnumber')
            dokar = row.get('dokar') or row.get('Documenttype')
            dokvr = row.get('dokvr') or row.get('Documentversion')
            doktl = row.get('doktl') or row.get('Documentpart')
            if doknr and dokar and dokvr and doktl:
                keys.add((doknr, dokar, dokvr, doktl))
        if not keys:
            return
        # Build a direct OR-composite WHERE clause against draw.
        # Only exact key matches are queried; no broad IN lists.
        or_clauses = []
        for k in keys:
            doknr, dokar, dokvr, doktl = [str(part).replace("'", "''") for part in k]
            or_clauses.append(
                f"(doknr='{doknr}' AND dokar='{dokar}' AND dokvr='{dokvr}' AND doktl='{doktl}')"
            )
        composite_filter = " OR ".join(or_clauses)
        query = f"""
            SELECT doknr, dokar, dokvr, doktl, begru
            FROM dil.draw
            WHERE begru IS NOT NULL AND begru <> ''
                AND ({composite_filter})
        """
        with dil_engine.begin() as con:
            df = pd.read_sql(query, con)
        for _, r in df.iterrows():
            key = (str(r['doknr']), str(r['dokar']), str(r['dokvr']), str(r['doktl']))
            val = str(r['begru']).strip() if r['begru'] is not None else None
            if val:
                _authgroup_cache.setdefault(key, val)
        print(f"[AUTH_PREFETCH] Loaded {len(df)} authorization group rows; cache size now {len(_authgroup_cache)}")
    except Exception as e:
        try:
            print(f"[WARN] Authorization group prefetch failed: {e}")
        except Exception:
            pass

def prepare_session_headers(server_session, session_snapshot, sap_system):
    """Prepare headers & cookies for a given SAP system without relying on Flask's request context.
    Maintains per-system CSRF token data inside the session_snapshot dict.
    """
    if 'bearer_token' not in session_snapshot or session_snapshot['bearer_token'] is None:
        raise Exception('Missing bearer_token in session snapshot')

    systems_ctx = session_snapshot.setdefault('systems', {})
    sys_ctx = systems_ctx.setdefault(sap_system, {})

    now = time.time()
    if ('x_csrf_token' not in sys_ctx or
        'csrf_token_time' not in sys_ctx or
        now - sys_ctx['csrf_token_time'] > 600):  # renew every 10 min
        # fetch new token
        headers = {
            'Authorization': 'Bearer ' + session_snapshot['bearer_token'],
            'X-API-Key': cfg.get(sap_system, 'X-API-Key'),
            'X-CSRF-Token': 'fetch',
            'Accept': 'application/json'
        }
        api_list = cfg.get(sap_system, 'api_list')
        first_element = next(iter(api_list))
        base_url = cfg.get(sap_system, 'api_list', first_element, 'base_url')
        resp = server_session.get(base_url, headers=headers)
        if resp.status_code != 200:
            raise Exception(f'Failed to fetch CSRF token for {sap_system}: {resp.status_code} {resp.reason}')
        sys_ctx['x_csrf_token'] = resp.headers.get('x-csrf-token')
        sys_ctx['cookies'] = resp.cookies
        sys_ctx['csrf_token_time'] = now

    header_dict = {
        'Authorization': 'Bearer ' + session_snapshot['bearer_token'],
        'X-API-Key': cfg.get(sap_system, 'X-API-Key'),
        'Content-Type': 'application/json',  # default, may be overwritten later for file upload
        'Accept': 'application/json',
        'Accept-Language': 'de',  # Request German language for descriptions (DRAT.LANGU = 'D')
        'sap-language': 'DE',  # SAP-specific language header
        'X-CSRF-Token': sys_ctx['x_csrf_token']
    }
    server_session.headers.update(header_dict)
    server_session.cookies.update(sys_ctx['cookies'])


def _extract_error_fields(resp, max_raw_len=500):
    """Extract structured error information from SAP/BTP OData responses."""
    info = {}
    if resp is None:
        return info
    try:
        info['status_code'] = resp.status_code
        info['reason'] = resp.reason
    except Exception:
        pass
    body_text = ''
    try:
        body_text = resp.text or ''
    except Exception:
        body_text = ''
    parsed = None
    if body_text:
        try:
            parsed = resp.json()
        except Exception:
            parsed = None
    if isinstance(parsed, dict):
        for k in ('title', 'detail', 'instance', 'status'):
            if k in parsed and parsed[k]:
                info[k] = parsed[k]
        # CAP / BTP style messages array
        if 'messages' in parsed and isinstance(parsed['messages'], list):
            info['messages'] = parsed['messages'][:10]
        err = parsed.get('error') if 'error' in parsed else None
        if isinstance(err, dict):
            if 'message' in err:
                msg_obj = err['message']
                if isinstance(msg_obj, dict) and 'value' in msg_obj:
                    info.setdefault('detail', msg_obj['value'])
                elif isinstance(msg_obj, str):
                    info.setdefault('detail', msg_obj)
            if 'code' in err:
                info.setdefault('code', err['code'])
            inner = err.get('innererror') if isinstance(err, dict) else None
            if isinstance(inner, dict):
                if 'errordetails' in inner:
                    try:
                        info['errordetails'] = inner['errordetails'][:10]
                    except Exception:
                        pass
                app_inner = inner.get('application') if isinstance(inner.get('application'), dict) else None
                if app_inner and isinstance(app_inner.get('messages'), list):
                    info['messages'] = app_inner['messages'][:10]
    return info


def _classify_error(err_info):
    """Classify an error into a broader bucket to ease filtering in UI/output."""
    if not err_info:
        return 'UNKNOWN'
    code = err_info.get('status_code') or err_info.get('status') or ''
    detail = (err_info.get('detail') or err_info.get('title') or '').lower()
    sap_code = str(err_info.get('code', '')).upper()
    
    # SAP-specific error codes
    if sap_code:
        if 'AUTH' in sap_code or 'PERM' in sap_code:
            return 'AUTH_ERROR'
        if 'LOCK' in sap_code:
            return 'LOCKED'
        if 'NOT_FOUND' in sap_code or 'NOTFOUND' in sap_code:
            return 'NOT_FOUND'
        if 'DUPLICATE' in sap_code or 'EXIST' in sap_code:
            return 'ALREADY_EXISTS'
        if 'INVALID' in sap_code:
            return 'VALIDATION_ERROR'
    
    if isinstance(code, int):
        if code >= 500:
            return 'SERVER_ERROR'
        if code == 429:
            return 'RATE_LIMIT'
        if code == 413:
            return 'PAYLOAD_TOO_LARGE'
        if code == 404:
            return 'NOT_FOUND'
        if code == 409:
            return 'CONFLICT'
        if code == 403:
            return 'FORBIDDEN'
        if code == 401:
            return 'UNAUTHORIZED'
        if code == 400:
            return 'BAD_REQUEST'
    
    # Text-based classification
    if 'timeout' in detail:
        return 'TIMEOUT'
    if 'duplicate' in detail or 'exist' in detail:
        return 'ALREADY_EXISTS'
    if 'size' in detail or 'large' in detail or 'limit' in detail:
        return 'PAYLOAD_TOO_LARGE'
    if 'lock' in detail:
        return 'LOCKED'
    if 'auth' in detail or 'permission' in detail:
        return 'AUTH_ERROR'
    if 'invalid' in detail or 'validation' in detail:
        return 'VALIDATION_ERROR'
    if 'connection' in detail or 'network' in detail:
        return 'NETWORK_ERROR'
    return 'OTHER'


def get_error_description(category):
    """Get human-readable description for error category."""
    descriptions = {
        'UNKNOWN': 'Unbekannter Fehler',
        'SERVER_ERROR': 'SAP Server Fehler (5xx)',
        'RATE_LIMIT': 'API Rate Limit erreicht',
        'PAYLOAD_TOO_LARGE': 'Datei zu groß',
        'NOT_FOUND': 'Dokument nicht gefunden',
        'CONFLICT': 'Konflikt/Änderungskonflikt',
        'FORBIDDEN': 'Keine Berechtigung',
        'UNAUTHORIZED': 'Nicht authentifiziert',
        'BAD_REQUEST': 'Ungültige Anfrage',
        'TIMEOUT': 'Zeitüberschreitung',
        'ALREADY_EXISTS': 'Bereits vorhanden',
        'LOCKED': 'Objekt gesperrt',
        'AUTH_ERROR': 'Berechtigungsfehler',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'NETWORK_ERROR': 'Netzwerkfehler',
        'OTHER': 'Sonstiger Fehler'
    }
    return descriptions.get(category, category)


def _new_timeline():
    return []


def _add_timeline_event(timeline, stage, status=None, start=None, end=None, error=None, meta=None):
    try:
        event = {
            'stage': stage,
            'status': status
        }
        if error:
            event['error'] = error
            event['error_class'] = _classify_error(error)
        if meta:
            event['meta'] = meta
        timeline.append(event)
    except Exception:
        pass


def _compact_doc_record(doc_record):
    """Produce a lightweight representation of a full doc_record.

    Removes bulky branches (read/write details) once we have timeline + overall_status.
    Additionally strips source identifier fields that are already implicit in headers
    or persisted separately, to reduce payload size passed back to callers.

    Dropped identifier keys inside meta.source_document:
        - Documentnumber
        - Documentpart
        - Documenttype
        - Documentversion
        - LOIOID

    If after pruning the source_document dict becomes empty, it is removed entirely.
    Safe on missing keys.
    """
    keep_keys = {'meta', 'overall_status', 'timeline'}
    compact = {k: v for k, v in doc_record.items() if k in keep_keys}
    try:
        src = compact.get('meta', {}).get('source_document')
        if isinstance(src, dict):
            for k in ['Documentnumber', 'Documentpart', 'Documenttype', 'Documentversion', 'LOIOID']:
                src.pop(k, None)
            # remove empty container to avoid noise
            if len(src) == 0:
                compact.get('meta', {}).pop('source_document', None)
    except Exception:
        pass  # pruning is best-effort; never break compaction
    return compact


def _flatten_doc_record(doc_record):
    """Flatten a (now compact) doc_record into a persistence row.
    Works with the minimized structure (meta, timeline, overall_status).
    Derives read/create/upload metrics from timeline events instead of bulky branches.
    """
    try:
        meta = doc_record.get('meta', {}) or {}
        src = meta.get('source_document', {}) or {}
        timeline = doc_record.get('timeline', []) or []

        def find_event(stage_names):
            if isinstance(stage_names, str):
                stage_names = {stage_names}
            else:
                stage_names = set(stage_names)
            for ev in timeline:
                if ev.get('stage') in stage_names:
                    return ev
            return {}

        read_ev = find_event('READ_ATTACHMENT')
        create_ev = find_event({'CREATE_INFO_RECORD', 'CREATE_INFO_RECORD_REUSED'})
        upload_ev = find_event('UPLOAD_ATTACHMENT')

        # Meta extraction helpers
        read_meta = read_ev.get('meta', {}) if isinstance(read_ev.get('meta'), dict) else {}
        create_meta = create_ev.get('meta', {}) if isinstance(create_ev.get('meta'), dict) else {}
        upload_meta = upload_ev.get('meta', {}) if isinstance(upload_ev.get('meta'), dict) else {}

        # Error class classification (prefer upload, then create)
        final_error_class = _classify_error(
            (upload_ev.get('error') or create_ev.get('error') or {})
        )

        row = {
            'logged_at_utc': dt.datetime.utcnow().isoformat(timespec='seconds'),
            # source identifiers (may be pruned already -> None)
            'source_documentnumber': src.get('Documentnumber'),
            'source_documentpart': src.get('Documentpart'),
            'source_documenttype': src.get('Documenttype'),
            'source_documentversion': src.get('Documentversion'),
            'source_loioid': src.get('LOIOID'),
            # file level meta
            'filename': meta.get('filename'),
            'description': meta.get('chosen_description'),
            'overall_status': doc_record.get('overall_status'),
            # read phase (derived)
            'read_status': read_ev.get('status'),
            'read_size_bytes': read_meta.get('size_bytes'),
            # create phase (derived)
            'create_status': create_ev.get('status'),
            'create_timing_ms': create_meta.get('timing_ms'),
            'create_error_class': (create_ev.get('error') or {}).get('status') or (create_ev.get('error') or {}).get('code'),
            # upload phase (derived)
            'upload_status': upload_ev.get('status'),
            'upload_timing_ms': upload_meta.get('timing_ms'),
            'upload_bytes_sent': upload_meta.get('bytes_sent'),
            'upload_padded_empty_file': upload_meta.get('padded_empty_file'),
            'final_error_class': final_error_class,
            # serialized JSON blobs (operations/payload kept minimal/empty for schema compatibility)
            'timeline_json': json.dumps(timeline),
            'operations_json': json.dumps([]),
            'payload_create_json': json.dumps((meta.get('payload') or {}).get('create', {})),
            'payload_upload_json': json.dumps((meta.get('payload') or {}).get('upload', {})),
        }
        return row
    except Exception as e:
        return {
            'logged_at_utc': dt.datetime.utcnow().isoformat(timespec='seconds'),
            'overall_status': f'FLATTEN_EXCEPTION {e}'
        }


def _sanitize_filename(name):
    """Replace forbidden characters in filenames with underscore.
    Keeps extension; collapsing multiple consecutive underscores into one for readability.
    Safe on any input (returns 'unnamed' if empty/None)."""
    try:
        if not name:
            return 'unnamed'
        # Translate forbidden characters
        trans_map = {ord(c): '_' for c in FORBIDDEN_FILENAME_CHARS}
        sanitized = name.translate(trans_map)
        # Collapse repeated underscores
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')
        sanitized = sanitized.strip('._')  # avoid leading/trailing punctuation causing issues
        # Enforce max length while preserving extension where possible
        if len(sanitized) > MAX_FILENAME_LEN:
            root, ext = os.path.splitext(sanitized)
            if ext and len(ext) < MAX_FILENAME_LEN:
                allowed_root_len = MAX_FILENAME_LEN - len(ext)
                if allowed_root_len > 0:
                    sanitized = root[:allowed_root_len] + ext
                else:
                    sanitized = sanitized[:MAX_FILENAME_LEN]
            else:
                sanitized = sanitized[:MAX_FILENAME_LEN]
        return sanitized or 'unnamed'
    except Exception:
        return 'unnamed'


def api_call(server_session, index, data_chunk, session_snapshot):
    """Construct and execute SAP read/create/upload flow returning compact doc_records only."""
    own_session = False
    if server_session is None:
        server_session = requests.Session()
        own_session = True
    start_time = time.time()
    return_data = []

    print("data_chunk:", data_chunk)
    sap_system = read_sap_system
    try:
        prepare_session_headers(server_session, session_snapshot, sap_system)
    except Exception as e:
        print('Error preparing headers for read system:', e)
        return {'index': index, 'Documentnumber': data_chunk.get('Documentnumber'), 'return_data': [
            {'overall_status': f'SESSION_ERROR {e}', 'timeline': [], 'meta': {'source_document': {'Documentnumber': data_chunk.get('Documentnumber')}}}
        ]}

    documents = get_info(server_session, sap_system, data_chunk['Documentnumber'], data_chunk['Documentpart'], data_chunk['Documenttype'], data_chunk['Documentversion'])

    if documents[0] != 200:
        print('Error during getinfo:', documents[0], documents[1])
        return_data.append({'overall_status': f'{documents[0]} {documents[1]}', 'timeline': [], 'meta': {'source_document': {'Documentnumber': data_chunk['Documentnumber']}}})
        time_taken = time.time() - start_time
        if time_taken < ADD_UP_TO:
            delay = ADD_UP_TO - time_taken
            print(f'Waiting for {delay} seconds')
            time.sleep(delay)
        return {'index': index, 'Documentnumber': data_chunk['Documentnumber'], 'return_data': return_data}

    if documents[0] == 200 and (documents[2] == [] or documents[2] is None):
        print('No documents in document container', data_chunk['Documentnumber'])
        return_data.append({'overall_status': f'{documents[0]} {documents[1]} - EMPTY', 'timeline': [], 'meta': {'source_document': {'Documentnumber': data_chunk['Documentnumber']}}})
        time_taken = time.time() - start_time
        if time_taken < ADD_UP_TO:
            delay = ADD_UP_TO - time_taken
            print(f'Waiting for {delay} seconds')
            time.sleep(delay)
        return {'index': index, 'Documentnumber': data_chunk['Documentnumber'], 'return_data': return_data}

    doc_created = False
    proceed_upload_global = False
    create_status_global = None

    for document in documents[2]:
        # Re-prepare headers for READ system each iteration (cleans Slug)
        try:
            prepare_session_headers(server_session, session_snapshot, read_sap_system)
            server_session.headers.pop('Slug', None)
        except Exception as e:
            print('Error re-preparing headers for read system (loop):', e)
            return_data.append({'overall_status': f'READ_PREP_FAIL {e}', 'timeline': [], 'meta': {'source_document': {'Documentnumber': data_chunk['Documentnumber']}}})
            continue

        selected_keys = ['Documentnumber', 'Documentpart', 'Documenttype', 'Documentversion', 'LOIOID']
        document_args = {k: document[k] for k in selected_keys}
        formatted_args = ",".join(f"{k}='{v}'" for k, v in document_args.items())
        base_read_url = cfg.get(sap_system, 'api_list', 'document', 'base_url')
        request_url = f"{base_read_url}/DocumentfilesSet({formatted_args})/$value"
        read_started = time.time()
        response = server_session.get(request_url)
        read_ended = time.time()

        # Build compact doc_record immediately
        doc_record = {
            'meta': {
                'source_document': {
                    'Documentnumber': document['Documentnumber'],
                    'Documentpart': document['Documentpart'],
                    'Documenttype': document['Documenttype'],
                    'Documentversion': document['Documentversion'],
                    'LOIOID': document.get('LOIOID')
                }
            },
            'timeline': _new_timeline()
        }

        if response.status_code == 200:
            filename = os.path.basename(document.get('Docpath', ''))
            filename = filename.split('?')[0] if filename else 'unknown_filename'
            filename = _sanitize_filename(filename)
            doc_record['meta']['filename'] = filename
            read_status = f"READ_{response.status_code}"
            size_bytes = len(response.content or b'')
            try:
                print(f"[READ] Retrieved file '{filename}' size={size_bytes} bytes Documentnumber={document.get('Documentnumber')} LOIOID={document.get('LOIOID')}")
            except Exception:
                pass
        else:
            doc_record['meta']['filename'] = ''
            read_status = f"READ_{response.status_code}"
            size_bytes = None

        _add_timeline_event(doc_record['timeline'], 'READ_ATTACHMENT', status=read_status, start=read_started, end=read_ended,
                            error=_extract_error_fields(response) if response.status_code != 200 else None,
                            meta={'url': request_url, 'size_bytes': size_bytes, 'status_code': response.status_code})
        overall_status = read_status

        # CREATE & UPLOAD
        if response.status_code == 200 and doc_record['meta']['filename']:
            try:
                prepare_session_headers(server_session, session_snapshot, write_sap_system)
                proceed_upload = False
                if not doc_created:
                    doc_type = document['Documenttype']
                    doc_number = "X55-" + document['Documentnumber'].lstrip('0')
                    doc_version = document['Documentversion']
                    doc_part = document['Documentpart']
                    source_description = document.get('Description') or document.get('DocumentDescription')
                    filename_for_desc = doc_record['meta'].get('filename') or 'Unnamed Document'
                    if isinstance(source_description, str):
                        source_description = source_description.strip()
                    if not source_description:
                        source_description = filename_for_desc
                    if len(source_description) > MAX_DESC_LEN:
                        source_description = source_description[:MAX_DESC_LEN]
                    doc_record['meta']['chosen_description'] = source_description
                    doc_base_url = cfg.get(write_sap_system, 'api_list', 'document', 'base_url')
                    create_url = f"{doc_base_url}/A_DocumentInfoRecord"
                    server_session.headers.update({'Content-Type': 'application/json'})
                    create_started = time.time()
                    dms_payload = {
                        'DocumentInfoRecordDocType': doc_type,
                        'DocumentInfoRecordDocNumber': doc_number,
                        'DocumentInfoRecordDocVersion': doc_version,
                        'DocumentInfoRecordDocPart': doc_part,
                        'to_DocDesc': [
                            {'Language': 'DE', 'DocumentDescription': source_description},
                            {'Language': 'EN', 'DocumentDescription': source_description}
                        ]
                    }
                    # Inject Authorization Group (BEGRU) if available in source system
                    auth_group = _get_auth_group(document['Documentnumber'], document['Documenttype'], document['Documentversion'], document['Documentpart'])
                    if auth_group:
                        dms_payload['AuthorizationGroup'] = auth_group
                        try:
                            print(f"[CREATE] Using Authorization Group '{auth_group}' for {doc_number}")
                        except Exception:
                            pass
                    else:
                        try:
                            print(f"[CREATE] No Authorization Group found for source ({document['Documentnumber']},{document['Documenttype']},{document['Documentversion']},{document['Documentpart']})")
                        except Exception:
                            pass
                    print("DMS Payload:", dms_payload)
                    create_resp = server_session.post(create_url, json=dms_payload)
                    create_ended = time.time()
                    timing_ms = round((create_ended - create_started) * 1000, 1)
                    try:
                        print(f"[CREATE] Target record number={doc_number} status={create_resp.status_code}")
                    except Exception:
                        pass
                    body_txt_lower = ''
                    try:
                        body_txt_lower = create_resp.text.lower()
                    except Exception:
                        pass
                    if create_resp.status_code in (200, 201):
                        create_status = f"S4_CREATE_{create_resp.status_code}"
                        proceed_upload = True
                    elif create_resp.status_code in (400, 409) and any(x in body_txt_lower for x in ['exist', 'duplicate', 'already']):
                        create_status = f"S4_CREATE_TOLERATED {create_resp.status_code}"
                        proceed_upload = True
                    else:
                        create_status = f"S4_CREATE_FAIL {create_resp.status_code}"
                    create_err = _extract_error_fields(create_resp) if not proceed_upload else None
                    _add_timeline_event(doc_record['timeline'], 'CREATE_INFO_RECORD', status=create_status, start=create_started, end=create_ended,
                                        error=create_err, meta={'url': create_url, 'timing_ms': timing_ms, 'multi_file_container': True})
                    overall_status = create_status
                    if proceed_upload:
                        doc_created = True
                        proceed_upload_global = True
                        create_status_global = create_status
                        doc_record.setdefault('meta', {}).setdefault('payload', {})
                        doc_record['meta']['payload']['create'] = {
                            'DocumentInfoRecordDocType': doc_type,
                            'DocumentInfoRecordDocNumber': doc_number
                        }
                    else:
                        proceed_upload_global = False
                else:
                    # Reused create
                    reused_status = create_status_global or 'S4_CREATE_REUSED'
                    _add_timeline_event(doc_record['timeline'], 'CREATE_INFO_RECORD_REUSED', status=reused_status,
                                        meta={'reused': True, 'multi_file_container': True})
                    proceed_upload = proceed_upload_global

                if doc_created and proceed_upload_global and proceed_upload:
                    filename = doc_record['meta']['filename']
                    mime_type, _ = mimetypes.guess_type(filename)
                    if not mime_type:
                        mime_type = 'application/octet-stream'
                    server_session.headers.update({'Content-Type': mime_type, 'Slug': filename})
                    payload_create = doc_record.get('meta', {}).get('payload', {}).get('create', {})
                    doc_type = payload_create.get('DocumentInfoRecordDocType')
                    doc_number = payload_create.get('DocumentInfoRecordDocNumber')
                    doc_version = document['Documentversion']
                    doc_part = document['Documentpart']
                    try:
                        attachment_base_url = cfg.get(write_sap_system, 'api_list', 'attachment', 'base_url')
                    except Exception:
                        attachment_base_url = cfg.get(write_sap_system, 'api_list', 'document', 'base_url')
                    attachment_url = (
                        f"{attachment_base_url}/A_DocumentInfoRecordAttch"\
                        f"(DocumentInfoRecordDocType='{doc_type}',"\
                        f"DocumentInfoRecordDocNumber='{doc_number}',"\
                        f"DocumentInfoRecordDocVersion='{doc_version}',"\
                        f"DocumentInfoRecordDocPart='{doc_part}'"\
                        f")/DocumentInfoRecordToAttachmentNavigation"
                    )
                    original_bytes = response.content or b''
                    padded = False
                    if len(original_bytes) == 0:
                        original_bytes = b' '
                        padded = True
                    upload_started = time.time()
                    upload_resp = server_session.post(attachment_url, data=original_bytes)
                    upload_ended = time.time()
                    upload_timing_ms = round((upload_ended - upload_started) * 1000, 1)
                    try:
                        print(f"[UPLOAD] '{filename}' bytes={len(original_bytes)} status={upload_resp.status_code}")
                    except Exception:
                        pass
                    if upload_resp.status_code in (200, 201):
                        status_label = 'CREATED' if upload_resp.status_code == 201 else 'OK'
                        upload_status = f"S4_{status_label}"
                    else:
                        upload_status = f"S4_UPLOAD_FAIL {upload_resp.status_code}"
                    upload_err = _extract_error_fields(upload_resp) if 'FAIL' in upload_status else None
                    _add_timeline_event(doc_record['timeline'], 'UPLOAD_ATTACHMENT', status=upload_status,
                                        error=upload_err, meta={'url': attachment_url, 'bytes_sent': len(original_bytes), 'padded_empty_file': padded, 'timing_ms': upload_timing_ms, 'mime_type': mime_type})
                    overall_status = upload_status
                    doc_record.setdefault('meta', {}).setdefault('payload', {})
                    doc_record['meta']['payload']['upload'] = {
                        'bytes_sent': len(original_bytes),
                        'padded_empty_file': padded,
                        'mime_type': mime_type
                    }
                else:
                    _add_timeline_event(doc_record['timeline'], 'UPLOAD_ATTACHMENT', status='SKIPPED_PREVIOUS_STAGE_FAILED', meta={'skipped': True})
                    if overall_status.startswith('READ_'):
                        overall_status = 'SKIPPED_PREVIOUS_STAGE_FAILED'
            except Exception as e:
                _add_timeline_event(doc_record['timeline'], 'EXCEPTION', status=f'S4_EXCEPTION {e}', error={'detail': str(e)})
                overall_status = f'S4_EXCEPTION {e}'
        else:
            _add_timeline_event(doc_record['timeline'], 'WRITE_SKIPPED', status='READ_FAILED_OR_EMPTY')
            overall_status = read_status

        doc_record['overall_status'] = overall_status
        return_data.append(doc_record)

        # Persist
        try:
            flat_row = _flatten_doc_record(doc_record)
            df_row = pd.DataFrame([flat_row])
            with misc_engine.begin() as con:
                df_row.to_sql('migration_log_documents', con, schema='dbo', if_exists='append', index=False, method='multi')
        except Exception as e:
            try:
                print('Failed to persist migration log row:', e)
            except Exception:
                pass

    # pacing
    time_taken = time.time() - start_time
    if time_taken < ADD_UP_TO:
        delay = ADD_UP_TO - time_taken
        print(f'Waiting for {delay} seconds')
        time.sleep(delay)
    if own_session:
        try:
            server_session.close()
        except Exception:
            pass
    return {'index': index, 'Documentnumber': data_chunk['Documentnumber'], 'return_data': return_data}


async def async_process(input_data, session_snapshot):
    """async process to create list of calls which will be executed later.
    session_snapshot is a plain dict copy of needed session values to avoid using Flask context in threads.
    """

    with ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
        print('run asynchon tasks')
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(executor, api_call, *(None, index, data_chunk, session_snapshot))
            for index, data_chunk in input_data.items()
        ]

        ## post processing
        for response in await asyncio.gather(*tasks):
            doc_list = input_data[response['index']].setdefault('documents_tree', [])
            for doc_tree in response['return_data']:
                compacted = _compact_doc_record(doc_tree)
                doc_list.append(compacted)
                    
                # # error handeling
                # except Exception as e:
                #     input_data[response['index']]['status'] = 'post processing error: ' + str(e)


def get_info(server_session, sap_system, Documentnumber, Documentpart='000', Documenttype='IY1', Documentversion='00'):
    """Get List of all attached Documents incl. Links.
    """
    
    api_args = {"Documentnumber":Documentnumber, "Documentpart":Documentpart, "Documenttype":Documenttype, "Documentversion":Documentversion}
    formatted_args   = ",".join(f"{key}='{value}'" for key, value in api_args.items())

    base_url = cfg.get(sap_system, "api_list", "document", "base_url")
    response = server_session.get(f"{base_url}/DocumentSet({formatted_args})?$expand=DocumentfilesSet" )   
    # print(f"{cfg.get(sap_system, "api_list", "document", 'base_url')}/DocumentSet({formatted_args})?$expand=DocumentfilesSet")
    doc_data = []

    try:
        data = json.loads(response.content)
    except:
        data = response.content

    # Handle empty response body (document not found in source system)
    if response.status_code == 200 and response.content == b'':
        print(f'[WARN] Document not found in source: {Documentnumber} - API returned empty body')
        return 200, 'NOT_FOUND_EMPTY', []  # Return empty list, not None
    
    if response.status_code == 200:
        # keep full raw for potential description lookup
        full_raw = data
        try:
            data = full_raw['d']['DocumentfilesSet']['results']
        except (KeyError, TypeError) as e:
            print(f'[WARN] Unexpected response structure for {Documentnumber}: {e}')
            print(f'Response content: {response.content[:500]}...' if len(response.content) > 500 else f'Response content: {response.content}')
            return 200, 'PARSE_ERROR', []
        
        # list of documents
        for item in data:
            item.pop('__metadata')
            # Attempt to inject a generic 'DocumentDescription' if present in parent structures or item itself
            # Common field paths: item['DocumentDescription'], item['Description'], etc.
            possible_desc = None
            for cand_key in ['DocumentDescription', 'Description', 'DocDescription', 'DOCUMENTDESCRIPTION']:
                cand_val = item.get(cand_key)
                if isinstance(cand_val, str) and cand_val.strip():
                    possible_desc = cand_val.strip()
                    break
            if possible_desc:
                item['DocumentDescription'] = possible_desc  # normalize
            doc_data.append(item)
        # print('doc_data:', json.dumps(doc_data, indent=4))
        return response.status_code, response.reason, doc_data
    
    else:
        print('Error during getinfo:', response.status_code, response.reason)
        try:
            print('Error detail:', json.dumps(data['error']['innererror']['errordetails'], indent=4))
        except:
            print('Error detail:', data)
        return response.status_code, f'API_ERROR_{response.status_code}', None


def start_worker(input_data):
    """start async workers (captures Flask session values before leaving request context)"""
    print('start async workers:')

    print('Start Worker with input data:')
    # print(input_data)
    
    base_data = input_data.to_dict(orient='index')
    # print(json.dumps(base_data, indent=4))

    # Batch prefetch authorization groups before kicking off async workload
    _prefetch_auth_groups(base_data)


    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # Snapshot only required values to avoid using http_session inside worker threads
    session_snapshot = {
        'bearer_token': http_session.get('bearer_token'),
        'sap_system': http_session.get('sap_system'),  # original selected system (may equal read_sap_system)
        # Optional legacy values if already fetched (will be renewed lazily otherwise)
        'x_csrf_token': http_session.get('x-csrf-token'),
        'cookies': http_session.get('cookies'),
        'csrf_token_time': http_session.get('csrf_token_time', 0)
    }

    future = asyncio.ensure_future(async_process(base_data, session_snapshot))
    loop.run_until_complete(future)
    print('all done')
    # print('return data:', json.dumps(base_data, indent=4))
    return base_data

if __name__ == "__main__":

    print('this is a module, not a script.')
    