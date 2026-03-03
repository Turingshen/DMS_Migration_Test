"""
Shared blueprint, configuration, and helper functions for all route modules.
"""

from flask import Blueprint, session
import pandas as pd
from sqlalchemy import text

from app.process import (
    DEFAULT_SOURCE_SYSTEM, DEFAULT_TARGET_SYSTEM,
    get_systems_by_type
)
from app_config import Config, MiscEngine, DilEngine


# ── Shared state ──────────────────────────────────────────────────────────────

cfg = Config.load()
migrate_bp = Blueprint('app', __name__)

misc_db = MiscEngine.load()
misc_engine = misc_db.engine

UPLOAD_FOLDER = 'userdata/migration_uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}

# Default settings - can be overridden via /settings
# pacing_seconds=0 means dynamic pacing based on file size (5-45s)
DEFAULT_SETTINGS = {
    'max_workers': 2,
    'pacing_seconds': 0  # 0 = dynamic pacing (recommended)
}


# ── Helper functions ──────────────────────────────────────────────────────────

def _is_basic_auth_system(system_id: str) -> bool:
    """Check if a SAP system uses Basic Auth (direct connection without API gateway)."""
    return cfg.config_env.get(system_id, {}).get('auth_type', 'oauth') == 'basic'


def _is_authenticated() -> bool:
    """Check if user is authenticated for the current source+target system combination.

    Returns True if:
    - OAuth bearer_token exists (covers OAuth source/target), OR
    - Both source AND target systems use Basic Auth (no OAuth needed)
    """
    if session.get('bearer_token'):
        return True
    source_sys = session.get('source_system', DEFAULT_SOURCE_SYSTEM)
    target_sys = session.get('target_system', DEFAULT_TARGET_SYSTEM)
    if _is_basic_auth_system(source_sys) and _is_basic_auth_system(target_sys):
        return True
    return False


def _build_session_snapshot():
    """Build a session snapshot dict from the current Flask session.

    This snapshot contains all data needed for background execution,
    including OAuth refresh tokens for standalone token refresh.
    """
    from app.process import MAX_API_WORKERS
    db_settings = _load_db_settings()
    return {
        'bearer_token': session.get('bearer_token'),
        'sap_system': session.get('sap_system'),
        'x_csrf_token': session.get('x-csrf-token'),
        'cookies': session.get('cookies'),
        'csrf_token_time': session.get('csrf_token_time', 0),
        'max_workers': session.get('max_workers') or db_settings.get('max_workers') or MAX_API_WORKERS,
        'pacing_seconds': session.get('pacing_seconds') if session.get('pacing_seconds') is not None else db_settings.get('pacing_seconds', 0),
        'source_system': session.get('source_system', DEFAULT_SOURCE_SYSTEM),
        'target_system': session.get('target_system', DEFAULT_TARGET_SYSTEM),
        'refresh_token': session.get('refresh_token'),
        'token_expires_at': session.get('token_expires_at'),
    }


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def df_to_json_safe(df):
    """Convert DataFrame to JSON-safe list of dicts, handling NaN/NaT properly."""
    import math

    def safe_value(val):
        if val is None:
            return None
        if pd.isna(val):
            return None
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return val

    records = df.to_dict('records')
    return [{k: safe_value(v) for k, v in record.items()} for record in records]


def get_template_context():
    """Get common template context variables."""
    if 'sap_system' not in session:
        sap_systems = cfg.get('sap_systems') or {}
        if sap_systems:
            session['sap_system'] = next(iter(sap_systems.keys()))
        else:
            session['sap_system'] = 'zbq'

    source_sys = session.get('source_system', DEFAULT_SOURCE_SYSTEM)
    target_sys = session.get('target_system', DEFAULT_TARGET_SYSTEM)
    source_systems, target_systems = get_systems_by_type()

    # DIL system info (single HANA instance, not switchable)
    dil_cfg = cfg.get('db', 'dil') or {}
    dil_host = dil_cfg.get('db_host', '')
    dil_short = dil_host.split('.')[0].upper() if dil_host else 'N/A'

    return {
        'sap_system': session.get('sap_system', 'zbq'),
        'sap_systems': cfg.get('sap_systems') or {},
        'au_name': session.get('fullName', 'User'),
        'site': session.get('site', 'Unknown'),
        'source_system': source_sys,
        'source_system_label': cfg.get(source_sys, 'system_label') if source_sys else 'Unknown',
        'target_system': target_sys,
        'target_system_label': cfg.get(target_sys, 'system_label') if target_sys else 'Unknown',
        'source_systems': source_systems,
        'target_systems': target_systems,
        'dil_host': dil_host,
        'dil_short': dil_short,
        'dil_port': dil_cfg.get('db_port', ''),
        'dil_connected': DilEngine.load().engine is not None,
        'max_workers': session.get('max_workers') or _load_db_settings().get('max_workers') or DEFAULT_SETTINGS.get('max_workers', 2),
        'pacing_seconds': session.get('pacing_seconds') if session.get('pacing_seconds') is not None else _load_db_settings().get('pacing_seconds', DEFAULT_SETTINGS.get('pacing_seconds', 0))
    }


def _load_db_settings():
    """Load persisted settings from migration_user_settings table."""
    try:
        with misc_engine.begin() as con:
            rows = con.execute(text(
                "SELECT setting_key, setting_value FROM dbo.migration_user_settings"
            )).fetchall()
        result = {}
        for key, val in rows:
            if key in ('max_workers',):
                result[key] = int(val) if val else DEFAULT_SETTINGS.get(key)
            elif key in ('pacing_seconds',):
                result[key] = float(val) if val else DEFAULT_SETTINGS.get(key)
            else:
                result[key] = val
        return result
    except Exception:
        return {}


def _save_db_setting(key, value, user='system'):
    """Persist a single setting to migration_user_settings (upsert)."""
    try:
        with misc_engine.begin() as con:
            con.execute(text("""
                MERGE dbo.migration_user_settings AS t
                USING (SELECT :key AS setting_key) AS s
                    ON t.setting_key = s.setting_key
                WHEN MATCHED THEN
                    UPDATE SET setting_value = :val, updated_at = GETUTCDATE(), updated_by = :user
                WHEN NOT MATCHED THEN
                    INSERT (setting_key, setting_value, updated_by)
                    VALUES (:key, :val, :user);
            """), {'key': key, 'val': str(value), 'user': user})
    except Exception as e:
        print(f'[SETTINGS_WARN] Could not persist setting {key}: {e}')
