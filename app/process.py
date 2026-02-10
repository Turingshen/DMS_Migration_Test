"""SAP R/3 to S/4HANA document migration - API integration module.

Provides session management, error classification, file sanitization,
and the core get_info() function for reading document data from SAP.
"""
import requests
import mimetypes
import pandas as pd
import json
import os
import yaml
import datetime as dt
import time
import authentication as auth

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

# Defaults — can be overridden per session via /switch_system
DEFAULT_SOURCE_SYSTEM = "zhl"
DEFAULT_TARGET_SYSTEM = "zbq"

# Module-level aliases (used by execute.py at snapshot time)
read_sap_system = DEFAULT_SOURCE_SYSTEM
write_sap_system = DEFAULT_TARGET_SYSTEM


def get_source_system(session_snapshot=None):
    """Get active source (read) SAP system from session or default."""
    if session_snapshot and 'source_system' in session_snapshot:
        return session_snapshot['source_system']
    return DEFAULT_SOURCE_SYSTEM


def get_target_system(session_snapshot=None):
    """Get active target (write) SAP system from session or default."""
    if session_snapshot and 'target_system' in session_snapshot:
        return session_snapshot['target_system']
    return DEFAULT_TARGET_SYSTEM


def get_systems_by_type():
    """Return dict of source (R3) and target (S4) system lists from config."""
    source_systems = {}  # R3 systems
    target_systems = {}  # S4 systems
    config = cfg.config_env
    for key, value in config.items():
        if isinstance(value, dict) and 'system_label' in value and 'system_type' in value:
            if value['system_type'] == 'R3':
                source_systems[key] = value['system_label']
            elif value['system_type'] == 'S4':
                target_systems[key] = value['system_label']
    return source_systems, target_systems


def prepare_session_headers(server_session, session_snapshot, sap_system):
    """Prepare headers & cookies for a given SAP system without relying on Flask's request context.
    Maintains per-system CSRF token data inside the session_snapshot dict.
    
    Supports two auth modes:
    - OAuth/API-Key (default): Bearer token + X-API-Key via BTP API Gateway
    - Basic Auth: username/password for direct SAP (ZV) systems (auth_type='basic' in config)
    """
    auth_type = cfg.config_env.get(sap_system, {}).get('auth_type', 'oauth')
    is_basic = auth_type == 'basic'

    if is_basic:
        # Load encrypted credentials from DB
        from app.credentials import get_credentials
        creds = get_credentials(sap_system)
        if not creds:
            raise Exception(f'No Basic Auth credentials stored for {sap_system}. Configure them in Settings.')
        auth_tuple = (creds['username'], creds['password'])
        verify_ssl = cfg.config_env.get(sap_system, {}).get('verify_ssl', True)
    else:
        # OAuth mode — requires bearer_token in session
        if 'bearer_token' not in session_snapshot or session_snapshot['bearer_token'] is None:
            raise Exception('Missing bearer_token in session snapshot')

    systems_ctx = session_snapshot.setdefault('systems', {})
    sys_ctx = systems_ctx.setdefault(sap_system, {})

    # ── STEP 1: Clean session state BEFORE any requests to this system ──
    # Remove stale headers, cookies, and auth from the previous system.
    # This MUST happen before the CSRF fetch, otherwise foreign headers/cookies
    # (e.g. BTP Bearer token, ZHL cookies) get sent to ZVFR3 and cause 403.
    if is_basic:
        server_session.headers.pop('Authorization', None)
        server_session.headers.pop('X-API-Key', None)
        server_session.auth = auth_tuple
        server_session.verify = verify_ssl
    else:
        server_session.auth = None
        server_session.verify = True  # Re-enable SSL verification for BTP gateway
    server_session.cookies.clear()

    # ── STEP 2: CSRF token management ──
    now = time.time()
    if ('x_csrf_token' not in sys_ctx or
        'csrf_token_time' not in sys_ctx or
        now - sys_ctx['csrf_token_time'] > 600):  # renew every 10 min
        # Fetch new CSRF token (session is now clean — no foreign cookies/headers)
        if is_basic:
            headers = {
                'X-CSRF-Token': 'fetch',
                'Accept': 'application/json'
            }
            base_url = cfg.get(sap_system, 'api_list', 'document', 'base_url')
            resp = server_session.get(base_url, headers=headers, auth=auth_tuple, verify=verify_ssl)
        else:
            headers = {
                'Authorization': 'Bearer ' + session_snapshot['bearer_token'],
                'X-API-Key': cfg.get(sap_system, 'X-API-Key'),
                'X-CSRF-Token': 'fetch',
                'Accept': 'application/json'
            }
            base_url = cfg.get(sap_system, 'api_list', 'document', 'base_url')
            resp = server_session.get(base_url, headers=headers)
        if resp.status_code != 200:
            raise Exception(f'Failed to fetch CSRF token for {sap_system}: {resp.status_code} {resp.reason}')
        sys_ctx['x_csrf_token'] = resp.headers.get('x-csrf-token')
        # IMPORTANT: Save the FULL session cookies, not just resp.cookies.
        # SAP servers may redirect (e.g. /API_DMS_PROCESS_SRV → /API_DMS_PROCESS_SRV/)
        # and set critical cookies (sap-usercontext, SAP_SESSIONID) in the redirect response.
        # resp.cookies only contains cookies from the final response, missing redirect cookies.
        # server_session.cookies has ALL cookies set during the entire request chain.
        sys_ctx['cookies'] = server_session.cookies.copy()
        sys_ctx['csrf_token_time'] = now
    else:
        # Use cached cookies from previous CSRF fetch
        server_session.cookies.update(sys_ctx['cookies'])

    # ── STEP 3: Set session headers for subsequent API calls ──
    if is_basic:
        header_dict = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Accept-Language': 'de',
            'sap-language': 'DE',
            'X-CSRF-Token': sys_ctx['x_csrf_token']
        }
    else:
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
    """Classify an error into a clear, actionable category.
    
    Categories are grouped by root cause for easier troubleshooting:
    - API_KEY_*: APIM configuration issues
    - TOKEN_*: OAuth/Authentication issues  
    - CSRF_*: CSRF token issues
    - SOURCE_*: Problems reading from source system (R/3)
    - TARGET_*: Problems writing to target system (S/4)
    - UPLOAD_*: File upload specific issues
    - NETWORK_*: Connection/timeout issues
    """
    if not err_info:
        return 'UNKNOWN'
    
    # Extract key fields
    code = err_info.get('status_code') or err_info.get('status') or 0
    detail = (err_info.get('detail') or err_info.get('title') or '').lower()
    reason = (err_info.get('reason') or '').lower()
    sap_code = str(err_info.get('code', '')).upper()
    instance = str(err_info.get('instance', '')).lower()
    
    # Handle malformed status_code (legacy errors with string like "Error during getinfo:")
    if isinstance(code, str):
        code_lower = code.lower()
        if 'error during getinfo' in code_lower or 'error during' in code_lower:
            # Legacy error format - classify by reason
            if 'unauthorized' in reason:
                return 'TOKEN_EXPIRED'
            if 'forbidden' in reason:
                return 'AUTH_FORBIDDEN'
            if 'ok' in reason:  # "unexpected OK" - empty response
                return 'SOURCE_NOT_FOUND'
            return 'SOURCE_READ_ERROR'
        try:
            code = int(code) if code.isdigit() else 0
        except:
            code = 0
    
    # === API KEY ISSUES (APIM) ===
    if 'invalid apikey' in detail or 'apikey' in detail.lower():
        return 'API_KEY_INVALID'
    if 'api key' in detail or 'api-key' in detail:
        return 'API_KEY_INVALID'
    
    # === CSRF TOKEN ISSUES ===
    if 'csrf' in detail or 'csrf' in reason:
        return 'CSRF_FAILED'
    
    # === TOKEN / AUTH ISSUES ===
    if code == 401:
        if 'expired' in detail or 'token' in detail:
            return 'TOKEN_EXPIRED'
        return 'TOKEN_INVALID'
    
    # === PERMISSION ISSUES ===
    if code == 403:
        if 'invalid apikey' in detail:
            return 'API_KEY_INVALID'
        if 'permission' in detail or 'authorized' in detail:
            return 'AUTH_NO_PERMISSION'
        return 'AUTH_FORBIDDEN'
    
    # === SAP-SPECIFIC ERROR CODES ===
    if sap_code:
        if 'AUTH' in sap_code or 'PERM' in sap_code or 'BEGRU' in sap_code:
            return 'AUTH_NO_PERMISSION'
        if 'LOCK' in sap_code:
            return 'TARGET_LOCKED'
        if 'NOT_FOUND' in sap_code or 'NOTFOUND' in sap_code:
            return 'SOURCE_NOT_FOUND'
        if 'DUPLICATE' in sap_code or 'EXIST' in sap_code:
            return 'TARGET_EXISTS'
        if 'INVALID' in sap_code:
            return 'VALIDATION_ERROR'
    
    # === TIMEOUT / GATEWAY ISSUES ===
    if code == 504:
        return 'GATEWAY_TIMEOUT'
    if code == 502 or code == 503:
        return 'SERVER_UNAVAILABLE'
    if 'timeout' in detail or 'timed out' in detail:
        return 'UPLOAD_TIMEOUT'
    
    # === RATE LIMITING ===
    if code == 429:
        return 'RATE_LIMITED'
    
    # === PAYLOAD SIZE ===
    if code == 413:
        return 'UPLOAD_SIZE_EXCEEDED'
    if 'size' in detail and ('exceed' in detail or 'limit' in detail or 'large' in detail):
        return 'UPLOAD_SIZE_EXCEEDED'
    
    # === NOT FOUND ===
    if code == 404:
        if 'attachment' in instance or 'file' in detail:
            return 'SOURCE_NOT_FOUND'
        return 'TARGET_NOT_FOUND'
    
    # === CONFLICT / DUPLICATE ===
    if code == 409 or 'duplicate' in detail or 'already exist' in detail:
        return 'TARGET_EXISTS'
    
    # === SERVER ERRORS (500+) ===
    if code >= 500:
        if 'documentinforecord' in instance or 'create' in detail:
            return 'TARGET_CREATE_FAILED'
        if 'attachment' in instance or 'upload' in detail:
            return 'UPLOAD_FAILED'
        return 'SERVER_ERROR'
    
    # === BAD REQUEST ===
    if code == 400:
        # Fehlende Mappings erkennen (Dokumentart, Werk, etc. nicht vorhanden)
        if 'nicht vorhanden' in detail or 'not found' in detail or 'does not exist' in detail:
            if 'dokumentart' in detail or 'document type' in detail:
                return 'MAPPING_DOCTYPE_MISSING'
            if 'werk' in detail or 'plant' in detail:
                return 'MAPPING_PLANT_MISSING'
            if 'material' in detail:
                return 'MAPPING_MATERIAL_MISSING'
            if 'equipment' in detail or 'equi' in detail:
                return 'MAPPING_EQUIPMENT_MISSING'
            return 'MAPPING_MISSING'
        # Ungültiges Dateiformat / fehlende Extension
        if 'anlagenformat' in detail or 'erweiterung' in detail or 'file format' in detail or 'file extension' in detail:
            return 'VALIDATION_FILETYPE_UNKNOWN'
        # Fehlende Pflichtfelder
        if 'mussfeld' in detail or 'pflichtfeld' in detail or 'required field' in detail:
            if 'begru' in detail or 'berecht' in detail:
                return 'VALIDATION_BEGRU_MISSING'
            return 'VALIDATION_REQUIRED_FIELD'
        if 'validation' in detail or 'invalid' in detail:
            return 'VALIDATION_ERROR'
        return 'BAD_REQUEST'
    
    # === TEXT-BASED FALLBACKS ===
    if 'lock' in detail:
        return 'TARGET_LOCKED'
    if 'permission' in detail or 'authorized' in detail:
        return 'AUTH_NO_PERMISSION'
    if 'connection' in detail or 'network' in detail:
        return 'NETWORK_ERROR'
    if 'empty' in detail or 'no document' in detail or 'not found' in detail:
        return 'SOURCE_NOT_FOUND'
    
    return 'OTHER'


def get_error_description(category):
    """Get human-readable description for error category with action hint."""
    descriptions = {
        # Unknown
        'UNKNOWN': ('Unbekannter Fehler', 'Details prüfen'),
        'OTHER': ('Sonstiger Fehler', 'Details prüfen'),
        
        # API Key / APIM Issues
        'API_KEY_INVALID': ('API-Key ungültig', 'API im APIM freischalten'),
        'API_KEY_MISSING': ('API-Key fehlt', 'Konfiguration prüfen'),
        
        # Token / Auth Issues
        'TOKEN_EXPIRED': ('OAuth Token abgelaufen', 'Neu einloggen'),
        'TOKEN_INVALID': ('OAuth Token ungültig', 'Neu einloggen'),
        'CSRF_FAILED': ('CSRF Token Fehler', 'Session erneuern'),
        
        # Permission Issues  
        'AUTH_NO_PERMISSION': ('Keine SAP-Berechtigung', 'BEGRU/Rolle prüfen'),
        'AUTH_FORBIDDEN': ('Zugriff verweigert (403)', 'Berechtigungen prüfen'),
        
        # Source System Issues (R/3)
        'SOURCE_NOT_FOUND': ('Dokument in R/3 nicht gefunden', 'Quelldaten prüfen'),
        'SOURCE_EMPTY': ('Container ohne Dateien', 'Erwartet - leer'),
        'SOURCE_READ_ERROR': ('Lesefehler im Quellsystem', 'R/3 API prüfen'),
        
        # Target System Issues (S/4)
        'TARGET_CREATE_FAILED': ('Anlage fehlgeschlagen', 'SAP Log prüfen'),
        'TARGET_EXISTS': ('Dokument existiert bereits', 'Duplikat prüfen'),
        'TARGET_LOCKED': ('Objekt gesperrt', 'Sperre lösen'),
        'TARGET_NOT_FOUND': ('Zielobjekt nicht gefunden', 'Mapping prüfen'),
        
        # Upload Issues
        'UPLOAD_SIZE_EXCEEDED': ('Datei zu groß', 'Max. 50MB pro Datei'),
        'UPLOAD_TIMEOUT': ('Upload-Timeout', 'Kleinere Datei verwenden'),
        'UPLOAD_FAILED': ('Upload fehlgeschlagen', 'Details prüfen'),
        
        # Network / Gateway Issues
        'GATEWAY_TIMEOUT': ('API Gateway Timeout (504)', 'Später erneut versuchen'),
        'SERVER_UNAVAILABLE': ('Server nicht erreichbar', 'Später erneut versuchen'),
        'RATE_LIMITED': ('Rate Limit erreicht (429)', 'Pacing erhöhen'),
        'SERVER_ERROR': ('SAP Serverfehler (5xx)', 'SAP Support kontaktieren'),
        'NETWORK_ERROR': ('Netzwerkfehler', 'Verbindung prüfen'),
        
        # Validation Issues
        'VALIDATION_ERROR': ('Validierungsfehler', 'Eingabedaten prüfen'),
        'VALIDATION_REQUIRED_FIELD': ('Pflichtfeld fehlt', 'Quelldaten prüfen'),
        'VALIDATION_BEGRU_MISSING': ('Berechtigungsgruppe fehlt', 'BEGRU in Quelldaten prüfen'),
        'VALIDATION_FILETYPE_UNKNOWN': ('Dateityp unbekannt', 'Extension in DRAW.filep prüfen'),
        'BAD_REQUEST': ('Ungültige Anfrage (400)', 'Request prüfen'),
    }
    
    entry = descriptions.get(category)
    if entry:
        return entry[0]  # Return just the description for backwards compatibility
    return category


def get_error_details(category):
    """Get full error details including description and action hint.
    
    Returns:
        tuple: (description, action_hint) or (category, '') if not found
    """
    descriptions = {
        # API Key / APIM Issues
        'API_KEY_INVALID': ('API-Key ungültig', 'API im APIM freischalten'),
        'API_KEY_MISSING': ('API-Key fehlt', 'Konfiguration prüfen'),
        
        # Token / Auth Issues
        'TOKEN_EXPIRED': ('OAuth Token abgelaufen', 'Neu einloggen'),
        'TOKEN_INVALID': ('OAuth Token ungültig', 'Neu einloggen'),
        'CSRF_FAILED': ('CSRF Token Fehler', 'Session erneuern'),
        
        # Permission Issues  
        'AUTH_NO_PERMISSION': ('Keine SAP-Berechtigung', 'BEGRU/Rolle prüfen'),
        'AUTH_FORBIDDEN': ('Zugriff verweigert (403)', 'Berechtigungen prüfen'),
        
        # Source System Issues (R/3)
        'SOURCE_NOT_FOUND': ('Dokument in R/3 nicht gefunden', 'Quelldaten prüfen'),
        'SOURCE_EMPTY': ('Container ohne Dateien', 'Erwartet - leer'),
        'SOURCE_READ_ERROR': ('Lesefehler im Quellsystem', 'R/3 API prüfen'),
        
        # Target System Issues (S/4)
        'TARGET_CREATE_FAILED': ('Anlage fehlgeschlagen', 'SAP Log prüfen'),
        'TARGET_EXISTS': ('Dokument existiert bereits', 'Duplikat prüfen'),
        'TARGET_LOCKED': ('Objekt gesperrt', 'Sperre lösen'),
        'TARGET_NOT_FOUND': ('Zielobjekt nicht gefunden', 'Mapping prüfen'),
        
        # Mapping Issues (Objekt im Zielsystem nicht vorhanden)
        'MAPPING_MISSING': ('Stammdaten fehlen im Ziel', 'Mapping-Regel erstellen'),
        'MAPPING_DOCTYPE_MISSING': ('Dokumentart fehlt im Ziel', 'Dokumenttyp-Mapping erstellen'),
        'MAPPING_PLANT_MISSING': ('Werk fehlt im Zielsystem', 'Werk-Mapping prüfen'),
        'MAPPING_MATERIAL_MISSING': ('Material fehlt im Ziel', 'Material-Mapping prüfen'),
        'MAPPING_EQUIPMENT_MISSING': ('Equipment fehlt im Ziel', 'Equipment-Mapping prüfen'),
        
        # Upload Issues
        'UPLOAD_SIZE_EXCEEDED': ('Datei zu groß', 'Max. 50MB pro Datei'),
        'UPLOAD_TIMEOUT': ('Upload-Timeout', 'Kleinere Datei verwenden'),
        'UPLOAD_FAILED': ('Upload fehlgeschlagen', 'Details prüfen'),
        
        # Network / Gateway Issues
        'GATEWAY_TIMEOUT': ('API Gateway Timeout (504)', 'Später erneut versuchen'),
        'SERVER_UNAVAILABLE': ('Server nicht erreichbar', 'Später erneut versuchen'),
        'RATE_LIMITED': ('Rate Limit erreicht (429)', 'Pacing erhöhen'),
        'SERVER_ERROR': ('SAP Serverfehler (5xx)', 'SAP Support kontaktieren'),
        'NETWORK_ERROR': ('Netzwerkfehler', 'Verbindung prüfen'),
        
        # Validation Issues
        'VALIDATION_ERROR': ('Validierungsfehler', 'Eingabedaten prüfen'),
        'VALIDATION_REQUIRED_FIELD': ('Pflichtfeld fehlt', 'Quelldaten prüfen'),
        'VALIDATION_BEGRU_MISSING': ('Berechtigungsgruppe fehlt', 'BEGRU in Quelldaten prüfen'),
        'VALIDATION_FILETYPE_UNKNOWN': ('Dateityp unbekannt', 'Extension in DIL.DRAW.filep prüfen'),
        'BAD_REQUEST': ('Ungültige Anfrage (400)', 'Request prüfen'),
        
        # Unknown
        'UNKNOWN': ('Unbekannter Fehler', 'Details prüfen'),
        'OTHER': ('Sonstiger Fehler', 'Details prüfen'),
    }
    
    return descriptions.get(category, (category, ''))


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


def get_info(server_session, sap_system, Documentnumber, Documentpart='000', Documenttype='IY1', Documentversion='00'):
    """Get List of all attached Documents incl. Links.
    """
    # Strip leading zeros from document number - SAP API requires this format
    # e.g. '0000000000000010007841790' -> '10007841790'
    clean_docnumber = Documentnumber.lstrip('0') if Documentnumber else Documentnumber
    # Ensure at least one character remains if number was all zeros
    if not clean_docnumber and Documentnumber:
        clean_docnumber = '0'
    
    api_args = {"Documentnumber":clean_docnumber, "Documentpart":Documentpart, "Documenttype":Documenttype, "Documentversion":Documentversion}
    formatted_args   = ",".join(f"{key}='{value}'" for key, value in api_args.items())

    base_url = cfg.get(sap_system, "api_list", "document", "base_url")
    response = server_session.get(f"{base_url}/DocumentSet({formatted_args})?$expand=DocumentfilesSet,ObjectlinksSet,DESCRIPTIONSSet" )   
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
        
        # Extract ObjectlinksSet (DOKOB/OBJKY) from API response
        object_links = []
        try:
            object_links_raw = full_raw['d'].get('ObjectlinksSet', {}).get('results', [])
            for ol in object_links_raw:
                if '__metadata' in ol:
                    ol.pop('__metadata')
                object_links.append(ol)
        except (KeyError, TypeError, AttributeError):
            pass  # ObjectlinksSet not available or empty
        
        # Extract DESCRIPTIONSSet (document descriptions in multiple languages)
        descriptions = []
        try:
            descriptions_raw = full_raw['d'].get('DESCRIPTIONSSet', {}).get('results', [])
            for desc in descriptions_raw:
                if '__metadata' in desc:
                    desc.pop('__metadata')
                descriptions.append(desc)
        except (KeyError, TypeError, AttributeError):
            pass  # DESCRIPTIONSSet not available or empty
        
        # Get primary description (prefer German 'DE', fallback to English 'EN', then first available)
        primary_description = None
        if descriptions:
            # Sort by language priority
            for lang in ['DE', 'EN', 'D', 'E']:
                for desc in descriptions:
                    if desc.get('Languagecode', '').upper() == lang or desc.get('Language', '').upper() == lang:
                        primary_description = desc.get('Dktxt') or desc.get('Description') or desc.get('DocumentDescription')
                        if primary_description:
                            break
                if primary_description:
                    break
            # Fallback to first description if no language match
            if not primary_description and descriptions:
                first_desc = descriptions[0]
                primary_description = first_desc.get('Dktxt') or first_desc.get('Description') or first_desc.get('DocumentDescription')
        
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
            # Use primary description from DESCRIPTIONSSet if available
            if not possible_desc and primary_description:
                possible_desc = primary_description
            if possible_desc:
                item['DocumentDescription'] = possible_desc  # normalize
            
            # Inject ObjectlinksSet data into each file item for downstream use
            item['_ObjectlinksSet'] = object_links
            item['_DESCRIPTIONSSet'] = descriptions
            
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
    