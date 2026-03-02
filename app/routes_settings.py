"""Settings, credentials, SAP system routes."""

from flask import render_template, request, jsonify, session
from sqlalchemy import text

from app.blueprint import (
    migrate_bp, cfg, get_template_context,
    _load_db_settings, _save_db_setting, DEFAULT_SETTINGS,
)
from app.process import (
    read_sap_system, write_sap_system,
    DEFAULT_SOURCE_SYSTEM, DEFAULT_TARGET_SYSTEM,
    get_systems_by_type
)


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


# --- SAP Credentials (Basic Auth for ZV systems) -----------------------------

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


# --- SAP System Management (DB + YAML merge) ---------------------------------

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


