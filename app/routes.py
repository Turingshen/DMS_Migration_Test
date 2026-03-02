"""
Flask routes for document migration workflow.
Implements two-step migration: prepare -> validate -> execute
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, Response
import pandas as pd
import os
import json
from werkzeug.utils import secure_filename
from sqlalchemy import text

from app.prepare import prepare_migration
from app.execute import (
    execute_migration, request_cancel, is_cancel_requested, is_migration_running,
    execute_linking, request_link_cancel, is_linking_running, is_link_cancel_requested,
    run_migration_background, run_linking_background,
    get_background_result, clear_background_result
)
from app.process import (
    read_sap_system, write_sap_system,
    DEFAULT_SOURCE_SYSTEM, DEFAULT_TARGET_SYSTEM,
    get_systems_by_type
)
from app_config import Config, MiscEngine

cfg = Config.load()
migrate_bp = Blueprint('app', __name__)


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
    # If both systems use Basic Auth, no OAuth login is required
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

misc_db = MiscEngine.load()
misc_engine = misc_db.engine

UPLOAD_FOLDER = 'userdata/migration_uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def df_to_json_safe(df):
    """Convert DataFrame to JSON-safe list of dicts, handling NaN/NaT properly.
    
    Standard pd.to_dict('records') can leave NaN values that break JSON serialization.
    This function ensures all NaN/NaT/None values are converted to Python None.
    """
    import math
    
    def safe_value(val):
        """Convert a value to JSON-safe format."""
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
    # Ensure sap_system is set (use default if not present)
    if 'sap_system' not in session:
        # Try to get first available SAP system as default
        sap_systems = cfg.get('sap_systems') or {}
        if sap_systems:
            session['sap_system'] = next(iter(sap_systems.keys()))
        else:
            session['sap_system'] = 'zbq'  # fallback default
    
    # Source/target system from session (with defaults)
    source_sys = session.get('source_system', DEFAULT_SOURCE_SYSTEM)
    target_sys = session.get('target_system', DEFAULT_TARGET_SYSTEM)
    source_systems, target_systems = get_systems_by_type()
    
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
        'max_workers': session.get('max_workers') or _load_db_settings().get('max_workers') or DEFAULT_SETTINGS.get('max_workers', 2),
        'pacing_seconds': session.get('pacing_seconds') if session.get('pacing_seconds') is not None else _load_db_settings().get('pacing_seconds', DEFAULT_SETTINGS.get('pacing_seconds', 0))
    }


# Default settings - can be overridden via /settings
# pacing_seconds=0 means dynamic pacing based on file size (5-45s)
DEFAULT_SETTINGS = {
    'max_workers': 2,
    'pacing_seconds': 0  # 0 = dynamic pacing (recommended)
}


def _load_db_settings():
    """Load persisted settings from migration_user_settings table.
    Returns a dict of setting_key -> setting_value (typed)."""
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


@migrate_bp.route('/settings/json', methods=['GET'])
def settings_json():
    """Return current settings as JSON.  Priority: session > DB > defaults."""
    db_settings = _load_db_settings()
    current_settings = {
        'max_workers': session.get('max_workers') or db_settings.get('max_workers') or DEFAULT_SETTINGS['max_workers'],
        'pacing_seconds': session.get('pacing_seconds') if session.get('pacing_seconds') is not None else db_settings.get('pacing_seconds', DEFAULT_SETTINGS['pacing_seconds']),
        'source_system': session.get('source_system', DEFAULT_SOURCE_SYSTEM),
        'target_system': session.get('target_system', DEFAULT_TARGET_SYSTEM)
    }
    return jsonify(current_settings)


@migrate_bp.route('/switch_system', methods=['POST'])
def switch_system():
    """Switch source or target SAP system."""
    try:
        data = request.get_json()
        source_systems, target_systems = get_systems_by_type()
        all_systems = {**source_systems, **target_systems}
        
        changed = {}
        
        if 'source_system' in data:
            sys_id = data['source_system']
            if sys_id not in source_systems:
                return jsonify({'success': False, 'error': f'{sys_id} is not a valid source (R3) system'}), 400
            session['source_system'] = sys_id
            changed['source_system'] = sys_id
            changed['source_system_label'] = source_systems[sys_id]
        
        if 'target_system' in data:
            sys_id = data['target_system']
            if sys_id not in target_systems:
                return jsonify({'success': False, 'error': f'{sys_id} is not a valid target (S4) system'}), 400
            session['target_system'] = sys_id
            changed['target_system'] = sys_id
            changed['target_system_label'] = target_systems[sys_id]
        
        if not changed:
            return jsonify({'success': False, 'error': 'Provide source_system or target_system'}), 400
        
        return jsonify({'success': True, **changed})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page for migration configuration."""
    if request.method == 'GET':
        # Get current settings: session > DB > defaults
        db_settings = _load_db_settings()
        current_settings = {
            'max_workers': session.get('max_workers') or db_settings.get('max_workers') or DEFAULT_SETTINGS['max_workers'],
            'pacing_seconds': session.get('pacing_seconds') if session.get('pacing_seconds') is not None else db_settings.get('pacing_seconds', DEFAULT_SETTINGS['pacing_seconds'])
        }
        return render_template('settings.html', settings=current_settings, **get_template_context())
    
    # POST - save settings
    try:
        data = request.get_json()
        max_workers = int(data.get('max_workers', DEFAULT_SETTINGS['max_workers']))
        pacing_seconds = float(data.get('pacing_seconds', DEFAULT_SETTINGS['pacing_seconds']))
        
        # Validate
        if max_workers < 1 or max_workers > 50:
            return jsonify({'success': False, 'error': 'Max Workers must be between 1 and 50'}), 400
        if pacing_seconds < 0 or pacing_seconds > 60:
            return jsonify({'success': False, 'error': 'Pacing must be between 0 and 60 seconds'}), 400
        
        # Save to session AND database
        session['max_workers'] = max_workers
        session['pacing_seconds'] = pacing_seconds
        current_user = session.get('fullName', 'system')
        _save_db_setting('max_workers', max_workers, current_user)
        _save_db_setting('pacing_seconds', pacing_seconds, current_user)
        
        return jsonify({'success': True, 'max_workers': max_workers, 'pacing_seconds': pacing_seconds})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/pacing_stats', methods=['GET'])
def pacing_stats():
    """Get historical pacing statistics for optimization."""
    try:
        from app.execute import get_historical_pacing_stats
        stats = get_historical_pacing_stats()
        # Return stats directly for frontend consumption
        return jsonify(stats)
    except Exception as e:
        return jsonify({'has_data': False, 'error': str(e)}), 500


# ─── SAP Credentials (Basic Auth for ZV systems) ─────────────────────────────

@migrate_bp.route('/credentials', methods=['GET'])
def get_credentials_list():
    """List all SAP systems and their credential status."""
    try:
        from app.credentials import list_all_sap_systems, get_credential_info
        systems = list_all_sap_systems()
        result = []
        for sys_info in systems:
            sid = sys_info['system_id']
            info = get_credential_info(sid)
            entry = {
                'system_id': sid,
                'system_label': sys_info['system_label'],
                'system_type': sys_info['system_type'],
                'auth_type': sys_info['auth_type'],
                'has_credentials': info is not None,
                'username': info['username'] if info else None,
                'updated_at': info['updated_at'] if info else None,
                'updated_by': info['updated_by'] if info else None,
            }
            result.append(entry)
        return jsonify({'success': True, 'systems': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/credentials', methods=['POST'])
def save_credentials():
    """Save encrypted credentials for any SAP system."""
    try:
        from app.credentials import save_credentials as _save, list_all_sap_systems
        data = request.get_json()
        system_id = data.get('system_id', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not system_id or not username or not password:
            return jsonify({'success': False, 'error': 'system_id, username and password are required'}), 400

        # Verify system exists in config
        known_ids = [s['system_id'] for s in list_all_sap_systems()]
        if system_id not in known_ids:
            return jsonify({'success': False, 'error': f'{system_id} is not a known SAP system'}), 400

        updated_by = session.get('fullName', session.get('preferred_username', 'unknown'))
        _save(system_id, username, password, updated_by)

        return jsonify({'success': True, 'message': f'Credentials for {system_id} saved'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/credentials/<system_id>', methods=['DELETE'])
def delete_credentials(system_id):
    """Delete credentials for a system."""
    try:
        from app.credentials import delete_credentials as _delete
        deleted = _delete(system_id)
        if deleted:
            return jsonify({'success': True, 'message': f'Credentials for {system_id} deleted'})
        else:
            return jsonify({'success': False, 'error': f'No credentials found for {system_id}'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/credentials/test/<system_id>', methods=['POST'])
def test_credentials(system_id):
    """Test credentials by attempting a CSRF token fetch against the ZV system."""
    try:
        from app.credentials import get_credentials, list_basic_auth_systems
        import requests as req_lib

        if system_id not in list_basic_auth_systems():
            return jsonify({'success': False, 'error': f'{system_id} is not a Basic Auth system'}), 400

        creds = get_credentials(system_id)
        if not creds:
            return jsonify({'success': False, 'error': 'No credentials stored for this system'}), 404

        # Try fetching a CSRF token with Basic Auth
        base_url = cfg.get(system_id, 'api_list', 'document', 'base_url')
        verify_ssl = cfg.get(system_id, 'verify_ssl') if 'verify_ssl' in cfg.config_env.get(system_id, {}) else True

        resp = req_lib.get(
            base_url,
            auth=(creds['username'], creds['password']),
            headers={'X-CSRF-Token': 'Fetch', 'Accept': 'application/json'},
            verify=verify_ssl,
            timeout=15
        )
        if resp.status_code == 200:
            csrf = resp.headers.get('x-csrf-token', '')
            return jsonify({
                'success': True,
                'message': f'Connection successful (HTTP {resp.status_code})',
                'csrf_token_received': bool(csrf)
            })
        else:
            return jsonify({
                'success': False,
                'error': f'HTTP {resp.status_code} {resp.reason}'
            }), 200  # return 200 so frontend gets the JSON
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── SAP System Management (DB + YAML merge) ─────────────────────────────────

@migrate_bp.route('/sap-systems', methods=['GET'])
def get_sap_systems():
    """Get all SAP systems (merged: YAML defaults + DB overrides)."""
    try:
        from app_config import SapSystemManager
        mgr = SapSystemManager()
        merged = mgr.get_merged_systems()
        # Convert to list for JSON, mask API keys for display
        systems_list = []
        for sid, sys_data in merged.items():
            entry = dict(sys_data)
            # Mask API key (show first 8 chars + ***)
            raw_key = entry.get('api_key', '')
            entry['api_key_masked'] = (raw_key[:8] + '***') if len(raw_key) > 8 else raw_key
            entry['api_key'] = raw_key  # full key for editing
            # Convert apis dict to list
            entry['apis'] = list(entry.get('apis', {}).values())
            systems_list.append(entry)
        return jsonify({'success': True, 'systems': systems_list})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/sap-systems', methods=['POST'])
def save_sap_system():
    """Create or update a SAP system (saved to DB)."""
    try:
        from app_config import SapSystemManager
        data = request.get_json()
        system_id = (data.get('system_id') or '').strip().lower()
        system_label = (data.get('system_label') or '').strip()
        system_type = (data.get('system_type') or '').strip().upper()
        host = (data.get('host') or '').strip()
        auth_type = (data.get('auth_type') or 'oauth').strip().lower()
        api_key = (data.get('api_key') or '').strip()
        verify_ssl = data.get('verify_ssl', True)

        if not system_id or not system_label or system_type not in ('R3', 'S4'):
            return jsonify({'success': False, 'error': 'system_id, system_label und system_type (R3/S4) sind erforderlich'}), 400

        updated_by = session.get('fullName', session.get('preferred_username', 'system'))
        mgr = SapSystemManager()
        mgr.save_system(system_id, system_label, system_type, host, auth_type, api_key, verify_ssl, updated_by)

        # Also save APIs if provided
        apis = data.get('apis', [])
        for api in apis:
            api_name = (api.get('api_name') or '').strip()
            base_url = (api.get('base_url') or '').strip()
            api_label = (api.get('api_label') or api_name).strip()
            if api_name and base_url:
                mgr.save_api(system_id, api_name, base_url, api_label)

        # Refresh in-memory config
        mgr.update_config_env()

        return jsonify({'success': True, 'message': f'System {system_id} gespeichert'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/sap-systems/<system_id>', methods=['DELETE'])
def delete_sap_system(system_id):
    """Soft-delete a SAP system (only DB entries, YAML remains untouched)."""
    try:
        from app_config import SapSystemManager
        mgr = SapSystemManager()
        deleted = mgr.delete_system(system_id)
        if deleted:
            mgr.update_config_env()
            return jsonify({'success': True, 'message': f'System {system_id} deaktiviert'})
        else:
            return jsonify({'success': False, 'error': f'{system_id} ist kein DB-Eintrag (nur YAML-Systeme können nicht gelöscht werden)'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/sap-systems/<system_id>/apis', methods=['POST'])
def save_sap_api(system_id):
    """Add or update an API for a SAP system."""
    try:
        from app_config import SapSystemManager
        data = request.get_json()
        api_name = (data.get('api_name') or '').strip()
        base_url = (data.get('base_url') or '').strip()
        api_label = (data.get('api_label') or api_name).strip()

        if not api_name or not base_url:
            return jsonify({'success': False, 'error': 'api_name und base_url sind erforderlich'}), 400

        mgr = SapSystemManager()
        mgr.save_api(system_id, api_name, base_url, api_label)
        mgr.update_config_env()

        return jsonify({'success': True, 'message': f'API {api_name} für {system_id} gespeichert'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/sap-systems/<system_id>/apis/<api_name>', methods=['DELETE'])
def delete_sap_api(system_id, api_name):
    """Soft-delete an API from a SAP system."""
    try:
        from app_config import SapSystemManager
        mgr = SapSystemManager()
        mgr.delete_api(system_id, api_name)
        mgr.update_config_env()
        return jsonify({'success': True, 'message': f'API {api_name} von {system_id} deaktiviert'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/')
def index():
    """Main migration dashboard - shows batches and status."""
    return render_template('index.html', **get_template_context())


@migrate_bp.route('/wave-overview')
def wave_overview():
    """Wave overview page - Kanban view of migration waves and their progress."""
    return render_template('wave_overview.html', **get_template_context())


@migrate_bp.route('/batches', methods=['GET'])
def get_batches():
    """Get list of all migration batches."""
    try:
        # Get batch info with actual record counts from staging table
        query = """
            SELECT 
                b.batch_id,
                b.created_at,
                b.created_by,
                b.source_file,
                b.description,
                b.notes,
                b.wave,
                b.migration_phase,
                b.estimated_duration_h,
                ISNULL(b.task_qual_load, 0) as task_qual_load,
                ISNULL(b.task_qual_link, 0) as task_qual_link,
                ISNULL(b.task_prod_load, 0) as task_prod_load,
                ISNULL(b.task_prod_link, 0) as task_prod_link,
                b.task_qual_load_start, b.task_qual_load_dur,
                b.task_qual_link_start, b.task_qual_link_dur,
                b.task_prod_load_start, b.task_prod_load_dur,
                b.task_prod_link_start, b.task_prod_link_dur,
                COALESCE(s.total_count, b.total_records) as total_records,
                b.approved_records,
                COALESCE(s.executed_count, b.executed_records) as executed_records,
                COALESCE(s.success_count, b.successful_records) as successful_records,
                COALESCE(s.failed_count, b.failed_records) as failed_records,
                b.status,
                COALESCE(s.link_pending, 0) as link_pending,
                COALESCE(s.link_linked, 0) as link_linked,
                COALESCE(s.link_exists, 0) as link_exists,
                COALESCE(s.link_failed, 0) as link_failed,
                COALESCE(s.link_total, 0) as link_total
            FROM dbo.migration_batch b
            LEFT JOIN (
                SELECT 
                    batch_id,
                    COUNT(*) as total_count,
                    SUM(CASE WHEN execution_status IN ('success', 'failed', 'partial') THEN 1 ELSE 0 END) as executed_count,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN ISNULL(link_status, 'pending') = 'pending' AND execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1 ELSE 0 END) as link_pending,
                    SUM(CASE WHEN link_status = 'linked' THEN 1 ELSE 0 END) as link_linked,
                    SUM(CASE WHEN link_status = 'link_exists' THEN 1 ELSE 0 END) as link_exists,
                    SUM(CASE WHEN link_status = 'link_failed' THEN 1 ELSE 0 END) as link_failed,
                    SUM(CASE WHEN ISNULL(link_status, 'pending') IN ('linked', 'link_exists', 'link_failed', 'pending') AND execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1 ELSE 0 END) as link_total
                FROM dbo.migration_staging
                GROUP BY batch_id
            ) s ON b.batch_id = s.batch_id
            ORDER BY b.created_at DESC
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        # Replace NaN/NaT with None for JSON serialization
        df = df.where(pd.notnull(df), None)
        # Extra safety: replace any remaining NaN/inf values
        import numpy as np
        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
        # Convert date columns to string for JSON
        for col in ['task_qual_load_start','task_qual_link_start','task_prod_load_start','task_prod_link_start']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: str(x)[:10] if x is not None and pd.notnull(x) else None)
        batches = df.to_dict(orient='records')
        return jsonify({'success': True, 'batches': batches})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch_statistics', methods=['GET'])
def get_batch_statistics():
    """Get statistics for a specific batch."""
    try:
        batch_id = request.args.get('batch_id')
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        query = """
            SELECT 
                batch_id,
                total_records,
                executed_records,
                successful_records,
                failed_records,
                notes,
                execution_stats
            FROM dbo.migration_batch
            WHERE batch_id = :batch_id
        """
        
        with misc_engine.begin() as con:
            result = con.execute(text(query), {'batch_id': batch_id}).fetchone()
        
        if not result:
            return jsonify({'success': False, 'error': 'Batch not found'}), 404
        
        # Parse execution_stats as JSON for statistics (fall back to notes for legacy data)
        import json
        statistics = {}
        stats_source = result.execution_stats if hasattr(result, 'execution_stats') and result.execution_stats else result.notes
        if stats_source:
            try:
                statistics = json.loads(stats_source)
            except json.JSONDecodeError:
                pass
        
        # Add fallback values if no statistics available
        if not statistics:
            statistics = {
                'batch_duration_seconds': 0,
                'batch_duration_formatted': '-',
                'total_documents': result.executed_records or 0,
                'total_files': 0,
                'total_bytes': 0,
                'total_mb': 0,
                'avg_time_per_document_seconds': 0,
                'avg_time_per_mb_seconds': 0,
                'throughput_mb_per_minute': 0,
                'workers': '-',
                'pacing_seconds': '-',
                'message': 'Statistics not available for this batch (executed before statistics feature)'
            }
        
        return jsonify({'success': True, 'statistics': statistics})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/download_template', methods=['GET'])
def download_template():
    """Download the Excel template for migration data upload."""
    import os
    from flask import send_file
    
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration_template.xlsx')
    
    if os.path.exists(template_path):
        return send_file(
            template_path,
            as_attachment=True,
            download_name='migration_template.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        return jsonify({'success': False, 'error': 'Template file not found'}), 404


@migrate_bp.route('/prepare', methods=['GET', 'POST'])
def prepare():
    """Step 1: Prepare migration data."""
    if request.method == 'GET':
        return render_template('prepare.html', **get_template_context())
    
    try:
        # Check if file upload or database query
        use_file = request.form.get('use_file', 'false') == 'true'
        
        # Get batch metadata
        wave = request.form.get('wave', '').strip() or None
        description = request.form.get('description', '').strip()[:40] or None
        notes = request.form.get('notes', '').strip() or None
        
        if use_file:
            # Handle file upload
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'No file uploaded'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'}), 400
            
            if not allowed_file(file.filename):
                return jsonify({'success': False, 'error': 'Invalid file type. Use Excel or CSV.'}), 400
            
            # Save uploaded file
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # Prepare migration from file
            # Pass session snapshot so prepare can call source API for descriptions
            snap = dict(session)
            result = prepare_migration(filepath, wave=wave, description=description, notes=notes, session_snapshot=snap)
        else:
            # Prepare migration from database query
            custom_query = request.form.get('custom_query', '').strip()
            query_source = request.form.get('query_source', 'dil')  # 'dil' or 'datastore'
            snap = dict(session)
            result = prepare_migration(custom_query=custom_query if custom_query else None, query_source=query_source, wave=wave, description=description, notes=notes, session_snapshot=snap)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>', methods=['PUT'])
def update_batch(batch_id):
    """Update batch description, notes and wave."""
    try:
        data = request.get_json()
        description = data.get('description', '').strip()[:40] if data.get('description') else None
        notes = data.get('notes', '').strip() if data.get('notes') else None
        wave = data.get('wave', '').strip() if data.get('wave') else None
        estimated_duration_h = data.get('estimated_duration_h')
        if estimated_duration_h is not None:
            try:
                estimated_duration_h = float(estimated_duration_h) if estimated_duration_h != '' else None
            except (ValueError, TypeError):
                estimated_duration_h = None

        task_qual_load = 1 if data.get('task_qual_load') else 0
        task_qual_link = 1 if data.get('task_qual_link') else 0
        task_prod_load = 1 if data.get('task_prod_load') else 0
        task_prod_link = 1 if data.get('task_prod_link') else 0

        # Per-task start dates and durations
        task_qual_load_start = data.get('task_qual_load_start') or None
        task_qual_load_dur = int(data['task_qual_load_dur']) if data.get('task_qual_load_dur') else None
        task_qual_link_start = data.get('task_qual_link_start') or None
        task_qual_link_dur = int(data['task_qual_link_dur']) if data.get('task_qual_link_dur') else None
        task_prod_load_start = data.get('task_prod_load_start') or None
        task_prod_load_dur = int(data['task_prod_load_dur']) if data.get('task_prod_load_dur') else None
        task_prod_link_start = data.get('task_prod_link_start') or None
        task_prod_link_dur = int(data['task_prod_link_dur']) if data.get('task_prod_link_dur') else None
        
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_batch
                SET description = :description,
                    notes = :notes,
                    wave = :wave,
                    estimated_duration_h = :estimated_duration_h,
                    task_qual_load = :task_qual_load,
                    task_qual_link = :task_qual_link,
                    task_prod_load = :task_prod_load,
                    task_prod_link = :task_prod_link,
                    task_qual_load_start = :tqls, task_qual_load_dur = :tqld,
                    task_qual_link_start = :tkls, task_qual_link_dur = :tkld,
                    task_prod_load_start = :tpls, task_prod_load_dur = :tpld,
                    task_prod_link_start = :tpks, task_prod_link_dur = :tpkd
                WHERE batch_id = :batch_id
            """), {'description': description, 'notes': notes, 'wave': wave,
                   'estimated_duration_h': estimated_duration_h,
                   'task_qual_load': task_qual_load, 'task_qual_link': task_qual_link,
                   'task_prod_load': task_prod_load, 'task_prod_link': task_prod_link,
                   'tqls': task_qual_load_start, 'tqld': task_qual_load_dur,
                   'tkls': task_qual_link_start, 'tkld': task_qual_link_dur,
                   'tpls': task_prod_load_start, 'tpld': task_prod_load_dur,
                   'tpks': task_prod_link_start, 'tpkd': task_prod_link_dur,
                   'batch_id': batch_id})
        
        return jsonify({'success': True, 'message': 'Batch updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/estimate-duration', methods=['POST'])
def estimate_batch_duration(batch_id):
    """Auto-calculate estimated duration based on file count and total size."""
    try:
        with misc_engine.begin() as con:
            result = con.execute(text("""
                SELECT 
                    COUNT(*) as doc_count,
                    COALESCE(SUM(CAST(file_size_bytes AS BIGINT)), 0) as total_bytes
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
            """), {'batch_id': batch_id}).fetchone()

            doc_count = result[0] or 0
            total_bytes = result[1] or 0
            total_gb = total_bytes / (1024 * 1024 * 1024)

            # Estimation: ~100 docs/hour API throughput + ~2 GB/hour upload speed
            time_by_docs = doc_count / 100.0
            time_by_size = total_gb / 2.0
            estimated_h = round(max(time_by_docs, time_by_size, 0.5), 1)

            con.execute(text("""
                UPDATE dbo.migration_batch
                SET estimated_duration_h = :dur
                WHERE batch_id = :batch_id
            """), {'dur': estimated_h, 'batch_id': batch_id})

        return jsonify({
            'success': True,
            'estimated_duration_h': estimated_h,
            'doc_count': doc_count,
            'total_gb': round(total_gb, 2)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>', methods=['DELETE'])
def delete_batch(batch_id):
    """Delete a batch and all associated records."""
    try:
        # Check if batch exists
        with misc_engine.begin() as con:
            result = con.execute(text("""
                SELECT batch_id, status FROM dbo.migration_batch WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            batch = result.fetchone()
            
            if not batch:
                return jsonify({'success': False, 'error': 'Batch not found'}), 404
            
            # Don't allow deleting executing batches
            if batch[1] == 'executing':
                return jsonify({'success': False, 'error': 'Cannot delete batch while executing'}), 400
            
            # Delete file details first (foreign key constraint)
            r1 = con.execute(text("""
                DELETE FROM dbo.migration_file_details WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete logs
            r2 = con.execute(text("""
                DELETE FROM dbo.migration_logs WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete object mappings
            r3 = con.execute(text("""
                DELETE FROM dbo.migration_object_mapping WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete staging records
            r4 = con.execute(text("""
                DELETE FROM dbo.migration_staging WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete batch
            con.execute(text("""
                DELETE FROM dbo.migration_batch WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
        
        return jsonify({
            'success': True, 
            'message': f'Batch {batch_id} gelöscht',
            'deleted': {
                'file_details': r1.rowcount,
                'logs': r2.rowcount,
                'object_mappings': r3.rowcount,
                'staging_records': r4.rowcount
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/refresh-data-stream', methods=['GET'])
def refresh_batch_data_stream(batch_id):
    """SSE streaming endpoint that combines:
    1. Fetch metadata (LOIO, file sizes) from DIL
    2. Fetch filenames from DIL.DRAW (for file extension workaround)
    3. Apply migration rules
    
    This replaces the separate 'Fetch Metadata' and 'Apply Rules' buttons.
    """
    
    def generate():
        try:
            from app_config import DilEngine
            from app.prepare import load_translations
            
            dil_db = DilEngine.load()
            dil_engine = dil_db.engine
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Loading batch records...'})}\n\n"
            
            # Get all records for this batch
            query = f"""
                SELECT id, source_documentnumber, source_documentpart, source_documenttype, source_documentversion,
                       file_size_bytes, source_loioid, filename
                FROM dbo.migration_staging
                WHERE batch_id = '{batch_id}'
                  AND skip_migration = 0
            """
            
            with misc_engine.begin() as con:
                df = pd.read_sql(query, con)
            
            if len(df) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No records found'})}\n\n"
                return
            
            total_records = int(len(df))
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'init', 'total': total_records, 'percent': 5, 'message': f'Found {total_records} records'})}\n\n"
            
            # ========== PHASE 1: LOIO Lookup ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'loio', 'message': 'Phase 1/4: Looking up LOIO_IDs from DIL...'})}\n\n"
            
            # Build conditions for batch lookup - VECTORIZED approach
            df['dokvr_padded'] = df['source_documentversion'].astype(str).str.zfill(2)
            df['doktl_padded'] = df['source_documentpart'].astype(str).str.zfill(3)
            df['doknr_escaped'] = df['source_documentnumber'].astype(str).str.replace("'", "''", regex=False)
            df['dokar_escaped'] = df['source_documenttype'].astype(str).str.replace("'", "''", regex=False)
            
            conditions = (
                "(DOKNR='" + df['doknr_escaped'] + 
                "' AND DOKAR='" + df['dokar_escaped'] + 
                "' AND DOKVR='" + df['dokvr_padded'] + 
                "' AND DOKTL='" + df['doktl_padded'] + "')"
            ).tolist()
            
            # Keep doknr_escaped/dokar_escaped for reuse in DRAW/DRAT phases (dropped after DRAT)
            
            # Query LOIO_IDs in chunks (1000 per query for fewer round-trips)
            chunk_size = 1000
            all_loios = []
            total_conditions = len(conditions)
            
            for i in range(0, total_conditions, chunk_size):
                chunk = conditions[i:i + chunk_size]
                where_clause = " OR ".join(chunk)
                loio_query = f"""
                    SELECT DOKNR, DOKAR, DOKVR, DOKTL, LO_OBJID
                    FROM DIL.DMS_DOC2LOIO
                    WHERE MANDT = '100'
                    AND ({where_clause})
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(loio_query, con)
                all_loios.append(chunk_df)
                
                if i % 2000 == 0:
                    pct = 5 + int((i / total_conditions) * 15)  # 5-20%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'loio', 'percent': pct, 'message': f'LOIO lookup: {i}/{total_conditions}'})}\n\n"
            
            loio_df = pd.DataFrame()
            if all_loios and not all(len(c) == 0 for c in all_loios):
                loio_df = pd.concat(all_loios, ignore_index=True)
                loio_df.columns = [c.lower() for c in loio_df.columns]
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'loio', 'percent': 20, 'message': f'Found {len(loio_df)} LOIO_IDs'})}\n\n"
            
            # ========== PHASE 2: File Size Lookup ==========
            loio_ids = loio_df['lo_objid'].dropna().unique().tolist() if len(loio_df) > 0 else []
            total_size_records = 0
            size_df = pd.DataFrame()
            
            if loio_ids:
                yield f"data: {json.dumps({'type': 'status', 'phase': 'size', 'message': f'Phase 2/4: Looking up file sizes for {len(loio_ids)} LOIOs...'})}\n\n"
                
                all_sizes = []
                chunk_size = 2000
                total_loios = len(loio_ids)
                
                for i in range(0, total_loios, chunk_size):
                    chunk = loio_ids[i:i + chunk_size]
                    placeholders = ",".join([f"'{lid}'" for lid in chunk])
                    size_query = f"""
                        SELECT LOIO_ID, FILE_SIZE, FILE_NAME
                        FROM DIL.DMS_FILE_SIZE
                        WHERE LOIO_ID IN ({placeholders})
                    """
                    with dil_engine.begin() as con:
                        chunk_df = pd.read_sql(size_query, con)
                    all_sizes.append(chunk_df)
                    
                    if i % 4000 == 0:
                        pct = 20 + int((i / total_loios) * 15)  # 20-35%
                        yield f"data: {json.dumps({'type': 'progress', 'phase': 'size', 'percent': pct, 'message': f'File sizes: {i}/{total_loios}'})}\n\n"
                
                total_size_records = sum(len(c) for c in all_sizes)
                if total_size_records > 0:
                    size_df = pd.concat(all_sizes, ignore_index=True)
                    size_df.columns = [c.lower() for c in size_df.columns]
                    size_df = size_df.sort_values('file_size', ascending=False).drop_duplicates(subset=['loio_id'], keep='first')
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'size', 'percent': 35, 'message': f'Found {total_size_records} file sizes'})}\n\n"
            
            # ========== PHASE 3: Filename Lookup from DRAW ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'draw', 'message': 'Phase 3/4: Looking up filenames from DIL.DRAW...'})}\n\n"
            
            # Build document keys for DRAW lookup - VECTORIZED (no iterrows!)
            draw_conditions = (
                "(doknr = '" + df['doknr_escaped'] +
                "' AND dokar = '" + df['dokar_escaped'] +
                "' AND dokvr = '" + df['dokvr_padded'] +
                "' AND doktl = '" + df['doktl_padded'] + "')"
            ).tolist()
            
            all_filenames = []
            chunk_size = 1000
            total_draw = len(draw_conditions)
            
            for i in range(0, total_draw, chunk_size):
                chunk = draw_conditions[i:i + chunk_size]
                where_clause = " OR ".join(chunk)
                
                draw_query = f"""
                    SELECT doknr, dokar, dokvr, doktl, filep, dokst
                    FROM dil.DRAW
                    WHERE {where_clause}
"""
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(draw_query, con)
                all_filenames.append(chunk_df)
                
                if i % 3000 == 0:
                    pct = 35 + int((i / total_draw) * 15)  # 35-50%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'draw', 'percent': pct, 'message': f'DRAW lookup: {i}/{total_draw}'})}\n\n"
            
            filename_df = pd.DataFrame()
            filenames_found = 0
            if all_filenames:
                filename_df = pd.concat(all_filenames, ignore_index=True)
                filename_df.columns = [c.lower() for c in filename_df.columns]
                # Deduplicate: DRAW can have multiple rows per document
                filename_df = filename_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')
                filenames_found = int(filename_df['filep'].notna().sum())
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'draw', 'percent': 50, 'message': f'Found {filenames_found} filenames from DRAW'})}\n\n"
            
            # ========== PHASE 3b: Description Lookup from DRAT ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'drat', 'message': 'Phase 3b/4: Looking up descriptions from DIL.DRAT...'})}\n\n"
            
            # Reuse vectorized conditions from DRAW (same keys)
            all_descriptions = []
            drat_chunk_size = 1000
            total_drat = len(draw_conditions)
            
            for i in range(0, total_drat, drat_chunk_size):
                chunk = draw_conditions[i:i + drat_chunk_size]
                # Uppercase column names for DRAT (SAP convention)
                where_clause = " OR ".join(c.replace('doknr', 'DOKNR').replace('dokar', 'DOKAR').replace('dokvr', 'DOKVR').replace('doktl', 'DOKTL') for c in chunk)
                drat_query = f"""
                    SELECT DOKNR, DOKAR, DOKVR, DOKTL, LANGU, DKTXT
                    FROM DIL.DRAT
                    WHERE MANDT = '100' AND ({where_clause})
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(drat_query, con)
                all_descriptions.append(chunk_df)
                
                if i % 3000 == 0:
                    pct = 50 + int((i / total_drat) * 5)  # 50-55%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'drat', 'percent': pct, 'message': f'DRAT lookup: {i}/{total_drat}'})}\n\n"
            
            drat_df = pd.DataFrame()
            descriptions_found = 0
            if all_descriptions:
                drat_df = pd.concat(all_descriptions, ignore_index=True)
                drat_df.columns = [c.lower() for c in drat_df.columns]
                # Language priority: E (English) > D (German) > any
                drat_df['_lang_prio'] = drat_df['langu'].map({'E': 0, 'D': 1}).fillna(2).astype(int)
                drat_df = drat_df.sort_values('_lang_prio')
                drat_final = drat_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')[['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt']].copy()
                descriptions_found = int(drat_final['dktxt'].notna().sum())
            else:
                drat_final = pd.DataFrame(columns=['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt'])
            
            # Clean up temp escaped columns (no longer needed)
            df.drop(['doknr_escaped', 'dokar_escaped'], axis=1, inplace=True, errors='ignore')
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'drat', 'percent': 55, 'message': f'Found {descriptions_found} descriptions from DRAT'})}\n\n"
            
            # ========== PHASE 4: Apply Rules ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'rules', 'message': 'Phase 4/4: Applying migration rules...'})}\n\n"
            
            from app.prepare import apply_translations as _apply_translations
            rules = load_translations()
            rules_applied = len(rules)
            
            # Get full records for rule application
            with misc_engine.begin() as con:
                full_df = pd.read_sql(f"""
                    SELECT id, source_documenttype, source_documentnumber, source_documentversion,
                           source_documentpart, source_description, authorization_group,
                           source_dokob, source_objky, filename,
                           target_documenttype, target_documentnumber, target_documentversion,
                           target_documentpart, target_dokob, target_objky,
                           source_document_status, target_document_status
                    FROM dbo.migration_staging
                    WHERE batch_id = '{batch_id}'
                """, con)
            
            # Initialize target columns from source if not set
            if full_df['target_documenttype'].isna().all():
                full_df['target_documenttype'] = full_df['source_documenttype']
            
            # Add alias columns so rules referencing short names work
            # against staging column names (e.g. 'documenttype' -> 'source_documenttype')
            _ALIASES = {
                'documenttype': 'source_documenttype',
                'documentnumber': 'source_documentnumber',
                'documentversion': 'source_documentversion',
                'documentpart': 'source_documentpart',
                'description': 'source_description',
            }
            for alias, real_col in _ALIASES.items():
                if alias not in full_df.columns and real_col in full_df.columns:
                    full_df[alias] = full_df[real_col]
            
            # Apply rules using proper apply_translations which handles conditions
            full_df = _apply_translations(full_df, rules)
            
            # Recompute target_documentnumber based on (possibly changed) target_documenttype
            # VECTORIZED approach: apply sanitize_doknr to all rows at once instead of iterrows
            from app.process import sanitize_doknr as _sanitize_doknr
            INTERNAL_NUMBERING_TYPES = {'IY1', 'IY2'}
            
            if 'target_documentnumber_sanitized' not in full_df.columns:
                full_df['target_documentnumber_sanitized'] = None
            
            # Precompute masks
            target_type_str = full_df['target_documenttype'].fillna('').astype(str).str.strip().str.upper()
            is_internal = target_type_str.isin(INTERNAL_NUMBERING_TYPES)
            
            source_nr_str = full_df['source_documentnumber'].fillna('').astype(str).str.strip()
            has_source_nr = source_nr_str != ''
            is_numeric = source_nr_str.str.isdigit() & has_source_nr
            is_alphanumeric = has_source_nr & ~is_numeric
            
            tgt_nr_str = full_df['target_documentnumber'].fillna('').astype(str).str.strip()
            has_tgt_nr = tgt_nr_str != ''
            
            # Apply sanitize_doknr vectorized via .apply (function has branching logic, not purely vectorizable)
            def _compute_doknr_row(row):
                target_type = str(row.get('target_documenttype') or '').strip().upper()
                current_tgt_nr = row.get('target_documentnumber')
                source_nr = str(row.get('source_documentnumber') or '').strip()
                
                if target_type in INTERNAL_NUMBERING_TYPES:
                    if source_nr and not source_nr.isdigit():
                        sanitized, _ = _sanitize_doknr(source_nr)
                        if sanitized and sanitized.strip():
                            return source_nr[:25], sanitized[:25]
                    return None, None
                elif pd.isna(current_tgt_nr) or str(current_tgt_nr).strip() == '':
                    if source_nr:
                        tgt_nr = source_nr[:25]
                        sanitized, _ = _sanitize_doknr(tgt_nr)
                        if sanitized and sanitized.strip():
                            return tgt_nr, sanitized
                    return None, None
                else:
                    sanitized, _ = _sanitize_doknr(str(current_tgt_nr))
                    if sanitized and sanitized.strip():
                        return current_tgt_nr, sanitized
                    return None, None
            
            doknr_results = full_df.apply(_compute_doknr_row, axis=1, result_type='expand')
            full_df['target_documentnumber'] = doknr_results[0]
            full_df['target_documentnumber_sanitized'] = doknr_results[1]
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'rules', 'percent': 60, 'message': f'Applied {rules_applied} rules'})}\n\n"
            
            # ========== MERGE AND UPDATE ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'update', 'message': 'Merging data and updating database...'})}\n\n"
            
            # Merge LOIO data with file sizes
            if len(loio_df) > 0 and len(size_df) > 0:
                loio_df = loio_df.merge(
                    size_df[['loio_id', 'file_size', 'file_name']],
                    how='left',
                    left_on='lo_objid',
                    right_on='loio_id'
                )
            elif len(loio_df) > 0:
                loio_df['file_size'] = None
                loio_df['file_name'] = None
            
            # Remove duplicates
            if len(loio_df) > 0:
                loio_df = loio_df.sort_values('file_size', ascending=False, na_position='last')
                loio_df = loio_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')
            
            # Prepare merge with staging IDs
            df_merged = df.copy()
            if len(loio_df) > 0:
                df_merged = df.merge(
                    loio_df,
                    how='left',
                    left_on=['source_documentnumber', 'source_documenttype', 'dokvr_padded', 'doktl_padded'],
                    right_on=['doknr', 'dokar', 'dokvr', 'doktl']
                )
                df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            
            # Merge filenames from DRAW
            if len(filename_df) > 0:
                df_merged['_doknr'] = df_merged['source_documentnumber'].astype(str)
                df_merged['_dokar'] = df_merged['source_documenttype'].astype(str)
                df_merged['_dokvr'] = df_merged['source_documentversion'].astype(str).str.zfill(2)
                df_merged['_doktl'] = df_merged['source_documentpart'].astype(str).str.zfill(3)
                
                df_merged = df_merged.merge(
                    filename_df[['doknr', 'dokar', 'dokvr', 'doktl', 'filep', 'dokst']],
                    how='left',
                    left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
                    right_on=['doknr', 'dokar', 'dokvr', 'doktl'],
                    suffixes=('', '_draw')
                )
                df_merged.drop(columns=['_doknr', '_dokar', '_dokvr', '_doktl',
                                        'doknr_draw', 'dokar_draw', 'dokvr_draw', 'doktl_draw'],
                               errors='ignore', inplace=True)
                df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            
            # Merge descriptions from DRAT
            if len(drat_final) > 0:
                df_merged['_doknr'] = df_merged['source_documentnumber'].astype(str)
                df_merged['_dokar'] = df_merged['source_documenttype'].astype(str)
                df_merged['_dokvr'] = df_merged['source_documentversion'].astype(str).str.zfill(2)
                df_merged['_doktl'] = df_merged['source_documentpart'].astype(str).str.zfill(3)
                
                df_merged = df_merged.merge(
                    drat_final[['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt']],
                    how='left',
                    left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
                    right_on=['doknr', 'dokar', 'dokvr', 'doktl'],
                    suffixes=('', '_drat')
                )
                df_merged.drop(columns=['_doknr', '_dokar', '_dokvr', '_doktl',
                                        'doknr_drat', 'dokar_drat', 'dokvr_drat', 'doktl_drat'],
                               errors='ignore', inplace=True)
                df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 70, 'message': 'Preparing bulk update...'})}\n\n"
            
            # Prepare update data
            update_data = []
            for _, row in df_merged.iterrows():
                staging_id = int(row['id'])
                source_loioid = str(row.get('lo_objid', '')) if pd.notna(row.get('lo_objid')) else None
                file_size_bytes = int(row.get('file_size')) if pd.notna(row.get('file_size')) else None
                
                # Filename: prefer DRAW.filep if available
                draw_filename = str(row.get('filep', '')) if pd.notna(row.get('filep')) else None
                dil_filename = str(row.get('file_name', '')) if pd.notna(row.get('file_name')) else None
                filename = draw_filename or dil_filename
                
                # Document status from DRAW.DOKST
                dokst = str(row.get('dokst', '')) if pd.notna(row.get('dokst')) else None
                
                # Description from DRAT.DKTXT
                drat_desc = str(row.get('dktxt', '')) if pd.notna(row.get('dktxt')) else None
                if drat_desc and drat_desc.strip():
                    drat_desc = drat_desc.strip()[:200]
                else:
                    drat_desc = None
                
                update_data.append({
                    'staging_id': staging_id,
                    'source_loioid': source_loioid,
                    'file_size_bytes': file_size_bytes,
                    'filename': filename,
                    'source_document_status': dokst if dokst else None,
                    'source_description': drat_desc
                })
            
            # Also get rule updates
            rule_updates = {}
            for _, row in full_df.iterrows():
                rule_updates[int(row['id'])] = {
                    'target_documenttype': row.get('target_documenttype'),
                    'target_documentnumber': row.get('target_documentnumber'),
                    'target_documentnumber_sanitized': row.get('target_documentnumber_sanitized'),
                    'target_documentversion': row.get('target_documentversion'),
                    'target_documentpart': row.get('target_documentpart'),
                    'authorization_group': row.get('authorization_group'),
                    'target_dokob': row.get('target_dokob'),
                    'target_objky': row.get('target_objky'),
                    'target_document_status': row.get('target_document_status')
                }
            
            # Bulk update using temp table
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 75, 'message': 'Bulk updating via temp table...'})}\n\n"
            
            updated_count = 0
            with misc_engine.begin() as con:
                # Create temp table for metadata
                con.execute(text("""
                    IF OBJECT_ID('tempdb..#refresh_update') IS NOT NULL DROP TABLE #refresh_update;
                    CREATE TABLE #refresh_update (
                        staging_id INT PRIMARY KEY,
                        source_loioid NVARCHAR(100),
                        file_size_bytes BIGINT,
                        filename NVARCHAR(500),
                        source_document_status NVARCHAR(20),
                        source_description NVARCHAR(200)
                    );
                """))
                
                # Insert metadata updates
                update_df = pd.DataFrame(update_data)
                update_df = update_df[update_df['source_loioid'].notna() | update_df['filename'].notna() | update_df['source_document_status'].notna() | update_df['source_description'].notna()]
                
                if len(update_df) > 0:
                    chunk_size = 900
                    for i in range(0, len(update_df), chunk_size):
                        chunk = update_df.iloc[i:i + chunk_size]
                        chunk.to_sql('#refresh_update', con, if_exists='append', index=False, method='multi')
                        
                        if i % 5000 == 0:
                            pct = 75 + int((i / len(update_df)) * 10)  # 75-85%
                            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': pct, 'message': f'Temp table: {i}/{len(update_df)}'})}\n\n"
                    
                    # Update metadata
                    result = con.execute(text("""
                        UPDATE s
                        SET s.source_loioid = COALESCE(t.source_loioid, s.source_loioid),
                            s.file_size_bytes = COALESCE(t.file_size_bytes, s.file_size_bytes),
                            s.filename = CASE WHEN t.filename IS NOT NULL AND t.filename != 'None' AND t.filename != '' 
                                              THEN t.filename ELSE s.filename END,
                            s.source_document_status = COALESCE(t.source_document_status, s.source_document_status),
                            s.source_description = CASE WHEN t.source_description IS NOT NULL AND t.source_description != ''
                                                        AND (s.source_description IS NULL OR s.source_description = '')
                                                        THEN t.source_description ELSE s.source_description END
                        FROM dbo.migration_staging s
                        INNER JOIN #refresh_update t ON s.id = t.staging_id
                    """))
                    updated_count = result.rowcount
                
                con.execute(text("DROP TABLE #refresh_update"))
                
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 85, 'message': f'Updated {updated_count} metadata records'})}\n\n"
                
                # Update rule results via BULK temp table (not row-by-row!)
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 86, 'message': 'Bulk updating rule results...'})}\n\n"
                
                con.execute(text("""
                    IF OBJECT_ID('tempdb..#rules_update') IS NOT NULL DROP TABLE #rules_update;
                    CREATE TABLE #rules_update (
                        staging_id INT PRIMARY KEY,
                        target_documenttype NVARCHAR(10),
                        target_documentnumber NVARCHAR(50),
                        target_documentnumber_sanitized NVARCHAR(50),
                        target_documentversion NVARCHAR(10),
                        target_documentpart NVARCHAR(10),
                        authorization_group NVARCHAR(10),
                        target_dokob NVARCHAR(20),
                        target_objky NVARCHAR(100),
                        target_document_status NVARCHAR(10)
                    );
                """))
                
                # Build DataFrame from rule_updates dict
                rules_rows = []
                for staging_id, vals in rule_updates.items():
                    rules_rows.append({
                        'staging_id': staging_id,
                        'target_documenttype': vals.get('target_documenttype'),
                        'target_documentnumber': vals.get('target_documentnumber'),
                        'target_documentnumber_sanitized': vals.get('target_documentnumber_sanitized'),
                        'target_documentversion': vals.get('target_documentversion'),
                        'target_documentpart': vals.get('target_documentpart'),
                        'authorization_group': vals.get('authorization_group'),
                        'target_dokob': vals.get('target_dokob'),
                        'target_objky': vals.get('target_objky'),
                        'target_document_status': vals.get('target_document_status')
                    })
                
                rules_df = pd.DataFrame(rules_rows)
                # Replace NaN with None for SQL compatibility
                rules_df = rules_df.where(pd.notnull(rules_df), None)
                
                # Bulk insert into temp table
                rules_chunk_size = 900
                for i in range(0, len(rules_df), rules_chunk_size):
                    chunk = rules_df.iloc[i:i + rules_chunk_size]
                    chunk.to_sql('#rules_update', con, if_exists='append', index=False, method='multi')
                    
                    if i % 5000 == 0 and i > 0:
                        pct = 86 + int((i / len(rules_df)) * 4)  # 86-90%
                        yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': pct, 'message': f'Rules temp table: {i}/{len(rules_df)}'})}\n\n"
                
                # Single UPDATE JOIN — replaces 100k individual UPDATEs!
                con.execute(text("""
                    UPDATE s
                    SET s.target_documenttype = t.target_documenttype,
                        s.target_documentnumber = t.target_documentnumber,
                        s.target_documentnumber_sanitized = t.target_documentnumber_sanitized,
                        s.target_documentversion = t.target_documentversion,
                        s.target_documentpart = t.target_documentpart,
                        s.authorization_group = t.authorization_group,
                        s.target_dokob = t.target_dokob,
                        s.target_objky = t.target_objky,
                        s.target_document_status = t.target_document_status
                    FROM dbo.migration_staging s
                    INNER JOIN #rules_update t ON s.id = t.staging_id
                """))
                
                con.execute(text("DROP TABLE #rules_update"))
                
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 90, 'message': 'Rule updates complete'})}\n\n"
            
            # ========== PHASE 5: Object-Link Counts ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'link_counts', 'message': 'Phase 5/5: Calculating object link counts...'})}\n\n"
            
            import json as _json
            
            # Load staging records with their object links
            with misc_engine.begin() as con:
                link_rows = con.execute(text("""
                    SELECT id, source_object_links, source_dokob, source_objky
                    FROM dbo.migration_staging
                    WHERE batch_id = :batch_id AND skip_migration = 0
                """), {'batch_id': batch_id}).fetchall()
            
            link_updates = []  # list of {staging_id, src, excl, tgt}
            for row in link_rows:
                rec_id = row[0]
                links_json = row[1]
                primary_dokob = row[2]
                primary_objky = row[3]
                
                # Parse links
                links = []
                if links_json:
                    try:
                        links = _json.loads(links_json)
                    except (ValueError, TypeError):
                        pass
                if not links and primary_dokob and primary_objky:
                    links = [{'dokob': primary_dokob, 'objky': primary_objky}]
                
                src_count = len(links)
                
                link_updates.append({
                    'staging_id': rec_id,
                    'source_link_count': src_count,
                    'excluded_link_count': 0,
                    'target_link_count': src_count
                })
            
            # Bulk update via temp table
            if link_updates:
                link_df = pd.DataFrame(link_updates)
                with misc_engine.begin() as con:
                    con.execute(text("""
                        IF OBJECT_ID('tempdb..#link_counts') IS NOT NULL DROP TABLE #link_counts;
                        CREATE TABLE #link_counts (
                            staging_id INT PRIMARY KEY,
                            source_link_count INT,
                            excluded_link_count INT,
                            target_link_count INT
                        );
                    """))
                    
                    for i in range(0, len(link_df), 900):
                        chunk = link_df.iloc[i:i + 900]
                        chunk.to_sql('#link_counts', con, if_exists='append', index=False, method='multi')
                    
                    con.execute(text("""
                        UPDATE s
                        SET s.source_link_count = t.source_link_count,
                            s.excluded_link_count = t.excluded_link_count,
                            s.target_link_count = t.target_link_count
                        FROM dbo.migration_staging s
                        INNER JOIN #link_counts t ON s.id = t.staging_id
                    """))
                    con.execute(text("DROP TABLE #link_counts"))
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'link_counts', 'percent': 95, 'message': f'Link counts updated: {len(link_updates)} records'})}\n\n"
            
            # Calculate statistics
            total_bytes = size_df['file_size'].dropna().sum() if len(size_df) > 0 else 0
            max_bytes = size_df['file_size'].dropna().max() if len(size_df) > 0 else 0
            
            # Convert numpy types to native Python types for JSON serialization
            yield f"data: {json.dumps({'type': 'complete', 'message': 'Refresh complete', 'metadata_updated': int(updated_count), 'rules_applied': int(rules_applied), 'filenames_found': int(filenames_found), 'descriptions_found': int(descriptions_found), 'total_records': int(total_records), 'total_size_mb': round(float(total_bytes) / (1024 * 1024), 1) if total_bytes else 0, 'max_file_mb': round(float(max_bytes) / (1024 * 1024), 1) if max_bytes else 0, 'links_excluded': int(links_excluded_total), 'records_zero_links': int(records_zero_links)})}\n\n"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


@migrate_bp.route('/batch/<batch_id>/progress', methods=['GET'])
def get_batch_progress(batch_id):
    """Get execution progress for a batch (for live polling during execution)."""
    try:
        query = f"""
            SELECT 
                batch_id,
                status,
                migration_phase,
                total_records,
                executed_records,
                successful_records,
                failed_records,
                created_at,
                last_execution_started_at
            FROM dbo.migration_batch
            WHERE batch_id = '{batch_id}'
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        if len(df) == 0:
            return jsonify({'success': False, 'error': 'Batch not found'}), 404
        
        row = df.iloc[0]
        total = row['total_records'] or 0
        executed = row['executed_records'] or 0
        success = row['successful_records'] or 0
        failed = row['failed_records'] or 0
        
        # Get partial count from staging table (container created but upload incomplete)
        # Scope to current execution run to avoid stale counts from previous runs
        partial = 0
        try:
            exec_start = row.get('last_execution_started_at')
            with misc_engine.begin() as con:
                if exec_start and row['status'] == 'executing':
                    # During execution: only count partials from THIS run
                    partial_result = con.execute(text(f"""
                        SELECT COUNT(*) FROM dbo.migration_staging
                        WHERE batch_id = '{batch_id}' 
                            AND execution_status = 'partial'
                            AND execution_started_at >= :exec_start
                    """), {'exec_start': exec_start}).fetchone()
                else:
                    # Not executing: show all partials (batch overview)
                    partial_result = con.execute(text(f"""
                        SELECT COUNT(*) FROM dbo.migration_staging
                        WHERE batch_id = '{batch_id}' AND execution_status = 'partial'
                    """)).fetchone()
                partial = partial_result[0] if partial_result else 0
        except:
            pass
        
        # Calculate progress percentage
        progress_pct = (executed / total * 100) if total > 0 else 0
        
        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'status': row['status'],
            'migration_phase': row.get('migration_phase', 'upload'),
            'total': int(total),
            'executed': int(executed),
            'successful': int(success),
            'failed': int(failed),
            'partial': int(partial),
            'remaining': int(total - executed),
            'progress_pct': round(progress_pct, 1),
            'is_running': is_migration_running(batch_id)[0] or row['status'] == 'executing',
            'is_linking': is_linking_running(batch_id)[0] or row['status'] == 'linking',
            'background_result': get_background_result(batch_id) if not is_migration_running(batch_id)[0] and row['status'] != 'executing' else None
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/preview-stats', methods=['GET'])
def get_batch_preview_stats(batch_id):
    """Get aggregated statistics for batch preview (computed on DB level for performance).
    Returns counts and file size buckets without loading all records.
    Buckets only count non-success records (pending/failed/partial) for runtime estimation."""
    try:
        # Aggregate stats in single SQL query - much faster than loading all records
        # Use CAST to BIGINT for file_size_bytes to avoid integer overflow on large batches
        # Buckets only count non-success records for accurate runtime estimation
        query = text("""
            SELECT 
                COUNT(*) as total_records,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 1 THEN 1 ELSE 0 END) as skipped_count,
                SUM(CASE WHEN execution_status = 'success' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN execution_status = 'pending' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as pending_count,
                SUM(CASE WHEN execution_status = 'failed' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as failed_count,
                SUM(CASE WHEN execution_status = 'partial' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as partial_count,
                -- Ablage counts (only non-skipped)
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND ISNULL(ablage, 'KPRO') = 'KPRO' THEN 1 ELSE 0 END) as kpro_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND ablage = 'DB' THEN 1 ELSE 0 END) as db_count,
                -- Buckets count only non-skipped, non-success records for runtime estimation
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND (file_size_bytes IS NULL OR file_size_bytes = 0) THEN 1 ELSE 0 END) as unknown_size_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 0 AND file_size_bytes <= 1048576 THEN 1 ELSE 0 END) as tiny_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 1048576 AND file_size_bytes <= 10485760 THEN 1 ELSE 0 END) as small_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 10485760 AND file_size_bytes <= 52428800 THEN 1 ELSE 0 END) as medium_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 52428800 THEN 1 ELSE 0 END) as large_count,
                -- Total size only for non-skipped, non-success records
                SUM(CAST(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 0 THEN file_size_bytes ELSE 0 END AS BIGINT)) as total_size_bytes,
                MAX(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' THEN file_size_bytes ELSE 0 END) as max_file_size
            FROM dbo.migration_staging
            WHERE batch_id = :batch_id
        """)
        
        with misc_engine.begin() as con:
            result = con.execute(query, {'batch_id': batch_id}).fetchone()
        
        if not result or result.total_records == 0:
            return jsonify({'success': False, 'error': 'Batch not found or empty'}), 404
        
        skipped_count = result.skipped_count or 0
        total_active = (result.total_records or 0) - skipped_count
        
        # Use actual pending count from DB (records with execution_status = 'pending')
        actual_pending_count = result.pending_count or 0
        # Also calculate "to execute" count (all non-success, non-skipped)
        to_execute_count = total_active - (result.success_count or 0)
        
        return jsonify({
            'success': True,
            'stats': {
                'total': result.total_records or 0,
                'total_active': total_active,
                'skipped': skipped_count,
                'success': result.success_count or 0,
                'pending': actual_pending_count,  # Real pending from DB
                'to_execute': to_execute_count,   # All non-success, non-skipped
                'failed': result.failed_count or 0,
                'partial': result.partial_count or 0,
                'kpro': result.kpro_count or 0,
                'db': result.db_count or 0,
                'buckets': {
                    'tiny': result.tiny_count or 0,
                    'small': result.small_count or 0,
                    'medium': result.medium_count or 0,
                    'large': result.large_count or 0,
                    'unknown': result.unknown_size_count or 0
                },
                'total_size_bytes': int(result.total_size_bytes or 0),
                'max_file_size': int(result.max_file_size or 0)
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/error-categories', methods=['GET'])
def get_batch_error_categories(batch_id):
    """Get distinct error categories for a batch with counts.
    
    Reads directly from migration_staging.error_category column.
    """
    try:
        categories_dict = {}
        
        with misc_engine.connect() as con:
            # Get categories directly from staging table (covers all cases)
            result = con.execute(text("""
                SELECT error_category, COUNT(*) as cnt
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
                    AND execution_status IN ('failed', 'partial')
                    AND error_category IS NOT NULL
                GROUP BY error_category
                ORDER BY cnt DESC
            """), {'batch_id': batch_id}).fetchall()
            
            for row in result:
                categories_dict[row[0]] = row[1]
        
        # Convert to list sorted by count
        categories = [{'category': cat, 'count': cnt} for cat, cnt in categories_dict.items()]
        categories.sort(key=lambda x: -x['count'])
        
        return jsonify({
            'success': True,
            'categories': categories
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/records', methods=['GET'])
def get_batch_records(batch_id):
    """Get staging records for a batch with optional pagination for large datasets.
    
    Query params:
        page: Page number (1-based), default=1
        per_page: Records per page, default=5000 (0 = all records)
        status_filter: Filter by execution_status (optional)
        error_category: Filter by error category (applied in Python after dynamic classification)
        search: Full-text search across DOKNR, OBJKY, description (server-side, searches ALL records)
        ablage_filter: Filter by ablage value ('KPRO' or 'DB')
    """
    try:
        # Parse pagination params
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 5000, type=int)  # Default 5000 for large batches
        status_filter = request.args.get('status_filter', '')
        error_category_filter = request.args.get('error_category', '')
        search_term = request.args.get('search', '').strip()
        ablage_filter = request.args.get('ablage_filter', '').strip()
        
        # Build WHERE clause with ms. prefix for JOIN
        where_conditions = [f"ms.batch_id = '{batch_id}'"]
        if status_filter:
            where_conditions.append(f"ms.execution_status = '{status_filter}'")
        # If filtering by error_category, filter by failed/partial status AND the category in staging table
        if error_category_filter:
            where_conditions.append("ms.execution_status IN ('failed', 'partial')")
            where_conditions.append(f"ms.error_category = '{error_category_filter}'")
        # Server-side text search: search across DOKNR, OBJKY, description, filename, target_documentnumber
        if search_term:
            safe_search = search_term.replace("'", "''")
            where_conditions.append(f"(ms.source_documentnumber LIKE '%{safe_search}%' OR ms.source_objky LIKE '%{safe_search}%' OR ms.source_description LIKE '%{safe_search}%' OR ms.filename LIKE '%{safe_search}%' OR ms.target_documentnumber LIKE '%{safe_search}%' OR ms.source_dokob LIKE '%{safe_search}%')")
        # Ablage filter (KPRO or DB)
        if ablage_filter in ('KPRO', 'DB'):
            where_conditions.append(f"ISNULL(ms.ablage, 'KPRO') = '{ablage_filter}'")
        where_clause = " AND ".join(where_conditions)
        
        # First get total count (with all filters applied)
        count_conditions = [f"ms.batch_id = '{batch_id}'"]
        if status_filter:
            count_conditions.append(f"ms.execution_status = '{status_filter}'")
        if error_category_filter:
            count_conditions.append("ms.execution_status IN ('failed', 'partial')")
            count_conditions.append(f"ms.error_category = '{error_category_filter}'")
        if search_term:
            safe_search = search_term.replace("'", "''")
            count_conditions.append(f"(ms.source_documentnumber LIKE '%{safe_search}%' OR ms.source_objky LIKE '%{safe_search}%' OR ms.source_description LIKE '%{safe_search}%' OR ms.filename LIKE '%{safe_search}%' OR ms.target_documentnumber LIKE '%{safe_search}%' OR ms.source_dokob LIKE '%{safe_search}%')")
        if ablage_filter in ('KPRO', 'DB'):
            count_conditions.append(f"ISNULL(ms.ablage, 'KPRO') = '{ablage_filter}'")
        count_query = "SELECT COUNT(*) FROM dbo.migration_staging ms WHERE " + " AND ".join(count_conditions)
        
        # Build paginated query using OFFSET/FETCH for SQL Server
        # Use ms.error_category from staging table (set during execution)
        if per_page > 0:
            offset = (page - 1) * per_page
            query = f"""
                SELECT 
                    ms.id,
                    ms.source_documentnumber,
                    ms.source_documentpart,
                    ms.source_documenttype,
                    ms.source_documentversion,
                    ms.source_loioid,
                    ms.source_description,
                    ms.source_dokob,
                    ms.source_objky,
                    ms.target_documentnumber,
                    ms.target_documentnumber_sanitized,
                    ms.target_documentpart,
                    ms.target_documenttype,
                    ms.target_documentversion,
                    ms.filename,
                    ms.file_size_bytes,
                    ms.mime_type,
                    ms.authorization_group,
                    ms.validation_status,
                    ms.validation_notes,
                    ms.execution_status,
                    ms.execution_error,
                    ms.user_approved,
                    ms.skip_migration,
                    ms.error_category,
                    ms.target_dokob,
                    ms.target_objky,
                    ms.link_status,
                    ms.link_error,
                    ms.container_created,
                    ms.source_document_status,
                    ms.target_document_status,
                    ms.ablage,
                    ms.source_object_links,
                    ms.source_file_count,
                    ms.target_file_count,
                    ms.source_link_count,
                    ms.excluded_link_count,
                    ms.target_link_count
                FROM dbo.migration_staging ms
                WHERE {where_clause}
                ORDER BY ms.source_documenttype, ms.source_documentnumber, ms.source_documentversion, ms.source_documentpart, ms.source_dokob
                OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY
            """
        else:
            # per_page=0 means get all records (for backwards compatibility)
            query = f"""
                SELECT 
                    ms.id,
                    ms.source_documentnumber,
                    ms.source_documentpart,
                    ms.source_documenttype,
                    ms.source_documentversion,
                    ms.source_loioid,
                    ms.source_description,
                    ms.source_dokob,
                    ms.source_objky,
                    ms.target_documentnumber,
                    ms.target_documentnumber_sanitized,
                    ms.target_documentpart,
                    ms.target_documenttype,
                    ms.target_documentversion,
                    ms.filename,
                    ms.file_size_bytes,
                    ms.mime_type,
                    ms.authorization_group,
                    ms.validation_status,
                    ms.validation_notes,
                    ms.execution_status,
                    ms.execution_error,
                    ms.user_approved,
                    ms.skip_migration,
                    ms.error_category,
                    ms.target_dokob,
                    ms.target_objky,
                    ms.link_status,
                    ms.link_error,
                    ms.container_created,
                    ms.source_document_status,
                    ms.target_document_status,
                    ms.ablage,
                    ms.source_object_links,
                    ms.source_file_count,
                    ms.target_file_count,
                    ms.source_link_count,
                    ms.excluded_link_count,
                    ms.target_link_count
                FROM dbo.migration_staging ms
                WHERE {where_clause}
                ORDER BY ms.source_documenttype, ms.source_documentnumber, ms.source_documentversion, ms.source_documentpart, ms.source_dokob
            """
        
        with misc_engine.begin() as con:
            total_count = con.execute(text(count_query)).scalar()
            df = pd.read_sql(query, con)
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        records = df_to_json_safe(df)
        
        # If error_category is NULL but execution_error exists, classify dynamically
        from app.process import _classify_error
        for record in records:
            if not record.get('error_category') and record.get('execution_error'):
                try:
                    error_str = record['execution_error']
                    if isinstance(error_str, str):
                        import json
                        try:
                            error_info = json.loads(error_str)
                        except:
                            # Legacy format like "Error during getinfo: unexpexted Error"
                            error_info = {'status_code': error_str, 'reason': error_str}
                    else:
                        error_info = error_str
                    record['error_category'] = _classify_error(error_info)
                except:
                    record['error_category'] = 'UNKNOWN'
        
        # Apply error_category filter in Python (after dynamic classification)
        if error_category_filter:
            records = [r for r in records if r.get('error_category') == error_category_filter]
        
        # Calculate pagination info
        filtered_count = len(records) if error_category_filter else total_count
        total_pages = (filtered_count + per_page - 1) // per_page if per_page > 0 else 1
        
        return jsonify({
            'success': True, 
            'records': records,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': filtered_count,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/preview', methods=['GET'])
def preview_view():
    """Show preview interface for a batch."""
    batch_id = request.args.get('batch_id')
    if not batch_id:
        return "Batch ID required", 400
    
    context = get_template_context()
    context['batch_id'] = batch_id
    return render_template('preview.html', **context)





@migrate_bp.route('/execute', methods=['POST'])
def execute():
    """Step 2: Execute migration for approved records (background).
    
    Starts execution in a background thread and returns immediately.
    Frontend polls /batch/<id>/progress for live status updates.
    """
    try:
        if not _is_authenticated():
            return jsonify({
                'success': False, 
                'error': 'Not logged in. Please login to SAP first.',
                'login_required': True
            }), 401
        
        data = request.get_json()
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        # Check if already running
        is_running, reason = is_migration_running(batch_id)
        if is_running:
            return jsonify({
                'success': False,
                'error': f'Migration already in progress: {reason}',
                'already_running': True
            })
        
        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_migration_background(batch_id, snapshot)
        
        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': 'Migration gestartet. Fortschritt wird automatisch aktualisiert.'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/execute_selected', methods=['POST'])
def execute_selected():
    """Execute migration for selected records only (background)."""
    try:
        if not _is_authenticated():
            return jsonify({
                'success': False, 
                'error': 'Not logged in. Please login to SAP first.',
                'login_required': True
            }), 401
        
        data = request.get_json()
        batch_id = data.get('batch_id')
        record_ids = data.get('record_ids', [])
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        if not record_ids:
            return jsonify({'success': False, 'error': 'No records selected'}), 400
        
        # Check if already running
        is_running, reason = is_migration_running(batch_id)
        if is_running:
            return jsonify({
                'success': False,
                'error': f'Migration already in progress: {reason}',
                'already_running': True
            })
        
        # Reset selected records to pending for execution
        record_ids_str = ','.join(str(id) for id in record_ids)
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND id IN ({record_ids_str})
                    AND skip_migration = 0
            """))
            
            # Also immediately reset the batch counters so the frontend
            # sees correct values from the very first poll (no race condition
            # with the background thread which resets them later again).
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET status = 'executing',
                    migration_phase = 'upload',
                    total_records = {len(record_ids)},
                    executed_records = 0,
                    successful_records = 0,
                    failed_records = 0,
                    last_execution_started_at = GETUTCDATE()
                WHERE batch_id = '{batch_id}'
            """))
        
        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_migration_background(batch_id, snapshot, record_ids=record_ids)
        
        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': f'Migration für {len(record_ids)} Datensätze gestartet.'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/cancel', methods=['POST'])
def cancel_migration(batch_id):
    """Cancel a running migration for the given batch."""
    try:
        # Check if migration is actually running
        if not is_migration_running(batch_id):
            return jsonify({
                'success': False, 
                'error': 'No migration is currently running for this batch'
            }), 400
        
        # Request cancellation
        request_cancel(batch_id)
        
        return jsonify({
            'success': True,
            'message': f'Cancellation requested for batch {batch_id}. Migration will stop after current operations complete.',
            'cancel_requested': True
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# Phase 2: Object Link Creation (Verlinkung) Routes
# ============================================================================

@migrate_bp.route('/execute_linking', methods=['POST'])
def execute_link_all():
    """Phase 2: Execute object linking for all eligible records (background)."""
    try:
        if not _is_authenticated():
            return jsonify({
                'success': False,
                'error': 'Nicht angemeldet. Bitte zuerst bei SAP anmelden.',
                'login_required': True
            }), 401

        data = request.get_json()
        batch_id = data.get('batch_id')

        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID erforderlich'}), 400

        # Check if already running
        running, msg = is_linking_running(batch_id)
        if running:
            return jsonify({'success': False, 'error': msg, 'already_running': True})

        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_linking_background(batch_id, snapshot)

        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': 'Verlinkung gestartet. Fortschritt wird automatisch aktualisiert.'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/execute_linking_selected', methods=['POST'])
def execute_link_selected():
    """Phase 2: Execute object linking for selected records only (background)."""
    try:
        if not _is_authenticated():
            return jsonify({
                'success': False,
                'error': 'Nicht angemeldet. Bitte zuerst bei SAP anmelden.',
                'login_required': True
            }), 401

        data = request.get_json()
        batch_id = data.get('batch_id')
        record_ids = data.get('record_ids', [])

        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID erforderlich'}), 400

        if not record_ids:
            return jsonify({'success': False, 'error': 'Keine Datensätze ausgewählt'}), 400

        # Check if already running
        running, msg = is_linking_running(batch_id)
        if running:
            return jsonify({'success': False, 'error': msg, 'already_running': True})

        # Reset link_status for selected records so they can be re-linked
        record_ids_str = ','.join(str(rid) for rid in record_ids)
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET link_status = 'pending',
                    link_error = NULL,
                    link_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND id IN ({record_ids_str})
                    AND execution_status IN ('success', 'partial')
                    AND ISNULL(container_created, 0) = 1
            """))

        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_linking_background(batch_id, snapshot, record_ids=record_ids)

        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': f'Verlinkung für {len(record_ids)} Datensätze gestartet.'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/cancel-linking', methods=['POST'])
def cancel_linking(batch_id):
    """Cancel a running linking operation for the given batch."""
    try:
        running, msg = is_linking_running(batch_id)
        if not running:
            return jsonify({
                'success': False,
                'error': 'Keine Verlinkung läuft für diesen Batch'
            }), 400

        request_link_cancel(batch_id)

        return jsonify({
            'success': True,
            'message': f'Abbruch angefordert für Batch {batch_id}. Verlinkung wird nach Abschluss laufender Operationen beendet.',
            'cancel_requested': True
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/link-progress', methods=['GET'])
def get_link_progress(batch_id):
    """Get linking progress for a batch (for live polling during Phase 2)."""
    try:
        with misc_engine.begin() as con:
            # Get batch phase info
            batch_row = con.execute(text(f"""
                SELECT migration_phase, status
                FROM dbo.migration_batch
                WHERE batch_id = '{batch_id}'
            """)).fetchone()

            if not batch_row:
                return jsonify({'success': False, 'error': 'Batch nicht gefunden'}), 404

            # Get link status counts
            link_stats = con.execute(text(f"""
                SELECT
                    SUM(CASE WHEN link_status = 'linked' THEN 1 ELSE 0 END) as linked,
                    SUM(CASE WHEN link_status = 'link_exists' THEN 1 ELSE 0 END) as link_exists,
                    SUM(CASE WHEN link_status = 'link_failed' THEN 1 ELSE 0 END) as link_failed,
                    SUM(CASE WHEN link_status = 'linking' THEN 1 ELSE 0 END) as linking_now,
                    SUM(CASE WHEN ISNULL(link_status, 'pending') = 'pending' AND execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1 ELSE 0 END) as link_pending,
                    SUM(CASE WHEN execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1 ELSE 0 END) as link_total
                FROM dbo.migration_staging
                WHERE batch_id = '{batch_id}'
            """)).fetchone()

        linked = link_stats[0] or 0
        link_exists = link_stats[1] or 0
        link_failed = link_stats[2] or 0
        linking_now = link_stats[3] or 0
        link_pending = link_stats[4] or 0
        link_total = link_stats[5] or 0

        completed = linked + link_exists + link_failed
        progress_pct = (completed / link_total * 100) if link_total > 0 else 0

        is_linking = is_linking_running(batch_id)[0]
        result_data = {
            'success': True,
            'batch_id': batch_id,
            'migration_phase': batch_row.migration_phase,
            'status': batch_row.status,
            'link_total': int(link_total),
            'linked': int(linked),
            'link_exists': int(link_exists),
            'link_failed': int(link_failed),
            'linking_now': int(linking_now),
            'link_pending': int(link_pending),
            'completed': int(completed),
            'progress_pct': round(progress_pct, 1),
            'is_linking': is_linking
        }

        # Include background result when linking is done
        if not is_linking:
            bg_result = get_background_result(f"{batch_id}_linking")
            if bg_result:
                result_data['background_result'] = bg_result

        return jsonify(result_data)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/status', methods=['GET'])
def get_batch_status(batch_id):
    """Get current status of a batch including whether migration is running or cancelled."""
    try:
        with misc_engine.begin() as con:
            batch = con.execute(text("""
                SELECT status, total_records, executed_records, successful_records, failed_records
                FROM dbo.migration_batch
                WHERE batch_id = :batch_id
            """), {'batch_id': batch_id}).fetchone()
        
        if not batch:
            return jsonify({'success': False, 'error': 'Batch not found'}), 404
        
        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'status': batch[0],
            'total_records': batch[1] or 0,
            'executed_records': batch[2] or 0,
            'successful_records': batch[3] or 0,
            'failed_records': batch[4] or 0,
            'is_running': is_migration_running(batch_id),
            'cancel_requested': is_cancel_requested(batch_id)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/debug/metadata', methods=['GET'])
def debug_metadata():
    """Temporary debug endpoint: fetch ZHL API $metadata using session bearer token."""
    import requests as _req, os as _os
    token = session.get('bearer_token')
    if not token:
        return jsonify(error='No bearer_token in session – please login first'), 401
    base_url = cfg.get('zhl', 'api_list', 'document', 'base_url')
    api_key  = cfg.get('zhl', 'X-API-Key')
    url = f"{base_url}/$metadata"
    headers = {"Authorization": f"Bearer {token}", "x-api-key": api_key}
    resp = _req.get(url, headers=headers, timeout=30)
    # Save to file so it can be inspected
    out_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), '_metadata_response.xml')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    return resp.text, resp.status_code, {'Content-Type': resp.headers.get('Content-Type', 'text/xml')}


@migrate_bp.route('/debug/document/<docnr>', methods=['GET'])
def debug_document(docnr):
    """Temporary debug endpoint: fetch raw API response for a document."""
    import requests as _req, json as _json
    token = session.get('bearer_token')
    if not token:
        return jsonify(error='No bearer_token in session – please login first'), 401
    sap_system = request.args.get('system', 'zhl')
    dokar = request.args.get('dokar', 'ZLH')
    dokvr = request.args.get('dokvr', '00')
    doktl = request.args.get('doktl', '000')
    base_url = cfg.get(sap_system, 'api_list', 'document', 'base_url')
    api_key  = cfg.get(sap_system, 'X-API-Key')
    # Strip leading zeros for API call (same as process.py)
    clean_nr = docnr.lstrip('0') or '0'
    args = f"Documentnumber='{clean_nr}',Documentpart='{doktl}',Documenttype='{dokar}',Documentversion='{dokvr}'"
    url = f"{base_url}/DocumentSet({args})?$expand=DocumentfilesSet,ObjectlinksSet,DESCRIPTIONSSet&$format=json"
    headers = {"Authorization": f"Bearer {token}", "x-api-key": api_key, "Accept": "application/json"}
    resp = _req.get(url, headers=headers, timeout=30)
    try:
        data = resp.json()
        return _json.dumps(data, indent=2, ensure_ascii=False), resp.status_code, {'Content-Type': 'application/json'}
    except Exception:
        return resp.text, resp.status_code


@migrate_bp.route('/api/funcloc/search', methods=['GET'])
def funcloc_search():
    """Proxy: query S4 FunctionalLocation API via session bearer token."""
    import requests as _req
    sap_system = request.args.get('system', 'zbq')
    query_filter = request.args.get('filter', '')
    top = request.args.get('top', '20')
    entity_set = request.args.get('entity', 'FunctionalLocation')  # from OpenAPI spec

    sys_cfg = cfg.config_env.get(sap_system, {})
    auth_type = sys_cfg.get('auth_type', 'oauth')

    if auth_type == 'basic':
        from app.credentials import get_credentials
        creds = get_credentials(sap_system)
        if not creds:
            return jsonify(success=False, error=f'No credentials for {sap_system}'), 401
        auth_tuple = (creds['username'], creds['password'])
        verify_ssl = sys_cfg.get('verify_ssl', True)
        headers = {'Accept': 'application/json'}
        auth_kw = dict(auth=auth_tuple, verify=verify_ssl)
    else:
        token = session.get('bearer_token')
        if not token:
            return jsonify(success=False, error='Not logged in'), 401
        api_key = cfg.get(sap_system, 'X-API-Key')
        headers = {
            'Authorization': f'Bearer {token}',
            'X-API-Key': api_key,
            'Accept': 'application/json'
        }
        auth_kw = {}

    funcloc_cfg = cfg.get(sap_system, 'api_list', 'funcloc')
    if not funcloc_cfg:
        return jsonify(success=False, error=f'No funcloc API configured for {sap_system}'), 400
    base_url = funcloc_cfg['base_url']

    # Build OData URL
    params = f"$top={top}&$select=FunctionalLocation,FunctionalLocationLabelName,MaintenancePlant,FunctionalLocationName"
    if query_filter:
        params += f"&$filter={query_filter}"
    url = f"{base_url}/{entity_set}?{params}"

    try:
        resp = _req.get(url, headers=headers, timeout=30, **auth_kw)
        if resp.status_code != 200:
            return jsonify(success=False, error=f'API returned {resp.status_code}', detail=resp.text[:1000], url=url), resp.status_code
        data = resp.json()
        results = data.get('d', {}).get('results', [])
        return jsonify(success=True, results=results, count=len(results), url=url)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


@migrate_bp.route('/api/funcloc/service-doc', methods=['GET'])
def funcloc_service_doc():
    """Proxy: fetch OData service document to discover entity sets."""
    import requests as _req
    sap_system = request.args.get('system', 'zbq')
    sys_cfg = cfg.config_env.get(sap_system, {})
    auth_type = sys_cfg.get('auth_type', 'oauth')

    if auth_type == 'basic':
        from app.credentials import get_credentials
        creds = get_credentials(sap_system)
        if not creds:
            return jsonify(success=False, error=f'No credentials for {sap_system}'), 401
        auth_tuple = (creds['username'], creds['password'])
        verify_ssl = sys_cfg.get('verify_ssl', True)
        headers = {'Accept': 'application/json'}
        auth_kw = dict(auth=auth_tuple, verify=verify_ssl)
    else:
        token = session.get('bearer_token')
        if not token:
            return jsonify(success=False, error='Not logged in'), 401
        api_key = cfg.get(sap_system, 'X-API-Key')
        headers = {
            'Authorization': f'Bearer {token}',
            'X-API-Key': api_key,
            'Accept': 'application/json'
        }
        auth_kw = {}

    funcloc_cfg = cfg.get(sap_system, 'api_list', 'funcloc')
    if not funcloc_cfg:
        return jsonify(success=False, error=f'No funcloc API configured for {sap_system}'), 400
    base_url = funcloc_cfg['base_url']

    try:
        resp = _req.get(base_url, headers=headers, timeout=30, **auth_kw)
        return resp.text, resp.status_code, {'Content-Type': resp.headers.get('Content-Type', 'application/json')}
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


@migrate_bp.route('/api/funcloc/metadata', methods=['GET'])
def funcloc_metadata():
    """Proxy: fetch $metadata from FunctionalLocation API to inspect fields."""
    import requests as _req
    sap_system = request.args.get('system', 'zbq')
    sys_cfg = cfg.config_env.get(sap_system, {})
    auth_type = sys_cfg.get('auth_type', 'oauth')

    if auth_type == 'basic':
        from app.credentials import get_credentials
        creds = get_credentials(sap_system)
        if not creds:
            return jsonify(success=False, error=f'No credentials for {sap_system}'), 401
        auth_tuple = (creds['username'], creds['password'])
        verify_ssl = sys_cfg.get('verify_ssl', True)
        headers = {'Accept': 'application/xml'}
        auth_kw = dict(auth=auth_tuple, verify=verify_ssl)
    else:
        token = session.get('bearer_token')
        if not token:
            return jsonify(success=False, error='Not logged in'), 401
        api_key = cfg.get(sap_system, 'X-API-Key')
        headers = {
            'Authorization': f'Bearer {token}',
            'X-API-Key': api_key,
            'Accept': 'application/xml'
        }
        auth_kw = {}

    funcloc_cfg = cfg.get(sap_system, 'api_list', 'funcloc')
    if not funcloc_cfg:
        return jsonify(success=False, error=f'No funcloc API configured for {sap_system}'), 400
    base_url = funcloc_cfg['base_url']
    url = f"{base_url}/$metadata"

    try:
        resp = _req.get(url, headers=headers, timeout=30, **auth_kw)
        return resp.text, resp.status_code, {'Content-Type': resp.headers.get('Content-Type', 'text/xml')}
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


@migrate_bp.route('/keep-alive', methods=['GET'])
def keep_alive():
    """Lightweight session keep-alive endpoint.
    
    Called periodically by the browser to prevent session expiry
    during long-running migrations or when returning from sleep mode.
    Also returns info about any currently executing batch so the UI
    can auto-reconnect to running migrations.
    """
    try:
        session.modified = True  # Touch session to reset expiry timer

        # Check for any currently executing batch
        executing_batch = None
        try:
            with misc_engine.begin() as con:
                row = con.execute(text("""
                    SELECT TOP 1 batch_id, total_records, executed_records,
                           successful_records, failed_records, migration_phase
                    FROM dbo.migration_batch
                    WHERE status = 'executing'
                    ORDER BY created_at DESC
                """)).fetchone()
                if row:
                    executing_batch = {
                        'batch_id': row[0],
                        'total': row[1] or 0,
                        'executed': row[2] or 0,
                        'successful': row[3] or 0,
                        'failed': row[4] or 0,
                        'phase': row[5] or 'upload'
                    }
        except Exception:
            pass

        return jsonify({
            'success': True,
            'session_active': True,
            'executing_batch': executing_batch
        })
    except Exception as e:
        return jsonify({'success': False, 'session_active': False, 'error': str(e)}), 500


@migrate_bp.route('/token-status', methods=['GET'])
def get_token_status():
    """Get current authentication token status for monitoring."""
    try:
        from authentication import get_token_remaining_seconds, is_token_expiring_soon
        
        bearer_token = session.get('bearer_token')
        has_refresh_token = bool(session.get('refresh_token'))
        remaining_seconds = get_token_remaining_seconds()
        
        if not bearer_token:
            return jsonify({
                'success': True,
                'logged_in': False,
                'message': 'Not logged in'
            })
        
        return jsonify({
            'success': True,
            'logged_in': True,
            'has_refresh_token': has_refresh_token,
            'token_remaining_seconds': remaining_seconds,
            'token_remaining_minutes': remaining_seconds // 60 if remaining_seconds else None,
            'is_expiring_soon': is_token_expiring_soon(300),
            'can_auto_refresh': has_refresh_token,
            'message': f"Token valid for {remaining_seconds // 60}min" if remaining_seconds else "Token expiry unknown"
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/skip_records', methods=['POST'])
def skip_records():
    """Mark records as skipped (excluded from migration)."""
    try:
        data = request.get_json()
        batch_id = data.get('batch_id')
        record_ids = data.get('record_ids', [])
        skip = data.get('skip', True)
        reason = data.get('reason', '')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        if not record_ids:
            return jsonify({'success': False, 'error': 'No record IDs provided'}), 400
        
        # Build the IN clause for record IDs
        ids_str = ','.join(str(int(rid)) for rid in record_ids)
        skip_value = 1 if skip else 0
        
        with misc_engine.begin() as con:
            # Update skip_migration flag
            result = con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET skip_migration = {skip_value},
                    execution_error = CASE 
                        WHEN {skip_value} = 1 THEN 'Skipped: {reason}'
                        ELSE execution_error
                    END
                WHERE batch_id = '{batch_id}'
                    AND id IN ({ids_str})
            """))
            updated_count = result.rowcount
        
        return jsonify({
            'success': True,
            'updated': updated_count,
            'skip': skip,
            'reason': reason
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/error_overview', methods=['GET'])
def get_error_overview():
    """Get overview of all errors grouped by category for dashboard display."""
    try:
        from app.process import get_error_details
        
        with misc_engine.connect() as con:
            # Get error counts grouped by category across all batches
            result = con.execute(text("""
                SELECT 
                    fd.error_category,
                    COUNT(*) as cnt
                FROM dbo.migration_file_details fd
                INNER JOIN dbo.migration_staging ms ON fd.staging_id = ms.id
                WHERE fd.upload_status NOT LIKE 'SUCCESS%'
                    AND ms.execution_status = 'failed'
                    AND ms.skip_migration = 0
                    AND fd.error_category IS NOT NULL
                GROUP BY fd.error_category
                ORDER BY cnt DESC
            """)).fetchall()
            
            errors = []
            total = 0
            for row in result:
                cat, cnt = row
                total += cnt
                errors.append({
                    'category': cat,
                    'count': cnt
                })
        
        return jsonify({
            'success': True,
            'errors': errors,
            'total_errors': total
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/retry_by_category', methods=['POST'])
def retry_by_category():
    """Reset and retry all failed records with a specific error category."""
    try:
        data = request.get_json()
        category = data.get('category')
        
        if not category:
            return jsonify({'success': False, 'error': 'Category required'}), 400
        
        # Get staging IDs with this error category
        with misc_engine.begin() as con:
            # Find staging_ids from file_details with this category
            result = con.execute(text("""
                SELECT DISTINCT fd.staging_id
                FROM dbo.migration_file_details fd
                INNER JOIN dbo.migration_staging ms ON fd.staging_id = ms.id
                WHERE fd.error_category = :category
                    AND ms.execution_status = 'failed'
                    AND ms.skip_migration = 0
            """), {'category': category}).fetchall()
            
            staging_ids = [row[0] for row in result]
            
            if not staging_ids:
                return jsonify({'success': True, 'reset_count': 0, 'message': 'No records to retry'})
            
            ids_str = ','.join(str(id) for id in staging_ids)
            
            # Reset these staging records to pending
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE id IN ({ids_str})
            """))
            
            reset_count = len(staging_ids)
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} records with category {category} reset to pending'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/retry_all_errors', methods=['POST'])
def retry_all_errors():
    """Reset all failed and partial records across all batches."""
    try:
        with misc_engine.begin() as con:
            result = con.execute(text("""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE execution_status IN ('failed', 'partial')
                    AND skip_migration = 0
            """))
            reset_count = result.rowcount
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} failed/partial records reset to pending'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/reset_failed', methods=['POST'])
def reset_failed():
    """Reset all failed AND partial records to pending status (without re-executing).
    
    For partial records: container_created and target_documentnumber are preserved.
    The execution loop will detect container_created=1 and skip already-uploaded files
    via get_successfully_uploaded_files() → SUCCESS_SKIPPED.
    """
    try:
        data = request.get_json()
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        # Reset all failed AND partial records to pending
        # Note: container_created and target_documentnumber are NOT cleared,
        # so partial records will only retry the missing files.
        with misc_engine.begin() as con:
            result = con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND execution_status IN ('failed', 'partial')
                    AND skip_migration = 0
            """))
            reset_count = result.rowcount
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} failed/partial records reset to pending'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/results', methods=['GET'])
def get_results(batch_id):
    """Get execution results for a batch."""
    try:
        query = f"""
            SELECT 
                id,
                source_documentnumber,
                target_documentnumber,
                source_documenttype,
                target_documenttype,
                source_loioid,
                source_description,
                execution_status,
                execution_error,
                execution_started_at,
                execution_completed_at,
                validation_notes,
                validated_by,
                validated_at,
                authorization_group,
                filename,
                file_size_bytes,
                mime_type
            FROM dbo.migration_staging
            WHERE batch_id = '{batch_id}'
                AND execution_status != 'pending'
            ORDER BY source_documenttype, source_documentnumber, source_documentversion, source_documentpart, source_dokob
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        results = df_to_json_safe(df)
        
        # Parse execution_error JSON strings into objects
        for record in results:
            if record.get('execution_error'):
                try:
                    import json
                    record['execution_error'] = json.loads(record['execution_error'])
                except (json.JSONDecodeError, TypeError):
                    pass  # Keep as string if not valid JSON
        
        return jsonify({'success': True, 'results': results})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Translation Management Routes ====================

@migrate_bp.route('/rules')
def migration_rules_page():
    """Migration rules management page (renamed from Translation Rules)."""
    return render_template('translations.html', **get_template_context())


@migrate_bp.route('/rules/list', methods=['GET'])
def list_migration_rules():
    """Get all active migration rules (translation/overwrite)."""
    try:
        # Check if execution_order column exists
        with misc_engine.begin() as con:
            col_check = con.execute(text("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'migration_translations' 
                AND COLUMN_NAME = 'execution_order'
            """)).fetchone()
            
            has_exec_order = col_check[0] > 0 if col_check else False
            
            if has_exec_order:
                query = """
                    SELECT 
                        id,
                        rule_type,
                        source_column,
                        target_column,
                        source_value,
                        target_value,
                        condition_column,
                        condition_value,
                        condition_operator,
                        execution_order,
                        created_at,
                        created_by,
                        active,
                        notes
                    FROM dbo.migration_translations
                    WHERE active = 1
                    ORDER BY execution_order, id
                """
            else:
                query = """
                    SELECT 
                        id,
                        rule_type,
                        source_column,
                        target_column,
                        source_value,
                        target_value,
                        condition_column,
                        condition_value,
                        condition_operator,
                        100 as execution_order,
                        created_at,
                        created_by,
                        active,
                        notes
                    FROM dbo.migration_translations
                    WHERE active = 1
                    ORDER BY id
                """
            
            df = pd.read_sql(query, con)
        
        translations = df.to_dict(orient='records')
        return jsonify({'success': True, 'rules': translations})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/add', methods=['POST'])
def add_migration_rule():
    """Add a new migration rule (translation or overwrite)."""
    try:
        data = request.get_json()
        rule_type = (data.get('rule_type') or 'translation').strip().lower()
        source_column = data.get('source_column', '').strip()
        target_column = data.get('target_column', '').strip()
        source_value = (data.get('source_value') or '').strip()
        target_value = data.get('target_value', '')  # Allow empty string, only check for None
        notes = data.get('notes', '').strip()
        condition_column = (data.get('condition_column') or '').strip()
        condition_value = (data.get('condition_value') or '').strip()
        condition_operator = (data.get('condition_operator') or 'contains').strip().lower()
        
        # Auto-assign execution_order: add at the bottom (max + 10)
        with misc_engine.begin() as con:
            max_order_result = con.execute(text("SELECT ISNULL(MAX(execution_order), 0) FROM dbo.migration_translations")).fetchone()
            execution_order = (max_order_result[0] if max_order_result else 0) + 10
        
        if rule_type not in ('translation', 'overwrite'):
            return jsonify({'success': False, 'error': 'Invalid rule_type'}), 400

        if rule_type == 'translation':
            if not source_column or not target_column or target_value is None:
                return jsonify({'success': False, 'error': 'source_column, target_column and target_value are required'}), 400
        else:  # overwrite
            if not target_column or target_value is None:
                return jsonify({'success': False, 'error': 'target_column and target_value are required for overwrite'}), 400
        
        user_email = session.get('user_email', 'system')
        
        insert_query = text("""
            INSERT INTO dbo.migration_translations 
            (rule_type, source_column, target_column, source_value, target_value, 
             condition_column, condition_value, condition_operator,
             execution_order, created_by, notes)
            VALUES (:rule_type, :source_column, :target_column, :source_value, :target_value,
                    :condition_column, :condition_value, :condition_operator,
                    :execution_order, :created_by, :notes)
        """)
        
        with misc_engine.begin() as con:
            con.execute(insert_query, {
                'rule_type': rule_type,
                'source_column': source_column,
                'target_column': target_column,
                'source_value': source_value,
                'target_value': target_value,
                'condition_column': condition_column or None,
                'condition_value': condition_value or None,
                'condition_operator': condition_operator,
                'execution_order': execution_order,
                'created_by': user_email,
                'notes': notes
            })
        
        return jsonify({'success': True, 'message': 'Migration rule added successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/update', methods=['POST'])
def update_migration_rule(rule_id):
    """Update an existing migration rule."""
    try:
        data = request.get_json()
        source_column = (data.get('source_column') or '').strip()
        target_column = (data.get('target_column') or '').strip()
        target_value = data.get('target_value', '')  # Allow empty string, only check for None
        notes = data.get('notes', '').strip()
        condition_column = (data.get('condition_column') or '').strip()
        condition_value = (data.get('condition_value') or '').strip()
        condition_operator = (data.get('condition_operator') or '').strip()
        execution_order = data.get('execution_order', 100)
        
        if target_value is None:
            return jsonify({'success': False, 'error': 'Target value is required'}), 400
        
        update_query = text("""
            UPDATE dbo.migration_translations
            SET source_column = :source_column,
                target_column = :target_column,
                target_value = :target_value,
                condition_column = :condition_column,
                condition_value = :condition_value,
                condition_operator = :condition_operator,
                execution_order = :execution_order,
                notes = :notes
            WHERE id = :id
        """)
        
        with misc_engine.begin() as con:
            con.execute(update_query, {
                'source_column': source_column or None,
                'target_column': target_column or None,
                'target_value': target_value,
                'condition_column': condition_column or None,
                'condition_value': condition_value or None,
                'condition_operator': condition_operator or None,
                'execution_order': execution_order,
                'notes': notes,
                'id': rule_id
            })
        
        return jsonify({'success': True, 'message': 'Migration rule updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/delete', methods=['POST'])
def delete_migration_rule(rule_id):
    """Delete (deactivate) a migration rule."""
    try:
        delete_query = text("""
            UPDATE dbo.migration_translations
            SET active = 0
            WHERE id = :id
        """)
        
        with misc_engine.begin() as con:
            con.execute(delete_query, {'id': rule_id})
        
        return jsonify({'success': True, 'message': 'Migration rule deleted successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/move_up', methods=['POST'])
def move_rule_up(rule_id):
    """Move a rule up in execution order."""
    try:
        with misc_engine.begin() as con:
            # Get current rule and the one above it
            current = con.execute(text("""
                SELECT id, execution_order FROM dbo.migration_translations
                WHERE id = :id AND active = 1
            """), {'id': rule_id}).fetchone()
            
            if not current:
                return jsonify({'success': False, 'error': 'Rule not found'}), 404
            
            prev = con.execute(text("""
                SELECT TOP 1 id, execution_order FROM dbo.migration_translations
                WHERE active = 1 AND execution_order < :order
                ORDER BY execution_order DESC, id DESC
            """), {'order': current[1]}).fetchone()
            
            if not prev:
                return jsonify({'success': False, 'error': 'Already at top'}), 400
            
            # Swap execution orders
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': prev[1], 'id': current[0]})
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': current[1], 'id': prev[0]})
        
        return jsonify({'success': True, 'message': 'Rule moved up'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/move_down', methods=['POST'])
def move_rule_down(rule_id):
    """Move a rule down in execution order."""
    try:
        with misc_engine.begin() as con:
            # Get current rule and the one below it
            current = con.execute(text("""
                SELECT id, execution_order FROM dbo.migration_translations
                WHERE id = :id AND active = 1
            """), {'id': rule_id}).fetchone()
            
            if not current:
                return jsonify({'success': False, 'error': 'Rule not found'}), 404
            
            next_rule = con.execute(text("""
                SELECT TOP 1 id, execution_order FROM dbo.migration_translations
                WHERE active = 1 AND execution_order > :order
                ORDER BY execution_order ASC, id ASC
            """), {'order': current[1]}).fetchone()
            
            if not next_rule:
                return jsonify({'success': False, 'error': 'Already at bottom'}), 400
            
            # Swap execution orders
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': next_rule[1], 'id': current[0]})
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': current[1], 'id': next_rule[0]})
        
        return jsonify({'success': True, 'message': 'Rule moved down'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@migrate_bp.route('/batch/<batch_id>/logs', methods=['GET'])
def get_batch_logs(batch_id):
    """Get execution logs/results for a specific batch."""
    try:
        print(f"[LOGS] Fetching logs for batch: {batch_id}")
        
        query = f"""
            SELECT 
                id,
                source_documentnumber,
                target_documentnumber,
                source_documenttype,
                target_documenttype,
                source_description,
                authorization_group,
                execution_status,
                execution_error,
                execution_started_at,
                execution_completed_at,
                validation_status,
                user_approved,
                skip_migration,
                validated_at,
                validated_by,
                validation_notes,
                filename,
                mime_type
            FROM dbo.migration_staging
            WHERE batch_id = '{batch_id}'
            ORDER BY execution_completed_at DESC, id DESC
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        print(f"[LOGS] Found {len(df)} records for batch {batch_id}")
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        logs = df_to_json_safe(df)
        
        # Parse execution_error JSON if present
        for log in logs:
            if log.get('execution_error'):
                try:
                    log['execution_error'] = json.loads(log['execution_error'])
                except:
                    pass
        
        return jsonify({'success': True, 'logs': logs})
        
    except Exception as e:
        print(f"[LOGS_ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/details')
def details_page():
    """Migration details page - combined document and file view."""
    batch_id = request.args.get('batch_id')
    return render_template('migration_details.html', batch_id=batch_id, **get_template_context())


# =============================================================================
# FILE DETAILS API
# =============================================================================

@migrate_bp.route('/batch/<batch_id>/file-details', methods=['GET'])
def get_batch_file_details(batch_id):
    """
    Get detailed file-level migration results for a batch.
    
    Query Parameters:
        - status: Filter by upload_status (SUCCESS, UPLOAD_FAIL, etc.)
        - error_category: Filter by error category (AUTH_ERROR, TIMEOUT, etc.)
        - staging_id: Filter by specific container/staging ID
        - filename: Filter by filename (partial match)
        - has_error: Filter for files with errors (true/false)
        - page: Page number (default 1)
        - per_page: Results per page (default 100, max 1000)
    """
    try:
        print(f"[FILE_DETAILS] Fetching file details for batch: {batch_id}")
        
        # Parse filter parameters
        status_filter = request.args.get('status')
        error_category_filter = request.args.get('error_category')
        staging_id_filter = request.args.get('staging_id')
        filename_filter = request.args.get('filename')
        has_error_filter = request.args.get('has_error')
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(1000, max(10, int(request.args.get('per_page', 100))))
        
        # Build dynamic WHERE clause
        where_clauses = ["fd.batch_id = :batch_id"]
        params = {'batch_id': batch_id}
        
        if status_filter:
            where_clauses.append("fd.upload_status LIKE :status")
            params['status'] = f"%{status_filter}%"
        
        if error_category_filter:
            where_clauses.append("fd.error_category = :error_category")
            params['error_category'] = error_category_filter
        
        if staging_id_filter:
            where_clauses.append("fd.staging_id = :staging_id")
            params['staging_id'] = int(staging_id_filter)
        
        if filename_filter:
            where_clauses.append("fd.filename LIKE :filename")
            params['filename'] = f"%{filename_filter}%"
        
        if has_error_filter:
            if has_error_filter.lower() == 'true':
                where_clauses.append("fd.upload_status <> 'SUCCESS'")
            else:
                where_clauses.append("fd.upload_status = 'SUCCESS'")
        
        where_sql = " AND ".join(where_clauses)
        
        # Get total count for pagination
        count_query = f"""
            SELECT COUNT(*) as total
            FROM dbo.migration_file_details fd
            WHERE {where_sql}
        """
        
        # Main query with staging info join
        offset = (page - 1) * per_page
        query = f"""
            SELECT 
                fd.id,
                fd.staging_id,
                fd.file_index,
                fd.filename,
                fd.loio_id,
                fd.file_size_bytes,
                fd.file_size_mb,
                fd.mime_type,
                fd.upload_status,
                fd.http_status_code,
                fd.upload_time_seconds,
                fd.error_category,
                fd.error_code,
                fd.error_detail,
                fd.error_messages,
                fd.is_size_error,
                fd.created_at,
                s.source_documentnumber,
                s.source_documenttype,
                s.target_documentnumber,
                s.source_description
            FROM dbo.migration_file_details fd
            LEFT JOIN dbo.migration_staging s ON fd.staging_id = s.id
            WHERE {where_sql}
            ORDER BY fd.staging_id, fd.file_index
            OFFSET :offset ROWS FETCH NEXT :per_page ROWS ONLY
        """
        params['offset'] = offset
        params['per_page'] = per_page
        
        with misc_engine.begin() as con:
            # Get total count
            count_result = con.execute(text(count_query), params).fetchone()
            total_count = count_result[0] if count_result else 0
            
            # Get file details
            df = pd.read_sql(text(query), con, params=params)
        
        print(f"[FILE_DETAILS] Found {len(df)} file records (page {page}, total: {total_count})")
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        file_details = df_to_json_safe(df)
        
        # Parse JSON error_messages if present
        for detail in file_details:
            if detail.get('error_messages'):
                try:
                    detail['error_messages'] = json.loads(detail['error_messages'])
                except:
                    pass
        
        return jsonify({
            'success': True, 
            'file_details': file_details,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'total_pages': (total_count + per_page - 1) // per_page
            }
        })
        
    except Exception as e:
        print(f"[FILE_DETAILS_ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/file-details/summary', methods=['GET'])
def get_batch_file_summary(batch_id):
    """
    Get aggregated summary statistics for file-level migration results.
    Useful for populating filter dropdowns and showing overview stats.
    """
    try:
        summary_query = """
            SELECT 
                COUNT(*) as total_files,
                SUM(CASE WHEN upload_status = 'SUCCESS' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN upload_status <> 'SUCCESS' THEN 1 ELSE 0 END) as error_count,
                SUM(CASE WHEN is_size_error = 1 THEN 1 ELSE 0 END) as size_error_count,
                COUNT(DISTINCT staging_id) as container_count,
                SUM(file_size_bytes) as total_bytes,
                AVG(CAST(upload_time_seconds AS FLOAT)) as avg_upload_time
            FROM dbo.migration_file_details
            WHERE batch_id = :batch_id
        """
        
        status_query = """
            SELECT upload_status, COUNT(*) as count
            FROM dbo.migration_file_details
            WHERE batch_id = :batch_id
            GROUP BY upload_status
            ORDER BY count DESC
        """
        
        error_category_query = """
            SELECT error_category, COUNT(*) as count
            FROM dbo.migration_file_details
            WHERE batch_id = :batch_id AND error_category IS NOT NULL
            GROUP BY error_category
            ORDER BY count DESC
        """
        
        containers_with_errors_query = """
            SELECT 
                fd.staging_id,
                s.source_documentnumber,
                COUNT(*) as file_count,
                SUM(CASE WHEN fd.upload_status <> 'SUCCESS' THEN 1 ELSE 0 END) as error_count
            FROM dbo.migration_file_details fd
            LEFT JOIN dbo.migration_staging s ON fd.staging_id = s.id
            WHERE fd.batch_id = :batch_id
            GROUP BY fd.staging_id, s.source_documentnumber
            HAVING SUM(CASE WHEN fd.upload_status <> 'SUCCESS' THEN 1 ELSE 0 END) > 0
            ORDER BY error_count DESC
        """
        
        with misc_engine.begin() as con:
            # Main summary
            summary_result = con.execute(text(summary_query), {'batch_id': batch_id}).fetchone()
            
            # Status distribution
            status_df = pd.read_sql(text(status_query), con, params={'batch_id': batch_id})
            status_dist = df_to_json_safe(status_df)
            
            # Error category distribution
            error_df = pd.read_sql(text(error_category_query), con, params={'batch_id': batch_id})
            error_dist = df_to_json_safe(error_df)
            
            # Containers with errors
            containers_df = pd.read_sql(text(containers_with_errors_query), con, params={'batch_id': batch_id})
            containers_with_errors = df_to_json_safe(containers_df)
        
        summary = {
            'total_files': summary_result[0] or 0,
            'success_count': summary_result[1] or 0,
            'error_count': summary_result[2] or 0,
            'size_error_count': summary_result[3] or 0,
            'container_count': summary_result[4] or 0,
            'total_bytes': summary_result[5] or 0,
            'total_mb': round((summary_result[5] or 0) / 1024 / 1024, 2),
            'avg_upload_time': round(summary_result[6] or 0, 2)
        }
        
        return jsonify({
            'success': True,
            'summary': summary,
            'status_distribution': status_dist,
            'error_categories': error_dist,
            'containers_with_errors': containers_with_errors
        })
        
    except Exception as e:
        print(f"[FILE_SUMMARY_ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/file-details/export/<batch_id>', methods=['GET'])
def export_file_details(batch_id):
    """Export file details as CSV for external analysis."""
    try:
        query = """
            SELECT 
                fd.staging_id,
                s.source_documentnumber,
                s.source_documenttype,
                s.source_description,
                fd.file_index,
                fd.filename,
                fd.loio_id,
                fd.file_size_bytes,
                fd.file_size_mb,
                fd.mime_type,
                fd.upload_status,
                fd.http_status_code,
                fd.upload_time_seconds,
                fd.error_category,
                fd.error_code,
                fd.error_detail,
                fd.is_size_error,
                fd.created_at
            FROM dbo.migration_file_details fd
            LEFT JOIN dbo.migration_staging s ON fd.staging_id = s.id
            WHERE fd.batch_id = :batch_id
            ORDER BY fd.staging_id, fd.file_index
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(text(query), con, params={'batch_id': batch_id})
        
        # Generate CSV
        from io import StringIO
        from flask import Response
        
        output = StringIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=file_details_{batch_id}.csv'}
        )
        
    except Exception as e:
        print(f"[EXPORT_ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# OBJECT MAPPING API (per Batch)
# =============================================================================

@migrate_bp.route('/api/batch/<batch_id>')
def get_batch_info_api(batch_id):
    """Get batch info for API calls."""
    try:
        with misc_engine.begin() as con:
            batch_query = """
                SELECT batch_id, wave, description, total_records, status, created_at
                FROM dbo.migration_batch
                WHERE batch_id = :batch_id
            """
            batch_row = con.execute(text(batch_query), {'batch_id': batch_id}).fetchone()
            if batch_row:
                batch_info = {
                    'batch_id': batch_row[0],
                    'wave': batch_row[1],
                    'description': batch_row[2],
                    'total_records': batch_row[3],
                    'status': batch_row[4],
                    'created_at': str(batch_row[5]) if batch_row[5] else None
                }
                return jsonify({'success': True, 'batch': batch_info})
            else:
                return jsonify({'success': False, 'error': 'Batch not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping')
def batch_object_mapping_page(batch_id):
    """Object mapping management page for a specific batch."""
    return render_template('object_mapping.html', batch_id=batch_id, **get_template_context())


@migrate_bp.route('/batch/<batch_id>/object-mapping/list', methods=['GET'])
def list_batch_object_mappings(batch_id):
    """Get all object mappings for a specific batch."""
    try:
        with misc_engine.begin() as con:
            # Get batch info
            batch_query = """
                SELECT batch_id, wave, description, total_records, status
                FROM dbo.migration_batch
                WHERE batch_id = :batch_id
            """
            batch_row = con.execute(text(batch_query), {'batch_id': batch_id}).fetchone()
            batch_info = None
            if batch_row:
                batch_info = {
                    'batch_id': batch_row[0],
                    'wave': batch_row[1],
                    'description': batch_row[2],
                    'total_records': batch_row[3],
                    'status': batch_row[4]
                }
            
            # Get mappings for this batch
            query = """
                SELECT 
                    id,
                    batch_id,
                    source_dokob,
                    source_objky,
                    target_dokob,
                    target_objky,
                    description,
                    created_at,
                    created_by,
                    active
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
                ORDER BY source_dokob, source_objky
            """
            df = pd.read_sql(text(query), con, params={'batch_id': batch_id})
        
        mappings = df.to_dict(orient='records')
        return jsonify({'success': True, 'mappings': mappings, 'total': len(mappings), 'batch': batch_info})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/add', methods=['POST'])
def add_batch_object_mapping(batch_id):
    """Add a new object mapping to a specific batch."""
    try:
        data = request.get_json()
        
        source_dokob = data.get('source_dokob', '').strip().upper()
        source_objky = data.get('source_objky', '').strip()
        target_dokob = data.get('target_dokob', '').strip().upper()
        target_objky = data.get('target_objky', '').strip()
        description = data.get('description', '').strip()
        
        if not source_dokob or not source_objky or not target_dokob or not target_objky:
            return jsonify({'success': False, 'error': 'All fields are required: source_dokob, source_objky, target_dokob, target_objky'}), 400
        
        current_user = session.get('fullName', 'system')
        
        with misc_engine.begin() as con:
            # Check for duplicate in this batch
            existing = con.execute(text("""
                SELECT id FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id 
                AND source_dokob = :source_dokob 
                AND source_objky = :source_objky 
                AND active = 1
            """), {'batch_id': batch_id, 'source_dokob': source_dokob, 'source_objky': source_objky}).fetchone()
            
            if existing:
                return jsonify({'success': False, 'error': f'Mapping for {source_dokob}/{source_objky} already exists in this batch'}), 400
            
            con.execute(text("""
                INSERT INTO dbo.migration_object_mapping 
                (batch_id, source_dokob, source_objky, target_dokob, target_objky, description, created_by, active)
                VALUES (:batch_id, :source_dokob, :source_objky, :target_dokob, :target_objky, :description, :created_by, 1)
            """), {
                'batch_id': batch_id,
                'source_dokob': source_dokob,
                'source_objky': source_objky,
                'target_dokob': target_dokob,
                'target_objky': target_objky,
                'description': description,
                'created_by': current_user
            })
        
        return jsonify({'success': True, 'message': 'Mapping added successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/<int:mapping_id>/update', methods=['POST', 'PUT'])
def update_batch_object_mapping(batch_id, mapping_id):
    """Update an existing object mapping."""
    try:
        data = request.get_json()
        
        source_dokob = data.get('source_dokob', '').strip().upper()
        source_objky = data.get('source_objky', '').strip()
        target_dokob = data.get('target_dokob', '').strip().upper()
        target_objky = data.get('target_objky', '').strip()
        description = data.get('description', '').strip()
        
        if not source_dokob or not source_objky or not target_dokob or not target_objky:
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_object_mapping
                SET source_dokob = :source_dokob,
                    source_objky = :source_objky,
                    target_dokob = :target_dokob,
                    target_objky = :target_objky,
                    description = :description
                WHERE id = :id AND batch_id = :batch_id
            """), {
                'source_dokob': source_dokob,
                'source_objky': source_objky,
                'target_dokob': target_dokob,
                'target_objky': target_objky,
                'description': description,
                'id': mapping_id,
                'batch_id': batch_id
            })
        
        return jsonify({'success': True, 'message': 'Mapping updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/<int:mapping_id>/delete', methods=['POST', 'DELETE'])
def delete_batch_object_mapping(batch_id, mapping_id):
    """Delete (deactivate) an object mapping."""
    try:
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_object_mapping SET active = 0 
                WHERE id = :id AND batch_id = :batch_id
            """), {'id': mapping_id, 'batch_id': batch_id})
        
        return jsonify({'success': True, 'message': 'Mapping deleted successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/download', methods=['GET'])
def download_batch_object_mapping(batch_id):
    """Download object mappings for a batch as Excel file with source values from staging."""
    try:
        with misc_engine.begin() as con:
            # Get existing mappings
            mappings_query = """
                SELECT 
                    source_dokob,
                    source_objky,
                    target_dokob,
                    target_objky,
                    description
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
                ORDER BY source_dokob, source_objky
            """
            df_mappings = pd.read_sql(text(mappings_query), con, params={'batch_id': batch_id})
            
            # Get unique DOKOB/OBJKY values from staging for this batch
            # NOTE: source_dokob/source_objky are populated during EXECUTE phase from API
            # So this will only show values for records that have been executed
            staging_query = """
                SELECT 
                    source_dokob,
                    source_objky,
                    COUNT(*) as document_count,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id AND source_dokob IS NOT NULL AND source_objky IS NOT NULL
                GROUP BY source_dokob, source_objky
                ORDER BY source_dokob, source_objky
            """
            df_staging = pd.read_sql(text(staging_query), con, params={'batch_id': batch_id})
            
            # Count total and executed records for info sheet
            count_query = """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN source_dokob IS NOT NULL THEN 1 ELSE 0 END) as with_dokob,
                    SUM(CASE WHEN execution_status IN ('success', 'failed') THEN 1 ELSE 0 END) as executed
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
            """
            counts = con.execute(text(count_query), {'batch_id': batch_id}).fetchone()
            total_records = counts[0] if counts else 0
            records_with_dokob = counts[1] if counts else 0
            executed_records = counts[2] if counts else 0
            
            # Get batch info
            batch_query = """
                SELECT wave, description FROM dbo.migration_batch WHERE batch_id = :batch_id
            """
            batch_row = con.execute(text(batch_query), {'batch_id': batch_id}).fetchone()
            batch_wave = batch_row[0] if batch_row else ''
            batch_desc = batch_row[1] if batch_row else ''
        
        # Create Excel file with multiple sheets
        from io import BytesIO
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet 1: Existing Mappings
            df_mappings.to_excel(writer, sheet_name='Mappings', index=False)
            
            # Sheet 2: Source values from staging (for reference when creating mappings)
            # Add empty target columns for convenience
            if not df_staging.empty:
                df_staging['target_dokob'] = ''
                df_staging['target_objky'] = ''
                df_staging['description'] = ''
            df_staging.to_excel(writer, sheet_name='Batch Objects', index=False)
            
            # Sheet 3: Unmapped objects (objects in staging without a mapping)
            if not df_staging.empty and not df_mappings.empty:
                # Find unmapped by comparing (df_staging uses source_dokob/source_objky after renaming)
                mapped_keys = set(zip(df_mappings['source_dokob'], df_mappings['source_objky']))
                unmapped_mask = ~df_staging.apply(
                    lambda row: (row['source_dokob'], row['source_objky']) in mapped_keys, axis=1
                )
                df_unmapped = df_staging[unmapped_mask].copy()
            elif df_mappings.empty and not df_staging.empty:
                df_unmapped = df_staging.copy()
            else:
                df_unmapped = pd.DataFrame()
            
            if not df_unmapped.empty:
                df_unmapped.to_excel(writer, sheet_name='Unmapped Objects', index=False)
            
            # Sheet 4: Info sheet with batch statistics and notes
            info_data = {
                'Info': [
                    'Batch ID',
                    'Wave',
                    'Description',
                    '',
                    'Total Records',
                    'Records with DOKOB/OBJKY',
                    'Executed Records',
                    '',
                    'Note'
                ],
                'Value': [
                    batch_id,
                    batch_wave,
                    batch_desc,
                    '',
                    str(total_records),
                    str(records_with_dokob),
                    str(executed_records),
                    '',
                    'DOKOB/OBJKY values are fetched from API during EXECUTE phase. '
                    'If "Batch Objects" sheet is empty, start migration first to populate values.'
                ]
            }
            df_info = pd.DataFrame(info_data)
            df_info.to_excel(writer, sheet_name='Info', index=False)
        
        output.seek(0)
        
        filename = f'object_mapping_{batch_id}.xlsx'
        if batch_wave:
            filename = f'object_mapping_{batch_wave}_{batch_id[:20]}.xlsx'
        
        return Response(
            output.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/object-mapping/download-template', methods=['GET'])
def download_object_mapping_template():
    """Download empty Excel template for object mapping."""
    try:
        from io import BytesIO
        
        # Create template with headers and example
        df = pd.DataFrame({
            'source_dokob': ['IFLOT', 'PMQMEL', 'PMAUFK'],
            'source_objky': ['DE-LU-E-B211-MA10', '000100012345', '000012345678'],
            'target_dokob': ['IFLOT', 'PMQMEL', 'PMAUFK'],
            'target_objky': ['DE-LU-E-B211-MA10', '000100012345', '000012345678'],
            'description': ['Functional Location', 'Notification', 'Order']
        })
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Object Mapping', index=False)
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': 'attachment; filename=object_mapping_template.xlsx'}
        )
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/upload', methods=['POST'])
def upload_batch_object_mapping(batch_id):
    """Upload Excel file with object mappings for a specific batch."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Read Excel file
        df = pd.read_excel(file)
        
        # Validate required columns
        required_cols = ['source_dokob', 'source_objky', 'target_dokob', 'target_objky']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            return jsonify({'success': False, 'error': f'Missing columns: {missing_cols}'}), 400
        
        # Get mode: 'replace' = delete all and insert, 'append' = add only new
        mode = request.form.get('mode', 'append')
        current_user = session.get('fullName', 'system')
        
        added = 0
        skipped = 0
        updated = 0
        
        with misc_engine.begin() as con:
            if mode == 'replace':
                # Deactivate all existing mappings for this batch
                con.execute(text("UPDATE dbo.migration_object_mapping SET active = 0 WHERE batch_id = :batch_id"), 
                           {'batch_id': batch_id})
            
            for _, row in df.iterrows():
                source_dokob = str(row['source_dokob']).strip().upper()
                source_objky = str(row['source_objky']).strip()
                target_dokob = str(row['target_dokob']).strip().upper()
                target_objky = str(row['target_objky']).strip()
                description = str(row.get('description', '') or '').strip()
                
                if not source_dokob or not source_objky or not target_dokob or not target_objky:
                    skipped += 1
                    continue
                
                # Check if mapping exists in this batch
                existing = con.execute(text("""
                    SELECT id, active FROM dbo.migration_object_mapping
                    WHERE batch_id = :batch_id 
                    AND source_dokob = :source_dokob 
                    AND source_objky = :source_objky
                """), {'batch_id': batch_id, 'source_dokob': source_dokob, 'source_objky': source_objky}).fetchone()
                
                if existing:
                    # Update existing mapping
                    con.execute(text("""
                        UPDATE dbo.migration_object_mapping
                        SET target_dokob = :target_dokob, target_objky = :target_objky, 
                            description = :description, active = 1
                        WHERE id = :id
                    """), {
                        'target_dokob': target_dokob,
                        'target_objky': target_objky,
                        'description': description,
                        'id': existing[0]
                    })
                    updated += 1
                else:
                    # Insert new mapping
                    con.execute(text("""
                        INSERT INTO dbo.migration_object_mapping 
                        (batch_id, source_dokob, source_objky, target_dokob, target_objky, description, created_by, active)
                        VALUES (:batch_id, :source_dokob, :source_objky, :target_dokob, :target_objky, :description, :created_by, 1)
                    """), {
                        'batch_id': batch_id,
                        'source_dokob': source_dokob,
                        'source_objky': source_objky,
                        'target_dokob': target_dokob,
                        'target_objky': target_objky,
                        'description': description,
                        'created_by': current_user
                    })
                    added += 1
        
        # Auto-apply mappings to staging records immediately after upload
        staging_applied = 0
        try:
            from app.prepare import apply_object_mappings_for_batch
            staging_applied = apply_object_mappings_for_batch(batch_id)
        except Exception as e:
            print(f"[WARN] Auto-apply after upload failed: {e}")
        
        apply_msg = f', {staging_applied} auf Staging angewendet' if staging_applied > 0 else ''
        return jsonify({
            'success': True,
            'message': f'Upload complete: {added} added, {updated} updated, {skipped} skipped{apply_msg}',
            'added': added,
            'updated': updated,
            'skipped': skipped,
            'staging_applied': staging_applied
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/stats', methods=['GET'])
def batch_object_mapping_stats(batch_id):
    """Get statistics about object mappings for a batch."""
    try:
        with misc_engine.begin() as con:
            # Count total mappings
            mapping_count_query = """
                SELECT COUNT(*) as cnt
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
            """
            total_mappings = con.execute(text(mapping_count_query), {'batch_id': batch_id}).fetchone()[0] or 0
            
            # Count unique sources and targets
            unique_query = """
                SELECT 
                    COUNT(DISTINCT source_dokob + '|' + source_objky) as unique_sources,
                    COUNT(DISTINCT target_dokob + '|' + target_objky) as unique_targets
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
            """
            unique_row = con.execute(text(unique_query), {'batch_id': batch_id}).fetchone()
            unique_sources = unique_row[0] if unique_row else 0
            unique_targets = unique_row[1] if unique_row else 0
            
            # Count unmapped objects in staging
            unmapped_query = """
                SELECT COUNT(DISTINCT s.source_dokob + '|' + s.source_objky) as cnt
                FROM dbo.migration_staging s
                LEFT JOIN dbo.migration_object_mapping m 
                    ON m.batch_id = s.batch_id
                    AND s.source_dokob = m.source_dokob 
                    AND s.source_objky = m.source_objky 
                    AND m.active = 1
                WHERE s.batch_id = :batch_id
                AND s.source_dokob IS NOT NULL
                AND m.id IS NULL
            """
            unmapped_count = con.execute(text(unmapped_query), {'batch_id': batch_id}).fetchone()[0] or 0
        
        return jsonify({
            'success': True, 
            'total_mappings': total_mappings,
            'unique_sources': unique_sources,
            'unique_targets': unique_targets,
            'unmapped_count': unmapped_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/unmapped', methods=['GET'])
def batch_object_mapping_unmapped(batch_id):
    """
    Get list of source objects in this batch that have no mapping.
    """
    try:
        with misc_engine.begin() as con:
            query = """
                SELECT 
                    s.source_dokob as dokob,
                    s.source_objky as objky,
                    COUNT(*) as count
                FROM dbo.migration_staging s
                LEFT JOIN dbo.migration_object_mapping m 
                    ON m.batch_id = s.batch_id
                    AND s.source_dokob = m.source_dokob 
                    AND s.source_objky = m.source_objky 
                    AND m.active = 1
                WHERE s.batch_id = :batch_id
                AND s.source_dokob IS NOT NULL
                AND m.id IS NULL
                GROUP BY s.source_dokob, s.source_objky
                ORDER BY s.source_dokob, s.source_objky
            """
            df = pd.read_sql(text(query), con, params={'batch_id': batch_id})
        
        unmapped = df.to_dict(orient='records')
        
        return jsonify({'success': True, 'unmapped': unmapped, 'total': len(unmapped)})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/object-mapping/all-batches', methods=['GET'])
def object_mapping_all_batches():
    """
    Get overview of all batches and their mapping status.
    """
    try:
        with misc_engine.begin() as con:
            query = """
                SELECT 
                    b.batch_id,
                    b.wave,
                    b.description,
                    b.total_records,
                    b.status,
                    COUNT(DISTINCT m.id) as mapping_count,
                    COUNT(DISTINCT CASE WHEN s.source_dokob IS NOT NULL AND m.id IS NULL 
                                        THEN CONCAT(s.source_dokob, '|', s.source_objky) END) as unmapped_count
                FROM dbo.migration_batch b
                LEFT JOIN dbo.migration_staging s ON b.batch_id = s.batch_id
                LEFT JOIN dbo.migration_object_mapping m 
                    ON m.batch_id = b.batch_id
                    AND s.source_dokob = m.source_dokob 
                    AND s.source_objky = m.source_objky 
                    AND m.active = 1
                GROUP BY b.batch_id, b.wave, b.description, b.total_records, b.status
                ORDER BY b.wave, b.batch_id
            """
            df = pd.read_sql(query, con)
        
        batches = df.to_dict(orient='records')
        
        return jsonify({'success': True, 'batches': batches})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/apply', methods=['POST'])
def apply_batch_object_mappings(batch_id):
    """
    Apply object mappings to staging records for a batch.
    
    NOTE: Since source_dokob/source_objky are now fetched from API during EXECUTE phase,
    this endpoint will only work for records that have already been (partially) executed.
    For new batches, object mappings are applied ON-THE-FLY during EXECUTE.
    
    This endpoint is kept for backward compatibility with manually-set source values.
    """
    try:
        from app.prepare import apply_object_mappings_for_batch
        
        updated = apply_object_mappings_for_batch(batch_id)
        
        # Add a note if no updates were made
        message = f'Applied mappings to {updated} staging records'
        if updated == 0:
            message += '. Note: Object mappings are now applied on-the-fly during EXECUTE (source_dokob/source_objky come from API).'
        
        return jsonify({
            'success': True, 
            'message': message,
            'updated': updated
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==============================================================================
# OBJECT MAPPING – Bulk Add, DIL Lookup, API Lookup
# ==============================================================================

@migrate_bp.route('/batch/<batch_id>/object-mapping/bulk-add', methods=['POST'])
def bulk_add_object_mappings(batch_id):
    """Bulk-add multiple mappings in one request (for 1:1, DIL-lookup, etc.)."""
    try:
        data = request.get_json()
        mappings = data.get('mappings', [])
        if not mappings:
            return jsonify(success=False, error='No mappings provided'), 400

        current_user = session.get('fullName', 'system')
        added = 0
        skipped = 0

        with misc_engine.begin() as con:
            for m in mappings:
                sd = str(m.get('source_dokob', '')).strip().upper()
                so = str(m.get('source_objky', '')).strip()
                td = str(m.get('target_dokob', '')).strip().upper()
                to_ = str(m.get('target_objky', '')).strip()
                desc = str(m.get('description', '')).strip()
                if not sd or not so or not td or not to_:
                    skipped += 1
                    continue
                existing = con.execute(text("""
                    SELECT id FROM dbo.migration_object_mapping
                    WHERE batch_id = :batch_id AND source_dokob = :sd AND source_objky = :so AND active = 1
                """), {'batch_id': batch_id, 'sd': sd, 'so': so}).fetchone()
                if existing:
                    skipped += 1
                    continue
                con.execute(text("""
                    INSERT INTO dbo.migration_object_mapping
                    (batch_id, source_dokob, source_objky, target_dokob, target_objky, description, created_by, active)
                    VALUES (:batch_id, :sd, :so, :td, :to_, :desc, :user, 1)
                """), {'batch_id': batch_id, 'sd': sd, 'so': so, 'td': td, 'to_': to_, 'desc': desc, 'user': current_user})
                added += 1

        return jsonify(success=True, added=added, skipped=skipped)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


# ==============================================================================
# OBJECT MAPPING – DOKOB Strategy Settings
# ==============================================================================

@migrate_bp.route('/batch/<batch_id>/object-mapping/dokob-strategy', methods=['GET'])
def get_dokob_strategy(batch_id):
    """Get saved strategy per DOKOB for this batch."""
    try:
        with misc_engine.begin() as con:
            rows = con.execute(text("""
                SELECT dokob, source_method, target_method, updated_at, updated_by,
                       strno_prefix_old, strno_prefix_new
                FROM dbo.migration_dokob_strategy
                WHERE batch_id = :batch_id
            """), {'batch_id': batch_id}).fetchall()
        strategies = {}
        for r in rows:
            strategies[r[0]] = {
                'source_method': r[1],
                'target_method': r[2],
                'updated_at': r[3].isoformat() if r[3] else None,
                'updated_by': r[4],
                'strno_prefix_old': r[5] or '',
                'strno_prefix_new': r[6] or ''
            }
        return jsonify(success=True, strategies=strategies)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/dokob-strategy', methods=['PUT'])
def set_dokob_strategy(batch_id):
    """Save strategy for one DOKOB type. Body: {dokob, source_method, target_method}."""
    try:
        data = request.get_json()
        dokob = str(data.get('dokob', '')).strip().upper()
        source_method = str(data.get('source_method', 'none')).strip().lower()
        target_method = str(data.get('target_method', 'none')).strip().lower()
        if not dokob:
            return jsonify(success=False, error='dokob required'), 400
        valid_source = ('none', 'dil')
        valid_target = ('none', 'api', 'excel', '1:1')
        if source_method not in valid_source:
            return jsonify(success=False, error=f'source_method must be one of {valid_source}'), 400
        if target_method not in valid_target:
            return jsonify(success=False, error=f'target_method must be one of {valid_target}'), 400

        # STRNO prefix fields (optional, relevant for IFLOT)
        strno_prefix_old = str(data.get('strno_prefix_old', '') or '').strip()[:10]
        strno_prefix_new = str(data.get('strno_prefix_new', '') or '').strip()[:10]

        current_user = session.get('fullName', 'system')
        with misc_engine.begin() as con:
            con.execute(text("""
                MERGE dbo.migration_dokob_strategy AS t
                USING (SELECT :batch_id AS batch_id, :dokob AS dokob) AS s
                    ON t.batch_id = s.batch_id AND t.dokob = s.dokob
                WHEN MATCHED THEN
                    UPDATE SET source_method = :src, target_method = :tgt,
                               strno_prefix_old = :pold, strno_prefix_new = :pnew,
                               updated_at = GETUTCDATE(), updated_by = :user
                WHEN NOT MATCHED THEN
                    INSERT (batch_id, dokob, source_method, target_method, strno_prefix_old, strno_prefix_new, updated_by)
                    VALUES (:batch_id, :dokob, :src, :tgt, :pold, :pnew, :user);
            """), {'batch_id': batch_id, 'dokob': dokob, 'src': source_method,
                   'tgt': target_method, 'pold': strno_prefix_old or None,
                   'pnew': strno_prefix_new or None, 'user': current_user})

        return jsonify(success=True, dokob=dokob, source_method=source_method, target_method=target_method,
                       strno_prefix_old=strno_prefix_old, strno_prefix_new=strno_prefix_new)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


# ==============================================================================
# EXCLUSION – Excel Template Download / Upload
# ==============================================================================

@migrate_bp.route('/api/exclusion-template/download', methods=['GET'])
def download_exclusion_template():
    """Download an empty Excel exclusion template.
    One sheet per DOKOB type with the key column and an example row."""
    from flask import send_file
    from app.db_schema import EXCLUSION_EXCEL_SHEETS
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='2E75B6', end_color='2E75B6', fill_type='solid')
    example_font = Font(italic=True, color='888888')
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    for dokob, sheet_def in EXCLUSION_EXCEL_SHEETS.items():
        ws = wb.create_sheet(title=dokob)
        key_col = sheet_def['key_column']
        label = sheet_def['label']
        example = sheet_def.get('example', '')

        # Header row
        ws.cell(row=1, column=1, value=key_col).font = header_font
        ws.cell(row=1, column=1).fill = header_fill
        ws.cell(row=1, column=1).alignment = Alignment(horizontal='center')
        ws.cell(row=1, column=1).border = thin_border

        # Description column
        ws.cell(row=1, column=2, value='Beschreibung (optional)').font = header_font
        ws.cell(row=1, column=2).fill = header_fill
        ws.cell(row=1, column=2).alignment = Alignment(horizontal='center')
        ws.cell(row=1, column=2).border = thin_border

        # Example row
        ws.cell(row=2, column=1, value=example).font = example_font
        ws.cell(row=2, column=2, value=f'Beispiel {label}').font = example_font

        # Additional example rows (e.g. PMPLKO has multiple format types)
        extra_examples = sheet_def.get('extra_examples', [])
        for i, (ex_val, ex_desc) in enumerate(extra_examples, start=3):
            ws.cell(row=i, column=1, value=ex_val).font = example_font
            ws.cell(row=i, column=2, value=ex_desc).font = example_font

        # Auto-width
        all_examples = [example] + [e[0] for e in extra_examples]
        ws.column_dimensions['A'].width = max(len(key_col), max(len(e) for e in all_examples)) + 4
        ws.column_dimensions['B'].width = 30

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name='exclusion_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@migrate_bp.route('/api/exclusion-template/upload', methods=['POST'])
def upload_exclusion_template():
    """Upload a filled Excel exclusion template.
    Parses all sheets matching DOKOB names and returns the exclusion keys per type.
    Also stores the parsed keys in a temp JSON file so the batch creation SSE stream
    can read them (SSE uses GET, so we can't POST data with it)."""
    from app.db_schema import EXCLUSION_EXCEL_SHEETS

    if 'file' not in request.files:
        return jsonify(success=False, error='Keine Datei hochgeladen'), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify(success=False, error='Keine Datei ausgewählt'), 400

    try:
        # Read all sheets
        xl = pd.ExcelFile(file, engine='openpyxl')
        result = {}
        total_keys = 0

        for dokob, sheet_def in EXCLUSION_EXCEL_SHEETS.items():
            if dokob not in xl.sheet_names:
                continue
            df = xl.parse(dokob)
            key_col = sheet_def['key_column']

            # Find the key column (case-insensitive)
            col_map = {c.strip().upper(): c for c in df.columns}
            actual_col = col_map.get(key_col.upper())
            if not actual_col:
                continue

            # Extract non-empty keys, skip example row (italic font not detectable in pandas)
            keys = df[actual_col].dropna().astype(str).str.strip()
            keys = keys[keys != '']
            # Remove the example value(s)
            example_val = sheet_def.get('example', '')
            if example_val:
                keys = keys[keys != example_val]
            for ex_val, _ in sheet_def.get('extra_examples', []):
                keys = keys[keys != ex_val]

            keys_list = keys.unique().tolist()

            # Also check for description column
            desc_col = col_map.get('BESCHREIBUNG (OPTIONAL)') or col_map.get('BESCHREIBUNG')
            descriptions = {}
            if desc_col:
                for _, row in df.iterrows():
                    k = str(row.get(actual_col, '')).strip()
                    d = str(row.get(desc_col, '')).strip()
                    if k and k != example_val and d and d != f'Beispiel {sheet_def["label"]}':
                        descriptions[k] = d

            if keys_list:
                result[dokob] = {
                    'key_column': key_col,
                    'keys': keys_list,
                    'count': len(keys_list),
                    'descriptions': descriptions
                }
                total_keys += len(keys_list)

        # Store exclusion keys in temp file for batch creation SSE stream
        os.makedirs('userdata', exist_ok=True)
        temp_path = os.path.join('userdata', 'pending_exclusion_keys.json')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)

        return jsonify(success=True, exclusions=result, total_keys=total_keys,
                       sheets_found=list(result.keys()))

    except Exception as e:
        import traceback
        return jsonify(success=False, error=str(e), detail=traceback.format_exc()), 500


@migrate_bp.route('/api/exclusion-template/clear', methods=['POST'])
def clear_pending_exclusion_keys():
    """Clear the pending exclusion keys (e.g. when user removes upload)."""
    temp_path = os.path.join('userdata', 'pending_exclusion_keys.json')
    if os.path.exists(temp_path):
        os.remove(temp_path)
    return jsonify(success=True)


# ==============================================================================
# OBJECT MAPPING – DIL Lookup
# ==============================================================================


@migrate_bp.route('/batch/<batch_id>/object-mapping/dil-lookup', methods=['GET'])
def dil_lookup_for_mapping(batch_id):
    """
    Query DIL (HANA) to find all unique OBJKY values for a given DOKOB
    that appear in the batch's staging table.
    Returns source keys from DIL.DRAD that can be used for 1:1 mapping.
    """
    dokob = request.args.get('dokob', '').strip().upper()
    if not dokob:
        return jsonify(success=False, error='dokob parameter required'), 400

    try:
        # First get the unmapped objkeys for this dokob from staging
        with misc_engine.begin() as con:
            unmapped_q = """
                SELECT DISTINCT s.source_dokob as dokob, s.source_objky as objky
                FROM dbo.migration_staging s
                LEFT JOIN dbo.migration_object_mapping m
                    ON m.batch_id = s.batch_id
                    AND s.source_dokob = m.source_dokob
                    AND s.source_objky = m.source_objky
                    AND m.active = 1
                WHERE s.batch_id = :batch_id
                AND s.source_dokob = :dokob
                AND s.source_dokob IS NOT NULL
                AND m.id IS NULL
            """
            df_unmapped = pd.read_sql(text(unmapped_q), con, params={'batch_id': batch_id, 'dokob': dokob})

        if df_unmapped.empty:
            return jsonify(success=True, results=[], message=f'No unmapped entries for {dokob}')

        unmapped_keys = df_unmapped['objky'].tolist()

        # Now verify these keys exist in DIL
        from app_config import DilEngine
        dil_db = DilEngine.load()
        dil_engine = dil_db.engine

        # Build a DOKOB-specific query
        dil_queries = {
            'EQUI': "SELECT DISTINCT drad.OBJKY as objky, equz.IWERK as werk FROM DIL.DRAD drad JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231' WHERE drad.DOKOB = 'EQUI' AND drad.OBJKY IN ({placeholders})",
            'IFLOT': "SELECT DISTINCT drad.OBJKY as objky, iflot.IWERK as werk FROM DIL.DRAD drad JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR WHERE drad.DOKOB = 'IFLOT' AND drad.OBJKY IN ({placeholders})",
            'MPLA': "SELECT DISTINCT drad.OBJKY as objky FROM DIL.DRAD drad JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL WHERE drad.DOKOB = 'MPLA' AND drad.OBJKY IN ({placeholders})",
            'PMPLKO': "SELECT DISTINCT drad.OBJKY as objky, plko.WERKS as werk FROM DIL.DRAD drad JOIN DIL.PLKO plko ON LEFT(drad.OBJKY,1) = plko.PLNTY AND SUBSTRING(drad.OBJKY,2,8) = plko.PLNNR AND RIGHT(drad.OBJKY,2) = plko.PLNAL WHERE drad.DOKOB = 'PMPLKO' AND drad.OBJKY IN ({placeholders})",
            'PMAUFK': "SELECT DISTINCT drad.OBJKY as objky, aufk.WERKS as werk FROM DIL.DRAD drad JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR WHERE drad.DOKOB = 'PMAUFK' AND drad.OBJKY IN ({placeholders})",
            'PMAFVC': "SELECT DISTINCT drad.OBJKY as objky, afvc.WERKS as werk FROM DIL.DRAD drad JOIN DIL.AFVC afvc ON SUBSTRING(drad.OBJKY,3,10) = afvc.AUFPL AND SUBSTRING(drad.OBJKY,13,8) = afvc.APLZL WHERE drad.DOKOB = 'PMAFVC' AND drad.OBJKY IN ({placeholders})",
            'PMQMEL': "SELECT DISTINCT drad.OBJKY as objky, qmih.IWERK as werk FROM DIL.DRAD drad JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM WHERE drad.DOKOB = 'PMQMEL' AND drad.OBJKY IN ({placeholders})",
            'STKO_DOC': "SELECT DISTINCT drad.OBJKY as objky, stko.WRKAN as werk FROM DIL.DRAD drad JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX) WHERE drad.DOKOB = 'STKO_DOC' AND drad.OBJKY IN ({placeholders})",
            'STPO_DOC': "SELECT DISTINCT drad.OBJKY as objky FROM DIL.DRAD drad JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX) WHERE drad.DOKOB = 'STPO_DOC' AND drad.OBJKY IN ({placeholders})",
        }

        template = dil_queries.get(dokob)
        if not template:
            # Fallback: simple DRAD-only query
            template = "SELECT DISTINCT OBJKY as objky FROM DIL.DRAD WHERE DOKOB = :dokob_param AND OBJKY IN ({placeholders})"

        # Build parameterised IN-list (HANA uses positional params)
        params = {}
        ph_parts = []
        for i, key in enumerate(unmapped_keys):
            pname = f'k{i}'
            ph_parts.append(f':{pname}')
            params[pname] = key
        placeholders_str = ', '.join(ph_parts)
        sql = template.replace('{placeholders}', placeholders_str)
        if ':dokob_param' in sql:
            params['dokob_param'] = dokob

        with dil_engine.begin() as con:
            df_dil = pd.read_sql(text(sql), con, params=params)

            # IFLOT: enrich with STRNO from IFLOS (active records only)
            if dokob == 'IFLOT' and not df_dil.empty:
                found_keys = df_dil['objky'].tolist()
                ph2 = {}
                ph2_parts = []
                for i, k in enumerate(found_keys):
                    pn = f's{i}'
                    ph2_parts.append(f':{pn}')
                    ph2[pn] = k
                iflos_sql = f"SELECT TPLNR as tplnr, STRNO as strno FROM DIL.IFLOS WHERE ACTVS = 'X' AND TPLNR IN ({', '.join(ph2_parts)})"
                df_iflos = pd.read_sql(text(iflos_sql), con, params=ph2)
                df_iflos.columns = [c.lower() for c in df_iflos.columns]
                strno_map = dict(zip(df_iflos['tplnr'], df_iflos['strno']))
                df_dil['strno'] = df_dil['objky'].map(strno_map).fillna('')

        results = df_dil.to_dict(orient='records')
        return jsonify(success=True, results=results, total=len(results), dokob=dokob)

    except Exception as e:
        import traceback
        return jsonify(success=False, error=str(e), detail=traceback.format_exc()), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/api-lookup', methods=['GET'])
def api_lookup_for_mapping(batch_id):
    """
    Query SAP OData API for objects matching a DOKOB type.
    Currently supports: EQUI (Equipment API), IFLOT (FunctionalLocation API).
    """
    import requests as _req
    dokob = request.args.get('dokob', '').strip().upper()
    if not dokob:
        return jsonify(success=False, error='dokob parameter required'), 400

    # Map DOKOB to API config key and entity set
    api_map = {
        'EQUI':  {'config_key': 'equipment', 'entity': 'Equipment',          'key_field': 'Equipment'},
        'IFLOT': {'config_key': 'funcloc',   'entity': 'FunctionalLocation', 'key_field': 'FunctionalLocation'},
    }
    if dokob not in api_map:
        return jsonify(success=False, error=f'API lookup not supported for {dokob}. Use DIL or Excel instead.'), 400

    amap = api_map[dokob]
    # Determine SAP system — prefer zbq (S4)
    sap_system = 'zbq'
    sys_cfg = cfg.config_env.get(sap_system, {})
    auth_type = sys_cfg.get('auth_type', 'oauth')

    if auth_type == 'basic':
        from app.credentials import get_credentials
        creds = get_credentials(sap_system)
        if not creds:
            return jsonify(success=False, error=f'No credentials for {sap_system}'), 401
        headers = {'Accept': 'application/json'}
        auth_kw = dict(auth=(creds['username'], creds['password']), verify=sys_cfg.get('verify_ssl', True))
    else:
        token = session.get('bearer_token')
        if not token:
            return jsonify(success=False, error='Not logged in — Bearer Token fehlt'), 401
        api_key = cfg.get(sap_system, 'X-API-Key')
        headers = {'Authorization': f'Bearer {token}', 'X-API-Key': api_key, 'Accept': 'application/json'}
        auth_kw = {}

    api_cfg = cfg.get(sap_system, 'api_list', amap['config_key'])
    if not api_cfg:
        return jsonify(success=False, error=f'No {amap["config_key"]} API configured for {sap_system}'), 400
    base_url = api_cfg['base_url']

    # Get unmapped keys to filter
    try:
        with misc_engine.begin() as con:
            unmapped_q = """
                SELECT DISTINCT s.source_objky as objky
                FROM dbo.migration_staging s
                LEFT JOIN dbo.migration_object_mapping m
                    ON m.batch_id = s.batch_id AND s.source_dokob = m.source_dokob
                    AND s.source_objky = m.source_objky AND m.active = 1
                WHERE s.batch_id = :batch_id AND s.source_dokob = :dokob
                AND s.source_dokob IS NOT NULL AND m.id IS NULL
            """
            df = pd.read_sql(text(unmapped_q), con, params={'batch_id': batch_id, 'dokob': dokob})

        if df.empty:
            return jsonify(success=True, results=[], message=f'No unmapped entries for {dokob}')

        # Query API for first 50 unmapped keys
        keys = df['objky'].tolist()[:50]
        all_results = []
        key_field = amap['key_field']

        # IFLOT: load STRNO prefix replacement config
        strno_prefix_old = ''
        strno_prefix_new = ''
        if dokob == 'IFLOT':
            with misc_engine.begin() as con2:
                prow = con2.execute(text("""
                    SELECT strno_prefix_old, strno_prefix_new
                    FROM dbo.migration_dokob_strategy
                    WHERE batch_id = :batch_id AND dokob = 'IFLOT'
                """), {'batch_id': batch_id}).fetchone()
                if prow and prow[0] and prow[1]:
                    strno_prefix_old = prow[0]
                    strno_prefix_new = prow[1]

        # Batch API calls — OData filters with 'or'
        for key in keys:
            search_key = key
            # IFLOT: replace STRNO prefix (first N chars)
            if strno_prefix_old and strno_prefix_new and key.startswith(strno_prefix_old):
                search_key = strno_prefix_new + key[len(strno_prefix_old):]

            odata_filter = f"{key_field} eq '{search_key}'"
            url = f"{base_url}/{amap['entity']}?$top=1&$filter={odata_filter}"
            try:
                resp = _req.get(url, headers=headers, timeout=15, **auth_kw)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get('d', {}).get('results', [])
                    # Tag results with original source key for mapping
                    for r in results:
                        r['_source_objky'] = key
                        if search_key != key:
                            r['_transformed_key'] = search_key
                    all_results.extend(results)
            except Exception:
                pass  # skip individual failures

        return jsonify(success=True, results=all_results, count=len(all_results),
                       url=f'{base_url}/{amap["entity"]}', total_queried=len(keys),
                       strno_prefix_old=strno_prefix_old, strno_prefix_new=strno_prefix_new)
    except Exception as e:
        import traceback
        return jsonify(success=False, error=str(e), detail=traceback.format_exc()), 500


# ==============================================================================
# DMS OBJEKTE - Routes für die Werksfilterung und DMS-Daten-Ladung aus DIL
# ==============================================================================


@migrate_bp.route('/api/dms/werke', methods=['GET'])
def get_dms_werke():
    """
    Get list of all Werke (plants) from cached JSON file.
    Run load_werke_cache.py to refresh the cache.
    """
    try:
        cache_file = 'userdata/werke_cache.json'
        
        if not os.path.exists(cache_file):
            return jsonify({
                'success': False, 
                'error': 'Werke-Cache nicht gefunden. Bitte load_werke_cache.py ausführen.'
            }), 404
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        return jsonify({
            'success': True,
            'werke': cache_data['werke'],
            'total_werke': cache_data['total_werke'],
            'total_objects': cache_data['total_objects'],
            'generated_at': cache_data.get('generated_at', 'unknown'),
            'source': cache_data.get('source', 'unknown')
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'success': False, 
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@migrate_bp.route('/api/dms/load-stream')
def load_dms_objects_stream():
    """
    Load DMS objects with Server-Sent Events for real-time progress.
    Query parameters: werke (comma-separated), auto_save (boolean)
    """
    from flask import Response
    import time
    import json
    
    werke_param = request.args.get('werke', '')
    auto_save = request.args.get('auto_save', 'true').lower() == 'true'
    selected_werke = [w.strip() for w in werke_param.split(',') if w.strip()]
    
    def generate():
        start_time = time.time()
        
        try:
            from app_config import DilEngine
            import pandas as pd
            
            if not selected_werke:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Keine Werke ausgewählt'})}\n\n"
                return
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Verbinde mit DIL...', 'percent': 5})}\n\n"
            
            dil_db = DilEngine.load()
            if dil_db.engine is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'DIL database not connected'})}\n\n"
                return
            
            werke_filter = "', '".join(selected_werke)
            
            # Define queries per DOKOB with exclusion rules
            # Exclusion rules (status-based, applied in SQL):
            # - EQUI/IFLOT: Exclude if JEST status I0320, I0013, I0076 (deleted)
            # - PMAUFK: Exclude if JEST status I0045 (TECO) or I0013, I0076 (deleted)
            # - PMQMEL/SMQMEL: Exclude if JEST status I0072 (closed) or I0076 (deleted)
            # - PMAFVC: Exclude if parent order is TECO/deleted
            # - STKO_DOC: Exclude if STKO.LOEKZ = 'X'
            # - STPO_DOC: Exclude if STPO.LKENZ = 'X'
            # - PLKO: Exclude if PLKO.LOEKZ = 'X'
            # Post-filter (applied in Python):
            # - ALL: Exclude if no entry in DMS_DOC_FILES (no file in Content Repository)
            # Scalar subquery: checks DMS_DOC_FILES for file existence
            _has_file_sql = """CASE WHEN EXISTS (
                        SELECT 1 FROM DIL.DMS_DOC_FILES df 
                        WHERE df.DOKNR = drad.DOKNR AND df.DOKAR = drad.DOKAR 
                        AND df.DOKVR = drad.DOKVR AND df.DOKTL = drad.DOKTL 
                        AND df.MANDT = '100'
                    ) THEN 1 ELSE 0 END as HAS_FILE"""
            
            queries = {
                'EQUI': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY, 
                           equz.IWERK as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231'
                    JOIN DIL.EQUI equi ON drad.OBJKY = equi.EQUNR
                    WHERE drad.DOKOB = 'EQUI' AND equz.IWERK IN ('{werke_filter}')
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
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR
                    WHERE drad.DOKOB = 'IFLOT' AND iflot.IWERK IN ('{werke_filter}')
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
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
                    LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
                    WHERE drad.DOKOB = 'MPLA' 
                      AND COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) IN ('{werke_filter}')
                """,
                'PMPLKO': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           plko.WERKS as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.PLKO plko ON 
                        LEFT(drad.OBJKY, 1) = plko.PLNTY AND
                        SUBSTRING(drad.OBJKY, 2, 8) = plko.PLNNR AND
                        RIGHT(drad.OBJKY, 2) = plko.PLNAL
                    WHERE drad.DOKOB = 'PMPLKO' AND plko.WERKS IN ('{werke_filter}')
                      AND (plko.LOEKZ IS NULL OR plko.LOEKZ = '')
                """,
                'PMAUFK': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           aufk.WERKS as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR
                    WHERE drad.DOKOB = 'PMAUFK' AND aufk.WERKS IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = aufk.OBJNR 
                          AND j.STAT IN ('I0045', 'I0013', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'PMAFVC': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           afvc.WERKS as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.AFVC afvc ON 
                        SUBSTRING(drad.OBJKY, 3, 10) = afvc.AUFPL AND
                        SUBSTRING(drad.OBJKY, 13, 8) = afvc.APLZL
                    JOIN DIL.AFKO afko ON afvc.AUFPL = afko.AUFPL
                    JOIN DIL.AUFK aufk ON afko.AUFNR = aufk.AUFNR
                    WHERE drad.DOKOB = 'PMAFVC' AND afvc.WERKS IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = aufk.OBJNR 
                          AND j.STAT IN ('I0045', 'I0013', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'PMQMEL': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           qmih.IWERK as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
                    WHERE drad.DOKOB = 'PMQMEL' AND qmih.IWERK IN ('{werke_filter}')
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
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
                    WHERE drad.DOKOB = 'SMQMEL' AND qmih.IWERK IN ('{werke_filter}')
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
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
                    WHERE drad.DOKOB = 'STKO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                      AND (stko.LOEKZ IS NULL OR stko.LOEKZ = '')
                """,
                'STPO_DOC': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           stko.WRKAN as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX)
                    JOIN DIL.STKO stko ON stpo.STLNR = stko.STLNR
                    WHERE drad.DOKOB = 'STPO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                      AND (stpo.LKENZ IS NULL OR stpo.LKENZ = '')
                """
            }
            
            # Define count queries (without exclusion filter) to calculate excluded count
            count_queries = {
                'EQUI': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231'
                    WHERE drad.DOKOB = 'EQUI' AND equz.IWERK IN ('{werke_filter}')
                """,
                'IFLOT': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR
                    WHERE drad.DOKOB = 'IFLOT' AND iflot.IWERK IN ('{werke_filter}')
                """,
                'MPLA': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
                    LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
                    WHERE drad.DOKOB = 'MPLA' 
                      AND COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) IN ('{werke_filter}')
                """,
                'PMPLKO': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.PLKO plko ON 
                        LEFT(drad.OBJKY, 1) = plko.PLNTY AND
                        SUBSTRING(drad.OBJKY, 2, 8) = plko.PLNNR AND
                        RIGHT(drad.OBJKY, 2) = plko.PLNAL
                    WHERE drad.DOKOB = 'PMPLKO' AND plko.WERKS IN ('{werke_filter}')
                """,
                'PMAUFK': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR
                    WHERE drad.DOKOB = 'PMAUFK' AND aufk.WERKS IN ('{werke_filter}')
                """,
                'PMAFVC': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.AFVC afvc ON 
                        SUBSTRING(drad.OBJKY, 3, 10) = afvc.AUFPL AND
                        SUBSTRING(drad.OBJKY, 13, 8) = afvc.APLZL
                    WHERE drad.DOKOB = 'PMAFVC' AND afvc.WERKS IN ('{werke_filter}')
                """,
                'PMQMEL': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    WHERE drad.DOKOB = 'PMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                """,
                'SMQMEL': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    WHERE drad.DOKOB = 'SMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                """,
                'STKO_DOC': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
                    WHERE drad.DOKOB = 'STKO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                """,
                'STPO_DOC': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX)
                    JOIN DIL.STKO stko ON stpo.STLNR = stko.STLNR
                    WHERE drad.DOKOB = 'STPO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                """
            }
            
            all_results = []
            stats = {}
            stats_total = {}  # Total counts without exclusion
            stats_excluded = {}  # Excluded counts (status-based)
            stats_no_file = {}  # Records with DB storage (DRAO, no DMS_DOC_FILES/KPRO entry)
            total_queries = len(queries)
            
            with dil_db.engine.begin() as con:
                for idx, (dokob, query) in enumerate(queries.items()):
                    percent = 10 + int((idx / total_queries) * 80)
                    yield f"data: {json.dumps({'type': 'progress', 'dokob': dokob, 'message': f'Lade {dokob}...', 'percent': percent, 'step': idx + 1, 'total_steps': total_queries})}\n\n"
                    
                    query_start = time.time()
                    try:
                        # Get data (includes FILEP column from LEFT JOIN DRAW)
                        df = pd.read_sql(query, con)
                        df.columns = [c.lower() for c in df.columns]
                        
                        # Map HAS_FILE to ABLAGE column: KPRO (Content Repository) or DB (DRAO)
                        total_after_status = len(df)
                        if 'has_file' in df.columns:
                            df['ablage'] = df['has_file'].map({1: 'KPRO', 0: 'DB'}).fillna('DB')
                            db_count = int((df['has_file'] == 0).sum())
                            df = df.drop(columns=['has_file'])
                        else:
                            df['ablage'] = 'KPRO'
                            db_count = 0
                        
                        count = len(df)
                        stats[dokob] = count
                        stats_no_file[dokob] = db_count  # now tracks DB-stored count (not excluded)
                        if count > 0:
                            all_results.append(df)
                        
                        # Get total count (without any filter) for exclusion statistics
                        total_count = total_after_status  # Default
                        excluded_count = 0
                        if dokob in count_queries:
                            try:
                                result = con.execute(text(count_queries[dokob]))
                                total_count = result.scalar() or 0
                                excluded_count = total_count - total_after_status  # Status-excluded only
                            except Exception as count_err:
                                print(f"[DMS Load] Count query error for {dokob}: {count_err}")
                        
                        stats_total[dokob] = total_count
                        stats_excluded[dokob] = excluded_count
                        
                        query_time = time.time() - query_start
                        
                        yield f"data: {json.dumps({'type': 'step_complete', 'dokob': dokob, 'count': count, 'total': total_count, 'excluded': excluded_count, 'no_file': db_count, 'time': f'{query_time:.2f}s', 'percent': percent + 5})}\n\n"
                        print(f"[DMS Load] {dokob}: {count} records (status-excluded {excluded_count}, db-stored {db_count}) in {query_time:.2f}s")
                    except Exception as e:
                        print(f"[DMS Load] ERROR in {dokob}: {str(e)}")
                        stats[dokob] = 0
                        yield f"data: {json.dumps({'type': 'step_error', 'dokob': dokob, 'error': str(e)})}\n\n"
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Verarbeite Daten...', 'percent': 95})}\n\n"
            
            # Combine all results
            if all_results:
                combined_df = pd.concat(all_results, ignore_index=True)
                data_list = combined_df.to_dict(orient='records')
            else:
                data_list = []
            
            stats['total'] = len(data_list)
            total_time = time.time() - start_time
            
            # Auto-save to SQLite
            saved = False
            if auto_save:
                try:
                    import sqlite3
                    os.makedirs('userdata', exist_ok=True)
                    db_path = 'userdata/dms_objects.db'
                    conn = sqlite3.connect(db_path)
                    if data_list:
                        df_save = pd.DataFrame(data_list)
                        df_save.to_sql('dms_objects', conn, if_exists='replace', index=False)
                    else:
                        # Clear old data when new load returns 0 results
                        cursor = conn.cursor()
                        cursor.execute("DROP TABLE IF EXISTS dms_objects")
                        conn.commit()
                    conn.close()
                    saved = True
                    print(f"[DMS Load] Auto-saved {len(data_list)} records to {db_path}")
                except Exception as save_error:
                    print(f"[DMS Load] Auto-save failed: {save_error}")
            
            # Send final result with exclusion statistics
            yield f"data: {json.dumps({'type': 'complete', 'stats': stats, 'stats_total': stats_total, 'stats_excluded': stats_excluded, 'stats_no_file': stats_no_file, 'count': len(data_list), 'query_time': f'{total_time:.2f}s', 'saved': saved, 'data': data_list})}\n\n"
            
        except Exception as e:
            import traceback
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'traceback': traceback.format_exc()})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })


@migrate_bp.route('/api/dms/save', methods=['POST'])
def save_dms_objects():
    """
    Save loaded DMS objects to local SQLite database.
    Creates a new table or appends to existing.
    """
    try:
        import sqlite3
        
        data = request.get_json()
        objects = data.get('data', [])
        
        if not objects:
            return jsonify({'success': False, 'error': 'Keine Daten zum Speichern'}), 400
        
        # Create userdata folder if needed
        os.makedirs('userdata', exist_ok=True)
        
        # Save to SQLite
        db_path = 'userdata/dms_objects.db'
        conn = sqlite3.connect(db_path)
        
        # Create DataFrame and save
        import pandas as pd
        df = pd.DataFrame(objects)
        df.to_sql('dms_objects', conn, if_exists='replace', index=False)
        
        conn.close()
        
        return jsonify({
            'success': True,
            'count': len(objects),
            'db_path': db_path
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'success': False, 
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@migrate_bp.route('/api/dms/status', methods=['GET'])
def get_dms_status():
    """
    Get status of local DMS objects database.
    """
    try:
        import sqlite3
        db_path = 'userdata/dms_objects.db'
        
        if not os.path.exists(db_path):
            return jsonify({'success': True, 'count': 0, 'exists': False})
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dms_objects")
        count = cursor.fetchone()[0]
        conn.close()
        
        return jsonify({
            'success': True,
            'count': count,
            'exists': True,
            'db_path': db_path
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'count': 0,
            'error': str(e)
        })


@migrate_bp.route('/api/dms/dokob-stats', methods=['GET'])
def get_dms_dokob_stats():
    """
    Get DOKOB (object type) statistics from local DMS database.
    Returns count per DOKOB for filtering in batch creation.
    """
    try:
        import sqlite3
        db_path = 'userdata/dms_objects.db'
        
        if not os.path.exists(db_path):
            return jsonify({'success': True, 'dokobs': []})
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dokob, COUNT(*) as count 
            FROM dms_objects 
            GROUP BY dokob 
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        dokobs = [{'dokob': row[0] or 'UNKNOWN', 'count': row[1]} for row in rows]
        
        return jsonify({
            'success': True,
            'dokobs': dokobs
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@migrate_bp.route('/api/dms/create-batch-stream', methods=['GET'])
def create_dms_migration_batch_stream():
    """
    Create a migration batch from local DMS objects database using SSE for progress.
    Uses GET with query parameters for EventSource compatibility.
    
    Query params:
        wave: Wave identifier (required)
        description: Batch description
        notes: Additional notes
        dokob_filter: Comma-separated list of DOKOB values to include (optional, empty = all)
    
    Exclusion keys are read from userdata/pending_exclusion_keys.json (uploaded via
    /api/exclusion-template/upload) and applied before staging insertion.
    """
    import sqlite3
    from datetime import datetime
    from app.db_schema import EXCLUSION_EXCEL_SHEETS
    
    wave = request.args.get('wave')
    description = request.args.get('description', '')
    notes = request.args.get('notes', '')
    dokob_filter = request.args.get('dokob_filter', '')  # Comma-separated list of DOKOBs
    
    if not wave:
        return jsonify({'success': False, 'error': 'Wave ist erforderlich'})
    
    db_path = 'userdata/dms_objects.db'
    if not os.path.exists(db_path):
        return jsonify({'success': False, 'error': 'Keine DMS-Objekte in lokaler Datenbank'})
    
    # Extract session data BEFORE the generator (outside request context)
    current_user = session.get('user_email', 'system')
    
    # Parse DOKOB filter
    dokob_list = [d.strip() for d in dokob_filter.split(',') if d.strip()] if dokob_filter else []
    
    # Load pending exclusion keys (if uploaded via Excel)
    exclusion_keys = {}  # {dokob_upper: set of objky strings}
    excl_descriptions = {}  # {dokob: {objky: label}}
    temp_excl_path = os.path.join('userdata', 'pending_exclusion_keys.json')
    if os.path.exists(temp_excl_path):
        try:
            with open(temp_excl_path, 'r', encoding='utf-8') as f:
                excl_data = json.load(f)
            for dokob, info in excl_data.items():
                dk = dokob.strip().upper()
                exclusion_keys[dk] = set(str(k).strip() for k in info.get('keys', []))
                excl_descriptions[dk] = info.get('descriptions', {})
        except Exception as e:
            print(f"[DMS Batch] Warning: Could not load exclusion keys: {e}")
    
    def generate():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Lese lokale Datenbank...', 'percent': 5})}\n\n"
            
            # Read from SQLite with optional DOKOB filter
            conn = sqlite3.connect(db_path)
            if dokob_list:
                placeholders = ','.join(['?' for _ in dokob_list])
                query = f"SELECT * FROM dms_objects WHERE dokob IN ({placeholders})"
                dms_df = pd.read_sql(query, conn, params=dokob_list)
                filter_info = f"DOKOB-Filter: {', '.join(dokob_list)}"
            else:
                dms_df = pd.read_sql("SELECT * FROM dms_objects", conn)
                filter_info = "Alle Objekttypen"
            conn.close()
            
            if len(dms_df) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Keine DMS-Objekte gefunden (evtl. Filter zu streng)'})}\n\n"
                return
            
            total_records = len(dms_df)
            yield f"data: {json.dumps({'type': 'status', 'message': f'{total_records:,} Datensätze geladen ({filter_info})', 'percent': 10})}\n\n"
            
            # ── Apply exclusion keys (filter out matching DOKOB+OBJKY) ──
            excluded_count = 0
            excluded_per_dokob = {}
            if exclusion_keys:
                before_count = len(dms_df)
                
                # Build mask: keep rows where (dokob, objky) is NOT in exclusion keys
                def is_excluded(row):
                    dk = str(row.get('dokob', '')).strip().upper()
                    ok = str(row.get('objky', '')).strip()
                    return dk in exclusion_keys and ok in exclusion_keys[dk]
                
                excl_mask = dms_df.apply(is_excluded, axis=1)
                
                # Count excluded per DOKOB
                if excl_mask.any():
                    excluded_rows = dms_df[excl_mask]
                    for dk in excluded_rows['dokob'].unique():
                        dk_upper = str(dk).strip().upper()
                        cnt = int((excluded_rows['dokob'] == dk).sum())
                        excluded_per_dokob[dk_upper] = cnt
                
                dms_df = dms_df[~excl_mask].reset_index(drop=True)
                excluded_count = before_count - len(dms_df)
                
                if excluded_count > 0:
                    excl_detail = ', '.join(f'{k}: {v}' for k, v in excluded_per_dokob.items())
                    yield f"data: {json.dumps({'type': 'status', 'message': f'{excluded_count:,} Objekte durch Ausschluss-Liste entfernt ({excl_detail})', 'percent': 12})}\n\n"
                    print(f"[DMS Batch] Exclusion applied: {excluded_count} records removed ({excl_detail})")
            
            if len(dms_df) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Keine Objekte nach Anwendung der Ausschluss-Liste übrig'})}\n\n"
                return
            
            # Generate batch ID
            batch_id = f"DMS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Get unique Werke from the loaded data
            unique_werke = dms_df['werk'].unique().tolist() if 'werk' in dms_df.columns else []
            werke_str = ', '.join(sorted(unique_werke))
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Bereite Staging-Daten vor...', 'percent': 15})}\n\n"
            
            # Helper function to compute target document number
            # - Auto-generated IDs (25 digits, all numeric) → None (will get new number in target)
            # - Manual/external IDs (contain letters) → preserve as target number
            def compute_target_docnumber(doknr):
                if pd.isnull(doknr):
                    return None
                val = str(doknr).strip()
                # Check if this is an auto-generated ID (25 chars, all numeric after stripping leading zeros)
                if len(val) == 25:
                    try:
                        int(val.lstrip('0') or '0')
                        return None  # Auto-generated → will get new number
                    except (ValueError, TypeError):
                        pass
                # Manual/external ID → preserve it
                return val[:25]
            
            # Prepare staging DataFrame using vectorized operations (FAST!)
            # NOTE: target_* fields depend on whether source is auto-generated or manual
            # - Auto-generated IDs → target stays None (will get new number during migration)
            # - Manual/external IDs → target = source (preserve external number)
            staging_df = pd.DataFrame({
                'batch_id': batch_id,
                'created_by': current_user,
                'source_documentnumber': dms_df['doknr'].fillna(''),
                'source_documentpart': dms_df['doktl'].fillna('000'),
                'source_documenttype': dms_df['dokar'].fillna(''),
                'source_documentversion': dms_df['dokvr'].fillna('00'),
                'source_dokob': dms_df['dokob'].fillna(''),
                'source_objky': dms_df['objky'].fillna(''),
                'target_documentnumber': dms_df['doknr'].apply(compute_target_docnumber),
                'target_documentpart': dms_df['doktl'].fillna('000'),
                'target_documenttype': dms_df['dokar'].fillna(''),
                'target_documentversion': dms_df['dokvr'].fillna('00'),
                'ablage': dms_df['ablage'].fillna('KPRO') if 'ablage' in dms_df.columns else 'KPRO',
                'user_approved': 0,
                'skip_migration': 0,
                'validation_status': 'pending',
                'execution_status': 'pending'
            })
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Schreibe in Staging-Datenbank...', 'percent': 20})}\n\n"
            
            # Save to staging database in chunks (SQL Server limit with method='multi' is ~1000)
            chunk_size = 900
            total_rows = len(staging_df)
            
            with misc_engine.begin() as con:
                for i in range(0, total_rows, chunk_size):
                    chunk_df = staging_df.iloc[i:i + chunk_size]
                    chunk_df.to_sql(
                        'migration_staging',
                        con,
                        schema='dbo',
                        if_exists='append',
                        index=False,
                        method='multi'
                    )
                    
                    # Calculate progress (20% to 90%)
                    progress = 20 + int(70 * min(i + chunk_size, total_rows) / total_rows)
                    rows_done = min(i + chunk_size, total_rows)
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'{rows_done:,} / {total_rows:,} Zeilen', 'percent': progress, 'rows': rows_done, 'total': total_rows})}\n\n"
                    print(f"[DMS Batch] Inserted rows {i+1}-{rows_done} of {total_rows}")
                
                yield f"data: {json.dumps({'type': 'status', 'message': 'Erstelle Batch-Eintrag...', 'percent': 95})}\n\n"
                
                # Create batch record with Werke info
                batch_record = pd.DataFrame([{
                    'batch_id': batch_id,
                    'created_by': current_user,
                    'source_file': f'DMS Objects: {werke_str}' if werke_str else 'dms_objects.db',
                    'total_records': len(staging_df),
                    'status': 'prepared',
                    'wave': wave,
                    'description': description[:40] if description else None,
                    'notes': f"Werke: {werke_str}\n{notes}" if werke_str else notes if notes else None
                }])
                
                batch_record.to_sql(
                    'migration_batch',
                    con,
                    schema='dbo',
                    if_exists='append',
                    index=False
                )
                
                # Persist exclusion keys to DB (for later reference / re-download)
                if exclusion_keys:
                    for dk, keys_set in exclusion_keys.items():
                        descs = excl_descriptions.get(dk, {})
                        for objky_val in keys_set:
                            try:
                                con.execute(text("""
                                    INSERT INTO dbo.migration_exclusion_keys
                                        (batch_id, dokob, objky, label, excluded_by)
                                    VALUES (:batch_id, :dokob, :objky, :label, :user)
                                """), {
                                    'batch_id': batch_id,
                                    'dokob': dk,
                                    'objky': objky_val,
                                    'label': descs.get(objky_val),
                                    'user': current_user
                                })
                            except Exception:
                                pass  # Skip duplicate keys silently
            
            # Clean up temp exclusion file
            if os.path.exists(temp_excl_path):
                try:
                    os.remove(temp_excl_path)
                except Exception:
                    pass
            
            print(f"[DMS Batch] Created batch {batch_id} with {len(staging_df)} records"
                  f" (excluded: {excluded_count})")
            
            yield f"data: {json.dumps({'type': 'complete', 'success': True, 'batch_id': batch_id, 'record_count': len(staging_df), 'excluded_count': excluded_count, 'excluded_per_dokob': excluded_per_dokob, 'wave': wave, 'percent': 100})}\n\n"
            
        except Exception as e:
            import traceback
            print(f"[DMS Batch ERROR] {e}")
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })


# ========================================================================
# Wave Plan CRUD
# ========================================================================

@migrate_bp.route('/wave-plans', methods=['GET'])
def get_wave_plans():
    """Get all wave plans."""
    try:
        with misc_engine.connect() as con:
            # Check if table exists first
            check = text("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='migration_wave_plan'
            """)
            if con.execute(check).fetchone()[0] == 0:
                return jsonify({'success': True, 'waves': []})

            result = con.execute(text("""
                SELECT id, wave_name,
                       qual_load_start, qual_load_end, qual_load_status,
                       qual_link_start, qual_link_end, qual_link_status,
                       prod_load_start, prod_load_end, prod_load_status,
                       prod_link_start, prod_link_end, prod_link_status,
                       notes, created_at, updated_at
                FROM dbo.migration_wave_plan
                ORDER BY wave_name
            """)).fetchall()

            waves = []
            for row in result:
                waves.append({
                    'id': row[0],
                    'wave_name': row[1],
                    'qual_load_start': str(row[2]) if row[2] else None,
                    'qual_load_end': str(row[3]) if row[3] else None,
                    'qual_load_status': row[4] or 'vorbereitung',
                    'qual_link_start': str(row[5]) if row[5] else None,
                    'qual_link_end': str(row[6]) if row[6] else None,
                    'qual_link_status': row[7] or 'vorbereitung',
                    'prod_load_start': str(row[8]) if row[8] else None,
                    'prod_load_end': str(row[9]) if row[9] else None,
                    'prod_load_status': row[10] or 'vorbereitung',
                    'prod_link_start': str(row[11]) if row[11] else None,
                    'prod_link_end': str(row[12]) if row[12] else None,
                    'prod_link_status': row[13] or 'vorbereitung',
                    'notes': row[14],
                    'created_at': str(row[15]) if row[15] else None,
                    'updated_at': str(row[16]) if row[16] else None,
                })
            return jsonify({'success': True, 'waves': waves})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@migrate_bp.route('/wave-plans', methods=['POST'])
def create_wave_plan():
    """Create or update a wave plan."""
    try:
        data = request.json
        wave_name = data.get('wave_name', '').strip()
        if not wave_name:
            return jsonify({'success': False, 'error': 'wave_name ist erforderlich'})

        with misc_engine.begin() as con:
            # Check if exists
            existing = con.execute(text(
                "SELECT id FROM dbo.migration_wave_plan WHERE wave_name = :wn"
            ), {'wn': wave_name}).fetchone()

            if existing:
                # Update
                con.execute(text("""
                    UPDATE dbo.migration_wave_plan SET
                        qual_load_start = :qls, qual_load_end = :qle, qual_load_status = :qlst,
                        qual_link_start = :qks, qual_link_end = :qke, qual_link_status = :qkst,
                        prod_load_start = :pls, prod_load_end = :ple, prod_load_status = :plst,
                        prod_link_start = :pks, prod_link_end = :pke, prod_link_status = :pkst,
                        notes = :notes, updated_at = GETUTCDATE()
                    WHERE wave_name = :wn
                """), {
                    'wn': wave_name,
                    'qls': data.get('qual_load_start') or None,
                    'qle': data.get('qual_load_end') or None,
                    'qlst': data.get('qual_load_status', 'vorbereitung'),
                    'qks': data.get('qual_link_start') or None,
                    'qke': data.get('qual_link_end') or None,
                    'qkst': data.get('qual_link_status', 'vorbereitung'),
                    'pls': data.get('prod_load_start') or None,
                    'ple': data.get('prod_load_end') or None,
                    'plst': data.get('prod_load_status', 'vorbereitung'),
                    'pks': data.get('prod_link_start') or None,
                    'pke': data.get('prod_link_end') or None,
                    'pkst': data.get('prod_link_status', 'vorbereitung'),
                    'notes': data.get('notes', ''),
                })
                return jsonify({'success': True, 'message': f'{wave_name} aktualisiert'})
            else:
                # Insert
                con.execute(text("""
                    INSERT INTO dbo.migration_wave_plan
                        (wave_name, qual_load_start, qual_load_end, qual_load_status,
                         qual_link_start, qual_link_end, qual_link_status,
                         prod_load_start, prod_load_end, prod_load_status,
                         prod_link_start, prod_link_end, prod_link_status, notes)
                    VALUES
                        (:wn, :qls, :qle, :qlst, :qks, :qke, :qkst,
                         :pls, :ple, :plst, :pks, :pke, :pkst, :notes)
                """), {
                    'wn': wave_name,
                    'qls': data.get('qual_load_start') or None,
                    'qle': data.get('qual_load_end') or None,
                    'qlst': data.get('qual_load_status', 'vorbereitung'),
                    'qks': data.get('qual_link_start') or None,
                    'qke': data.get('qual_link_end') or None,
                    'qkst': data.get('qual_link_status', 'vorbereitung'),
                    'pls': data.get('prod_load_start') or None,
                    'ple': data.get('prod_load_end') or None,
                    'plst': data.get('prod_load_status', 'vorbereitung'),
                    'pks': data.get('prod_link_start') or None,
                    'pke': data.get('prod_link_end') or None,
                    'pkst': data.get('prod_link_status', 'vorbereitung'),
                    'notes': data.get('notes', ''),
                })
                return jsonify({'success': True, 'message': f'{wave_name} erstellt'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@migrate_bp.route('/wave-plans/<int:wave_id>', methods=['DELETE'])
def delete_wave_plan(wave_id):
    """Delete a wave plan."""
    try:
        with misc_engine.begin() as con:
            con.execute(text("DELETE FROM dbo.migration_wave_plan WHERE id = :id"), {'id': wave_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@migrate_bp.route('/wave-plans/task-status', methods=['PUT'])
def update_wave_task_status():
    """Update a single task status for a wave plan."""
    try:
        data = request.json
        wave_id = data.get('wave_id')
        task_field = data.get('task_field')  # e.g. 'qual_load_status'
        new_status = data.get('status')

        allowed_fields = ['qual_load_status', 'qual_link_status', 'prod_load_status', 'prod_link_status']
        allowed_statuses = ['vorbereitung', 'arbeit', 'fertig']

        if task_field not in allowed_fields:
            return jsonify({'success': False, 'error': f'Ungültiges Feld: {task_field}'})
        if new_status not in allowed_statuses:
            return jsonify({'success': False, 'error': f'Ungültiger Status: {new_status}'})

        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_wave_plan
                SET {task_field} = :status, updated_at = GETUTCDATE()
                WHERE id = :id
            """), {'status': new_status, 'id': wave_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
