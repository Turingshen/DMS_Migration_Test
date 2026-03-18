"""
Step 2: Execute migration based on approved staging records.
Reads from staging database and performs API calls.

Supports background execution: execute_migration() and execute_linking() can run
in a background thread without Flask request context. Session data is passed as
a session_snapshot dict. Token refresh for OAuth systems works standalone via
_refresh_token_standalone().
"""

import pandas as pd
import time
import json
import requests
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from flask import session as http_session

# Global migration lock to prevent parallel executions
_migration_lock = threading.Lock()
_active_migrations = {}  # batch_id -> start_time
_cancel_requested = {}   # batch_id -> True/False - for graceful cancellation

# Background execution results storage
_background_results = {}  # batch_id -> result dict (kept until next execution)

# Circuit Breaker settings
CIRCUIT_BREAKER_THRESHOLD = 3  # Stop after N consecutive auth errors
CIRCUIT_BREAKER_ERRORS = (401, 403)  # HTTP status codes that trigger circuit breaker
PACKAGE_SIZE = 50  # Process in packages of N records (balance between responsiveness and throughput)

# Token refresh import (for automatic refresh before packages)
try:
    from authentication import ensure_valid_token, get_token_remaining_seconds
    TOKEN_REFRESH_AVAILABLE = True
except ImportError:
    TOKEN_REFRESH_AVAILABLE = False

from app_config import Config, MiscEngine
from app.process import (
    prepare_session_headers, 
    get_info,
    _extract_error_fields,
    _sanitize_filename,
    _classify_error,
    get_error_description,
    sanitize_doknr,
    is_csrf_error,
    force_csrf_renewal,
    MAX_API_WORKERS,
    MAX_DESC_LEN,
    read_sap_system,
    write_sap_system,
    get_source_system,
    get_target_system
)
from app.logger import get_logger
from app.prepare import load_object_mappings, apply_object_mappings_for_batch

cfg = Config.load()


def load_batch_dokob_filter(batch_id):
    """Load the DOKOB filter for a batch from DB. Returns a set of uppercase DOKOB strings, or None if no filter."""
    try:
        with misc_engine.begin() as con:
            row = con.execute(text(
                "SELECT dokob_filter FROM dbo.migration_batch WHERE batch_id = :bid"
            ), {'bid': batch_id}).fetchone()
        if row and row[0]:
            return set(d.strip().upper() for d in row[0].split(',') if d.strip())
    except Exception:
        pass
    return None
misc_db = MiscEngine.load()
misc_engine = misc_db.engine

# Import DIL engine for DRAW fallback (optional - may not be available in all environments)
try:
    from app_config import DilEngine
    dil_db = DilEngine.load()
    dil_engine = dil_db.engine
    DIL_AVAILABLE = True
except Exception:
    DIL_AVAILABLE = False
    dil_engine = None


# Extension normalization: map non-standard extensions to SAP-recognized equivalents.
# SAP determines DAPPL (Application type) from the file extension in the Slug header.
# Unrecognized extensions (e.g. .zipx) result in DAPPL=BIN ("Any kind of binary data").
EXTENSION_NORMALIZE_MAP = {
    'zipx': 'zip',    # WinZip extended → standard ZIP
    'jpeg': 'jpg',    # JPEG alias
    'jfif': 'jpg',    # JPEG File Interchange Format
    'tiff': 'tif',    # TIFF alias
    'htm':  'html',   # HTML alias
    'mpeg': 'mpg',    # MPEG alias
    'docm': 'docx',   # Word macro-enabled
    'xlsm': 'xlsx',   # Excel macro-enabled
    'pptm': 'pptx',   # PowerPoint macro-enabled
}

# Additional MIME types for extensions Python's mimetypes module doesn't know
CUSTOM_MIME_TYPES = {
    '.zipx': 'application/zip',
    '.jfif': 'image/jpeg',
    '.dwg':  'application/acad',
    '.dwf':  'application/x-dwf',
    '.msg':  'application/vnd.ms-outlook',
    '.eml':  'message/rfc822',
}


def _normalize_extension(filename):
    """Normalize file extension so SAP assigns the correct DAPPL.
    
    Example: 'report.zipx' → 'report.zip' (SAP: ZIP instead of BIN)
    
    Returns:
        tuple: (normalized_filename, was_changed)
    """
    if not filename or '.' not in filename:
        return filename, False
    name, ext = filename.rsplit('.', 1)
    ext_lower = ext.lower()
    if ext_lower in EXTENSION_NORMALIZE_MAP:
        new_ext = EXTENSION_NORMALIZE_MAP[ext_lower]
        return f"{name}.{new_ext}", True
    return filename, False


def _get_mime_type(filename):
    """Get MIME type for a filename, including custom mappings for uncommon extensions."""
    import mimetypes
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type and filename:
        # Check our custom map
        ext = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        mime_type = CUSTOM_MIME_TYPES.get(ext)
    return mime_type or 'application/octet-stream'


def _sanitize_slug(filename, percent_encode=True):
    """Sanitize a filename for use in the HTTP Slug header.
    
    The ``requests`` library encodes HTTP header values as latin-1.  Characters
    outside ASCII (like é, ü, ö, ä as well as CJK/Cyrillic) would be sent as
    raw latin-1 bytes, but the SAP target system expects UTF-8, causing garbled
    filenames (e.g. ``ü`` → ``�``).
    
    Strategy:
        1. NFC-normalize (compose precomposed accents: à instead of a + \\u0300)
        2. If *percent_encode* is True, percent-encode ALL non-ASCII chars
           (e.g. é → %C3%A9, ü → %C3%BC, Korean 창 → %EC%B0%BD).
           Otherwise replace them with ``_``.
        3. Normalize the file extension for SAP compatibility
    """
    if not filename:
        return 'unnamed'
    try:
        # Step 0: Normalize extension (e.g. .zipx → .zip)
        filename, ext_changed = _normalize_extension(filename)
        if ext_changed:
            import logging
            logging.getLogger('dms_migration').info(f"Extension normalized in Slug: {filename}")
        
        # Step 1: Normalize composable sequences (e.g. a + \\u0300 → à)
        normalized = unicodedata.normalize('NFC', filename)
        
        # Step 2: Percent-encode ALL non-ASCII characters.
        # Previously only non-latin-1 chars were encoded, but SAP interprets
        # Slug as UTF-8, so latin-1 chars (é, ü, ö, ä) sent as raw bytes
        # show up as replacement characters (�) in the target system.
        if percent_encode:
            from urllib.parse import quote
            safe_chars = []
            for ch in normalized:
                if ord(ch) > 127:
                    safe_chars.append(quote(ch, safe=''))
                else:
                    safe_chars.append(ch)
        else:
            safe_chars = []
            for ch in normalized:
                if ord(ch) > 127:
                    safe_chars.append('_')
                else:
                    safe_chars.append(ch)
        return ''.join(safe_chars) or 'unnamed'
    except Exception:
        # Absolute fallback: ASCII-only
        return filename.encode('ascii', 'replace').decode('ascii') or 'unnamed'


def get_filename_from_draw(doknr: str, dokar: str, dokvr: str, doktl: str) -> str:
    """
    Fallback: Get filename with extension from DIL.DRAW.filep.
    Used when API Docpath doesn't contain a valid file extension.
    
    Args:
        doknr: Document number (e.g., '0000000000000010002006217')
        dokar: Document type (e.g., 'IY1')
        dokvr: Document version (e.g., '00')
        doktl: Document part (e.g., '000')
    
    Returns:
        Filename with extension, or empty string if not found.
    """
    if not DIL_AVAILABLE or not dil_engine:
        return ''
    
    try:
        query = f"""
            SELECT filep
            FROM dil.DRAW
            WHERE doknr = '{doknr}'
              AND dokar = '{dokar}'
              AND dokvr = '{str(dokvr).zfill(2)}'
              AND doktl = '{str(doktl).zfill(3)}'
        """
        with dil_engine.begin() as con:
            result = con.execute(text(query)).fetchone()
        
        if result and result[0]:
            filep = str(result[0]).strip()
            # filep is the full filename with extension
            if '.' in filep:
                return filep
    except Exception as e:
        print(f"[WARN] DRAW fallback failed: {e}")
    
    return ''


# ============================================================================
# LOCAL_LINK Detection - Handles documents with local file paths (DAPPL=HTM)
# ============================================================================
# Background:
#   Some DMS documents (DAPPL=HTM) contain references to LOCAL FILE PATHS
#   instead of files stored in the SAP Content Repository (KPRO).
#   These paths are stored in DRAW.FILEP and look like:
#     - C:\Users\parkje\Desktop\file.pdf
#     - \\server\share\folder\file.pdf
#     - file:///C:/temp/document.pdf
#
# Challenge:
#   - The SAP API's CreateUrlAsAttachment function import only accepts
#     http:// or https:// URLs - file:// URLs are rejected.
#   - These "local link" documents have NO content in the Content Repository,
#     so there's nothing to download.
#
# Solution:
#   We create a Windows Internet Shortcut file (.url) containing the local path
#   and upload it as a regular attachment. When users download this file from
#   SAP and double-click it, Windows opens the local path (if accessible).
#
# Detection:
#   - DAPPL = 'HTM' (marked as hyperlink in DMS)
#   - DRAW.FILEP contains a local path (C:\, \\, file://) instead of http(s)://
# ============================================================================

def is_local_path(path: str) -> bool:
    """Check if a path is a local file path vs a remote web URL.
    
    LOCAL paths (.url shortcut required):
        - file://C:/... or file:///C:/...
        - C:\... or D:\... (Windows drive letter paths)
        - \\server\share\... (UNC network paths)
    
    REMOTE paths (CreateUrlAsAttachment works):
        - http://...
        - https://...
    
    Args:
        path: The path/URL string to check
    
    Returns:
        True if path is local (needs .url workaround), False for remote URLs
    """
    if not path:
        return False
    
    path_stripped = path.strip()
    path_lower = path_stripped.lower()
    
    # Remote web URLs - these work with CreateUrlAsAttachment
    if path_lower.startswith(('http://', 'https://')):
        return False
    
    # Local paths - need .url file workaround
    if path_lower.startswith('file://'):
        return True
    # Windows drive letter path: C:\, D:\, etc.
    if len(path_stripped) >= 2 and path_stripped[1] == ':':
        return True
    # UNC path: \\server\share
    if path_stripped.startswith('\\\\'):
        return True
    
    # Unknown format - assume local if it looks like a path
    return False


def is_web_url(path: str) -> bool:
    """Check if a path is a remote web URL (http:// or https://).
    
    WEB URLs require CreateUrlAsAttachment or .url shortcut upload.
    This is used to detect HTM documents that contain web links
    instead of local file paths or Content Repository files.
    
    Args:
        path: The path/URL string to check
    
    Returns:
        True if path is a web URL (http:// or https://)
    """
    if not path:
        return False
    return path.strip().lower().startswith(('http://', 'https://'))


def get_filep_from_draw(doknr: str, dokar: str, dokvr: str, doktl: str) -> str:
    """Get the raw FILEP value from DRAW for LOCAL_LINK detection.
    
    FILEP contains either:
        - A local file path (for DAPPL=HTM local links): C:\..., \\\\server\\...
        - A URL (for DAPPL=HTM web links): http://..., https://...
        - A filename (for normal files)
    
    Args:
        doknr: Document number (25 chars)
        dokar: Document type (e.g. 'IY1')
        dokvr: Document version (e.g. '00')
        doktl: Document part (e.g. '000')
    
    Returns:
        The raw FILEP value, or empty string if not found.
    """
    if not DIL_AVAILABLE or not dil_engine:
        return ''
    
    try:
        query = text("""
            SELECT FILEP FROM DIL.DRAW
            WHERE DOKNR = :doknr AND DOKAR = :dokar
              AND DOKVR = :dokvr AND DOKTL = :doktl
        """)
        with dil_engine.begin() as con:
            result = con.execute(query, {
                'doknr': doknr,
                'dokar': dokar,
                'dokvr': str(dokvr).zfill(2),
                'doktl': str(doktl).zfill(3)
            }).fetchone()
        
        if result and result[0]:
            return str(result[0]).strip()
    except Exception as e:
        print(f"[WARN] get_filep_from_draw failed: {e}")
    
    return ''


def create_local_link_placeholder(target_path: str) -> bytes:
    """Create empty placeholder content for local link files.
    
    For local links (files not in KPRO), we upload an empty file with the
    original filename. SAP determines DAPPL from the Slug header extension.
    
    NOTE: We don't create .url shortcut content because SAP rejects file:// URLs.
    Instead we upload empty content with the original filename so SAP assigns
    the correct DAPPL (PDF, JPG, etc.) based on file extension.
    
    Args:
        target_path: The local file path (unused, kept for API compatibility)
    
    Returns:
        Empty bytes (placeholder file with 0 bytes)
    """
    # Return empty bytes - SAP will create a 0-byte file with correct DAPPL
    # based on the filename extension in the Slug header
    return b''


def get_shortcut_filename(original_path: str) -> str:
    """Extract the original filename from a local path for SAP DAPPL detection.
    
    SAP determines DAPPL from the file extension in the Slug header.
    By keeping the original extension (e.g., .pdf, .jpg), SAP assigns the
    correct DAPPL instead of BIN/HTM.
    
    Examples:
        C:\temp\document.pdf → document.pdf (SAP DAPPL: PDF)
        \\server\share\file.xls → file.xls (SAP DAPPL: XLS)
        file:///C:/path/report.docx → report.docx (SAP DAPPL: DOC)
        C:\path\image.jpg → image.jpg (SAP DAPPL: JPG)
    
    Args:
        original_path: The original local path
    
    Returns:
        The filename with ORIGINAL extension for correct SAP DAPPL assignment
    """
    import os
    
    # Clean up the path
    path = original_path.strip()
    
    # Handle file:// URLs
    if path.lower().startswith('file://'):
        path = path[7:]  # Remove file://
        if path.startswith('/'):
            path = path[1:]  # Remove leading /
    
    # Get just the filename part - KEEP ORIGINAL EXTENSION
    basename = os.path.basename(path.replace('/', '\\'))
    
    # Return original filename with extension for correct SAP DAPPL
    return basename if basename else "link.url"


def get_filename_from_dms_doc_files(doknr: str, dokar: str, dokvr: str, doktl: str, file_index: int = 0) -> str:
    """
    Fallback: Get filename with extension from DIL.DMS_DOC_FILES.
    Used when API Docpath contains a GUID (KPRO files) without file extension.
    
    DMS_DOC_FILES has per-file records with:
      - FILENAME: real filename (e.g. '15B 100_2676.JPG')
      - DAPPL: file application/type (e.g. 'JPG', 'PDF', 'XLS')
      - FILE_IDX: 1-based file index within the document
    
    Args:
        doknr: Document number (25 chars, e.g. '0000000000000010002006217')
        dokar: Document type (e.g. 'IY1')
        dokvr: Document version (e.g. '00')
        doktl: Document part (e.g. '000')
        file_index: 0-based file index from the API loop (mapped to FILE_IDX = file_index + 1)
    
    Returns:
        Filename with extension, or empty string if not found.
    """
    if not DIL_AVAILABLE or not dil_engine:
        return ''
    
    try:
        # FILE_IDX in DMS_DOC_FILES is 1-based
        file_idx = file_index + 1
        query = text("""
            SELECT FILENAME, DAPPL
            FROM DIL.DMS_DOC_FILES
            WHERE DOKNR = :doknr
              AND DOKAR = :dokar
              AND DOKVR = :dokvr
              AND DOKTL = :doktl
              AND FILE_IDX = :file_idx
        """)
        with dil_engine.begin() as con:
            result = con.execute(query, {
                'doknr': doknr,
                'dokar': dokar,
                'dokvr': str(dokvr).zfill(2),
                'doktl': str(doktl).zfill(3),
                'file_idx': file_idx
            }).fetchone()
        
        if result:
            filename = str(result[0] or '').strip()
            dappl = str(result[1] or '').strip()
            
            # Prefer FILENAME if it has an extension
            if filename and '.' in filename:
                return filename
            # Construct from DAPPL if available (e.g. append .pdf)
            if dappl and filename:
                return f"{filename}.{dappl.lower()}"
            if dappl:
                return f"document.{dappl.lower()}"
    except Exception as e:
        print(f"[WARN] DMS_DOC_FILES fallback failed: {e}")
    
    return ''


def has_valid_extension(filename: str) -> bool:
    """Check if filename has a valid file extension (not just numbers)."""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[-1].lower()
    # Extension should be 2-5 chars and not all numbers
    return 2 <= len(ext) <= 5 and not ext.isdigit()


def _is_loid(name):
    """Check if name looks like a LOID (hex GUID without extension)."""
    import re
    return bool(re.fullmatch(r'[0-9A-Fa-f]{24,40}', name.strip())) if name else False


def _get_any_dappl(doknr, dokar, dokvr, doktl):
    """Get any DAPPL from DMS_DOC_FILES for this document (general extension)."""
    if not DIL_AVAILABLE or not dil_engine:
        return ''
    try:
        query = text("""
            SELECT DAPPL FROM DIL.DMS_DOC_FILES
            WHERE DOKNR = :nr AND DOKAR = :typ AND DOKVR = :ver AND DOKTL = :teil
              AND DAPPL IS NOT NULL AND DAPPL != ''
            ORDER BY FILE_IDX
        """)
        with dil_engine.begin() as con:
            result = con.execute(query, {
                'nr': doknr, 'typ': dokar,
                'ver': str(dokvr).zfill(2), 'teil': str(doktl).zfill(3)
            }).fetchone()
        return str(result[0]).strip() if result and result[0] else ''
    except Exception:
        return ''


def _resolve_filename(document, staging_record, file_index):
    """Resolve the best available filename from all sources.

    Priority:
      1) API Docpath (full path → extract basename)
      2) staging.filename (from Prepare phase)
      3) If no valid extension yet:
         a) Wsapplication code as extension
         b) DIL.DRAW.filep
         c) DIL.DMS_DOC_FILES (FILENAME + DAPPL per file)
         d) DIL.DMS_DOC_FILES (any DAPPL for this document)
      4) 'file_{index}' as absolute last resort

    LOID (hex GUID) is never returned as filename.
    """
    from app.process import _sanitize_filename

    # Source 1: API Docpath
    docpath = (document.get('Docpath', '') or '').replace('\\', '/')
    api_filename = _sanitize_filename(docpath.split('/')[-1] or '') if docpath else ''

    # Source 2: staging filename
    staging_filename = (staging_record.get('filename', '') or '').strip()

    # Pick the first non-empty candidate (but skip LOIDs)
    if api_filename and api_filename != 'unnamed' and not _is_loid(api_filename):
        filename = api_filename
    elif staging_filename and not _is_loid(staging_filename):
        filename = staging_filename
    else:
        filename = ''

    # If already valid → done
    if filename and has_valid_extension(filename):
        return filename

    # Source 3a: Wsapplication extension code
    ws_appl = (document.get('Wsapplication', '') or '').strip()
    if ws_appl and ws_appl.upper() not in ('WEB', 'HTM'):
        ext = ws_appl.lower()
        base = filename if filename else f'file_{file_index}'
        return f"{base}.{ext}"

    src_nr = staging_record.get('source_documentnumber', '')
    src_typ = staging_record.get('source_documenttype', '')
    src_ver = staging_record.get('source_documentversion', '')
    src_teil = staging_record.get('source_documentpart', '')

    # Source 3b: DIL.DRAW.filep
    draw_filename = get_filename_from_draw(src_nr, src_typ, src_ver, src_teil)
    if draw_filename and has_valid_extension(draw_filename):
        return draw_filename

    # Source 3c: DIL.DMS_DOC_FILES (specific file by FILE_IDX)
    dms_filename = get_filename_from_dms_doc_files(src_nr, src_typ, src_ver, src_teil, file_index)
    if dms_filename and has_valid_extension(dms_filename):
        return dms_filename

    # Source 3d: DIL.DMS_DOC_FILES (any DAPPL for this document)
    # Catches out-of-range file indices where specific FILE_IDX has no match
    any_dappl = _get_any_dappl(src_nr, src_typ, src_ver, src_teil)
    if any_dappl:
        base = filename if filename else f'file_{file_index}'
        return f"{base}.{any_dappl.lower()}"

    # Last resort — never return a LOID
    return filename or f'file_{file_index}'


# Pacing mode: 'response' = wait for API response, 'time' = time-based delays
# Time-based pacing is more reliable for APIs with rate limiting
PACING_MODE = 'time'  # 'response' or 'time'

# Minimum delay between containers (seconds) - prevents rate limiting
# Only applies in response mode; set to 0 for maximum throughput
MIN_CONTAINER_DELAY = 0.5

# Time-based pacing buckets (used when PACING_MODE = 'time')
PACING_BUCKETS = {
    'tiny':    {'max_mb': 1,    'pacing': 5},   # ≤1MB: Fast batch processing
    'small':   {'max_mb': 10,   'pacing': 10},  # 1-10MB: Normal processing
    'medium':  {'max_mb': 50,   'pacing': 20},  # 10-50MB: Larger files
    'large':   {'max_mb': float('inf'), 'pacing': 45},  # >50MB: Very large
    'unknown': {'pacing': 5}    # Unknown size: Assume small (same as tiny)
}

# Terminal logging verbosity: True = detailed, False = minimal (progress + errors only)
VERBOSE_TERMINAL_LOGGING = False

# API Warmup settings
WARMUP_ENABLED = True
WARMUP_REQUESTS = 3  # Number of warmup pings
WARMUP_DELAY = 0.5   # Delay between warmup requests (seconds)


# ============================================================================
# Standalone Token Refresh (works without Flask request context)
# ============================================================================

def _refresh_token_standalone(session_snapshot):
    """Refresh OAuth bearer token without Flask session context.
    
    Uses refresh_token stored in session_snapshot to get a new bearer token.
    Updates session_snapshot in-place with the new token.
    
    Returns:
        (success: bool, error_message: str or None)
    """
    refresh_tok = session_snapshot.get('refresh_token')
    if not refresh_tok:
        return False, "No refresh token in snapshot"
    
    try:
        oauth_config = cfg.config_env.get('auth', {})
        payload = {
            'client_id': oauth_config.get('payload', {}).get('client_id', ''),
            'client_secret': oauth_config.get('payload', {}).get('client_secret', ''),
            'grant_type': 'refresh_token',
            'refresh_token': refresh_tok,
        }
        auth_url = oauth_config.get('auth_url', '')
        
        response = requests.post(f"{auth_url}/token", data=payload, timeout=30)
        
        if response.status_code != 200:
            return False, f"Refresh failed: HTTP {response.status_code}"
        
        data = response.json()
        
        # Update snapshot with new tokens
        session_snapshot['bearer_token'] = data['access_token']
        
        if 'refresh_token' in data:
            session_snapshot['refresh_token'] = data['refresh_token']
        
        if 'expires_in' in data:
            expires_in = int(data['expires_in'])
            session_snapshot['token_expires_at'] = time.time() + expires_in
            print(f"[TOKEN] Standalone refresh OK, expires in {expires_in}s ({expires_in // 60} min)")
        
        return True, None
        
    except Exception as e:
        return False, f"Standalone refresh error: {str(e)}"


def _check_and_refresh_token(session_snapshot):
    """Check token health and refresh if needed. Works in both Flask and background context.
    
    For Basic Auth systems, always returns (True, None) since credentials don't expire.
    For OAuth systems, checks token_expires_at and refreshes if < 10 min remaining.
    
    Returns:
        (is_valid: bool, error_message: str or None)
    """
    # Basic Auth systems don't need token refresh
    source_sys = session_snapshot.get('source_system', read_sap_system)
    source_auth_type = cfg.config_env.get(source_sys, {}).get('auth_type', 'oauth')
    if source_auth_type == 'basic':
        return True, None
    
    # Check if token has expiry info in snapshot
    expires_at = session_snapshot.get('token_expires_at')
    if expires_at is not None:
        remaining = max(0, int(expires_at - time.time()))
        if remaining < 600:  # Less than 10 min remaining
            print(f"[TOKEN] Token expires in {remaining}s, attempting standalone refresh...")
            success, error = _refresh_token_standalone(session_snapshot)
            if not success:
                return False, f"Token expired and refresh failed: {error}"
            return True, None
        return True, None
    
    # No expiry info — try Flask session context as fallback (legacy path)
    if TOKEN_REFRESH_AVAILABLE:
        try:
            remaining = get_token_remaining_seconds()
            if remaining is not None and remaining < 600:
                print(f"[TOKEN] Token expires in {remaining}s, attempting Flask-context refresh...")
                is_valid, error = ensure_valid_token()
                if not is_valid:
                    return False, f"Token expired and refresh failed: {error}"
                # Update snapshot from Flask session
                session_snapshot['bearer_token'] = http_session.get('bearer_token')
                return True, None
        except RuntimeError:
            # No Flask request context — expected in background threads
            pass
    
    return True, None  # Can't check, assume valid


def get_background_result(batch_id):
    """Get the result of a background execution, if available."""
    return _background_results.get(batch_id)


def clear_background_result(batch_id):
    """Clear stored background result for a batch."""
    _background_results.pop(batch_id, None)


def warmup_api(session_snapshot, first_loio_id=None):
    """
    Send warmup requests to wake up the API before starting migration.
    This helps avoid initial 401/403/500 errors due to cold API instances.
    
    Supports both OAuth (Bearer + API-Key) and Basic Auth source systems.
    
    Args:
        session_snapshot: Dict with bearer_token and other auth info
        first_loio_id: Optional LOIO ID to use for warmup (from first record)
    
    Returns:
        dict with warmup results
    """
    if not WARMUP_ENABLED:
        return {'skipped': True}
    
    print(f"[WARMUP] Waking up API with {WARMUP_REQUESTS} requests...")
    
    results = []
    start_time = time.time()
    
    source_system = session_snapshot.get('source_system', read_sap_system)
    target_system = session_snapshot.get('target_system', write_sap_system)
    
    for i in range(WARMUP_REQUESTS):
        try:
            # Create a temporary session for warmup
            warmup_session = requests.Session()
            
            # Try to warm up source API using prepare_session_headers (handles OAuth + Basic Auth)
            try:
                prepare_session_headers(warmup_session, session_snapshot, source_system)
                source_base_url = cfg.get(source_system, 'api_list', 'document', 'base_url')
                if source_base_url:
                    resp = warmup_session.get(source_base_url, timeout=10)
                    results.append({
                        'target': 'source_api',
                        'status': resp.status_code,
                        'ok': resp.status_code in [200, 401, 403]
                    })
            except Exception as e:
                results.append({'target': 'source_api', 'status': str(e)[:50], 'ok': False})
            
            # Try to warm up target API
            try:
                prepare_session_headers(warmup_session, session_snapshot, target_system)
                target_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
                if target_base_url:
                    resp = warmup_session.get(target_base_url, timeout=10)
                    results.append({
                        'target': 'target_api',
                        'status': resp.status_code,
                        'ok': resp.status_code in [200, 401, 403]
                    })
            except Exception as e:
                results.append({'target': 'target_api', 'status': str(e)[:50], 'ok': False})
            
            if i < WARMUP_REQUESTS - 1:
                time.sleep(WARMUP_DELAY)
                
        except requests.exceptions.Timeout:
            results.append({'target': 'warmup', 'status': 'timeout', 'ok': False})
        except Exception as e:
            results.append({'target': 'warmup', 'status': str(e)[:50], 'ok': False})
    
    elapsed = time.time() - start_time
    success_count = sum(1 for r in results if r.get('ok'))
    
    print(f"[WARMUP] Completed in {elapsed:.1f}s - {success_count}/{len(results)} successful")
    
    return {
        'elapsed': elapsed,
        'results': results,
        'success': success_count > 0
    }


def get_historical_pacing_stats():
    """
    Analyze historical execution data to calculate pacing recommendations.
    Returns statistics per size bucket based on actual execution times.
    """
    try:
        query = """
            SELECT 
                file_size_bytes,
                DATEDIFF(MILLISECOND, execution_started_at, execution_completed_at) / 1000.0 as execution_time_sec,
                execution_status
            FROM dbo.migration_staging
            WHERE execution_status IN ('success', 'partial')
            AND execution_started_at IS NOT NULL
            AND execution_completed_at IS NOT NULL
            AND file_size_bytes IS NOT NULL
            AND file_size_bytes > 0
        """
        
        with misc_engine.begin() as con:
            result = con.execute(text(query))
            rows = result.fetchall()
        
        if not rows:
            return {
                'has_data': False,
                'message': 'Keine historischen Daten verfügbar',
                'buckets': PACING_BUCKETS
            }
        
        # Group by size bucket
        bucket_stats = {
            'tiny': {'count': 0, 'times': [], 'max_mb': 1},
            'small': {'count': 0, 'times': [], 'max_mb': 10},
            'medium': {'count': 0, 'times': [], 'max_mb': 50},
            'large': {'count': 0, 'times': [], 'max_mb': 999999}  # Use large number instead of inf for JSON compatibility
        }
        
        for row in rows:
            size_bytes, exec_time, status = row
            if size_bytes is None or exec_time is None:
                continue
            
            # Convert Decimal to float for division
            size_bytes = float(size_bytes)
            exec_time = float(exec_time)
            size_mb = size_bytes / (1024 * 1024)
            
            if size_mb <= 1:
                bucket = 'tiny'
            elif size_mb <= 10:
                bucket = 'small'
            elif size_mb <= 50:
                bucket = 'medium'
            else:
                bucket = 'large'
            
            bucket_stats[bucket]['count'] += 1
            bucket_stats[bucket]['times'].append(exec_time)
        
        # Calculate statistics for each bucket
        recommendations = {}
        for bucket_name, stats in bucket_stats.items():
            if stats['count'] > 0:
                times = stats['times']
                avg_time = sum(times) / len(times)
                max_time = max(times)
                min_time = min(times)
                # Recommended pacing = max_time + 20% buffer, rounded up
                recommended = round(max_time * 1.2, 1)
                
                recommendations[bucket_name] = {
                    'count': stats['count'],
                    'avg_time': round(avg_time, 2),
                    'min_time': round(min_time, 2),
                    'max_time': round(max_time, 2),
                    'current_pacing': PACING_BUCKETS[bucket_name]['pacing'],
                    'recommended_pacing': recommended,
                    'max_mb': stats['max_mb']
                }
            else:
                recommendations[bucket_name] = {
                    'count': 0,
                    'avg_time': None,
                    'min_time': None,
                    'max_time': None,
                    'current_pacing': PACING_BUCKETS[bucket_name]['pacing'],
                    'recommended_pacing': PACING_BUCKETS[bucket_name]['pacing'],
                    'max_mb': stats['max_mb']
                }
        
        total_records = sum(s['count'] for s in recommendations.values())
        
        return {
            'has_data': True,
            'total_records': total_records,
            'buckets': recommendations,
            'current_pacing': {k: v['pacing'] for k, v in PACING_BUCKETS.items() if k != 'unknown'}
        }
        
    except Exception as e:
        return {
            'has_data': False,
            'error': str(e),
            'buckets': PACING_BUCKETS
        }


def get_dynamic_pacing(file_size_bytes):
    """
    Calculate dynamic pacing based on file size.
    Smaller files get shorter pacing, larger files get more time.
    
    Args:
        file_size_bytes: File size in bytes (None if unknown)
        
    Returns:
        Pacing time in seconds
    """
    import math
    # Handle None, NaN, and invalid values - use tiny pacing as default for unknown small files
    try:
        if file_size_bytes is None:
            return PACING_BUCKETS['tiny']['pacing']  # Assume small file if unknown
        if math.isnan(float(file_size_bytes)):
            return PACING_BUCKETS['tiny']['pacing']
        if file_size_bytes <= 0:
            return PACING_BUCKETS['tiny']['pacing']
    except (TypeError, ValueError):
        return PACING_BUCKETS['tiny']['pacing']
    
    size_mb = file_size_bytes / (1024 * 1024)
    
    if size_mb <= 1:
        return PACING_BUCKETS['tiny']['pacing']
    elif size_mb <= 10:
        return PACING_BUCKETS['small']['pacing']
    elif size_mb <= 50:
        return PACING_BUCKETS['medium']['pacing']
    else:
        return PACING_BUCKETS['large']['pacing']


def load_approved_records(batch_id):
    """Load records from staging that are pending execution."""
    query = f"""
        SELECT 
            id,
            batch_id,
            source_documentnumber,
            source_documentpart,
            source_documenttype,
            source_documentversion,
            source_loioid,
            source_description,
            target_documentnumber,
            target_documentnumber_sanitized,
            target_documentpart,
            target_documenttype,
            target_documentversion,
            authorization_group,
            target_document_status,
            filename,
            file_size_bytes,
            skip_migration
        FROM dbo.migration_staging
        WHERE batch_id = '{batch_id}'
            AND skip_migration = 0
            AND execution_status = 'pending'
            AND (target_link_count IS NULL OR target_link_count > 0)
        ORDER BY CASE WHEN file_size_bytes IS NULL THEN 1 ELSE 0 END, file_size_bytes ASC, id
    """
    
    with misc_engine.begin() as con:
        df = pd.read_sql(query, con)
    
    return df


def load_specific_records(batch_id, record_ids):
    """Load specific records by IDs for execution."""
    if not record_ids:
        return pd.DataFrame()
    
    ids_str = ','.join(str(id) for id in record_ids)
    query = f"""
        SELECT 
            id,
            batch_id,
            source_documentnumber,
            source_documentpart,
            source_documenttype,
            source_documentversion,
            source_loioid,
            source_description,
            target_documentnumber,
            target_documentnumber_sanitized,
            target_documentpart,
            target_documenttype,
            target_documentversion,
            authorization_group,
            target_document_status,
            filename,
            file_size_bytes,
            skip_migration,
            ISNULL(container_created, 0) as container_created
        FROM dbo.migration_staging
        WHERE batch_id = '{batch_id}'
            AND id IN ({ids_str})
            AND skip_migration = 0
            AND (target_link_count IS NULL OR target_link_count > 0)
        ORDER BY CASE WHEN file_size_bytes IS NULL THEN 1 ELSE 0 END, file_size_bytes ASC, id
    """
    
    with misc_engine.begin() as con:
        df = pd.read_sql(query, con)
    
    return df


def update_execution_status(staging_id, status, error=None, error_category=None):
    """Update execution status for a staging record.
    
    Args:
        staging_id: The staging record ID
        status: 'success', 'failed', or 'partial'
        error: Error message or dict
        error_category: Optional error category. If not provided for failures, will be auto-classified.
    """
    try:
        # Determine error_category
        final_category = None
        if status == 'success':
            final_category = None  # Clear on success
        elif error_category:
            final_category = error_category  # Use provided category
        elif error:
            # Auto-classify from error
            final_category = _auto_classify_error(error)
        
        update_query = """
            UPDATE dbo.migration_staging
            SET execution_status = :status,
                execution_completed_at = GETUTCDATE(),
                execution_error = :error,
                error_category = :error_category
            WHERE id = :staging_id
        """
        
        with misc_engine.begin() as con:
            con.execute(text(update_query), {
                'status': status,
                'error': str(error) if error else None,
                'error_category': final_category,
                'staging_id': staging_id
            })
    except Exception as e:
        print(f"[UPDATE_ERROR] Failed to update staging_id={staging_id}: {e}")


def _auto_classify_error(error):
    """Auto-classify error string into a category."""
    if not error:
        return 'UNKNOWN'
    
    error_str = str(error).upper()
    
    # Check for common patterns
    if 'LOCAL_LINK' in error_str:
        return 'LOCAL_LINK'
    if 'WEB_URL' in error_str:
        return 'WEB_URL'
    if 'READ_EMPTY' in error_str or 'NO DOCUMENTS FOUND' in error_str:
        return 'READ_EMPTY'
    if 'READ_TIMEOUT' in error_str or 'TIMEOUT' in error_str:
        return 'TIMEOUT_RETRY'
    if 'API_ERROR_501' in error_str or '501' in error_str:
        return 'API_NOT_IMPLEMENTED'
    if 'API_ERROR_504' in error_str or '504' in error_str or 'GATEWAY TIMEOUT' in error_str:
        return 'TIMEOUT_RETRY'
    if 'API_ERROR_401' in error_str or 'UNAUTHORIZED' in error_str:
        return 'AUTH_ERROR'
    if 'API_ERROR_403' in error_str or 'FORBIDDEN' in error_str:
        return 'AUTH_FORBIDDEN'
    if 'API_ERROR_400' in error_str or 'BAD REQUEST' in error_str:
        return 'BAD_REQUEST'
    if 'API_ERROR_404' in error_str or 'NOT FOUND' in error_str:
        return 'SOURCE_NOT_FOUND'
    if 'API_ERROR_500' in error_str or 'INTERNAL SERVER ERROR' in error_str:
        return 'SERVER_ERROR'
    if 'CSRF' in error_str:
        return 'CSRF_FAILED'
    if 'DOC_NUMBER' in error_str or 'DOCUMENTNUMBER' in error_str:
        return 'CODE_BUG'
    if 'UPLOAD' in error_str:
        return 'UPLOAD_ERROR'
    if 'SIZE' in error_str and ('EXCEEDED' in error_str or 'LARGE' in error_str):
        return 'SIZE_EXCEEDED'
    
    return 'UNKNOWN'


def mark_execution_started(staging_id):
    """Mark execution as started by setting execution_started_at."""
    try:
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_staging
                SET execution_started_at = GETUTCDATE()
                WHERE id = :staging_id
            """), {'staging_id': staging_id})
    except Exception as e:
        print(f"[UPDATE_ERROR] Failed to mark started staging_id={staging_id}: {e}")


def update_metadata_fields(staging_id, loioid=None, description=None, filename=None, file_size=None, mime_type=None):
    """Update metadata fields for a staging record after successful read."""
    try:
        updates = []
        params = {'staging_id': staging_id}
        
        if loioid:
            updates.append("source_loioid = :loioid")
            params['loioid'] = loioid
        if description:
            updates.append("source_description = :description")
            params['description'] = description
        if filename:
            updates.append("filename = :filename")
            params['filename'] = filename
        if file_size is not None:
            updates.append("file_size_bytes = :file_size")
            params['file_size'] = file_size
        if mime_type:
            updates.append("mime_type = :mime_type")
            params['mime_type'] = mime_type
        
        if updates:
            update_query = f"""
                UPDATE dbo.migration_staging
                SET {', '.join(updates)}
                WHERE id = :staging_id
            """
            
            with misc_engine.begin() as con:
                con.execute(text(update_query), params)
    except Exception as e:
        print(f"[UPDATE_METADATA_ERROR] Failed to update metadata for staging_id={staging_id}: {e}")


def save_file_details(staging_id, batch_id, file_index, file_result, loio_id=None):
    """
    Save detailed file-level results to migration_file_details table.
    
    Args:
        staging_id: Parent staging record ID
        batch_id: Batch ID for filtering
        file_index: 0-based index of file in container
        file_result: Dict with upload result (status, error_detail, file_size, etc.)
        loio_id: LOIO ID of the file (optional)
    """
    import json
    
    try:
        # Extract error information
        error_detail = file_result.get('error_detail', {}) or {}
        error_messages = error_detail.get('messages') or error_detail.get('errordetails')
        
        # Get raw status and clean it for the status field
        raw_status = file_result.get('status', 'UNKNOWN')
        # Extract just the status code (e.g., "UPLOAD_FAIL_500: xyz" -> "UPLOAD_FAIL_500")
        if ':' in raw_status:
            clean_status = raw_status.split(':')[0].strip()
            # Store the extra info in error_detail if not already set
            extra_info = raw_status.split(':', 1)[1].strip() if len(raw_status.split(':')) > 1 else None
        else:
            clean_status = raw_status
            extra_info = None
        
        # Truncate status to 50 chars max (DB limit)
        clean_status = clean_status[:50] if clean_status else 'UNKNOWN'
        
        # Combine error details
        combined_error_detail = error_detail.get('detail') if error_detail else None
        if not combined_error_detail and extra_info:
            combined_error_detail = extra_info
        
        params = {
            'staging_id': staging_id,
            'batch_id': batch_id,
            'file_index': file_index,
            'filename': file_result.get('file'),
            'loio_id': loio_id,
            'file_size_bytes': file_result.get('file_size'),
            'file_size_mb': file_result.get('file_size_mb'),
            'mime_type': file_result.get('mime_type'),
            'upload_status': clean_status,
            'http_status_code': error_detail.get('status_code') if error_detail else (200 if file_result.get('status') == 'SUCCESS' else None),
            'upload_time_seconds': file_result.get('actual_time_seconds'),
            'error_category': file_result.get('error_category'),
            'error_code': error_detail.get('code') if error_detail else None,
            'error_detail': combined_error_detail,
            'error_messages': json.dumps(error_messages) if error_messages else None,
            'is_size_error': 1 if file_result.get('is_size_error') else 0
        }
        
        insert_query = """
            INSERT INTO dbo.migration_file_details (
                staging_id, batch_id, file_index, filename, loio_id,
                file_size_bytes, file_size_mb, mime_type,
                upload_status, http_status_code, upload_time_seconds,
                error_category, error_code, error_detail, error_messages, is_size_error
            ) VALUES (
                :staging_id, :batch_id, :file_index, :filename, :loio_id,
                :file_size_bytes, :file_size_mb, :mime_type,
                :upload_status, :http_status_code, :upload_time_seconds,
                :error_category, :error_code, :error_detail, :error_messages, :is_size_error
            )
        """
        
        with misc_engine.begin() as con:
            con.execute(text(insert_query), params)
            
    except Exception as e:
        print(f"[SAVE_FILE_DETAILS_ERROR] Failed to save file details for staging_id={staging_id}, file_index={file_index}: {e}")


def get_successfully_uploaded_files(staging_id):
    """Get list of file indices that were already successfully uploaded.
    
    Used for retry optimization - skip re-uploading files that succeeded.
    
    Args:
        staging_id: The staging record ID
        
    Returns:
        set: Set of file_index values that have upload_status starting with 'SUCCESS'
    """
    try:
        with misc_engine.begin() as con:
            result = con.execute(text("""
                SELECT file_index
                FROM dbo.migration_file_details
                WHERE staging_id = :staging_id
                  AND upload_status LIKE 'SUCCESS%'
            """), {'staging_id': staging_id}).fetchall()
            return {row[0] for row in result}
    except Exception as e:
        print(f"[GET_UPLOADED_FILES_ERROR] Failed to get uploaded files for staging_id={staging_id}: {e}")
        return set()


def get_cached_file_info(staging_id):
    """Get cached file info from migration_file_details for retry.
    
    When container is already created but upload failed, we can use the cached
    file info instead of reading from source system again (which may fail with 501).
    
    Args:
        staging_id: The staging record ID
        
    Returns:
        list: List of file info dicts compatible with get_info() result format
    """
    try:
        with misc_engine.begin() as con:
            # Get staging record for source document info
            staging = con.execute(text("""
                SELECT source_documentnumber, source_documentpart, 
                       source_documenttype, source_documentversion,
                       source_loioid, filename
                FROM dbo.migration_staging
                WHERE id = :staging_id
            """), {'staging_id': staging_id}).fetchone()
            
            if not staging:
                return None
            
            # Get file details (use correct column names: filename, loio_id)
            file_details = con.execute(text("""
                SELECT file_index, filename, loio_id, file_size_bytes, mime_type
                FROM dbo.migration_file_details
                WHERE staging_id = :staging_id
                ORDER BY file_index
            """), {'staging_id': staging_id}).fetchall()
            
            if not file_details:
                # No file details, but we have staging record - use that
                # Build a single file entry from staging record
                return [{
                    'Documentnumber': staging[0],
                    'Documentpart': staging[1],
                    'Documenttype': staging[2],
                    'Documentversion': staging[3],
                    'LOIOID': staging[4] or '',
                    'Docpath': staging[5] or '',
                    'Description': '',
                    '_cached': True  # Mark as cached for logging
                }]
            
            # Build file list from file_details
            files = []
            for fd in file_details:
                files.append({
                    'Documentnumber': staging[0],
                    'Documentpart': staging[1],
                    'Documenttype': staging[2],
                    'Documentversion': staging[3],
                    'LOIOID': fd[2] or staging[4] or '',
                    'Docpath': fd[1] or '',
                    'Description': '',
                    '_cached': True,
                    '_file_index': fd[0],
                    '_file_size': fd[3],
                    '_mime_type': fd[4]
                })
            return files
            
    except Exception as e:
        print(f"[GET_CACHED_FILE_INFO_ERROR] Failed to get cached file info for staging_id={staging_id}: {e}")
        return None


def is_auto_generated_id(doc_number):
    """Check if document number is auto-generated by SAP.
    
    Auto-generated IDs are:
    - Exactly 25 characters long
    - Convert to integer after removing leading zeros
    
    Args:
        doc_number: Document number to check
        
    Returns:
        bool: True if auto-generated, False if manually assigned
    """
    if not doc_number:
        return False
    
    doc_str = str(doc_number).strip()
    
    # Must be exactly 25 characters
    if len(doc_str) != 25:
        return False
    
    # Try to convert to integer after removing leading zeros
    try:
        int(doc_str.lstrip('0') or '0')
        return True  # Successfully converted to int = auto-generated
    except (ValueError, TypeError):
        return False  # Failed to convert = manually assigned


# ── Parallel file transfer helpers ──────────────────────────────────────────

def _download_one_file(file_index, document, session_snapshot, source_system, staging_record, logger):
    """Download a single file from source. Thread-safe (creates own session)."""
    dl_session = requests.Session()
    prepare_session_headers(dl_session, session_snapshot, source_system)
    dl_session.headers.pop('Slug', None)

    selected_keys = ['Documentnumber', 'Documentpart', 'Documenttype', 'Documentversion', 'LOIOID']
    document_args = {k: document[k] for k in selected_keys}
    formatted_args = ",".join(f"{k}='{v}'" for k, v in document_args.items())
    base_read_url = cfg.get(source_system, 'api_list', 'document', 'base_url')
    request_url = f"{base_read_url}/DocumentfilesSet({formatted_args})/$value"

    download_start = time.time()
    fallback_name = _resolve_filename(document, staging_record, file_index)
    try:
        response = dl_session.get(request_url, timeout=300)
    except Exception as ex:
        elapsed = time.time() - download_start
        logger.error(f"Download error file {file_index} after {elapsed:.1f}s: {ex}", category="READ")
        return {
            'file_index': file_index, 'success': False,
            'error_msg': f'READ_TIMEOUT: {str(ex)}',
            'error_detail': {'status_code': 0, 'detail': str(ex), 'elapsed_seconds': round(elapsed, 1)},
            'error_category': 'TIMEOUT', 'filename': fallback_name, 'elapsed': elapsed,
        }

    elapsed = time.time() - download_start
    if response.status_code != 200:
        error_info = _extract_error_fields(response)
        logger.error(f"Download failed file {file_index}: {response.status_code}", category="READ", details=error_info)
        return {
            'file_index': file_index, 'success': False,
            'error_msg': f'READ_FAIL_{response.status_code}',
            'error_detail': error_info,
            'error_category': _classify_error(error_info),
            'filename': fallback_name, 'elapsed': elapsed,
        }

    content = response.content
    filename = _resolve_filename(document, staging_record, file_index)
    filename, _ = _normalize_extension(filename)
    mime_type = _get_mime_type(filename)
    size = len(content) if content else 0
    size_mb = size / 1024 / 1024
    logger.info(f"Downloaded file {file_index}: {size:,} bytes ({size_mb:.2f} MB) in {elapsed:.1f}s", category="READ")
    return {
        'file_index': file_index, 'success': True,
        'content': content, 'filename': filename,
        'mime_type': mime_type, 'size': size, 'elapsed': elapsed,
    }


def _patch_responsible_person(session, create_resp_d, source_user, staging_id, misc_engine, logger):
    """PATCH the created document to set ResponsiblePersonName (SAP ignores it on POST)."""
    if not source_user or not source_user.strip():
        return
    try:
        entity_uri = create_resp_d.get('__metadata', {}).get('uri', '')
        if not entity_uri:
            logger.debug("No entity URI in CREATE response — skip ResponsiblePersonName PATCH", category="CREATE")
            return
        patch_resp = session.patch(
            entity_uri,
            json={'ResponsiblePersonName': source_user.strip()},
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=30,
        )
        if patch_resp.status_code in (200, 204):
            logger.info(f"ResponsiblePersonName set to '{source_user.strip()}' via PATCH", category="CREATE")
            with misc_engine.begin() as con:
                con.execute(text("UPDATE dbo.migration_staging SET pers_resp_target = :v WHERE id = :sid"),
                            {'v': source_user.strip(), 'sid': staging_id})
        else:
            logger.warning(f"ResponsiblePersonName PATCH {patch_resp.status_code}: {patch_resp.text[:200]}", category="CREATE")
    except Exception as e:
        logger.debug(f"Could not PATCH ResponsiblePersonName: {e}", category="CREATE")


def _patch_url_description(session, upload_resp, file_description, logger):
    """PATCH the created attachment to set UrlDescription from DRAO Description."""
    if not file_description:
        return
    try:
        resp_data = upload_resp.json()
        entity_uri = resp_data.get('d', {}).get('__metadata', {}).get('uri', '')
        if not entity_uri:
            logger.debug("No entity URI in upload response — skip UrlDescription PATCH", category="UPLOAD")
            return
        patch_resp = session.patch(
            entity_uri,
            json={'UrlDescription': file_description},
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=30,
        )
        if patch_resp.status_code in (200, 204):
            logger.info(f"UrlDescription set: '{file_description}'", category="UPLOAD")
        else:
            logger.warning(f"UrlDescription PATCH {patch_resp.status_code}: {patch_resp.text[:200]}", category="UPLOAD")
    except Exception as e:
        logger.debug(f"Could not PATCH UrlDescription: {e}", category="UPLOAD")


def _upload_one_file(file_index, content, filename, mime_type,
                     doc_type, doc_number, doc_version, doc_part,
                     session_snapshot, target_system, staging_id, batch_id,
                     loio_id, start_time, logger,
                     file_description=''):
    """Upload a single file to target. Thread-safe (creates own session)."""
    ul_session = requests.Session()
    prepare_session_headers(ul_session, session_snapshot, target_system)

    percent_encode = session_snapshot.get('percent_encode_slug', True) if session_snapshot else True
    slug_filename = _sanitize_slug(filename, percent_encode=percent_encode)
    ul_session.headers.update({'Content-Type': mime_type, 'Slug': slug_filename})

    try:
        attachment_base_url = cfg.get(target_system, 'api_list', 'attachment', 'base_url')
    except Exception:
        attachment_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')

    attachment_url = (
        f"{attachment_base_url}/A_DocumentInfoRecordAttch"
        f"(DocumentInfoRecordDocType='{doc_type}',"
        f"DocumentInfoRecordDocNumber='{doc_number}',"
        f"DocumentInfoRecordDocVersion='{doc_version}',"
        f"DocumentInfoRecordDocPart='{doc_part}'"
        f")/DocumentInfoRecordToAttachmentNavigation"
    )

    upload_content = content or b' '
    file_size = len(content) if content else 0
    file_size_mb = file_size / 1024 / 1024
    upload_timeout = max(60, 60 + int(file_size_mb * 10))

    upload_start = time.time()
    try:
        upload_resp = ul_session.post(attachment_url, data=upload_content, timeout=upload_timeout)
        if is_csrf_error(upload_resp):
            logger.warning(f"CSRF expired during UPLOAD file {file_index} — refreshing", category="UPLOAD")
            force_csrf_renewal(session_snapshot, target_system)
            prepare_session_headers(ul_session, session_snapshot, target_system)
            ul_session.headers.update({'Content-Type': mime_type, 'Slug': slug_filename})
            upload_resp = ul_session.post(attachment_url, data=upload_content, timeout=upload_timeout)
    except requests.exceptions.ConnectionError as ex:
        upload_elapsed = time.time() - upload_start
        return {
            'file_index': file_index, 'success': False,
            'file_result': {
                'file': filename, 'status': f'UPLOAD_CONNECTION_ERROR after {upload_elapsed:.1f}s',
                'error_detail': {'status_code': 0, 'detail': str(ex)[:500]},
                'error_category': 'CONNECTION_ERROR',
                'file_size': file_size, 'file_size_mb': round(file_size_mb, 2),
                'mime_type': mime_type, 'actual_time_seconds': round(upload_elapsed, 2),
            },
        }
    except requests.exceptions.Timeout as ex:
        upload_elapsed = time.time() - upload_start
        return {
            'file_index': file_index, 'success': False,
            'file_result': {
                'file': filename, 'status': f'UPLOAD_TIMEOUT after {upload_elapsed:.1f}s',
                'error_detail': {'status_code': 0, 'detail': str(ex)},
                'error_category': 'TIMEOUT',
                'file_size': file_size, 'file_size_mb': round(file_size_mb, 2),
                'mime_type': mime_type, 'actual_time_seconds': round(upload_elapsed, 2),
            },
        }

    upload_elapsed = time.time() - upload_start
    upload_time_total = time.time() - start_time

    if upload_resp.status_code in (200, 201):
        logger.info(f"Uploaded file {file_index}: {filename} ({file_size_mb:.2f} MB) in {upload_elapsed:.1f}s", category="UPLOAD")
        _patch_url_description(ul_session, upload_resp, file_description, logger)
        return {
            'file_index': file_index, 'success': True,
            'file_result': {
                'file': filename, 'status': 'SUCCESS',
                'file_size': file_size, 'file_size_mb': round(file_size_mb, 2),
                'mime_type': mime_type, 'actual_time_seconds': round(upload_time_total, 2),
            },
        }
    else:
        error_info = _extract_error_fields(upload_resp)
        error_msg = f'UPLOAD_FAIL_{upload_resp.status_code}'
        is_size_error = False
        if upload_resp.status_code in (413, 507) or any(
            ind in str(error_info).lower() for ind in ['too large', 'size', 'payload', 'limit', 'exceeded']
        ):
            is_size_error = True
            error_msg = f'SIZE_LIMIT_EXCEEDED_{upload_resp.status_code}'
        logger.error(f"Upload failed file {file_index}: {error_msg}", category="UPLOAD", details=error_info)
        return {
            'file_index': file_index, 'success': False,
            'file_result': {
                'file': filename, 'status': error_msg,
                'error_detail': error_info, 'error_category': _classify_error(error_info),
                'file_size': file_size, 'file_size_mb': round(file_size_mb, 2),
                'mime_type': mime_type, 'is_size_error': is_size_error,
                'actual_time_seconds': round(upload_time_total, 2),
            },
        }


def execute_single_document(staging_record, session_snapshot):
    """Execute migration for a single staging record.
    
    Each worker creates its own requests.Session for optimal connection pooling.
    The session_snapshot contains auth tokens and is shared read-only across workers.
    """
    staging_id = staging_record['id']
    batch_id = staging_record.get('batch_id')
    logger = get_logger(batch_id=batch_id, staging_id=staging_id)
    start_time = time.time()
    
    # Resolve source/target systems from session snapshot (with defaults)
    source_system = get_source_system(session_snapshot)
    target_system = get_target_system(session_snapshot)
    
    # Create worker-specific session for optimal connection pooling
    server_session = requests.Session()
    
    # Mark execution as started in database
    mark_execution_started(staging_id)
    
    logger.info(f"Starting migration for document {staging_record['source_documentnumber']}", category="EXECUTE")
    
    try:
        # Check if this is a RETRY with container already created
        # In that case, we can skip the READ from source system and use cached file info
        container_already_created = staging_record.get('container_created', 0) == 1
        
        if container_already_created:
            # RETRY MODE: Container exists, get file info from local database instead of API
            logger.info(f"Retry mode: Container already created, using cached file info", category="EXECUTE")
            cached_files = get_cached_file_info(staging_id)
            
            if cached_files:
                # Build documents structure from cached data
                documents = (200, 'OK', cached_files)
                logger.info(f"Using {len(cached_files)} cached file records for retry", category="EXECUTE")
                # IMPORTANT: Still need to set up session headers for binary read!
                prepare_session_headers(server_session, session_snapshot, source_system)
                server_session.headers.pop('Slug', None)
            else:
                # No cached file info - fall back to reading from source
                logger.warning(f"No cached file info found, falling back to source read", category="EXECUTE")
                container_already_created = False  # Force normal read path
        
        if not container_already_created:
            # LOCAL LINK DETECTION: DAPPL=HTM with no file content → likely a local link
            # that cannot be read from SAP Content Repository.
            staging_fn = staging_record.get('filename')
            staging_fsz = staging_record.get('file_size_bytes')
            if (staging_fn is None or staging_fn == '') or (staging_fsz is None or staging_fsz == 0):
                # Check DAPPL from DIL.DMS_DOC_FILES
                _local_link_dappl = ''
                try:
                    if DIL_AVAILABLE and dil_engine:
                        with dil_engine.begin() as _llcon:
                            _ll_row = _llcon.execute(text("""
                                SELECT DAPPL FROM DIL.DMS_DOC_FILES
                                WHERE DOKNR = :doknr AND DOKAR = :dokar
                                  AND DOKVR = :dokvr AND DOKTL = :doktl
                            """), {
                                'doknr': staging_record['source_documentnumber'],
                                'dokar': staging_record['source_documenttype'],
                                'dokvr': str(staging_record['source_documentversion']).zfill(2),
                                'doktl': str(staging_record['source_documentpart']).zfill(3)
                            }).fetchone()
                            if _ll_row:
                                _local_link_dappl = str(_ll_row[0] or '').strip().upper()
                except Exception as _lle:
                    logger.debug(f"Local link DAPPL check failed: {_lle}", category="READ")
                
                # HTM skip disabled for testing
                # if _local_link_dappl == 'HTM':
                #     error_msg = ("LOCAL_LINK - Lokaler Link (DAPPL=HTM) - "
                #                  "Datei nicht im Content Repository gespeichert. "
                #                  "Lokale Pfad-Referenz kann nicht migriert werden.")
                #     logger.info(error_msg, category="READ")
                #     update_execution_status(staging_id, 'success', error_msg)
                #     update_link_status(staging_id, 'link_skipped',
                #                        'Nicht notwendig - Lokaler Link (kein KPRO-Inhalt)')
                #     return {
                #         'staging_id': staging_id,
                #         'status': 'success',
                #         'error': error_msg,
                #         'error_category': 'LOCAL_LINK',
                #         'status_code': 200
                #     }
            
            # NORMAL MODE: Read from source system
            # Prepare session headers for read system
            prepare_session_headers(server_session, session_snapshot, source_system)
            server_session.headers.pop('Slug', None)
            
            logger.debug(f"Fetching document info from {source_system}", category="EXECUTE")
            
            # Get document info from source system
            documents = get_info(
                server_session,
                source_system,
                staging_record['source_documentnumber'],
                staging_record['source_documentpart'],
                staging_record['source_documenttype'],
                staging_record['source_documentversion']
            )
        
        if documents[0] != 200:
            import json
            error_info = {'status_code': documents[0], 'reason': documents[1]}
            error_msg = f"READ_FAILED {documents[0]} {documents[1]}"
            
            # Fallback local-link detection: if READ fails AND DAPPL=HTM → skip as local link
            _read_fail_dappl = ''
            try:
                if DIL_AVAILABLE and dil_engine:
                    with dil_engine.begin() as _rfcon:
                        _rf_row = _rfcon.execute(text("""
                            SELECT DAPPL FROM DIL.DMS_DOC_FILES
                            WHERE DOKNR = :doknr AND DOKAR = :dokar
                              AND DOKVR = :dokvr AND DOKTL = :doktl
                        """), {
                            'doknr': staging_record['source_documentnumber'],
                            'dokar': staging_record['source_documenttype'],
                            'dokvr': str(staging_record['source_documentversion']).zfill(2),
                            'doktl': str(staging_record['source_documentpart']).zfill(3)
                        }).fetchone()
                        if _rf_row:
                            _read_fail_dappl = str(_rf_row[0] or '').strip().upper()
            except Exception:
                pass
            
            # HTM skip disabled for testing
            # if _read_fail_dappl == 'HTM':
            #     skip_msg = ("LOCAL_LINK - Lokaler Link (DAPPL=HTM) - "
            #                 "READ fehlgeschlagen, Datei nicht im Content Repository. "
            #                 "Lokale Pfad-Referenz kann nicht migriert werden.")
            #     logger.info(skip_msg, category="READ")
            #     update_execution_status(staging_id, 'success', skip_msg)
            #     update_link_status(staging_id, 'link_skipped',
            #                        'Nicht notwendig - Lokaler Link (kein KPRO-Inhalt)')
            #     return {
            #         'staging_id': staging_id,
            #         'status': 'success',
            #         'error': skip_msg,
            #         'error_category': 'LOCAL_LINK',
            #         'status_code': 200
            #     }
            
            error_json = json.dumps(error_info)
            logger.error(error_msg, category="READ", details=error_info)
            update_execution_status(staging_id, 'failed', error_json)
            return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg, 'error_detail': error_info, 'status_code': documents[0]}
        
        if not documents[2] or len(documents[2]) == 0:
            error_msg = "READ_EMPTY - No documents found"
            logger.info(error_msg + " (treated as success - no files to migrate)", category="READ")
            # Treat as success: no files in source = nothing to migrate = OK
            update_execution_status(staging_id, 'success', error_msg)
            # Mark link as not needed (no container → no linking)
            update_link_status(staging_id, 'link_skipped', 'Nicht notwendig - Keine Dateien im Quellsystem')
            return {
                'staging_id': staging_id, 
                'status': 'success', 
                'error': error_msg, 
                'error_category': 'SOURCE_EMPTY',
                'status_code': 200
            }
        
        source_file_count = len(documents[2])
        logger.info(f"Found {source_file_count} files to migrate", category="EXECUTE")
        
        # Save source file count to staging table
        try:
            with misc_engine.begin() as con:
                con.execute(text("""
                    UPDATE dbo.migration_staging
                    SET source_file_count = :cnt
                    WHERE id = :staging_id
                """), {'cnt': source_file_count, 'staging_id': staging_id})
        except Exception as e:
            logger.debug(f"Failed to update source_file_count: {e}", category="EXECUTE")
        
        # Extract metadata from first document for updating staging table
        first_doc = documents[2][0] if documents[2] else {}
        doc_loioid = first_doc.get('LOIOID')
        # Prefer DocumentDescription (enriched from DESCRIPTIONSSet/parent) over file-level Description
        doc_description = first_doc.get('DocumentDescription') or first_doc.get('Description')
        doc_authgroup = first_doc.get('Authoritygroup')  # BEGRU from API
        
        # Extract ObjectlinksSet from API response (replaces DIL.DRAD query)
        # Collect ALL object links — each document can have multiple links
        object_links = first_doc.get('_ObjectlinksSet', [])
        api_dokob = None
        api_objky = None
        api_all_links = []  # All (dokob, objky) pairs from API
        if object_links:
            for ol in object_links:
                ol_dokob = ol.get('Objecttype', '').strip()
                ol_objky = ol.get('Objectkey', '').strip()
                if ol_dokob and ol_objky:
                    pair = (ol_dokob, ol_objky)
                    if pair not in api_all_links:
                        api_all_links.append(pair)
            if api_all_links:
                api_dokob, api_objky = api_all_links[0]
        
        # Apply DOKOB filter: split links into kept vs excluded
        dokob_filter_set = load_batch_dokob_filter(batch_id)
        excluded_links = []
        if dokob_filter_set and api_all_links:
            kept = []
            for pair in api_all_links:
                if pair[0].upper() in dokob_filter_set:
                    kept.append(pair)
                else:
                    excluded_links.append(pair)
            if excluded_links:
                logger.info(f"DOKOB filter excluded {len(excluded_links)} of {len(api_all_links)} links", category="OBJLINK")
            api_all_links = kept
            # Update primary dokob/objky to first kept link (if any)
            if api_all_links:
                api_dokob, api_objky = api_all_links[0]
            else:
                api_dokob, api_objky = None, None
        
        # Build updated source_object_links JSON from API (authoritative source)
        # Only contains links matching the batch's DOKOB filter (excluded links stored separately)
        import json as json_mod
        api_links_json = None
        excluded_links_json = None
        if api_all_links:
            api_links_json = json_mod.dumps([{'dokob': d, 'objky': o} for d, o in api_all_links])
            if len(api_all_links) > 1:
                logger.info(f"API returned {len(api_all_links)} object links (after filter)", category="OBJLINK")
        if excluded_links:
            excluded_links_json = json_mod.dumps([{'dokob': d, 'objky': o} for d, o in excluded_links])
        
        # Apply object mapping on-the-fly to get target_dokob/target_objky
        # NOTE: Object mappings are loaded per batch and cached within this function scope
        target_dokob = staging_record.get('target_dokob')  # May already be set from manual entry
        target_objky = staging_record.get('target_objky')
        
        if api_dokob and api_objky and not (target_dokob and target_objky):
            # Load mappings for this batch and lookup target values
            try:
                mappings = load_object_mappings(batch_id)
                if mappings:
                    key = (str(api_dokob).upper(), str(api_objky))
                    if key in mappings:
                        target_dokob, target_objky = mappings[key]
                        logger.debug(f"Object mapping found: {key} -> ({target_dokob}, {target_objky})", category="OBJLINK")
                    else:
                        logger.debug(f"No object mapping found for {key}", category="OBJLINK")
            except Exception as e:
                logger.debug(f"Failed to load object mappings: {e}", category="OBJLINK")
        
        # Update staging with API metadata (DOKOB, OBJKY, filtered links, Authoritygroup)
        # and resolved target values.
        # source_object_links contains only links matching batch DOKOB filter.
        # excluded_object_links contains links filtered out by DOKOB filter.
        # NOTE: authorization_group is ONLY updated from API if it was NULL in staging.
        # If a rule already set it (even to empty string ''), the rule takes precedence.
        # source_authorization_group always stores the original API value for reference.
        if api_dokob or api_objky or api_links_json or excluded_links_json or doc_authgroup or target_dokob or target_objky:
            try:
                with misc_engine.begin() as con:
                    con.execute(text("""
                        UPDATE dbo.migration_staging
                        SET source_dokob = COALESCE(:dokob, source_dokob),
                            source_objky = COALESCE(:objky, source_objky),
                            source_object_links = COALESCE(:links_json, source_object_links),
                            source_link_count = CASE WHEN :link_count IS NOT NULL THEN :link_count ELSE source_link_count END,
                            excluded_object_links = COALESCE(:excluded_json, excluded_object_links),
                            excluded_link_count = CASE WHEN :excluded_count IS NOT NULL THEN :excluded_count ELSE excluded_link_count END,
                            source_authorization_group = COALESCE(:authgroup, source_authorization_group),
                            authorization_group = CASE 
                                WHEN authorization_group IS NULL THEN :authgroup
                                ELSE authorization_group  
                            END,
                            target_dokob = COALESCE(:target_dokob, target_dokob),
                            target_objky = COALESCE(:target_objky, target_objky)
                        WHERE id = :staging_id
                    """), {
                        'staging_id': staging_id, 
                        'dokob': api_dokob, 
                        'objky': api_objky,
                        'links_json': api_links_json,
                        'link_count': len(api_all_links) if api_all_links else None,
                        'excluded_json': excluded_links_json,
                        'excluded_count': len(excluded_links) if excluded_links else None,
                        'authgroup': doc_authgroup,
                        'target_dokob': target_dokob,
                        'target_objky': target_objky
                    })
                logger.debug(f"Updated from API: DOKOB={api_dokob}, OBJKY={api_objky}, links={len(api_all_links)}, excluded={len(excluded_links)}, BEGRU={doc_authgroup}, target=({target_dokob},{target_objky})", category="EXECUTE")
            except Exception as e:
                logger.debug(f"Failed to update API metadata: {e}", category="EXECUTE")
        
        # Process each file in the document container
        doc_created = False
        results = []
        metadata_updated = False
        # batch_id already set at function start from staging_record
        
        # Extract document identifiers ONCE before the file loop.
        # CRITICAL: These must NOT be re-read from staging_record inside the loop,
        # because CREATE may update doc_number/doc_version/doc_part (e.g. IY1 auto-numbering)
        # and re-reading from the stale in-memory staging_record would overwrite the
        # correct values back to None.
        doc_type = staging_record['target_documenttype']
        doc_number = staging_record['target_documentnumber']
        doc_version = staging_record['target_documentversion'] or staging_record.get('source_documentversion', '01')
        doc_part = staging_record['target_documentpart'] or staging_record.get('source_documentpart', '000')
        
        # Check if container was already created in a previous (failed) attempt
        container_already_created = staging_record.get('container_created', 0) == 1
        if container_already_created:
            # Safety check: for internal numbering types, doc_number MUST exist.
            # If a previous CREATE succeeded but the number wasn't captured,
            # container_created=1 but target_documentnumber is NULL.
            # Instead of failing permanently, reset and create a NEW container.
            # (The orphaned S4 container from the previous attempt is accepted.)
            if not doc_number and doc_type in {'IY1', 'IY2'}:
                logger.warning(
                    f"RETRY_DOC_NUMBER_MISSING: container_created=1 but doc_number is NULL "
                    f"for internal-numbering type {doc_type}. Resetting to create a new "
                    f"container (orphaned S4 container accepted).", category="CREATE"
                )
                # Reset container state so a fresh CREATE will happen
                try:
                    with misc_engine.begin() as con:
                        con.execute(text("""
                            UPDATE dbo.migration_staging
                            SET container_created = 0,
                                target_documentnumber = NULL,
                                target_documentversion = NULL,
                                target_documentpart = NULL
                            WHERE id = :sid
                        """), {'sid': staging_id})
                        # Also delete any stale file_details from the broken attempt
                        con.execute(text("""
                            DELETE FROM dbo.migration_file_details
                            WHERE staging_id = :sid
                        """), {'sid': staging_id})
                    container_already_created = False
                    doc_number = None  # Will be set by CREATE response
                    logger.info(f"Reset container state for staging_id={staging_id}, will create new container", category="CREATE")
                except Exception as reset_ex:
                    error_msg = (
                        f"RETRY_DOC_NUMBER_MISSING: Could not auto-reset: {reset_ex}"
                    )
                    logger.error(error_msg, category="CREATE")
                    update_execution_status(staging_id, 'failed', error_msg)
                    return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg}
            else:
                logger.info(f"Container already created in previous attempt, skipping CREATE", category="CREATE")
            # Only mark doc_created if container still exists (not reset above)
            if container_already_created:
                doc_created = True
        
        # Get already successfully uploaded files (for retry optimization)
        # IMPORTANT: Only skip files if the container already exists from a previous attempt.
        # If container_created is False, ALL files must be re-uploaded to the NEW container
        # even if file_details has SUCCESS records from a previous (now-reset) run.
        if container_already_created:
            already_uploaded = get_successfully_uploaded_files(staging_id)
            if already_uploaded:
                logger.info(f"Retry mode: {len(already_uploaded)} files already uploaded successfully, will skip them", category="EXECUTE")
        else:
            already_uploaded = set()  # Fresh container → upload everything
            # Clean up stale file_details from previous failed attempts to avoid
            # duplicate rows in the validation dashboard.
            try:
                with misc_engine.begin() as con:
                    del_count = con.execute(text(
                        "DELETE FROM dbo.migration_file_details WHERE staging_id = :sid"
                    ), {'sid': staging_id}).rowcount
                    if del_count:
                        logger.info(f"Cleaned up {del_count} stale file_details from previous attempt", category="EXECUTE")
            except Exception as _cleanup_ex:
                logger.debug(f"file_details cleanup failed (non-critical): {_cleanup_ex}", category="EXECUTE")
        
        # ── PARALLEL DOWNLOAD: Pre-fetch all files from source ──────────────
        # For multi-file containers, download all files in parallel before the
        # sequential CREATE + upload loop. This overlaps download latency (~3-5s
        # per file) so total download time ≈ max(single) instead of sum(all).
        # Single-file containers skip this (no benefit from parallelism).
        _prefetched = {}  # file_index -> download result dict
        _has_web_files = any(
            (doc.get('Wsapplication', '') or '').strip().upper() == 'WEB'
            for doc in documents[2]
        )
        _files_to_download = [
            (fi, doc) for fi, doc in enumerate(documents[2])
            if fi not in already_uploaded
            and (doc.get('Wsapplication', '') or '').strip().upper() != 'WEB'
        ]
        
        if len(_files_to_download) > 1 and not container_already_created:
            logger.info(f"Parallel download: {len(_files_to_download)} files from source", category="READ")
            _dl_workers = min(len(_files_to_download), 5)
            with ThreadPoolExecutor(max_workers=_dl_workers) as _dl_pool:
                _dl_futures = {
                    _dl_pool.submit(
                        _download_one_file, fi, doc,
                        session_snapshot, source_system, staging_record, logger
                    ): fi
                    for fi, doc in _files_to_download
                }
                from concurrent.futures import as_completed as _as_completed
                for fut in _as_completed(_dl_futures):
                    res = fut.result()
                    _prefetched[res['file_index']] = res
            _dl_ok = sum(1 for r in _prefetched.values() if r['success'])
            logger.info(f"Parallel download complete: {_dl_ok}/{len(_prefetched)} OK", category="READ")
        
        for file_index, document in enumerate(documents[2]):
            # Skip files that were already successfully uploaded (retry optimization)
            if file_index in already_uploaded:
                logger.info(f"Skipping file {file_index} - already successfully uploaded", category="EXECUTE")
                # Add a placeholder result for the skipped file
                results.append({
                    'file': document.get('Docpath', '').split('/')[-1] or f'file_{file_index}',
                    'status': 'SUCCESS_SKIPPED',
                    'file_size': 0,
                    'file_size_mb': 0,
                    'mime_type': None,
                    'is_size_error': False,
                    'actual_time_seconds': 0,
                    'skipped': True
                })
                continue
            
            # ── WEB application: copy URL reference instead of downloading ──
            ws_appl = (document.get('Wsapplication', '') or '').strip().upper()
            docpath_url = (document.get('Docpath', '') or '').strip()
            
            if ws_appl == 'WEB' and docpath_url:
                logger.info(f"WEB application detected — copying URL reference instead of downloading", category="READ")
                logger.info(f"Docpath URL: {docpath_url}", category="READ")
                
                # Build a .url shortcut file content (Windows Internet Shortcut format)
                url_content = f"[InternetShortcut]\nURL={docpath_url}\n".encode('utf-8')
                filename = 'link.url'
                
                # Update metadata
                if not metadata_updated:
                    update_metadata_fields(
                        staging_id,
                        loioid=document.get('LOIOID'),
                        description=doc_description,
                        filename=filename,
                        file_size=len(url_content),
                        mime_type='application/x-url'
                    )
                    metadata_updated = True
                
                # Switch to target system and create container if needed
                prepare_session_headers(server_session, session_snapshot, target_system)
                
                if not doc_created:
                    # -- Container creation (same logic as normal flow) --
                    source_doc_number = staging_record['source_documentnumber']
                    is_auto_id = is_auto_generated_id(source_doc_number)
                    effective_description = doc_description or staging_record.get('source_description') or filename
                    if isinstance(effective_description, str):
                        effective_description = effective_description.strip()
                    if not effective_description:
                        effective_description = filename
                    if len(effective_description) > MAX_DESC_LEN:
                        effective_description = effective_description[:MAX_DESC_LEN]
                    
                    doc_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
                    create_url = f"{doc_base_url}/A_DocumentInfoRecord"
                    server_session.headers.update({'Content-Type': 'application/json'})
                    
                    dms_payload = {
                        'DocumentInfoRecordDocType': doc_type,
                        'DocumentInfoRecordDocVersion': doc_version,
                        'DocumentInfoRecordDocPart': doc_part,
                        'to_DocDesc': [
                            {'Language': 'DE', 'DocumentDescription': effective_description},
                            {'Language': 'EN', 'DocumentDescription': effective_description}
                        ]
                    }
                    
                    effective_doc_number = staging_record.get('target_documentnumber') or doc_number
                    doc_number_sent_to_s4 = False
                    rule_set_doc_number = staging_record.get('target_documentnumber')
                    if rule_set_doc_number:
                        dms_payload['DocumentInfoRecordDocNumber'] = rule_set_doc_number
                        doc_number_sent_to_s4 = True
                    elif effective_doc_number and not _is_purely_numeric(effective_doc_number):
                        dms_payload['DocumentInfoRecordDocNumber'] = effective_doc_number
                        doc_number_sent_to_s4 = True
                    
                    staging_authgroup = staging_record.get('authorization_group')
                    if staging_authgroup is not None:
                        effective_authgroup = staging_authgroup.strip() if staging_authgroup else ''
                    else:
                        effective_authgroup = doc_authgroup or ''
                    if effective_authgroup:
                        dms_payload['AuthorizationGroup'] = effective_authgroup
                    
                    source_user = staging_record.get('pers_resp_source')
                    
                    logger.info(f"Creating document info record (WEB)", category="CREATE")
                    create_resp = server_session.post(create_url, json=dms_payload)
                    
                    # CSRF retry
                    if is_csrf_error(create_resp):
                        logger.warning("CSRF token expired during WEB CREATE — refreshing and retrying", category="CREATE")
                        force_csrf_renewal(session_snapshot, target_system)
                        prepare_session_headers(server_session, session_snapshot, target_system)
                        server_session.headers.update({'Content-Type': 'application/json'})
                        create_resp = server_session.post(create_url, json=dms_payload)
                    
                    if create_resp.status_code in (200, 201):
                        resp_d = {}
                        try:
                            resp_d = create_resp.json().get('d', {})
                            created_doc_number = resp_d.get('DocumentInfoRecordDocNumber')
                            if created_doc_number:
                                doc_number = created_doc_number
                                with misc_engine.begin() as con:
                                    con.execute(text("""
                                        UPDATE dbo.migration_staging
                                        SET target_documentnumber = :num WHERE id = :sid
                                    """), {'num': created_doc_number, 'sid': staging_id})
                            created_doc_version = resp_d.get('DocumentInfoRecordDocVersion')
                            if created_doc_version and created_doc_version != doc_version:
                                doc_version = created_doc_version
                                with misc_engine.begin() as con:
                                    con.execute(text("UPDATE dbo.migration_staging SET target_documentversion = :v WHERE id = :sid"), {'v': doc_version, 'sid': staging_id})
                            created_doc_part = resp_d.get('DocumentInfoRecordDocPart')
                            if created_doc_part and created_doc_part != doc_part:
                                doc_part = created_doc_part
                                with misc_engine.begin() as con:
                                    con.execute(text("UPDATE dbo.migration_staging SET target_documentpart = :p WHERE id = :sid"), {'p': doc_part, 'sid': staging_id})
                        except Exception as e:
                            logger.warning(f"Failed to extract doc number from WEB CREATE response: {e}", category="CREATE")
                        
                        if not doc_number_sent_to_s4 and not doc_number:
                            error_msg = "CREATE_DOC_NUMBER_LOST: WEB doc created but number not captured"
                            logger.error(error_msg, category="CREATE")
                            update_execution_status(staging_id, 'failed', error_msg)
                            return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg}
                        
                        doc_created = True
                        with misc_engine.begin() as con:
                            con.execute(text("UPDATE dbo.migration_staging SET container_created = 1 WHERE id = :sid"), {'sid': staging_id})
                        logger.info(f"WEB document container created: {doc_number}", category="CREATE")
                        
                        _patch_responsible_person(server_session, resp_d, source_user, staging_id, misc_engine, logger)
                    else:
                        error_info = _extract_error_fields(create_resp)
                        error_msg = f"CREATE_FAIL_{create_resp.status_code}"
                        logger.error(error_msg, category="CREATE", details=error_info)
                        import json as _json
                        update_execution_status(staging_id, 'failed', _json.dumps(error_info))
                        return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg, 'error_detail': error_info}
                
                # Upload the .url file as attachment
                if doc_created and doc_number:
                    slug_filename = _sanitize_slug(filename)
                    server_session.headers.update({'Content-Type': 'application/octet-stream', 'Slug': slug_filename})
                    
                    try:
                        attachment_base_url = cfg.get(target_system, 'api_list', 'attachment', 'base_url')
                    except Exception:
                        attachment_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
                    
                    attachment_url = (
                        f"{attachment_base_url}/A_DocumentInfoRecordAttch"
                        f"(DocumentInfoRecordDocType='{doc_type}',"
                        f"DocumentInfoRecordDocNumber='{doc_number}',"
                        f"DocumentInfoRecordDocVersion='{doc_version}',"
                        f"DocumentInfoRecordDocPart='{doc_part}'"
                        f")/DocumentInfoRecordToAttachmentNavigation"
                    )
                    
                    logger.info(f"Uploading URL reference: {filename} ({len(url_content)} bytes)", category="UPLOAD")
                    try:
                        upload_resp = server_session.post(attachment_url, data=url_content, timeout=60)
                        # CSRF retry
                        if is_csrf_error(upload_resp):
                            logger.warning("CSRF token expired during WEB UPLOAD — refreshing and retrying", category="UPLOAD")
                            force_csrf_renewal(session_snapshot, target_system)
                            prepare_session_headers(server_session, session_snapshot, target_system)
                            server_session.headers.update({'Content-Type': 'application/octet-stream', 'Slug': slug_filename})
                            upload_resp = server_session.post(attachment_url, data=url_content, timeout=60)
                    except Exception as ex:
                        error_msg = f'UPLOAD_WEB_ERROR: {str(ex)[:300]}'
                        logger.error(error_msg, category="UPLOAD")
                        file_result = {'file': filename, 'status': error_msg, 'error_category': 'CONNECTION_ERROR'}
                        results.append(file_result)
                        save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                        continue
                    
                    if upload_resp.status_code in (200, 201):
                        logger.info(f"WEB URL reference uploaded successfully", category="UPLOAD")
                        _patch_url_description(server_session, upload_resp, document.get('FileDescription', ''), logger)
                        file_result = {
                            'file': filename,
                            'status': 'SUCCESS',
                            'file_size': len(url_content),
                            'file_size_mb': 0,
                            'mime_type': 'application/x-url',
                            'actual_time_seconds': 0
                        }
                    else:
                        error_info = _extract_error_fields(upload_resp)
                        error_msg = f"UPLOAD_WEB_FAIL_{upload_resp.status_code}"
                        logger.error(f"WEB URL upload failed: {error_msg}", category="UPLOAD", details=error_info)
                        file_result = {
                            'file': filename,
                            'status': error_msg,
                            'error_detail': error_info,
                            'error_category': _classify_error(error_info)
                        }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                continue  # Skip normal download/upload flow for WEB
            
            # ── LOCAL_LINK / WEB_URL: Handle documents with path references ──
            # NOTE: Most documents with local paths in FILEP still have content in the 
            # SAP Archive (Content Server). The download API uses DOKNR/LOID to fetch content,
            # NOT the file path. Therefore, we let the normal download flow handle these files.
            # The filename is correctly extracted by _resolve_filename() using split('/')[-1].
            #
            # This logic is now DISABLED - only kept for true "no content" cases in the future.
            # The normal download/upload pipeline handles all cases correctly.
            _is_local_link = False
            _is_web_url_link = False
            _link_path = ''
            
            if False and file_index == 0:  # DISABLED: Normal download handles local paths correctly
                # Get FILEP from DRAW to check if it's a local path or web URL
                _filep = get_filep_from_draw(
                    staging_record['source_documentnumber'],
                    staging_record['source_documenttype'],
                    staging_record['source_documentversion'],
                    staging_record['source_documentpart']
                )
                if _filep:
                    if is_local_path(_filep):
                        _is_local_link = True
                        _link_path = _filep
                        logger.info(f"LOCAL_LINK detected — local path reference: {_filep[:100]}...", category="READ")
                    elif is_web_url(_filep):
                        _is_web_url_link = True
                        _link_path = _filep
                        logger.info(f"WEB_URL detected — web URL reference (HTM): {_filep[:100]}...", category="READ")
            
            if (_is_local_link or _is_web_url_link) and _link_path:
                # Create empty placeholder file with original filename for correct DAPPL
                # Note: We don't use .url shortcut content because SAP rejects file:// URLs
                url_content = create_local_link_placeholder(_link_path)
                filename = get_shortcut_filename(_link_path)
                link_type = 'LOCAL_LINK' if _is_local_link else 'WEB_URL'
                
                logger.info(f"{link_type} placeholder → {filename} (original path: {_link_path[:80]}...)", category="READ")
                
                # Update metadata
                if not metadata_updated:
                    update_metadata_fields(
                        staging_id,
                        loioid=document.get('LOIOID'),
                        description=doc_description,
                        filename=filename,
                        file_size=0,  # Empty placeholder
                        mime_type='application/octet-stream'
                    )
                    metadata_updated = True
                
                # Switch to target system and create container if needed
                prepare_session_headers(server_session, session_snapshot, target_system)
                
                if not doc_created:
                    # Container creation for LOCAL_LINK/WEB_URL (same as WEB flow)
                    source_doc_number = staging_record['source_documentnumber']
                    effective_description = doc_description or staging_record.get('source_description') or filename
                    if isinstance(effective_description, str):
                        effective_description = effective_description.strip()
                    if not effective_description:
                        effective_description = filename
                    if len(effective_description) > MAX_DESC_LEN:
                        effective_description = effective_description[:MAX_DESC_LEN]
                    
                    doc_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
                    create_url = f"{doc_base_url}/A_DocumentInfoRecord"
                    server_session.headers.update({'Content-Type': 'application/json'})
                    
                    dms_payload = {
                        'DocumentInfoRecordDocType': doc_type,
                        'DocumentInfoRecordDocVersion': doc_version,
                        'DocumentInfoRecordDocPart': doc_part,
                        'to_DocDesc': [
                            {'Language': 'DE', 'DocumentDescription': effective_description},
                            {'Language': 'EN', 'DocumentDescription': effective_description}
                        ]
                    }
                    
                    effective_doc_number = staging_record.get('target_documentnumber') or doc_number
                    doc_number_sent_to_s4 = False
                    rule_set_doc_number = staging_record.get('target_documentnumber')
                    if rule_set_doc_number:
                        dms_payload['DocumentInfoRecordDocNumber'] = rule_set_doc_number
                        doc_number_sent_to_s4 = True
                    elif effective_doc_number and not _is_purely_numeric(effective_doc_number):
                        dms_payload['DocumentInfoRecordDocNumber'] = effective_doc_number
                        doc_number_sent_to_s4 = True
                    
                    staging_authgroup = staging_record.get('authorization_group')
                    if staging_authgroup is not None:
                        effective_authgroup = staging_authgroup.strip() if staging_authgroup else ''
                    else:
                        effective_authgroup = doc_authgroup or ''
                    if effective_authgroup:
                        dms_payload['AuthorizationGroup'] = effective_authgroup
                    
                    source_user = staging_record.get('pers_resp_source')
                    
                    logger.info(f"Creating document info record ({link_type})", category="CREATE")
                    create_resp = server_session.post(create_url, json=dms_payload)
                    
                    # CSRF retry
                    if is_csrf_error(create_resp):
                        logger.warning(f"CSRF token expired during {link_type} CREATE — refreshing", category="CREATE")
                        force_csrf_renewal(session_snapshot, target_system)
                        prepare_session_headers(server_session, session_snapshot, target_system)
                        server_session.headers.update({'Content-Type': 'application/json'})
                        create_resp = server_session.post(create_url, json=dms_payload)
                    
                    if create_resp.status_code in (200, 201):
                        resp_d = {}
                        try:
                            resp_d = create_resp.json().get('d', {})
                            created_doc_number = resp_d.get('DocumentInfoRecordDocNumber')
                            if created_doc_number:
                                doc_number = created_doc_number
                                with misc_engine.begin() as con:
                                    con.execute(text("""
                                        UPDATE dbo.migration_staging
                                        SET target_documentnumber = :num WHERE id = :sid
                                    """), {'num': created_doc_number, 'sid': staging_id})
                            created_doc_version = resp_d.get('DocumentInfoRecordDocVersion')
                            if created_doc_version and created_doc_version != doc_version:
                                doc_version = created_doc_version
                                with misc_engine.begin() as con:
                                    con.execute(text("UPDATE dbo.migration_staging SET target_documentversion = :v WHERE id = :sid"), {'v': doc_version, 'sid': staging_id})
                            created_doc_part = resp_d.get('DocumentInfoRecordDocPart')
                            if created_doc_part and created_doc_part != doc_part:
                                doc_part = created_doc_part
                                with misc_engine.begin() as con:
                                    con.execute(text("UPDATE dbo.migration_staging SET target_documentpart = :p WHERE id = :sid"), {'p': doc_part, 'sid': staging_id})
                        except Exception as e:
                            logger.warning(f"Failed to extract doc number from {link_type} CREATE response: {e}", category="CREATE")
                        
                        if not doc_number_sent_to_s4 and not doc_number:
                            error_msg = f"CREATE_DOC_NUMBER_LOST: {link_type} doc created but number not captured"
                            logger.error(error_msg, category="CREATE")
                            update_execution_status(staging_id, 'failed', error_msg)
                            return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg}
                        
                        doc_created = True
                        with misc_engine.begin() as con:
                            con.execute(text("UPDATE dbo.migration_staging SET container_created = 1 WHERE id = :sid"), {'sid': staging_id})
                        
                        _patch_responsible_person(server_session, resp_d, source_user, staging_id, misc_engine, logger)
                        logger.info(f"{link_type} document container created: {doc_number}", category="CREATE")
                    else:
                        error_info = _extract_error_fields(create_resp)
                        error_msg = f"CREATE_FAIL_{create_resp.status_code}"
                        logger.error(error_msg, category="CREATE", details=error_info)
                        import json as _json
                        update_execution_status(staging_id, 'failed', _json.dumps(error_info))
                        return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg, 'error_detail': error_info}
                
                # Upload the empty placeholder file as attachment (with original filename for DAPPL)
                if doc_created and doc_number:
                    slug_filename = _sanitize_slug(filename)
                    server_session.headers.update({'Content-Type': 'application/octet-stream', 'Slug': slug_filename})
                    
                    try:
                        attachment_base_url = cfg.get(target_system, 'api_list', 'attachment', 'base_url')
                    except Exception:
                        attachment_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
                    
                    attachment_url = (
                        f"{attachment_base_url}/A_DocumentInfoRecordAttch"
                        f"(DocumentInfoRecordDocType='{doc_type}',"
                        f"DocumentInfoRecordDocNumber='{doc_number}',"
                        f"DocumentInfoRecordDocVersion='{doc_version}',"
                        f"DocumentInfoRecordDocPart='{doc_part}'"
                        f")/DocumentInfoRecordToAttachmentNavigation"
                    )
                    
                    logger.info(f"Uploading {link_type} shortcut: {filename} ({len(url_content)} bytes)", category="UPLOAD")
                    try:
                        upload_resp = server_session.post(attachment_url, data=url_content, timeout=60)
                        # CSRF retry
                        if is_csrf_error(upload_resp):
                            logger.warning(f"CSRF token expired during {link_type} UPLOAD — refreshing", category="UPLOAD")
                            force_csrf_renewal(session_snapshot, target_system)
                            prepare_session_headers(server_session, session_snapshot, target_system)
                            server_session.headers.update({'Content-Type': 'application/octet-stream', 'Slug': slug_filename})
                            upload_resp = server_session.post(attachment_url, data=url_content, timeout=60)
                    except Exception as ex:
                        error_msg = f'UPLOAD_{link_type}_ERROR: {str(ex)[:300]}'
                        logger.error(error_msg, category="UPLOAD")
                        file_result = {'file': filename, 'status': error_msg, 'error_category': 'CONNECTION_ERROR'}
                        results.append(file_result)
                        save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                        continue
                    
                    if upload_resp.status_code in (200, 201):
                        logger.info(f"{link_type} placeholder uploaded: {filename} (ref: {_link_path[:60]}...)", category="UPLOAD")
                        _patch_url_description(server_session, upload_resp, document.get('FileDescription', ''), logger)
                        file_result = {
                            'file': filename,
                            'status': 'SUCCESS',
                            'file_size': 0,  # Empty placeholder
                            'file_size_mb': 0,
                            'mime_type': 'application/octet-stream',
                            'actual_time_seconds': 0,
                            'local_link': _is_local_link,
                            'web_url_link': _is_web_url_link,
                            'original_path': _link_path[:200]
                        }
                    else:
                        error_info = _extract_error_fields(upload_resp)
                        error_msg = f"UPLOAD_{link_type}_FAIL_{upload_resp.status_code}"
                        logger.error(f"{link_type} upload failed: {error_msg}", category="UPLOAD", details=error_info)
                        file_result = {
                            'file': filename,
                            'status': error_msg,
                            'error_detail': error_info,
                            'error_category': _classify_error(error_info)
                        }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                continue  # Skip normal download/upload flow for LOCAL_LINK/WEB_URL
            
            # ── DOWNLOAD: Use prefetched content or download inline ─────────
            if file_index in _prefetched:
                # Already downloaded in parallel phase (pop to mark handled)
                _pf = _prefetched.pop(file_index)
                if not _pf['success']:
                    # Prefetch failed — record the error and continue
                    file_result = {
                        'file': _pf.get('filename', f'file_{file_index}'),
                        'status': _pf.get('error_msg', 'READ_FAIL'),
                        'error_detail': _pf.get('error_detail'),
                        'error_category': _pf.get('error_category', 'OTHER'),
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                    continue
                response_content = _pf['content']
                filename = _pf['filename']
            else:
                # Serial download (single-file containers, retries, fallback)
                prepare_session_headers(server_session, session_snapshot, source_system)
                server_session.headers.pop('Slug', None)
                
                selected_keys = ['Documentnumber', 'Documentpart', 'Documenttype', 'Documentversion', 'LOIOID']
                document_args = {k: document[k] for k in selected_keys}
                formatted_args = ",".join(f"{k}='{v}'" for k, v in document_args.items())
                base_read_url = cfg.get(source_system, 'api_list', 'document', 'base_url')
                request_url = f"{base_read_url}/DocumentfilesSet({formatted_args})/$value"
                
                download_start = time.time()
                logger.info(f"Downloading file {file_index} from source: LOIOID={document.get('LOIOID')}", category="READ")
                _fallback_name = _resolve_filename(document, staging_record, file_index)
                
                try:
                    response = server_session.get(request_url, timeout=300)
                except Exception as read_ex:
                    download_elapsed = time.time() - download_start
                    error_msg = f'READ_TIMEOUT: {str(read_ex)}'
                    logger.error(f"File read timeout/error after {download_elapsed:.1f}s: {error_msg}", category="READ")
                    file_result = {
                        'file': _fallback_name, 
                        'status': error_msg,
                        'error_detail': {'status_code': 0, 'detail': str(read_ex), 'elapsed_seconds': round(download_elapsed, 1)},
                        'error_category': 'TIMEOUT'
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                    continue
                
                download_elapsed = time.time() - download_start
                download_size = len(response.content) if response.content else 0
                download_size_mb = download_size / 1024 / 1024
                logger.info(f"Download complete: {download_size:,} bytes ({download_size_mb:.2f} MB) in {download_elapsed:.1f}s", category="READ")
                
                if response.status_code != 200:
                    error_info = _extract_error_fields(response)
                    error_msg = f'READ_FAIL_{response.status_code}'
                    if response.status_code in (401, 403):
                        error_info['hint'] = 'Token may have expired. Try refreshing login.'
                    logger.error(f"File read failed: {error_msg}", category="READ", details=error_info)
                    file_result = {
                        'file': _fallback_name, 
                        'status': error_msg,
                        'error_detail': error_info,
                        'error_category': _classify_error(error_info)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                    continue
                
                response_content = response.content
                filename = _resolve_filename(document, staging_record, file_index)
                filename, _ = _normalize_extension(filename)
            
            # Update metadata fields in staging table (once, on first successful file read)
            if not metadata_updated:
                mime_type = _get_mime_type(filename)
                file_size = len(response_content) if response_content else 0
                
                update_metadata_fields(
                    staging_id,
                    loioid=doc_loioid,
                    description=doc_description,
                    filename=filename,
                    file_size=file_size,
                    mime_type=mime_type
                )
                metadata_updated = True
                logger.debug(f"Updated metadata: LOIOID={doc_loioid}, filename={filename}, size={file_size}, mime={mime_type}", category="EXECUTE")
            
            # Prepare for write operations
            prepare_session_headers(server_session, session_snapshot, target_system)
            
            # NOTE: doc_type, doc_number, doc_version, doc_part are set BEFORE the file loop
            # and updated by CREATE response. Do NOT re-read from staging_record here!
            
            # Create document info record (once per container)
            if not doc_created:
                
                # Check if source document number is auto-generated
                source_doc_number = staging_record['source_documentnumber']
                is_auto_id = is_auto_generated_id(source_doc_number)
                
                if is_auto_id:
                    logger.info(f"Source document {source_doc_number} is auto-generated (len={len(source_doc_number)}). Target system will assign new ID.", category="CREATE")
                else:
                    logger.info(f"Source document {source_doc_number} is manually assigned. Using as target ID.", category="CREATE")
                
                # Prepare description — prefer live API value over stale Prepare-time value
                # Priority: 1) doc_description (live from source API)
                #           2) staging source_description (from Prepare / previous retry)
                #           3) filename (last resort)
                effective_description = doc_description or staging_record.get('source_description') or filename
                if isinstance(effective_description, str):
                    effective_description = effective_description.strip()
                if not effective_description:
                    effective_description = filename  # Safety net if all sources were whitespace-only
                if len(effective_description) > MAX_DESC_LEN:
                    effective_description = effective_description[:MAX_DESC_LEN]
                
                if doc_description and doc_description != staging_record.get('source_description'):
                    logger.info(f"Using live API description: '{effective_description}'", category="CREATE")
                elif not doc_description and not staging_record.get('source_description'):
                    logger.info(f"No description available, using filename: '{effective_description}'", category="CREATE")
                
                # Create payload
                doc_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
                create_url = f"{doc_base_url}/A_DocumentInfoRecord"
                server_session.headers.update({'Content-Type': 'application/json'})
                
                dms_payload = {
                    'DocumentInfoRecordDocType': doc_type,
                    'DocumentInfoRecordDocVersion': doc_version,
                    'DocumentInfoRecordDocPart': doc_part,
                    'to_DocDesc': [
                        {'Language': 'DE', 'DocumentDescription': effective_description},
                        {'Language': 'EN', 'DocumentDescription': effective_description}
                    ]
                }
                
                # Document number handling:
                # The decision is based on the VALUE (numeric vs alphanumeric), NOT the document type!
                # - Numeric value (e.g. "123456") → Internal numbering → omit field (S4 auto-generates)
                # - Alphanumeric value (e.g. "ABLAGEORT") → External numbering → include (value is used)
                # - Translation rule set a specific target_documentnumber → Has priority, always include
                
                # Check if a rule explicitly set a different target_documentnumber
                rule_set_doc_number = doc_number and doc_number != source_doc_number
                effective_doc_number = doc_number or source_doc_number
                
                # Use pre-sanitized value from Prepare phase if available, else sanitize inline (safety net)
                pre_sanitized = staging_record.get('target_documentnumber_sanitized')
                if pre_sanitized and str(pre_sanitized).strip():
                    original_for_log = effective_doc_number
                    effective_doc_number = str(pre_sanitized).strip()
                    if effective_doc_number != (doc_number or source_doc_number):
                        logger.info(f"Using pre-sanitized DOKNR from Prepare: '{original_for_log}' → '{effective_doc_number}'", category="CREATE")
                elif effective_doc_number:
                    # Fallback: sanitize inline
                    effective_doc_number, doknr_changed = sanitize_doknr(effective_doc_number)
                    if doknr_changed:
                        logger.info(f"Sanitized DOKNR inline (fallback): '{doc_number or source_doc_number}' → '{effective_doc_number}'", category="CREATE")
                
                def _is_purely_numeric(val):
                    """Check if value is purely numeric (digits only)."""
                    return bool(val) and str(val).strip().isdigit()
                
                # Track whether we send a doc number to S4 (needed later for response validation)
                doc_number_sent_to_s4 = False
                
                # Decide based on VALUE, not on document type
                if rule_set_doc_number:
                    # Rule explicitly set a target_documentnumber → always use it
                    if effective_doc_number:
                        dms_payload['DocumentInfoRecordDocNumber'] = effective_doc_number
                        doc_number_sent_to_s4 = True
                        logger.info(f"Using rule-defined document number: {effective_doc_number}", category="CREATE")
                    else:
                        logger.warning(f"Rule set empty document number — S4 will auto-generate", category="CREATE")
                elif effective_doc_number and not _is_purely_numeric(effective_doc_number):
                    # Alphanumeric value → External numbering → include the value
                    dms_payload['DocumentInfoRecordDocNumber'] = effective_doc_number
                    doc_number_sent_to_s4 = True
                    logger.info(f"Using alphanumeric document number: {effective_doc_number}", category="CREATE")
                else:
                    # Numeric value or empty → Internal numbering → S4 auto-generates
                    logger.info(f"Omitting numeric document number — S4 will auto-generate", category="CREATE")
                
                # Add authorization group if available
                # Priority: staging_record.authorization_group (set by rules) > doc_authgroup (from API)
                # Rules can explicitly set authorization_group to '' (empty) to suppress it.
                staging_authgroup = staging_record.get('authorization_group')
                if staging_authgroup is not None:
                    # Rule has set a value (could be '' to suppress, or a specific group)
                    effective_authgroup = staging_authgroup.strip() if staging_authgroup else ''
                    if effective_authgroup:
                        logger.debug(f"Using rule-defined authorization group: {effective_authgroup}", category="CREATE")
                    else:
                        logger.debug(f"Authorization group suppressed by rule (source had: '{doc_authgroup}')", category="CREATE")
                else:
                    # No rule set — use API value as fallback
                    effective_authgroup = doc_authgroup or ''
                    if effective_authgroup:
                        logger.debug(f"Using source authorization group from API: {effective_authgroup}", category="CREATE")
                
                if effective_authgroup:
                    dms_payload['AuthorizationGroup'] = effective_authgroup
                
                source_user = staging_record.get('pers_resp_source')
                
                # Document status: do NOT include in CREATE payload.
                # S4 rejects internal-numbering types (IY1/IY2) when status is set during creation.
                # Status will be set via a separate PATCH call after document creation.
                target_doc_status = staging_record.get('target_document_status')
                if target_doc_status:
                    logger.debug(f"Document status '{target_doc_status}' will be applied after creation via PATCH", category="CREATE")
                
                logger.info(f"Creating document info record", category="CREATE")
                create_resp = server_session.post(create_url, json=dms_payload)
                
                # CSRF retry: if token expired mid-batch, refresh and retry once
                if is_csrf_error(create_resp):
                    logger.warning("CSRF token expired during CREATE — refreshing and retrying", category="CREATE")
                    force_csrf_renewal(session_snapshot, target_system)
                    prepare_session_headers(server_session, session_snapshot, target_system)
                    server_session.headers.update({'Content-Type': 'application/json'})
                    create_resp = server_session.post(create_url, json=dms_payload)
                
                body_txt_lower = create_resp.text.lower() if create_resp.text else ''
                
                if create_resp.status_code in (200, 201):
                    # Always extract the document number from response
                    # S4 may auto-generate a new number (for types with internal numbering like IY1/IY2)
                    # or confirm the number we sent (for types like I9D/I9S/I9T)
                    resp_d = {}
                    try:
                        response_data = create_resp.json()
                        if response_data and 'd' in response_data:
                            resp_d = response_data['d']
                            created_doc_number = resp_d.get('DocumentInfoRecordDocNumber')
                            # S4 may also change version/part (e.g. IY1: sent '01' → returned '00')
                            created_doc_version = resp_d.get('DocumentInfoRecordDocVersion')
                            created_doc_part = resp_d.get('DocumentInfoRecordDocPart')
                            
                            # Update doc_number from response
                            if created_doc_number:
                                if created_doc_number != doc_number:
                                    logger.info(f"Target system assigned document number: {created_doc_number}", category="CREATE")
                                doc_number = created_doc_number
                                with misc_engine.begin() as con:
                                    con.execute(text("""
                                        UPDATE dbo.migration_staging
                                        SET target_documentnumber = :new_doc_number
                                        WHERE id = :staging_id
                                    """), {'new_doc_number': created_doc_number, 'staging_id': staging_id})
                            else:
                                logger.warning("Could not extract document number from response", category="CREATE")
                            
                            # Update version/part if S4 changed them (critical for upload URL!)
                            if created_doc_version and created_doc_version != doc_version:
                                logger.info(f"S4 changed version: {doc_version} → {created_doc_version}", category="CREATE")
                                doc_version = created_doc_version
                                with misc_engine.begin() as con:
                                    con.execute(text("""
                                        UPDATE dbo.migration_staging
                                        SET target_documentversion = :ver
                                        WHERE id = :staging_id
                                    """), {'ver': created_doc_version, 'staging_id': staging_id})
                            if created_doc_part and created_doc_part != doc_part:
                                logger.info(f"S4 changed part: {doc_part} → {created_doc_part}", category="CREATE")
                                doc_part = created_doc_part
                                with misc_engine.begin() as con:
                                    con.execute(text("""
                                        UPDATE dbo.migration_staging
                                        SET target_documentpart = :part
                                        WHERE id = :staging_id
                                    """), {'part': created_doc_part, 'staging_id': staging_id})
                    except Exception as e:
                        logger.warning(f"Failed to extract document number from response: {e}", category="CREATE")
                    
                    # CRITICAL: If we did NOT send a doc_number to S4 (because it was numeric,
                    # allowing S4 to auto-generate), we MUST capture the auto-generated number
                    # from the CREATE response. If extraction failed, we must NOT mark container_created=1
                    # — otherwise retries skip CREATE and the auto-generated number is lost forever.
                    if not doc_number_sent_to_s4 and not doc_number:
                        error_msg = (
                            f"CREATE_DOC_NUMBER_LOST: S4 created {doc_type} document (HTTP {create_resp.status_code}) "
                            f"but auto-generated document number could not be extracted from response. "
                            f"The document exists in S4 without a known number. Manual cleanup required."
                        )
                        logger.error(error_msg, category="CREATE")
                        update_execution_status(staging_id, 'failed', error_msg)
                        return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg}
                    
                    logger.info(f"Document created successfully: {doc_number} (status {create_resp.status_code})", category="CREATE")
                    doc_created = True
                    
                    # Mark container as created for idempotent retries
                    with misc_engine.begin() as con:
                        con.execute(text("""
                            UPDATE dbo.migration_staging
                            SET container_created = 1
                            WHERE id = :staging_id
                        """), {'staging_id': staging_id})
                    
                    _patch_responsible_person(server_session, resp_d, source_user, staging_id, misc_engine, logger)
                    
                    # NOTE: Object Link creation is now Phase 2 (execute_linking)
                    # Phase 1 only creates the container and uploads files
                    
                elif create_resp.status_code in (400, 409) and any(x in body_txt_lower for x in ['exist', 'duplicate', 'already']):
                    logger.warning(f"Document already exists, continuing: {doc_number}", category="CREATE")
                    doc_created = True  # Tolerate existing
                    # Mark container as created (was created in a previous attempt)
                    with misc_engine.begin() as con:
                        con.execute(text("""
                            UPDATE dbo.migration_staging
                            SET container_created = 1
                            WHERE id = :staging_id
                        """), {'staging_id': staging_id})
                else:
                    error_info = _extract_error_fields(create_resp)
                    error_msg = f"CREATE_FAIL_{create_resp.status_code}"
                    if error_info.get('detail'):
                        error_msg += f": {error_info['detail']}"
                    logger.error(error_msg, category="CREATE", details=error_info)
                    import json
                    error_json = json.dumps(error_info)
                    update_execution_status(staging_id, 'failed', error_json)
                    return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg, 'error_detail': error_info, 'status_code': create_resp.status_code}
            
            # Upload attachment
            if doc_created:
                # Guard: doc_number must be set before building upload URL
                if not doc_number:
                    error_msg = (
                        f"UPLOAD_NO_DOC_NUMBER: Cannot upload — target document number is None. "
                        f"CREATE may have succeeded but the number was not captured."
                    )
                    logger.error(error_msg, category="UPLOAD")
                    update_execution_status(staging_id, 'failed', error_msg)
                    return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg}
                
                mime_type = _get_mime_type(filename)
                
                # Sanitize filename for HTTP Slug header: requests encodes headers
                # as latin-1, so non-latin-1 characters (e.g. Korean, CJK) are
                # percent-encoded (e.g. 창 → %EC%B0%BD) to stay HTTP-header-safe.
                # Extension is also normalized (e.g. .zipx → .zip) for SAP DAPPL.
                percent_encode = session_snapshot.get('percent_encode_slug', True) if session_snapshot else True
                slug_filename = _sanitize_slug(filename, percent_encode=percent_encode)
                server_session.headers.update({'Content-Type': mime_type, 'Slug': slug_filename})
                
                try:
                    attachment_base_url = cfg.get(target_system, 'api_list', 'attachment', 'base_url')
                except Exception:
                    attachment_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
                
                # Use doc_type/doc_number/doc_version/doc_part set before the file loop
                # and potentially updated by CREATE response. Never re-read from staging_record!
                
                attachment_url = (
                    f"{attachment_base_url}/A_DocumentInfoRecordAttch"
                    f"(DocumentInfoRecordDocType='{doc_type}',"
                    f"DocumentInfoRecordDocNumber='{doc_number}',"
                    f"DocumentInfoRecordDocVersion='{doc_version}',"
                    f"DocumentInfoRecordDocPart='{doc_part}'"
                    f")/DocumentInfoRecordToAttachmentNavigation"
                )
                
                content = response_content or b' '  # Pad empty files
                file_size = len(content)
                file_size_mb = file_size / 1024 / 1024
                
                # Get MIME type for file details
                current_mime_type = _get_mime_type(filename)
                
                logger.info(f"Uploading file: {filename} ({file_size:,} bytes / {file_size_mb:.2f} MB)", category="UPLOAD")
                logger.info(f"Upload URL: {attachment_url}", category="UPLOAD")
                logger.info(f"Upload headers: Content-Type={mime_type}, Slug={filename}", category="UPLOAD")
                
                # Upload mit Timeout: 60s base + 10s pro MB (für große Dateien)
                upload_timeout = max(60, 60 + int(file_size_mb * 10))
                logger.info(f"Upload timeout set to {upload_timeout}s (60 + {int(file_size_mb)}*10)", category="UPLOAD")
                upload_start = time.time()
                try:
                    upload_resp = server_session.post(attachment_url, data=content, timeout=upload_timeout)
                    # CSRF retry
                    if is_csrf_error(upload_resp):
                        logger.warning("CSRF token expired during UPLOAD — refreshing and retrying", category="UPLOAD")
                        force_csrf_renewal(session_snapshot, target_system)
                        prepare_session_headers(server_session, session_snapshot, target_system)
                        server_session.headers.update({'Content-Type': mime_type, 'Slug': filename})
                        upload_resp = server_session.post(attachment_url, data=content, timeout=upload_timeout)
                except requests.exceptions.ConnectionError as conn_ex:
                    upload_elapsed = time.time() - upload_start
                    error_msg = f'UPLOAD_CONNECTION_ERROR after {upload_elapsed:.1f}s'
                    logger.error(f"Upload connection error: {filename} ({file_size_mb:.2f} MB) after {upload_elapsed:.1f}s - {str(conn_ex)[:300]}", category="UPLOAD")
                    file_result = {
                        'file': filename,
                        'status': error_msg,
                        'error_detail': {'status_code': 0, 'detail': str(conn_ex)[:500], 'elapsed_seconds': round(upload_elapsed, 1), 'file_size_mb': round(file_size_mb, 2)},
                        'error_category': 'CONNECTION_ERROR',
                        'file_size': file_size,
                        'file_size_mb': round(file_size_mb, 2),
                        'mime_type': current_mime_type,
                        'actual_time_seconds': round(upload_elapsed, 2)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                    continue
                except requests.exceptions.Timeout as timeout_ex:
                    upload_elapsed = time.time() - upload_start
                    error_msg = f'UPLOAD_TIMEOUT after {upload_elapsed:.1f}s (limit={upload_timeout}s)'
                    logger.error(f"Upload timeout: {filename} ({file_size_mb:.2f} MB) after {upload_elapsed:.1f}s - {error_msg}", category="UPLOAD")
                    file_result = {
                        'file': filename,
                        'status': error_msg,
                        'error_detail': {'status_code': 0, 'detail': str(timeout_ex)},
                        'error_category': 'TIMEOUT',
                        'file_size': file_size,
                        'file_size_mb': round(file_size_mb, 2),
                        'mime_type': current_mime_type,
                        'actual_time_seconds': round(upload_elapsed, 2)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                    continue
                
                upload_elapsed = time.time() - upload_start
                resp_headers = dict(upload_resp.headers) if upload_resp.headers else {}
                throughput_info = f" ({file_size_mb/upload_elapsed:.1f} MB/s)" if upload_elapsed > 0.1 else ""
                logger.info(f"Upload response: status={upload_resp.status_code} in {upload_elapsed:.1f}s{throughput_info}", category="UPLOAD")
                
                if upload_resp.status_code in (200, 201):
                    upload_time = time.time() - start_time  # Actual processing time (no pacing)
                    logger.info(f"File uploaded successfully: {filename} (status {upload_resp.status_code}, {upload_elapsed:.1f}s, {file_size_mb:.2f} MB)", category="UPLOAD")
                    _patch_url_description(server_session, upload_resp, document.get('FileDescription', ''), logger)
                    file_result = {
                        'file': filename, 
                        'status': 'SUCCESS', 
                        'file_size': file_size,
                        'file_size_mb': round(file_size_mb, 2),
                        'mime_type': current_mime_type,
                        'actual_time_seconds': round(upload_time, 2)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                else:
                    upload_time = time.time() - start_time
                    error_info = _extract_error_fields(upload_resp)
                    error_msg = f'UPLOAD_FAIL_{upload_resp.status_code}'
                    
                    # Detect size-related errors
                    is_size_error = False
                    size_error_indicators = ['too large', 'size', 'payload', 'entity', 'limit', 'exceeded', 'maximum']
                    error_text = str(error_info).lower()
                    if upload_resp.status_code in (413, 507) or any(ind in error_text for ind in size_error_indicators):
                        is_size_error = True
                        error_msg = f'SIZE_LIMIT_EXCEEDED_{upload_resp.status_code}'
                        logger.error(f"File too large: {filename} ({file_size_mb:.2f} MB) - {error_msg}", category="UPLOAD", details=error_info)
                    else:
                        if error_info.get('detail'):
                            error_msg += f": {error_info['detail'][:100]}"
                        # Log extra detail for 502/503/504 gateway errors
                        if upload_resp.status_code in (502, 503, 504):
                            logger.error(f"Gateway error uploading {filename} ({file_size_mb:.2f} MB) after {upload_elapsed:.1f}s: "
                                         f"status={upload_resp.status_code}, response_body={upload_resp.text[:500] if upload_resp.text else 'empty'}, "
                                         f"response_headers={dict(upload_resp.headers)}",
                                         category="UPLOAD")
                        logger.error(f"Upload failed: {filename} ({file_size_mb:.2f} MB, {upload_elapsed:.1f}s) - {error_msg}", category="UPLOAD", details=error_info)
                    
                    file_result = {
                        'file': filename, 
                        'status': error_msg,
                        'error_detail': error_info,
                        'error_category': _classify_error(error_info),
                        'file_size': file_size,
                        'file_size_mb': round(file_size_mb, 2),
                        'mime_type': current_mime_type,
                        'is_size_error': is_size_error,
                        'actual_time_seconds': round(upload_time, 2)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                
                # ── Break to parallel-upload remaining prefetched files ──
                if _prefetched:
                    if any(pf['success'] for pf in _prefetched.values()):
                        break  # → parallel upload block below
        
        # ── PARALLEL UPLOAD: remaining prefetched files ─────────────────
        # After the serial loop handles the first file (CREATE + UPLOAD),
        # remaining successfully pre-downloaded files are uploaded here
        # in parallel to reduce total wall-clock time.
        if _prefetched and doc_created and doc_number:
            # Record failed prefetched downloads
            for _pfi in sorted(_prefetched):
                _pf = _prefetched[_pfi]
                if not _pf['success']:
                    _fail_result = {
                        'file': _pf.get('filename', f'file_{_pfi}'),
                        'status': _pf.get('error_msg', 'READ_FAIL'),
                        'error_detail': _pf.get('error_detail'),
                        'error_category': _pf.get('error_category', 'OTHER'),
                    }
                    results.append(_fail_result)
                    save_file_details(staging_id, batch_id, _pfi, _fail_result,
                                      loio_id=documents[2][_pfi].get('LOIOID'))
            
            # Upload successful downloads in parallel
            _ok_uploads = [
                (fi, pf) for fi, pf in sorted(_prefetched.items())
                if pf['success']
            ]
            if _ok_uploads:
                logger.info(
                    f"Parallel upload: {len(_ok_uploads)} remaining files to {doc_number}",
                    category="UPLOAD"
                )
                _ul_workers = min(len(_ok_uploads), 5)
                with ThreadPoolExecutor(max_workers=_ul_workers) as _ul_pool:
                    _ul_futures = {
                        _ul_pool.submit(
                            _upload_one_file, fi, pf['content'], pf['filename'],
                            pf['mime_type'], doc_type, doc_number, doc_version, doc_part,
                            session_snapshot, target_system, staging_id, batch_id,
                            documents[2][fi].get('LOIOID'), start_time, logger,
                            file_description=documents[2][fi].get('FileDescription', '')
                        ): fi
                        for fi, pf in _ok_uploads
                    }
                    from concurrent.futures import as_completed as _as_completed_ul
                    _par_results = []
                    for _fut in _as_completed_ul(_ul_futures):
                        _ures = _fut.result()
                        _par_results.append(_ures)
                        results.append(_ures['file_result'])
                        save_file_details(
                            staging_id, batch_id, _ures['file_index'],
                            _ures['file_result'],
                            loio_id=documents[2][_ures['file_index']].get('LOIOID')
                        )
                _par_ok = sum(1 for r in _par_results if r['success'])
                logger.info(
                    f"Parallel upload complete: {_par_ok}/{len(_ok_uploads)} OK",
                    category="UPLOAD"
                )
        
        # Calculate timing and size statistics
        execution_time = time.time() - start_time
        total_bytes = sum(r.get('file_size', 0) for r in results)
        
        # Determine overall status
        # Count SUCCESS and SUCCESS_SKIPPED as successful
        success_count = len([r for r in results if r['status'] in ('SUCCESS', 'SUCCESS_SKIPPED')])
        skipped_count = len([r for r in results if r.get('skipped', False)])
        
        # All files successful (including skipped from previous runs)
        if all(r['status'] in ('SUCCESS', 'SUCCESS_SKIPPED') for r in results):
            # Safety check: don't mark as success if no container was created and no doc_number
            # This catches edge cases where all files were "skipped" but no actual work was done
            if not doc_created and not doc_number:
                error_msg = (
                    f"INTEGRITY_ERROR: All {len(results)} files appear successful/skipped but "
                    f"no container was created and target_documentnumber is None. "
                    f"This likely means stale file_details from a previous run caused false skips."
                )
                logger.error(error_msg, category="EXECUTE")
                update_execution_status(staging_id, 'failed', error_msg)
                return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg}
            
            if skipped_count > 0:
                logger.info(f"Migration completed: {success_count - skipped_count} new + {skipped_count} skipped (already uploaded) in {execution_time:.2f}s", category="EXECUTE")
            else:
                logger.info(f"Migration completed successfully for all {len(results)} files in {execution_time:.2f}s ({total_bytes/1024/1024:.2f} MB)", category="EXECUTE")
            update_execution_status(staging_id, 'success')
            # Save target file count (successful uploads)
            try:
                with misc_engine.begin() as con:
                    con.execute(text("""
                        UPDATE dbo.migration_staging
                        SET target_file_count = :cnt
                        WHERE id = :staging_id
                    """), {'cnt': success_count, 'staging_id': staging_id})
            except Exception as e:
                logger.debug(f"Failed to update target_file_count: {e}", category="EXECUTE")
            return {
                'staging_id': staging_id, 
                'status': 'success', 
                'results': results,
                'stats': {
                    'execution_time': execution_time,
                    'total_bytes': total_bytes,
                    'file_count': len(results),
                    'skipped_count': skipped_count
                }
            }
        elif success_count == 0 and not doc_created:
            # No container created and no files uploaded -> this is a complete failure, not partial
            # Exclude skipped files from failure count (they were already successful)
            actual_failed = len([r for r in results if not r.get('skipped', False)])
            import json
            error_details = [r.get('error_detail') for r in results if r.get('error_detail')]
            error_summary = f"FAILED 0/{actual_failed} files - no container created"
            
            logger.error(f"Migration failed completely: 0 of {actual_failed} files, no container created in {execution_time:.2f}s", category="EXECUTE")
            
            if error_details:
                error_json = json.dumps({'summary': error_summary, 'errors': error_details})
                update_execution_status(staging_id, 'failed', error_json)
            else:
                update_execution_status(staging_id, 'failed', error_summary)
            
            return {
                'staging_id': staging_id, 
                'status': 'failed', 
                'results': results,
                'stats': {
                    'execution_time': execution_time,
                    'total_bytes': total_bytes,
                    'file_count': len(results),
                    'skipped_count': skipped_count
                }
            }
        else:
            # Container created but not all files uploaded -> partial success
            # Calculate actual new successes (excluding skipped)
            new_success_count = len([r for r in results if r['status'] == 'SUCCESS'])
            total_non_skipped = len([r for r in results if not r.get('skipped', False)])
            import json
            # Collect all errors from results (excluding skipped)
            error_details = [r.get('error_detail') for r in results if r.get('error_detail') and not r.get('skipped', False)]
            error_summary = f"PARTIAL_SUCCESS {success_count}/{len(results)} files"
            if skipped_count > 0:
                error_summary = f"PARTIAL_SUCCESS {new_success_count} new + {skipped_count} skipped / {len(results)} total"
            
            logger.warning(f"Partial success: {success_count} of {len(results)} files migrated (new: {new_success_count}, skipped: {skipped_count}) in {execution_time:.2f}s", category="EXECUTE")
            
            # Save target file count (successful uploads only)
            try:
                with misc_engine.begin() as con:
                    con.execute(text("""
                        UPDATE dbo.migration_staging
                        SET target_file_count = :cnt
                        WHERE id = :staging_id
                    """), {'cnt': success_count, 'staging_id': staging_id})
            except Exception as e:
                logger.debug(f"Failed to update target_file_count: {e}", category="EXECUTE")
            
            # Determine dominant error_category from failed file results
            failed_file_categories = [r.get('error_category') for r in results if r.get('error_category') and not r.get('skipped', False)]
            if failed_file_categories:
                # Use most common error category from failed files
                from collections import Counter
                partial_error_category = Counter(failed_file_categories).most_common(1)[0][0]
            else:
                partial_error_category = 'UNKNOWN'
            
            # Store detailed errors as JSON if available
            if error_details:
                error_json = json.dumps({'summary': error_summary, 'errors': error_details})
                update_execution_status(staging_id, 'partial', error_json, error_category=partial_error_category)
            else:
                update_execution_status(staging_id, 'partial', error_summary, error_category=partial_error_category)
            
            return {
                'staging_id': staging_id, 
                'status': 'partial', 
                'results': results,
                'stats': {
                    'execution_time': execution_time,
                    'total_bytes': total_bytes,
                    'file_count': len(results)
                }
            }
        
    except Exception as e:
        error_msg = f"EXCEPTION {e}"
        logger.critical(f"Exception during migration: {str(e)}", category="EXECUTE", details={'exception': str(e)})
        update_execution_status(staging_id, 'failed', error_msg)
        return {'staging_id': staging_id, 'status': 'failed', 'error': str(e), 'status_code': 500}
    
    finally:
        # Pacing between containers
        session_pacing = session_snapshot.get('pacing_seconds')
        
        if session_pacing and session_pacing > 0:
            # Manual override - use fixed pacing (legacy mode)
            time_taken = time.time() - start_time
            if time_taken < session_pacing:
                sleep_time = session_pacing - time_taken
                time.sleep(sleep_time)
        elif PACING_MODE == 'response':
            # Response-based pacing: API response already received, just add minimal delay
            # This prevents rate limiting while maximizing throughput
            if MIN_CONTAINER_DELAY > 0:
                time.sleep(MIN_CONTAINER_DELAY)
        else:
            # Legacy time-based pacing
            file_size = staging_record.get('file_size_bytes')
            dynamic_pacing = get_dynamic_pacing(file_size)
            time_taken = time.time() - start_time
            if time_taken < dynamic_pacing:
                sleep_time = dynamic_pacing - time_taken
                time.sleep(sleep_time)


def is_migration_running(batch_id):
    """Check if a migration is currently running for this batch."""
    global _active_migrations
    
    # Check in-memory lock first (most reliable)
    with _migration_lock:
        if batch_id in _active_migrations:
            start_time = _active_migrations[batch_id]
            elapsed_minutes = (time.time() - start_time) / 60
            if VERBOSE_TERMINAL_LOGGING:
                print(f"[LOCK] Batch {batch_id} has been running for {elapsed_minutes:.1f} minutes")
            return True, f"Migration already running since {elapsed_minutes:.1f} minutes"
    
    # Also check database status as fallback (in case of crash/restart)
    with misc_engine.connect() as con:
        result = con.execute(text(f"""
            SELECT status, total_records, executed_records, 
                   DATEDIFF(MINUTE, created_at, GETDATE()) as minutes_elapsed
            FROM dbo.migration_batch 
            WHERE batch_id = '{batch_id}'
        """)).fetchone()
        
        if result and result.status == 'executing':
            # Check if there are "executing" status records 
            executing_count = con.execute(text(f"""
                SELECT COUNT(*) as cnt 
                FROM dbo.migration_staging 
                WHERE batch_id = '{batch_id}' AND execution_status = 'executing'
            """)).fetchone().cnt
            
            if executing_count > 0:
                if VERBOSE_TERMINAL_LOGGING:
                    print(f"[LOCK] Found {executing_count} records still in 'executing' status - likely orphaned")
                return False, f"Found {executing_count} orphaned 'executing' records (will be reset)"
            
    return False, None


def clear_migration_lock(batch_id):
    """Remove the migration lock for a batch."""
    global _active_migrations
    with _migration_lock:
        if batch_id in _active_migrations:
            del _active_migrations[batch_id]
            if VERBOSE_TERMINAL_LOGGING:
                print(f"[LOCK] Released lock for batch {batch_id}")


def set_migration_lock(batch_id):
    """Set the migration lock for a batch."""
    global _active_migrations
    with _migration_lock:
        _active_migrations[batch_id] = time.time()
        if VERBOSE_TERMINAL_LOGGING:
            print(f"[LOCK] Acquired lock for batch {batch_id}")


def reset_orphaned_records(batch_id):
    """Reset any records stuck in 'executing' status back to 'pending'."""
    with misc_engine.begin() as con:
        result = con.execute(text(f"""
            UPDATE dbo.migration_staging
            SET execution_status = 'pending'
            WHERE batch_id = '{batch_id}' AND execution_status = 'executing'
        """))
        if result.rowcount > 0:
            if VERBOSE_TERMINAL_LOGGING:
                print(f"[CLEANUP] Reset {result.rowcount} orphaned 'executing' records to 'pending'")
        return result.rowcount


def request_cancel(batch_id):
    """Request cancellation of a running migration."""
    global _cancel_requested
    _cancel_requested[batch_id] = True
    print(f"[CANCEL] Cancellation requested for batch {batch_id}")
    return True


def is_cancel_requested(batch_id):
    """Check if cancellation was requested for this batch."""
    global _cancel_requested
    return _cancel_requested.get(batch_id, False)


def clear_cancel_request(batch_id):
    """Clear the cancel request flag for a batch."""
    global _cancel_requested
    if batch_id in _cancel_requested:
        del _cancel_requested[batch_id]


def check_token_validity(session_snapshot):
    """
    Quick check if the bearer token is still valid by making a lightweight API call.
    Returns (is_valid, error_message)
    """
    try:
        headers = {
            'Authorization': f"Bearer {session_snapshot.get('bearer_token')}",
            'Accept': 'application/json',
        }
        if session_snapshot.get('x_csrf_token'):
            headers['x-csrf-token'] = session_snapshot['x_csrf_token']
        
        cookies = session_snapshot.get('cookies', {})
        
        # Use the write API base URL for a quick check
        target_sys = get_target_system(session_snapshot)
        target_base_url = cfg.get(target_sys, 'api_list', 'document', 'base_url')
        if target_base_url:
            # Simple metadata request - very lightweight
            check_url = f"{target_base_url}/$metadata"
            response = requests.get(check_url, headers=headers, cookies=cookies, timeout=10)
            
            if response.status_code in (401, 403):
                return False, f"Token invalid (HTTP {response.status_code})"
            return True, None
        
        return True, None  # Can't check, assume valid
        
    except requests.exceptions.Timeout:
        return True, None  # Timeout doesn't mean token is invalid
    except Exception as e:
        return True, None  # Other errors don't mean token is invalid


def execute_migration(batch_id, record_ids=None, session_snapshot=None):
    """
    Main entry point for Step 2: Execute Migration.
    
    Can run in Flask request context (legacy) or as a background thread.
    When session_snapshot is provided, runs without Flask session dependency.
    
    Args:
        batch_id: Batch ID to execute
        record_ids: Optional list of specific record IDs to execute. If None, executes all pending.
        session_snapshot: Optional pre-built session snapshot dict. If None, reads from Flask session.
    
    Returns:
        dict with execution results
    """
    try:
        # Check if migration is already running
        is_running, reason = is_migration_running(batch_id)
        if is_running:
            return {
                'success': False,
                'error': f'Migration already in progress: {reason}',
                'already_running': True
            }
        
        # Reset any orphaned records from previous crashed execution
        reset_orphaned_records(batch_id)
        
        # Mark orphan records (target_link_count = 0) as skipped
        with misc_engine.begin() as con:
            orphan_result = con.execute(text("""
                UPDATE dbo.migration_staging
                SET execution_status = 'skipped_orphan'
                WHERE batch_id = :batch_id
                    AND skip_migration = 0
                    AND execution_status = 'pending'
                    AND target_link_count = 0
            """), {'batch_id': batch_id})
            if orphan_result.rowcount > 0:
                print(f"[ORPHAN_SKIP] Marked {orphan_result.rowcount} orphan records as skipped_orphan (all object links excluded)")
        
        # Set the lock
        set_migration_lock(batch_id)
        
        # Build session snapshot: use provided snapshot or read from Flask session
        if session_snapshot is None:
            # Legacy path: running inside Flask request context
            max_workers = http_session.get('max_workers', MAX_API_WORKERS)
            pacing_seconds = http_session.get('pacing_seconds', 0)
            session_snapshot = {
                'bearer_token': http_session.get('bearer_token'),
                'sap_system': http_session.get('sap_system'),
                'x_csrf_token': http_session.get('x-csrf-token'),
                'cookies': http_session.get('cookies'),
                'csrf_token_time': http_session.get('csrf_token_time', 0),
                'max_workers': max_workers,
                'pacing_seconds': pacing_seconds,
                'source_system': http_session.get('source_system', read_sap_system),
                'target_system': http_session.get('target_system', write_sap_system),
                'refresh_token': http_session.get('refresh_token'),
                'token_expires_at': http_session.get('token_expires_at'),
            }
        
        max_workers = session_snapshot.get('max_workers', MAX_API_WORKERS)
        pacing_seconds = session_snapshot.get('pacing_seconds', 0)
        
        # Load records - either specific IDs or all pending
        if record_ids:
            records_df = load_specific_records(batch_id, record_ids)
        else:
            records_df = load_approved_records(batch_id)
        
        if len(records_df) == 0:
            return {
                'success': False,
                'error': 'No records found for execution'
            }
        
        # API Warmup - wake up APIs before starting migration
        first_loio = None
        if len(records_df) > 0 and 'source_loioid' in records_df.columns:
            first_loio = records_df.iloc[0].get('source_loioid')
        warmup_result = warmup_api(session_snapshot, first_loio_id=first_loio)
        
        # Log pacing mode - always show start message
        pacing_mode = f"fixed={pacing_seconds}s" if pacing_seconds > 0 else "dynamic (5-45s)"
        print(f"[START] Batch {batch_id}: {len(records_df)} records, {max_workers} workers, pacing={pacing_mode}")
        
        # Track batch timing
        batch_start_time = time.time()
        total_records = len(records_df)
        
        # Update batch status - reset counters for this execution run
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET status = 'executing',
                    migration_phase = 'upload',
                    total_records = {total_records},
                    executed_records = 0,
                    successful_records = 0,
                    failed_records = 0,
                    last_execution_started_at = GETUTCDATE()
                WHERE batch_id = '{batch_id}'
            """))
        
        # Progress tracking
        completed_count = 0
        success_count = 0
        failed_count = 0
        partial_count = 0
        
        def update_progress():
            """Update progress in batch table for frontend polling."""
            nonlocal completed_count, success_count, failed_count, partial_count
            with misc_engine.begin() as con:
                con.execute(text(f"""
                    UPDATE dbo.migration_batch
                    SET executed_records = {completed_count},
                        successful_records = {success_count},
                        failed_records = {failed_count + partial_count}
                    WHERE batch_id = '{batch_id}'
                """))
        
        # Execute in parallel using ThreadPoolExecutor with PACKAGE-BASED processing
        # This allows cancel/circuit-breaker to work between packages
        results = []
        
        # Circuit breaker and cancel tracking
        consecutive_auth_errors = 0
        circuit_breaker_tripped = False
        cancel_reason = None
        clear_cancel_request(batch_id)  # Clear any previous cancel request
        
        # Convert DataFrame to list of tuples for package processing
        records_list = list(records_df.iterrows())
        
        # Use PACKAGE_SIZE for grouping, max_workers for parallelism within each package
        effective_package_size = PACKAGE_SIZE
        total_packages = (len(records_list) + effective_package_size - 1) // effective_package_size
        
        # For small batches, use single package to avoid overhead
        if total_records <= PACKAGE_SIZE:
            total_packages = 1
            effective_package_size = total_records
        
        print(f"[START] Batch {batch_id}: {total_records} records, {max_workers} workers (worker-specific sessions)")
        
        # NOTE: Each worker creates its own requests.Session() for optimal connection pooling
        # No shared server_session needed anymore
        token_refresh_failed = False
        
        for package_num in range(total_packages):
            # Check for cancellation BEFORE starting each package
            if is_cancel_requested(batch_id):
                cancel_reason = "User requested cancellation"
                print(f"[CANCEL] Migration cancelled by user before package {package_num + 1}/{total_packages}")
                break
            
            # Check circuit breaker before package
            if circuit_breaker_tripped:
                break
            
            # Token health check before each package (works in both Flask and background context)
            is_valid, error = _check_and_refresh_token(session_snapshot)
            if not is_valid:
                circuit_breaker_tripped = True
                token_refresh_failed = True
                cancel_reason = error
                print(f"[TOKEN] {cancel_reason}")
                break
            
            # Get records for this package
            start_idx = package_num * effective_package_size
            end_idx = min(start_idx + effective_package_size, len(records_list))
            package_records = records_list[start_idx:end_idx]
            
            print(f"[PACKAGE {package_num + 1}/{total_packages}] Processing records {start_idx + 1}-{end_idx}")
            
            # PROBE MODE: Test first record of first package to detect auth issues early
            if package_num == 0 and len(package_records) > 0:
                print(f"[PROBE] Testing first record to verify SAP authentication...")
                try:
                    _, probe_row = package_records[0]
                    probe_result = execute_single_document(probe_row, session_snapshot)
                    probe_error = str(probe_result.get('error', '')).lower()
                    probe_status = probe_result.get('status_code', 0)
                    
                    is_probe_auth_error = (
                        probe_status in CIRCUIT_BREAKER_ERRORS or
                        '403' in probe_error or '401' in probe_error or
                        'csrf' in probe_error or 'forbidden' in probe_error
                    )
                    
                    if is_probe_auth_error:
                        circuit_breaker_tripped = True
                        cancel_reason = f"PROBE FAILED: SAP auth error - {probe_result.get('error', 'Unknown')}"
                        print(f"[PROBE] {cancel_reason}")
                        print(f"[PROBE] Stopping migration - please check SAP credentials/CSRF token")
                        results.append(probe_result)
                        completed_count += 1
                        failed_count += 1
                        break
                    else:
                        print(f"[PROBE] First record OK (status: {probe_result.get('status')}) - continuing with batch")
                        results.append(probe_result)
                        completed_count += 1
                        if probe_result.get('status') == 'success':
                            success_count += 1
                        elif probe_result.get('status') == 'failed':
                            failed_count += 1
                        update_progress()  # Immediate DB update after probe for live progress
                        # Remove first record from package since we already processed it
                        package_records = package_records[1:]
                        
                except Exception as probe_ex:
                    probe_error_str = str(probe_ex).lower()
                    is_auth_exception = (
                        '403' in probe_error_str or '401' in probe_error_str or
                        'csrf' in probe_error_str or 'forbidden' in probe_error_str
                    )
                    if is_auth_exception:
                        circuit_breaker_tripped = True
                        cancel_reason = f"PROBE EXCEPTION: {probe_ex}"
                        print(f"[PROBE] {cancel_reason}")
                        print(f"[PROBE] Stopping migration - SAP authentication failed")
                        results.append({'status': 'failed', 'error': str(probe_ex)})
                        completed_count += 1
                        failed_count += 1
                        break
                    else:
                        print(f"[PROBE] Non-auth error: {probe_ex} - continuing")
                        results.append({'status': 'failed', 'error': str(probe_ex)})
                        completed_count += 1
                        failed_count += 1
                        package_records = package_records[1:]
            
            # Skip if no more records in package
            if not package_records:
                continue
            
            # Process this package with ThreadPoolExecutor
            # Each worker creates its own requests.Session for optimal connection pooling
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(execute_single_document, row, session_snapshot): idx
                    for idx, (_, row) in enumerate(package_records)
                }
                
                from concurrent.futures import as_completed
                for future in as_completed(futures):
                    # Check for cancellation during package processing
                    if is_cancel_requested(batch_id):
                        cancel_reason = "User requested cancellation"
                        print(f"[CANCEL] Migration cancelled during package {package_num + 1}")
                        executor.shutdown(wait=False)
                        break
                    
                    try:
                        result = future.result()
                        results.append(result)
                        
                        # Circuit breaker: Track consecutive auth errors
                        # Check both HTTP status codes AND error messages for auth failures
                        status_code = result.get('status_code', 0)
                        error_msg = str(result.get('error', '')).lower()
                        is_auth_error = (
                            status_code in CIRCUIT_BREAKER_ERRORS or
                            '403' in error_msg or
                            '401' in error_msg or
                            'csrf' in error_msg or
                            'forbidden' in error_msg or
                            'unauthorized' in error_msg
                        )
                        
                        if is_auth_error:
                            consecutive_auth_errors += 1
                            print(f"[AUTH_ERROR] Consecutive auth errors: {consecutive_auth_errors}/{CIRCUIT_BREAKER_THRESHOLD}")
                            if consecutive_auth_errors >= CIRCUIT_BREAKER_THRESHOLD:
                                circuit_breaker_tripped = True
                                cancel_reason = f"Circuit breaker: {consecutive_auth_errors} consecutive auth errors"
                                print(f"[CIRCUIT_BREAKER] {cancel_reason}")
                                print(f"[CIRCUIT_BREAKER] Token/CSRF likely expired - stopping to prevent wasted API calls")
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                        else:
                            # Reset counter on successful response (not auth error)
                            consecutive_auth_errors = 0
                        
                        # Update counters
                        completed_count += 1
                        if result.get('status') == 'success':
                            success_count += 1
                        elif result.get('status') == 'failed':
                            failed_count += 1
                        elif result.get('status') == 'partial':
                            partial_count += 1
                        
                        # Log progress
                        pct = (completed_count / total_records) * 100
                        elapsed = time.time() - batch_start_time
                        rate = completed_count / elapsed if elapsed > 0 else 0
                        eta_seconds = (total_records - completed_count) / rate if rate > 0 else 0
                        eta_str = f"{int(eta_seconds//60)}m {int(eta_seconds%60)}s" if eta_seconds > 0 else "-"
                        
                        # Print progress every 10 records or at 25%, 50%, 75%, 100%
                        if completed_count % 10 == 0 or pct in [25, 50, 75, 100] or completed_count == total_records:
                            auth_warning = f" (auth errors: {consecutive_auth_errors})" if consecutive_auth_errors > 0 else ""
                            print(f"[PROGRESS] {completed_count}/{total_records} ({pct:.0f}%) | ✓{success_count} ✗{failed_count} | ETA: {eta_str}{auth_warning}")
                        
                        # Update DB every 2 records or at end for live progress
                        if completed_count % 2 == 0 or completed_count == total_records:
                            update_progress()

                            
                    except Exception as e:
                        error_str = str(e).lower()
                        print(f"[EXECUTE_ERROR] {e}")
                        results.append({'status': 'failed', 'error': str(e)})
                        completed_count += 1
                        failed_count += 1
                        
                        # Circuit breaker: Also check exceptions for auth errors
                        is_auth_exception = (
                            '403' in error_str or
                            '401' in error_str or
                            'csrf' in error_str or
                            'forbidden' in error_str or
                            'unauthorized' in error_str
                        )
                        if is_auth_exception:
                            consecutive_auth_errors += 1
                            print(f"[AUTH_ERROR] Consecutive auth errors: {consecutive_auth_errors}/{CIRCUIT_BREAKER_THRESHOLD}")
                            if consecutive_auth_errors >= CIRCUIT_BREAKER_THRESHOLD:
                                circuit_breaker_tripped = True
                                cancel_reason = f"Circuit breaker: {consecutive_auth_errors} consecutive auth errors (exceptions)"
                                print(f"[CIRCUIT_BREAKER] {cancel_reason}")
                                print(f"[CIRCUIT_BREAKER] Token/CSRF likely expired - stopping")
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                        # Don't reset counter on non-auth exceptions - they could be unrelated errors
                
                # Break out of package loop if cancelled or circuit breaker
                if is_cancel_requested(batch_id) or circuit_breaker_tripped:
                    break
        
        # Note: Each worker creates and closes its own session internally
        
        # Handle circuit breaker or cancel situation
        if circuit_breaker_tripped or is_cancel_requested(batch_id):
            # Final progress update before setting stopped status
            update_progress()
            
            # Update batch status to reflect stopped state
            stop_reason = cancel_reason or "Unknown"
            remaining_records = total_records - completed_count
            
            with misc_engine.begin() as con:
                con.execute(text(f"""
                    UPDATE dbo.migration_batch
                    SET status = 'stopped',
                        executed_records = {completed_count},
                        successful_records = {success_count},
                        failed_records = {failed_count + partial_count}
                    WHERE batch_id = '{batch_id}'
                """))
            
            # Clear migration lock
            clear_migration_lock(batch_id)
            clear_cancel_request(batch_id)
            
            # Calculate timing
            batch_end_time = time.time()
            this_run_duration = batch_end_time - batch_start_time
            
            print(f"[STOPPED] Batch {batch_id} stopped after {completed_count}/{total_records} records in {this_run_duration:.1f}s")
            print(f"[STOPPED] Reason: {stop_reason}")
            print(f"[STOPPED] Remaining: {remaining_records} records still pending")
            
            return {
                'success': True,
                'stopped': True,
                'stop_reason': stop_reason,
                'circuit_breaker_tripped': circuit_breaker_tripped,
                'cancelled': is_cancel_requested(batch_id),
                'processed': completed_count,
                'total': total_records,
                'remaining': remaining_records,
                'successful': success_count,
                'failed': failed_count + partial_count,
                'duration_seconds': round(this_run_duration, 2),
                'message': f"Migration stopped: {stop_reason}. Processed {completed_count}/{total_records} records."
            }
        
        # Final progress update
        update_progress()
        
        # Calculate batch timing from THIS execution run
        batch_end_time = time.time()
        this_run_duration = batch_end_time - batch_start_time
        
        # Update batch statistics - count from this run's results
        success_count = len([r for r in results if r.get('status') == 'success'])
        failed_count = len([r for r in results if r.get('status') == 'failed'])
        partial_count = len([r for r in results if r.get('status') == 'partial'])
        
        # Calculate aggregate statistics from individual results
        total_bytes_this_run = sum(r.get('stats', {}).get('total_bytes', 0) for r in results)
        total_files_this_run = sum(r.get('stats', {}).get('file_count', 0) for r in results)
        
        # Now calculate statistics from database
        # If record_ids provided (execute_selected), only count those records
        # Otherwise count all executed records in the batch
        with misc_engine.begin() as con:
            # Build SQL with optional record_ids filter
            if record_ids:
                # Execute selected mode - only count the selected records
                record_ids_str = ','.join(str(id) for id in record_ids)
                stats_sql = f"""
                    SELECT 
                        COUNT(*) as total_executed,
                        SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                        SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                        SUM(CASE WHEN execution_status = 'partial' THEN 1 ELSE 0 END) as partial_count,
                        SUM(CAST(COALESCE(file_size_bytes, 0) AS BIGINT)) as total_bytes,
                        SUM(DATEDIFF(MILLISECOND, execution_started_at, execution_completed_at)) / 1000.0 as total_execution_time
                    FROM dbo.migration_staging 
                    WHERE batch_id = :batch_id 
                    AND id IN ({record_ids_str})
                    AND execution_status IN ('success', 'failed', 'partial')
                    AND execution_started_at IS NOT NULL
                    AND execution_completed_at IS NOT NULL
                """
            else:
                # Full batch execution - count all executed records
                stats_sql = """
                    SELECT 
                        COUNT(*) as total_executed,
                        SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                        SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                        SUM(CASE WHEN execution_status = 'partial' THEN 1 ELSE 0 END) as partial_count,
                        SUM(CAST(COALESCE(file_size_bytes, 0) AS BIGINT)) as total_bytes,
                        SUM(DATEDIFF(MILLISECOND, execution_started_at, execution_completed_at)) / 1000.0 as total_execution_time
                    FROM dbo.migration_staging 
                    WHERE batch_id = :batch_id 
                    AND execution_status IN ('success', 'failed', 'partial')
                    AND execution_started_at IS NOT NULL
                    AND execution_completed_at IS NOT NULL
                """
            cumulative = con.execute(text(stats_sql), {'batch_id': batch_id}).fetchone()
        
        # Use cumulative stats from database
        total_executed = cumulative[0] or 0
        cumulative_success = cumulative[1] or 0
        cumulative_failed = cumulative[2] or 0
        cumulative_partial = cumulative[3] or 0
        total_bytes = float(cumulative[4] or 0)  # Convert Decimal to float
        cumulative_execution_time = float(cumulative[5] or 0)  # Sum of all individual execution times
        
        # IMPORTANT: Use REAL elapsed time (this_run_duration), not cumulative execution time
        # With parallel workers, real time is shorter than sum of individual times
        # cumulative_execution_time is useful for avg_time_per_doc calculation
        real_duration = this_run_duration  # Actual wall-clock time for this run
        
        # Calculate statistics based on actual execution data
        total_mb = total_bytes / 1024 / 1024
        # avg_time_per_doc uses cumulative time (actual CPU time spent)
        avg_time_per_doc = cumulative_execution_time / total_executed if total_executed > 0 else 0
        # Throughput uses REAL duration (what user experiences with parallel workers)
        avg_time_per_mb = real_duration / total_mb if total_mb > 0 else 0
        throughput_mb_per_min = (total_mb / real_duration * 60) if real_duration > 0 else 0
        total_files = total_executed  # Approximation - 1 file per document on average
        
        # Determine final status based on results
        if cumulative_failed + cumulative_partial > 0:
            final_status = 'completed_with_errors'
        else:
            final_status = 'completed'
        
        # Update batch with CUMULATIVE statistics
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET status = '{final_status}',
                    migration_phase = 'upload_done',
                    executed_records = {total_executed},
                    successful_records = {cumulative_success},
                    failed_records = {cumulative_failed + cumulative_partial}
                WHERE batch_id = '{batch_id}'
            """))
        
        # Format REAL duration with hours if needed (what user experiences)
        if real_duration >= 3600:
            duration_formatted = f"{int(real_duration // 3600)}h {int((real_duration % 3600) // 60)}m {int(real_duration % 60)}s"
        else:
            duration_formatted = f"{int(real_duration // 60)}m {int(real_duration % 60)}s"
        
        # Build statistics summary (using real elapsed time for throughput)
        batch_stats = {
            'batch_duration_seconds': round(real_duration, 2),  # Real wall-clock time
            'batch_duration_formatted': duration_formatted,
            'cumulative_cpu_time_seconds': round(cumulative_execution_time, 2),  # Sum of individual times
            'total_documents': total_executed,
            'total_files': total_files,
            'total_bytes': total_bytes,
            'total_mb': round(total_mb, 2),
            'avg_time_per_document_seconds': round(avg_time_per_doc, 2),  # Based on cumulative time
            'avg_time_per_mb_seconds': round(avg_time_per_mb, 2),  # Based on real time
            'throughput_mb_per_minute': round(throughput_mb_per_min, 2),  # Based on real time
            'workers': max_workers,
            'parallel_speedup': round(cumulative_execution_time / real_duration, 2) if real_duration > 0 else 1,
            'pacing_seconds': pacing_seconds,
            'this_run': {
                'documents': len(results),
                'success': success_count,
                'failed': failed_count,
                'partial': partial_count,
                'duration_seconds': round(this_run_duration, 2)
            }
        }
        
        # Analyze file size errors
        size_errors = []
        all_file_results = []
        error_by_category = {}  # Collect errors by category
        all_error_details = []  # Collect detailed error info
        
        for r in results:
            # Document-level errors (e.g., CREATE_FAIL, READ_FAILED)
            if r.get('error_detail'):
                category = _classify_error(r.get('error_detail'))
                if category not in error_by_category:
                    error_by_category[category] = []
                error_by_category[category].append({
                    'staging_id': r.get('staging_id'),
                    'error': r.get('error'),
                    'detail': r.get('error_detail')
                })
                all_error_details.append({
                    'staging_id': r.get('staging_id'),
                    'category': category,
                    'category_desc': get_error_description(category),
                    'error': r.get('error'),
                    'status_code': r.get('error_detail', {}).get('status_code'),
                    'sap_code': r.get('error_detail', {}).get('code'),
                    'message': r.get('error_detail', {}).get('detail')
                })
            
            if r.get('results'):  # Individual document results contain file details
                for file_result in r.get('results', []):
                    all_file_results.append(file_result)
                    if file_result.get('is_size_error'):
                        size_errors.append({
                            'file': file_result.get('file'),
                            'size_mb': file_result.get('file_size_mb', 0),
                            'status': file_result.get('status')
                        })
                    # Collect file-level errors by category
                    if file_result.get('error_detail'):
                        category = file_result.get('error_category') or _classify_error(file_result.get('error_detail'))
                        if category not in error_by_category:
                            error_by_category[category] = []
                        error_by_category[category].append({
                            'file': file_result.get('file'),
                            'error': file_result.get('status'),
                            'detail': file_result.get('error_detail')
                        })
                        all_error_details.append({
                            'staging_id': r.get('staging_id'),
                            'file': file_result.get('file'),
                            'file_size_mb': file_result.get('file_size_mb'),
                            'category': category,
                            'category_desc': get_error_description(category),
                            'error': file_result.get('status'),
                            'status_code': file_result.get('error_detail', {}).get('status_code'),
                            'sap_code': file_result.get('error_detail', {}).get('code'),
                            'message': file_result.get('error_detail', {}).get('detail')
                        })
        
        # Calculate size-based statistics
        if all_file_results:
            successful_files = [f for f in all_file_results if f.get('status') == 'SUCCESS']
            failed_files = [f for f in all_file_results if f.get('status') != 'SUCCESS']
            
            # Find max successful file size
            max_success_size = max([f.get('file_size', 0) for f in successful_files], default=0)
            min_failed_size = min([f.get('file_size', 0) for f in failed_files], default=0) if failed_files else 0
            
            batch_stats['file_size_analysis'] = {
                'successful_files': len(successful_files),
                'failed_files': len(failed_files),
                'size_errors': len(size_errors),
                'max_successful_size_mb': round(max_success_size / 1024 / 1024, 2),
                'min_failed_size_mb': round(min_failed_size / 1024 / 1024, 2) if min_failed_size > 0 else None,
                'size_error_details': size_errors[:10]  # Limit to first 10
            }
            
            # Estimate size limit if we have both successful and failed
            if max_success_size > 0 and min_failed_size > 0:
                batch_stats['file_size_analysis']['estimated_limit_mb'] = round(max_success_size / 1024 / 1024, 2)
            
            # Timing analysis by file size (actual processing time, without pacing)
            timing_data = []
            for f in all_file_results:
                if f.get('file_size') and f.get('actual_time_seconds'):
                    timing_data.append({
                        'file': f.get('file'),
                        'size_mb': f.get('file_size_mb', round(f.get('file_size', 0) / 1024 / 1024, 2)),
                        'actual_time_seconds': f.get('actual_time_seconds'),
                        'status': 'SUCCESS' if f.get('status') == 'SUCCESS' else 'FAILED'
                    })
            
            if timing_data:
                # Sort by size for analysis
                timing_data.sort(key=lambda x: x['size_mb'])
                
                # Calculate average time per MB for successful files
                successful_timing = [t for t in timing_data if t['status'] == 'SUCCESS']
                if successful_timing:
                    total_success_mb = sum(t['size_mb'] for t in successful_timing)
                    total_success_time = sum(t['actual_time_seconds'] for t in successful_timing)
                    avg_seconds_per_mb = total_success_time / total_success_mb if total_success_mb > 0 else 0
                    
                    # Recommended pacing based on actual times
                    max_actual_time = max(t['actual_time_seconds'] for t in successful_timing)
                    recommended_pacing = round(max_actual_time * 1.2, 1)  # 20% buffer
                    
                    batch_stats['timing_analysis'] = {
                        'files_with_timing': len(timing_data),
                        'avg_seconds_per_mb': round(avg_seconds_per_mb, 2),
                        'max_actual_time_seconds': round(max_actual_time, 2),
                        'recommended_pacing_seconds': recommended_pacing,
                        'file_details': timing_data[:20]  # First 20 files with timing
                    }
                else:
                    batch_stats['timing_analysis'] = {
                        'files_with_timing': len(timing_data),
                        'note': 'No successful files with timing data',
                        'file_details': timing_data[:20]
                    }
        
        # Add error analysis to batch_stats
        error_summary = []
        for category, errors in error_by_category.items():
            error_summary.append({
                'category': category,
                'description': get_error_description(category),
                'count': len(errors),
                'examples': errors[:3]  # First 3 examples per category
            })
        # Sort by count descending
        error_summary.sort(key=lambda x: x['count'], reverse=True)
        
        batch_stats['error_analysis'] = {
            'total_errors': len(all_error_details),
            'categories': error_summary,
            'details': all_error_details[:50]  # Limit to first 50 detailed errors
        }
        
        # Save statistics to database (separate column, not notes)
        import json
        stats_json = json.dumps(batch_stats).replace("'", "''")
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET execution_stats = '{stats_json}'
                WHERE batch_id = '{batch_id}'
            """))
        
        # Print final summary - differentiate between full batch and selected records
        if record_ids:
            print(f"[DONE] Selected {len(record_ids)} records: ✓{cumulative_success} ✗{cumulative_failed} ⚠{cumulative_partial} | {batch_stats['batch_duration_formatted']} | {throughput_mb_per_min:.1f}MB/min")
        else:
            print(f"[DONE] Batch {batch_id}: ✓{cumulative_success} ✗{cumulative_failed} ⚠{cumulative_partial} | {batch_stats['batch_duration_formatted']} | {throughput_mb_per_min:.1f}MB/min")
        
        # Release the lock
        clear_migration_lock(batch_id)
        
        return {
            'success': True,
            'batch_id': batch_id,
            'total': len(results),
            'successful': success_count,
            'failed': failed_count,
            'partial': partial_count,
            'statistics': batch_stats
        }
        
    except Exception as e:
        print(f"[EXECUTE_ERROR] {e}")
        import traceback
        traceback.print_exc()
        
        # Release the lock on error
        clear_migration_lock(batch_id)
        
        return {
            'success': False,
            'error': str(e)
        }


# ============================================================================
# PHASE 2: Object Link Creation (Verlinkung)
# ============================================================================
# Phase 2 is separate from the upload phase. It creates Object Links
# (A_DocumentInfoRecordObjLink) for containers that were successfully uploaded
# in Phase 1. Phase 2 can run independently and in parallel since it only
# makes lightweight API calls (no file transfer).
# ============================================================================

# Separate lock and cancel tracking for linking (independent of upload)
_linking_lock = threading.Lock()
_active_linkings = {}   # batch_id -> start_time
_link_cancel_requested = {}  # batch_id -> True/False

LINK_PACKAGE_SIZE = 100  # Larger packages than upload since linking is lightweight


def is_linking_running(batch_id):
    """Check if a linking operation is currently running for this batch."""
    global _active_linkings
    with _linking_lock:
        if batch_id in _active_linkings:
            start_time = _active_linkings[batch_id]
            elapsed_minutes = (time.time() - start_time) / 60
            return True, f"Verlinkung läuft seit {elapsed_minutes:.1f} Minuten"
    return False, None


def set_linking_lock(batch_id):
    """Set the linking lock for a batch."""
    global _active_linkings
    with _linking_lock:
        _active_linkings[batch_id] = time.time()
        if VERBOSE_TERMINAL_LOGGING:
            print(f"[LINK_LOCK] Acquired lock for batch {batch_id}")


def clear_linking_lock(batch_id):
    """Remove the linking lock for a batch."""
    global _active_linkings
    with _linking_lock:
        if batch_id in _active_linkings:
            del _active_linkings[batch_id]
            if VERBOSE_TERMINAL_LOGGING:
                print(f"[LINK_LOCK] Released lock for batch {batch_id}")


def request_link_cancel(batch_id):
    """Request cancellation of a running linking operation."""
    global _link_cancel_requested
    _link_cancel_requested[batch_id] = True
    print(f"[LINK_CANCEL] Cancellation requested for batch {batch_id}")
    return True


def is_link_cancel_requested(batch_id):
    """Check if cancellation was requested for linking."""
    global _link_cancel_requested
    return _link_cancel_requested.get(batch_id, False)


def clear_link_cancel_request(batch_id):
    """Clear the link cancel request flag for a batch."""
    global _link_cancel_requested
    if batch_id in _link_cancel_requested:
        del _link_cancel_requested[batch_id]


def update_link_status(staging_id, status, error=None):
    """Update link_status for a staging record.
    
    Args:
        staging_id: The staging record ID
        status: 'pending', 'linking', 'linked', 'link_failed', 'link_exists', 'skipped', 
                'partial_linked', 'link_skipped'
        error: Error message (optional)
    """
    try:
        completed_clause = ""
        if status in ('linked', 'link_failed', 'link_exists', 'skipped', 'partial_linked', 'link_skipped'):
            completed_clause = ", link_completed_at = GETUTCDATE()"
        
        update_query = f"""
            UPDATE dbo.migration_staging
            SET link_status = :status,
                link_error = :error
                {completed_clause}
            WHERE id = :staging_id
        """
        
        with misc_engine.begin() as con:
            con.execute(text(update_query), {
                'status': status,
                'error': str(error) if error else None,
                'staging_id': staging_id
            })
    except Exception as e:
        print(f"[LINK_UPDATE_ERROR] Failed to update staging_id={staging_id}: {e}")


def batch_update_link_statuses(updates):
    """Bulk update link_status for multiple staging records in a single transaction.
    
    Much faster than calling update_link_status() individually for each record, 
    since it uses one DB connection/transaction instead of N.
    
    Args:
        updates: list of dicts with keys: staging_id, status, error (optional)
    """
    if not updates:
        return
    try:
        with misc_engine.begin() as con:
            # Split into completed (need timestamp) and non-completed
            for upd in updates:
                completed_clause = ""
                target_link_clause = ""
                if upd['status'] in ('linked', 'link_failed', 'link_exists', 'skipped', 'partial_linked', 'link_skipped'):
                    completed_clause = ", link_completed_at = GETUTCDATE()"
                # Update target_link_count with actual links created + already existed
                links_created = upd.get('links_created', 0) or 0
                links_existed = upd.get('links_existed', 0) or 0
                actual_target = links_created + links_existed
                if actual_target > 0 or upd['status'] in ('linked', 'partial_linked', 'link_exists'):
                    target_link_clause = f", target_link_count = {int(actual_target)}"
                
                con.execute(text(f"""
                    UPDATE dbo.migration_staging
                    SET link_status = :status,
                        link_error = :error
                        {completed_clause}
                        {target_link_clause}
                    WHERE id = :staging_id
                """), {
                    'status': upd['status'],
                    'error': upd.get('error'),
                    'staging_id': upd['staging_id']
                })
        print(f"[LINK_BATCH_UPDATE] Updated {len(updates)} records in single transaction")
    except Exception as e:
        print(f"[LINK_BATCH_UPDATE_ERROR] Failed to batch update {len(updates)} records: {e}")
        # Fallback: try individual updates
        for upd in updates:
            try:
                update_link_status(upd['staging_id'], upd['status'], upd.get('error'))
            except Exception:
                pass


def batch_set_linking(staging_ids):
    """Set link_status='linking' for multiple records at once.
    
    Args:
        staging_ids: list of staging record IDs
    """
    if not staging_ids:
        return
    try:
        with misc_engine.begin() as con:
            # Use IN clause with chunks of 1000
            for i in range(0, len(staging_ids), 1000):
                chunk = staging_ids[i:i+1000]
                placeholders = ', '.join(str(int(sid)) for sid in chunk)
                con.execute(text(f"""
                    UPDATE dbo.migration_staging
                    SET link_status = 'linking', link_error = NULL
                    WHERE id IN ({placeholders})
                """))
    except Exception as e:
        print(f"[LINK_BATCH_SET_ERROR] Failed to set linking for {len(staging_ids)} records: {e}")


def load_linkable_records(batch_id, record_ids=None):
    """Load records that are eligible for linking (Phase 2).
    
    Records must have:
      - execution_status IN ('success', 'partial') — container was uploaded
      - container_created = 1 — container confirmed
      - link_status IN ('pending', 'link_failed') — not yet linked (or retry)
      - source_object_links populated (for multi-link) OR target_dokob/target_objky (legacy)
    """
    base_query = """
        SELECT 
            id,
            batch_id,
            source_documentnumber,
            source_documentpart,
            source_documenttype,
            source_documentversion,
            target_documentnumber,
            target_documentpart,
            target_documenttype,
            target_documentversion,
            source_object_links,
            source_link_count,
            target_dokob,
            target_objky,
            link_status,
            link_error,
            container_created
        FROM dbo.migration_staging
        WHERE batch_id = :batch_id
            AND execution_status IN ('success', 'partial')
            AND ISNULL(container_created, 0) = 1
            AND ISNULL(link_status, 'pending') IN ('pending', 'link_failed')
            AND (
                (source_object_links IS NOT NULL AND source_object_links != '' AND source_object_links != '[]')
                OR (target_dokob IS NOT NULL AND target_dokob != '' AND target_objky IS NOT NULL AND target_objky != '')
            )
    """
    
    if record_ids:
        ids_str = ','.join(str(rid) for rid in record_ids)
        base_query += f" AND id IN ({ids_str})"
    
    base_query += " ORDER BY id"
    
    with misc_engine.begin() as con:
        df = pd.read_sql(text(base_query), con, params={'batch_id': batch_id})
    
    return df


def link_single_record(staging_record, session_snapshot, mappings_cache=None, skip_status_updates=False, dokob_filter_set=None):
    """Create Object Links for a single staging record (Phase 2).
    
    Makes lightweight POST(s) to A_DocumentInfoRecordObjLink.
    No file transfer — only metadata.
    
    Supports multiple object links per document: iterates through source_object_links JSON,
    applies object mapping for each, and creates all target links.
    
    Args:
        staging_record: dict with staging record data
        session_snapshot: SAP session/auth data
        mappings_cache: Pre-loaded mappings dict (source_dokob, source_objky) -> (target_dokob, target_objky).
                        If None, loads from DB (legacy, slower).
        skip_status_updates: If True, skip individual DB status updates (caller handles batch updates).
        dokob_filter_set: Set of uppercase DOKOB strings to include, or None for all.
    
    Returns:
        dict with 'staging_id', 'status', 'error' (optional), 'status_code' (optional),
              'links_created' (count), 'links_failed' (count), 'links_skipped' (count)
    """
    staging_id = staging_record['id']
    batch_id = staging_record.get('batch_id')
    logger = get_logger(batch_id=batch_id, staging_id=staging_id)
    
    doc_type = staging_record['target_documenttype']
    doc_number = staging_record['target_documentnumber']
    doc_version = staging_record['target_documentversion'] or staging_record.get('source_documentversion', '01')
    doc_part = staging_record['target_documentpart'] or staging_record.get('source_documentpart', '000')
    
    # Build list of source links to process.
    # source_object_links JSON is authoritative after execute (updated from API).
    # source_dokob/source_objky columns also enriched by API. Include both sources,
    # deduplicated, for backward compat with records executed before JSON update.
    source_links = []
    use_legacy_targets = False
    
    # Collect links from source_object_links JSON
    source_object_links_json = staging_record.get('source_object_links')
    if source_object_links_json:
        try:
            parsed = json.loads(source_object_links_json)
            if isinstance(parsed, list):
                for item in parsed:
                    dokob = item.get('dokob')
                    objky = item.get('objky')
                    if dokob and objky:
                        pair = (str(dokob).strip(), str(objky).strip())
                        if pair not in source_links:
                            source_links.append(pair)
        except (json.JSONDecodeError, TypeError):
            logger.debug(f"Could not parse source_object_links JSON", category="OBJLINK")
    
    # Also include source_dokob/source_objky columns (enriched by API during execute)
    primary_dokob = staging_record.get('source_dokob')
    primary_objky = staging_record.get('source_objky')
    if primary_dokob and primary_objky:
        pair = (str(primary_dokob).strip(), str(primary_objky).strip())
        if pair not in source_links:
            source_links.append(pair)
    
    # Apply DOKOB filter: only keep links whose DOKOB is in the batch's selection
    if dokob_filter_set and source_links:
        before = len(source_links)
        source_links = [p for p in source_links if p[0].upper() in dokob_filter_set]
        if len(source_links) < before:
            logger.info(f"DOKOB filter: {before} -> {len(source_links)} links (excluded {before - len(source_links)})", category="OBJLINK")
    
    # Fallback: if still no links, use legacy single target_dokob/target_objky
    if not source_links:
        legacy_dokob = staging_record.get('target_dokob')
        legacy_objky = staging_record.get('target_objky')
        if legacy_dokob and legacy_objky:
            source_links = [(legacy_dokob, legacy_objky)]  # These are already target values
            use_legacy_targets = True
        else:
            # No links to create
            if not skip_status_updates:
                update_link_status(staging_id, 'linked')  # Nothing to link is success
            return {
                'staging_id': staging_id,
                'status': 'linked',
                'links_created': 0,
                'links_failed': 0,
                'links_skipped': 0,
                'note': 'no_object_links'
            }
    
    # Load object mappings for this batch (use cache if provided)
    mappings = {}
    if not use_legacy_targets:
        if mappings_cache is not None:
            mappings = mappings_cache
        else:
            try:
                mappings = load_object_mappings(batch_id) or {}
            except Exception as e:
                logger.debug(f"Failed to load object mappings: {e}", category="OBJLINK")
    
    # Mark as linking
    if not skip_status_updates:
        update_link_status(staging_id, 'linking')
    
    try:
        # Create worker-specific session
        target_system = get_target_system(session_snapshot)
        server_session = requests.Session()
        prepare_session_headers(server_session, session_snapshot, target_system)
        server_session.headers.update({'Content-Type': 'application/json'})
        
        # Build base URL for object link POSTs
        doc_base_url = cfg.get(target_system, 'api_list', 'document', 'base_url')
        doc_key = (
            f"DocumentInfoRecordDocType='{doc_type}',"
            f"DocumentInfoRecordDocVersion='{doc_version}',"
            f"DocumentInfoRecordDocNumber='{doc_number}',"
            f"DocumentInfoRecordDocPart='{doc_part}'"
        )
        post_url = f"{doc_base_url}/A_DocumentInfoRecord({doc_key})/to_ProductObj"
        
        # ── Pre-check: fetch existing object links from SAP ──────────
        existing_links = set()
        try:
            get_resp = server_session.get(post_url, params={'$format': 'json'})
            if get_resp.status_code == 200:
                data = get_resp.json()
                results_list = data.get('d', {}).get('results', [])
                for entry in results_list:
                    ex_dokob = entry.get('LinkedSAPObject', '').strip()
                    ex_objky = entry.get('LinkedSAPObjectKey', '').strip()
                    if ex_dokob and ex_objky:
                        existing_links.add((ex_dokob, ex_objky))
                if existing_links:
                    logger.info(f"Pre-check: {len(existing_links)} existing links found in SAP", category="OBJLINK")
            else:
                logger.debug(f"Pre-check GET returned {get_resp.status_code}, proceeding without pre-check", category="OBJLINK")
        except Exception as pre_e:
            logger.debug(f"Pre-check failed ({pre_e}), proceeding without pre-check", category="OBJLINK")
        
        # Track results
        links_created = 0
        links_failed = 0
        links_skipped = 0
        links_existed = 0
        last_error = None
        
        # Process each object link
        for link_idx, (src_dokob, src_objky) in enumerate(source_links, start=1):
            counter = f"{link_idx:03d}"  # DocObjectLinkCounter: 001, 002, 003, ...
            
            # Resolve target values
            if use_legacy_targets:
                # Legacy mode: values are already target values
                target_dokob, target_objky = src_dokob, src_objky
            else:
                # Apply object mapping: source -> target
                key = (str(src_dokob).upper(), str(src_objky))
                if key in mappings:
                    target_dokob, target_objky = mappings[key]
                else:
                    # No mapping found -> pass through source values as-is
                    target_dokob, target_objky = src_dokob, src_objky
                    logger.info(f"No object mapping for {key}, passing through source values for link #{link_idx}", category="OBJLINK")
            
            # ── Pre-check: skip if link already exists in SAP ──────
            if (target_dokob, target_objky) in existing_links:
                logger.info(f"Link #{link_idx} already exists in SAP (pre-check): {target_dokob}/{target_objky} — skipping POST", category="OBJLINK")
                links_existed += 1
                continue
            
            object_link_payload = {
                'LinkedSAPObject': target_dokob,
                'LinkedSAPObjectKey': target_objky,
                'DocObjectLinkCounter': counter
            }
            
            logger.info(f"Creating object link #{link_idx}: {target_dokob}/{target_objky}", category="OBJLINK")
            logger.debug(f"Object link payload: {object_link_payload}", category="OBJLINK")
            
            try:
                link_resp = server_session.post(post_url, json=object_link_payload)
                # CSRF retry
                if is_csrf_error(link_resp):
                    logger.warning("CSRF token expired during OBJLINK — refreshing and retrying", category="OBJLINK")
                    force_csrf_renewal(session_snapshot, target_system)
                    prepare_session_headers(server_session, session_snapshot, target_system)
                    server_session.headers.update({'Content-Type': 'application/json'})
                    link_resp = server_session.post(post_url, json=object_link_payload)
                body_txt_lower = link_resp.text.lower() if link_resp.text else ''
                
                if link_resp.status_code not in (200, 201, 204):
                    resp_body = link_resp.text[:500] if link_resp.text else '(empty)'
                    logger.warning(f"Link #{link_idx} response {link_resp.status_code}: {resp_body}", category="OBJLINK_DEBUG")
                
                if link_resp.status_code in (200, 201, 204):
                    logger.info(f"Object link #{link_idx} created: {target_dokob}/{target_objky}", category="OBJLINK")
                    links_created += 1
                
                elif any(x in body_txt_lower for x in ['exist', 'duplicate', 'already', 'vorhanden', 'bereits']):
                    # SAP may return 400, 409, or even 500 for duplicates
                    logger.info(f"Object link #{link_idx} already exists (HTTP {link_resp.status_code}): {target_dokob}/{target_objky}", category="OBJLINK")
                    links_existed += 1
                
                else:
                    error_info = _extract_error_fields(link_resp)
                    # Build rich error string with all available information
                    err_detail = error_info.get('detail', 'Unknown')
                    err_code = error_info.get('code', '')
                    corr_id = error_info.get('correlation_id', '')
                    parts = [f"LINK_FAIL_{link_resp.status_code}"]
                    if err_code:
                        parts.append(f"[{err_code}]")
                    parts.append(err_detail)
                    if corr_id:
                        parts.append(f"(ID:{corr_id})")
                    last_error = ': '.join(parts[:2]) + ((' ' + ' '.join(parts[2:])) if len(parts) > 2 else '')
                    # Truncate to fit DB column (max 2000 chars)
                    if len(last_error) > 2000:
                        last_error = last_error[:1997] + '...'
                    logger.warning(f"Object link #{link_idx} failed: {last_error}", category="OBJLINK")
                    # Log full response body for debugging
                    raw = error_info.get('raw_body', '')
                    if raw:
                        logger.debug(f"Link #{link_idx} full response: {raw}", category="OBJLINK_DEBUG")
                    links_failed += 1
                    
            except Exception as e:
                logger.warning(f"Exception creating link #{link_idx}: {e}", category="OBJLINK")
                last_error = str(e)
                links_failed += 1
        
        # Determine overall status
        total_attempted = links_created + links_failed + links_existed
        if links_failed > 0 and links_created == 0 and links_existed == 0:
            # All failed, none succeeded or existed
            if not skip_status_updates:
                update_link_status(staging_id, 'link_failed', last_error)
            return {
                'staging_id': staging_id,
                'status': 'link_failed',
                'error': last_error,
                'links_created': links_created,
                'links_failed': links_failed,
                'links_skipped': links_skipped,
                'links_existed': links_existed
            }
        elif links_created > 0 or links_existed > 0:
            # At least some succeeded or already existed
            status = 'linked' if links_failed == 0 else 'partial_linked'
            if not skip_status_updates:
                update_link_status(staging_id, status)
            return {
                'staging_id': staging_id,
                'status': status,
                'links_created': links_created,
                'links_failed': links_failed,
                'links_skipped': links_skipped,
                'links_existed': links_existed
            }
        else:
            # All were skipped (no mappings found)
            if not skip_status_updates:
                update_link_status(staging_id, 'link_skipped', 'No object mappings found for any source link')
            return {
                'staging_id': staging_id,
                'status': 'link_skipped',
                'links_created': 0,
                'links_failed': 0,
                'links_skipped': links_skipped,
                'links_existed': 0
            }
    
    except Exception as e:
        logger.error(f"Exception in link_single_record: {e}", category="OBJLINK")
        if not skip_status_updates:
            update_link_status(staging_id, 'link_failed', str(e))
        return {
            'staging_id': staging_id,
            'status': 'link_failed',
            'error': str(e)
        }


def execute_linking(batch_id, record_ids=None, session_snapshot=None):
    """Execute Phase 2: Object Link creation for a batch.
    
    Creates Object Links (A_DocumentInfoRecordObjLink) for all eligible records.
    Eligible = container uploaded successfully + target_dokob/target_objky populated.
    
    Uses parallel execution with ThreadPoolExecutor (lightweight API calls).
    Supports cancellation, circuit breaker, and package-based processing.
    Can run in Flask request context (legacy) or as a background thread.
    
    Args:
        batch_id: The batch ID
        record_ids: Optional list of specific staging record IDs (for selected execution)
        session_snapshot: Optional pre-built session snapshot dict. If None, reads from Flask session.
    
    Returns:
        dict with success status, statistics, errors
    """
    # Check if linking is already running
    running, msg = is_linking_running(batch_id)
    if running:
        return {'success': False, 'error': msg}
    
    # Set lock
    set_linking_lock(batch_id)
    clear_link_cancel_request(batch_id)
    
    try:
        # Build session snapshot: use provided snapshot or read from Flask session
        if session_snapshot is None:
            max_workers = http_session.get('max_workers', MAX_API_WORKERS)
            session_snapshot = {
                'bearer_token': http_session.get('bearer_token'),
                'sap_system': http_session.get('sap_system'),
                'x_csrf_token': http_session.get('x-csrf-token'),
                'cookies': http_session.get('cookies'),
                'csrf_token_time': http_session.get('csrf_token_time', 0),
                'max_workers': max_workers,
                'source_system': http_session.get('source_system', read_sap_system),
                'target_system': http_session.get('target_system', write_sap_system),
                'refresh_token': http_session.get('refresh_token'),
                'token_expires_at': http_session.get('token_expires_at'),
            }
        
        max_workers = session_snapshot.get('max_workers', MAX_API_WORKERS)
        
        # Auto-apply object mappings to staging before loading
        # This ensures target_dokob/target_objky are populated even if mappings
        # were uploaded AFTER the upload phase completed
        try:
            applied = apply_object_mappings_for_batch(batch_id)
            if applied > 0:
                print(f"[LINK] Auto-applied object mappings to {applied} staging records")
        except Exception as e:
            print(f"[LINK_WARN] Could not auto-apply mappings: {e}")
        
        # Fix legacy READ_EMPTY records: change execution_status from 'failed' to 'success'
        # and mark link_status as 'link_skipped' (no files = nothing to link)
        try:
            with misc_engine.begin() as con:
                fixed = con.execute(text("""
                    UPDATE dbo.migration_staging
                    SET execution_status = 'success',
                        link_status = 'link_skipped',
                        link_error = 'Nicht notwendig - Keine Dateien im Quellsystem',
                        link_completed_at = GETUTCDATE()
                    WHERE batch_id = :batch_id
                        AND execution_status = 'failed'
                        AND execution_error LIKE '%READ_EMPTY%'
                        AND ISNULL(link_status, 'pending') IN ('pending', 'link_failed')
                """), {'batch_id': batch_id}).rowcount
                if fixed > 0:
                    print(f"[LINK] Fixed {fixed} READ_EMPTY records → success + link_skipped")
        except Exception as e:
            print(f"[LINK_WARN] Could not fix READ_EMPTY records: {e}")
        
        # Load linkable records
        records_df = load_linkable_records(batch_id, record_ids)
        
        if len(records_df) == 0:
            clear_linking_lock(batch_id)
            return {
                'success': False,
                'error': 'Keine verlinkbaren Datensätze gefunden. Voraussetzungen: Upload erfolgreich, Container angelegt, Objekt-Mapping vorhanden, noch nicht verlinkt.'
            }
        
        # Pre-load object mappings ONCE for the entire batch (avoid N+1 queries)
        mappings_cache = load_object_mappings(batch_id) or {}
        if mappings_cache:
            print(f"[LINK] Pre-loaded {len(mappings_cache)} object mappings (cached for all threads)")
        
        # Pre-load DOKOB filter for this batch (only link selected object types)
        dokob_filter_set = load_batch_dokob_filter(batch_id)
        if dokob_filter_set:
            print(f"[LINK] DOKOB filter active: {', '.join(sorted(dokob_filter_set))}")
        
        total_records = len(records_df)
        print(f"[LINK_START] Batch {batch_id}: {total_records} records for linking, {max_workers} workers")
        
        # Reset all linkable records to 'pending' so the progress bar starts at 0%
        # (otherwise re-runs start at 100% because 'link_failed' counts as completed)
        record_ids_to_reset = [int(r['id']) for _, r in records_df.iterrows()]
        ids_str = ','.join(str(rid) for rid in record_ids_to_reset)
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET link_status = 'pending', link_error = NULL
                WHERE id IN ({ids_str})
            """))
        
        # Update batch phase
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET migration_phase = 'linking',
                    status = CASE WHEN status IN ('completed', 'completed_with_errors', 'upload_done') 
                                  THEN 'linking' ELSE status END
                WHERE batch_id = '{batch_id}'
            """))
        
        # Progress tracking
        batch_start_time = time.time()
        completed_count = 0
        linked_count = 0
        exists_count = 0
        failed_count = 0
        
        # Circuit breaker
        consecutive_auth_errors = 0
        circuit_breaker_tripped = False
        cancel_reason = None
        
        # Convert to list for package processing
        records_list = list(records_df.iterrows())
        effective_package_size = LINK_PACKAGE_SIZE
        total_packages = (len(records_list) + effective_package_size - 1) // effective_package_size
        
        results = []
        
        for package_num in range(total_packages):
            # Check cancellation
            if is_link_cancel_requested(batch_id):
                cancel_reason = "User requested cancellation"
                print(f"[LINK_CANCEL] Linking cancelled before package {package_num + 1}/{total_packages}")
                break
            
            # Check circuit breaker
            if circuit_breaker_tripped:
                break
            
            # Token health check (works in both Flask and background context)
            is_valid, error = _check_and_refresh_token(session_snapshot)
            if not is_valid:
                circuit_breaker_tripped = True
                cancel_reason = error
                print(f"[LINK_TOKEN] {cancel_reason}")
                break
            
            # Get package records
            start_idx = package_num * effective_package_size
            end_idx = min(start_idx + effective_package_size, len(records_list))
            package_records = records_list[start_idx:end_idx]
            
            print(f"[LINK_PACKAGE {package_num + 1}/{total_packages}] Processing records {start_idx + 1}-{end_idx}")
            
            # Bulk set all records in this package to "linking" status
            package_ids = [row.to_dict()['id'] for _, row in package_records]
            batch_set_linking(package_ids)
            
            # Execute package in parallel (skip individual DB status updates - we batch them)
            package_results = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for _, row in package_records:
                    record_dict = row.to_dict()
                    future = executor.submit(link_single_record, record_dict, session_snapshot, 
                                             mappings_cache=mappings_cache, skip_status_updates=True,
                                             dokob_filter_set=dokob_filter_set)
                    futures[future] = record_dict['id']
                
                for future in futures:
                    try:
                        result = future.result(timeout=120)  # 2 min timeout per link
                        results.append(result)
                        package_results.append(result)
                        completed_count += 1
                        
                        status = result.get('status', '')
                        if status in ('linked', 'partial_linked'):
                            linked_count += 1
                            consecutive_auth_errors = 0
                        elif status in ('link_exists', 'link_skipped'):
                            exists_count += 1
                            consecutive_auth_errors = 0
                        elif status == 'link_failed':
                            failed_count += 1
                            # Check for auth errors (circuit breaker)
                            status_code = result.get('status_code', 0)
                            if status_code in CIRCUIT_BREAKER_ERRORS:
                                consecutive_auth_errors += 1
                                if consecutive_auth_errors >= CIRCUIT_BREAKER_THRESHOLD:
                                    circuit_breaker_tripped = True
                                    cancel_reason = f"Circuit breaker: {CIRCUIT_BREAKER_THRESHOLD} consecutive auth errors"
                                    print(f"[LINK_CIRCUIT] {cancel_reason}")
                                    break
                            else:
                                consecutive_auth_errors = 0
                    
                    except Exception as exc:
                        staging_id = futures[future]
                        package_results.append({'staging_id': staging_id, 'status': 'link_failed', 'error': str(exc)})
                        results.append({'staging_id': staging_id, 'status': 'link_failed', 'error': str(exc)})
                        completed_count += 1
                        failed_count += 1
            
            # Batch update all final statuses for this package in one transaction
            status_updates = []
            for r in package_results:
                sid = r.get('staging_id')
                st = r.get('status', 'link_failed')
                err = r.get('error')
                if st == 'link_skipped' and not err:
                    err = 'No object mappings found for any source link'
                status_updates.append({
                    'staging_id': sid, 'status': st, 'error': err,
                    'links_created': r.get('links_created', 0),
                    'links_existed': r.get('links_existed', 0)
                })
            batch_update_link_statuses(status_updates)
            
            # Update progress in batch table
            with misc_engine.begin() as con:
                con.execute(text(f"""
                    UPDATE dbo.migration_batch
                    SET executed_records = {completed_count}
                    WHERE batch_id = '{batch_id}'
                """))
        
        # Final statistics
        duration = time.time() - batch_start_time
        
        # Determine final phase
        if cancel_reason:
            final_phase = 'link_cancelled'
            final_status = 'link_cancelled'
        elif failed_count > 0:
            final_phase = 'completed'
            final_status = 'link_completed_with_errors'
        else:
            final_phase = 'completed'
            final_status = 'link_completed'
        
        # Update batch
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET migration_phase = '{final_phase}',
                    status = '{final_status}'
                WHERE batch_id = '{batch_id}'
            """))
        
        # Format duration
        if duration >= 3600:
            duration_formatted = f"{int(duration // 3600)}h {int((duration % 3600) // 60)}m {int(duration % 60)}s"
        elif duration >= 60:
            duration_formatted = f"{int(duration // 60)}m {int(duration % 60)}s"
        else:
            duration_formatted = f"{int(duration)}s"
        
        print(f"[LINK_DONE] Batch {batch_id}: {linked_count} linked, {exists_count} already existed, {failed_count} failed ({duration_formatted})")
        
        clear_linking_lock(batch_id)
        
        return {
            'success': True,
            'batch_id': batch_id,
            'total_records': total_records,
            'completed': completed_count,
            'linked': linked_count,
            'already_existed': exists_count,
            'failed': failed_count,
            'duration_seconds': round(duration, 2),
            'duration_formatted': duration_formatted,
            'cancel_reason': cancel_reason,
            'results': results
        }
    
    except Exception as e:
        print(f"[LINK_ERROR] Batch {batch_id}: {e}")
        import traceback
        traceback.print_exc()
        
        # Update batch phase on error
        try:
            with misc_engine.begin() as con:
                con.execute(text(f"""
                    UPDATE dbo.migration_batch
                    SET migration_phase = 'link_error',
                        status = 'link_error'
                    WHERE batch_id = '{batch_id}'
                """))
        except Exception:
            pass
        
        clear_linking_lock(batch_id)
        
        return {
            'success': False,
            'error': str(e)
        }


# ============================================================================
# Background Execution Wrappers
# ============================================================================

def run_migration_background(batch_id, session_snapshot, record_ids=None):
    """Run execute_migration in a background thread.
    
    Starts a daemon thread that runs execute_migration() with the provided
    session_snapshot. The result is stored in _background_results for later
    retrieval via get_background_result().
    
    Args:
        batch_id: Batch ID to execute
        session_snapshot: Pre-built session snapshot dict (must include all auth data)
        record_ids: Optional list of specific record IDs
    
    Returns:
        threading.Thread object (already started)
    """
    def _worker():
        try:
            result = execute_migration(batch_id, record_ids=record_ids, session_snapshot=session_snapshot)
            _background_results[batch_id] = result
            print(f"[BG] Migration {batch_id} finished: success={result.get('success')}")
        except Exception as e:
            print(f"[BG_ERROR] Migration {batch_id} crashed: {e}")
            import traceback
            traceback.print_exc()
            _background_results[batch_id] = {'success': False, 'error': str(e)}
    
    thread = threading.Thread(target=_worker, name=f"migration-{batch_id}", daemon=True)
    thread.start()
    print(f"[BG] Migration {batch_id} started in background thread")
    return thread


def run_linking_background(batch_id, session_snapshot, record_ids=None):
    """Run execute_linking in a background thread.
    
    Starts a daemon thread that runs execute_linking() with the provided
    session_snapshot. The result is stored in _background_results for later
    retrieval via get_background_result().
    
    Args:
        batch_id: Batch ID to execute
        session_snapshot: Pre-built session snapshot dict
        record_ids: Optional list of specific record IDs
    
    Returns:
        threading.Thread object (already started)
    """
    def _worker():
        try:
            result = execute_linking(batch_id, record_ids=record_ids, session_snapshot=session_snapshot)
            _background_results[f"{batch_id}_linking"] = result
            print(f"[BG] Linking {batch_id} finished: success={result.get('success')}")
        except Exception as e:
            print(f"[BG_ERROR] Linking {batch_id} crashed: {e}")
            import traceback
            traceback.print_exc()
            _background_results[f"{batch_id}_linking"] = {'success': False, 'error': str(e)}
    
    thread = threading.Thread(target=_worker, name=f"linking-{batch_id}", daemon=True)
    thread.start()
    print(f"[BG] Linking {batch_id} started in background thread")
    return thread
