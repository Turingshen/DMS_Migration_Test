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
        from app.credentials import list_all_sap_systems, get_credential_info, list_db_only_credentials
        systems = list_all_sap_systems()
        result = []
        known_ids = [s['system_id'] for s in systems]
        for sys_info in systems:
            sid = sys_info['system_id']
            info = get_credential_info(sid)
            # Config default for client
            config_client = cfg.config_env.get(sid, {}).get('client')
            config_host = cfg.config_env.get(sid, {}).get('host')
            entry = {
                'system_id': sid,
                'system_label': sys_info['system_label'],
                'system_type': sys_info['system_type'],
                'auth_type': sys_info['auth_type'],
                'has_credentials': info is not None,
                'username': info['username'] if info else None,
                'updated_at': info['updated_at'] if info else None,
                'updated_by': info['updated_by'] if info else None,
                'sap_client': info['sap_client'] if info and info.get('sap_client') else config_client,
                'config_client': config_client,
                'description': info['description'] if info and info.get('description') else sys_info['system_label'],
                'host': info['host'] if info and info.get('host') else config_host,
                'is_custom': False,
            }
            result.append(entry)

        # Include custom systems that exist only in the credentials DB
        for cust in list_db_only_credentials(known_ids):
            result.append({
                'system_id': cust['system_id'],
                'system_label': cust['description'] or cust['system_id'],
                'system_type': 'custom',
                'auth_type': 'basic',
                'has_credentials': True,
                'username': cust['username'],
                'updated_at': cust['updated_at'],
                'updated_by': cust['updated_by'],
                'sap_client': cust['sap_client'],
                'config_client': None,
                'description': cust['description'] or cust['system_id'],
                'host': cust['host'],
                'is_custom': True,
            })
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
        sap_client = (data.get('sap_client') or '').strip() or None
        description = (data.get('description') or '').strip() or None
        host = (data.get('host') or '').strip() or None

        # Validate sap_client: must be 3-digit numeric or empty
        if sap_client and (len(sap_client) != 3 or not sap_client.isdigit()):
            return jsonify({'success': False, 'error': 'Mandant muss 3-stellig numerisch sein (z.B. 100, 200)'}), 400

        if not system_id or not username:
            return jsonify({'success': False, 'error': 'system_id und username sind erforderlich'}), 400

        # system_id: allow config systems and custom (DB-only) IDs
        import re
        if not re.match(r'^[a-zA-Z0-9_]{2,50}$', system_id):
            return jsonify({'success': False, 'error': 'System-ID darf nur Buchstaben, Ziffern und _ enthalten (2-50 Zeichen)'}), 400

        # Password required for new entries, optional for updates
        from app.credentials import has_credentials
        if not password and not has_credentials(system_id):
            return jsonify({'success': False, 'error': 'Passwort ist für neue Einträge erforderlich'}), 400

        updated_by = session.get('fullName', session.get('preferred_username', 'unknown'))
        _save(system_id, username, password, updated_by, sap_client=sap_client, description=description, host=host)

        # Sync host change to sap_systems table (single source of truth)
        if host:
            try:
                from app_config import SapSystemManager
                mgr = SapSystemManager()
                existing = mgr.get_system(system_id)
                if existing and existing.get('host') != host:
                    mgr.save_system(
                        system_id,
                        existing['system_label'],
                        existing['system_type'],
                        host=host,
                        auth_type=existing.get('auth_type', 'oauth'),
                        api_key=existing.get('api_key', ''),
                        sap_client=existing.get('sap_client', ''),
                        verify_ssl=existing.get('verify_ssl', True),
                        updated_by=updated_by
                    )
                    mgr.update_config_env()
            except Exception:
                pass  # non-critical: next restart will sync

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
    """Test credentials by attempting a CSRF token fetch against the SAP system."""
    try:
        from app.credentials import get_credentials, list_basic_auth_systems, has_credentials
        from app_config import SapSystemManager
        import requests as req_lib

        is_basic = system_id in list_basic_auth_systems()
        is_custom = not is_basic and has_credentials(system_id)

        if not is_basic and not is_custom:
            return jsonify({'success': False, 'error': f'{system_id} ist kein bekanntes System'}), 400

        creds = get_credentials(system_id)
        if not creds:
            return jsonify({'success': False, 'error': 'Keine Zugangsdaten für dieses System hinterlegt'}), 404

        # Determine base_url and verify_ssl from DB (sap_systems + sap_system_apis)
        mgr = SapSystemManager()
        sys_data = mgr.get_system(system_id)

        if sys_data and sys_data.get('apis'):
            # Use first configured API base_url from DB
            first_api = next(iter(sys_data['apis'].values()), None)
            base_url = first_api['base_url'] if first_api else None
            verify_ssl = sys_data.get('verify_ssl', True)
        else:
            return jsonify({'success': False, 'error': 'Keine API-URL in der DB konfiguriert – bitte API-Endpunkt unter Systems & APIs anlegen'}), 400

        if not base_url:
            return jsonify({'success': False, 'error': 'Keine Test-URL ermittelbar – bitte API-Endpunkt konfigurieren'}), 400

        test_headers = {'X-CSRF-Token': 'Fetch', 'Accept': 'application/json'}
        # Add sap-client header: credential DB > system config > YAML fallback
        sap_client = creds.get('sap_client') or (sys_data.get('sap_client') if sys_data else None) or cfg.config_env.get(system_id, {}).get('client')
        if sap_client:
            test_headers['sap-client'] = str(sap_client)

        resp = req_lib.get(
            base_url,
            auth=(creds['username'], creds['password']),
            headers=test_headers,
            verify=verify_ssl,
            timeout=15
        )
        diag = f"URL: {base_url} | User: {creds['username']}"
        if sap_client:
            diag += f" | Mandant: {sap_client}"
        if resp.status_code == 200:
            csrf = resp.headers.get('x-csrf-token', '')
            return jsonify({
                'success': True,
                'message': f'Verbindung erfolgreich (HTTP {resp.status_code})',
                'csrf_token_received': bool(csrf),
                'details': diag
            })
        else:
            body_hint = ''
            try:
                body_hint = resp.text[:300] if resp.text else ''
            except Exception:
                pass
            return jsonify({
                'success': False,
                'error': f'HTTP {resp.status_code} {resp.reason}',
                'details': diag,
                'body': body_hint
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
        sap_client = (data.get('sap_client') or '').strip()
        verify_ssl = data.get('verify_ssl', True)
        environment = (data.get('environment') or '').strip().upper()
        if environment not in ('DEV', 'QUAL', 'PROD', ''):
            environment = ''

        if not system_id or not system_label or system_type not in ('R3', 'S4'):
            return jsonify({'success': False, 'error': 'system_id, system_label und system_type (R3/S4) sind erforderlich'}), 400

        updated_by = session.get('fullName', session.get('preferred_username', 'system'))
        mgr = SapSystemManager()
        mgr.save_system(system_id, system_label, system_type, host, auth_type, api_key, sap_client, verify_ssl, updated_by, environment)

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
            return jsonify({'success': False, 'error': f'{system_id} ist kein DB-Eintrag'}), 400
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


# --- Health Check (parallel system ping) --------------------------------------

@migrate_bp.route('/api/health-check', methods=['POST'])
def health_check():
    """Ping all SAP systems in parallel: CSRF token fetch + API endpoint reachability."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.credentials import get_credentials, list_basic_auth_systems, has_credentials
    from app_config import SapSystemManager
    import requests as req_lib
    import time as _time

    mgr = SapSystemManager()
    merged = mgr.get_merged_systems()
    basic_systems = list_basic_auth_systems()
    bearer_token = session.get('bearer_token')

    def _check_system(system_id, sys_data):
        """Check a single system. Returns dict with status info."""
        result = {
            'system_id': system_id,
            'status': 'unknown',      # ok | warn | error | skip
            'csrf': None,             # True/False/None
            'apis': {},               # api_name -> {reachable, status_code}
            'message': '',
            'ms': 0,
        }
        t0 = _time.time()
        is_basic = system_id in basic_systems
        is_custom = not is_basic and has_credentials(system_id)
        verify_ssl = sys_data.get('verify_ssl', True)

        # --- 1) CSRF token check (only for systems with credentials) ---
        if is_basic or is_custom:
            try:
                creds = get_credentials(system_id)
                if creds:
                    # Use first configured API URL from DB for CSRF fetch
                    apis = sys_data.get('apis', {})
                    first_api = next(iter(apis.values()), None) if apis else None
                    csrf_url = first_api['base_url'] if first_api else None
                    ssl = sys_data.get('verify_ssl', False)

                    if csrf_url:
                        hdrs = {'X-CSRF-Token': 'Fetch', 'Accept': 'application/json'}
                        sap_client = creds.get('sap_client') or sys_data.get('sap_client') or cfg.config_env.get(system_id, {}).get('client')
                        if sap_client:
                            hdrs['sap-client'] = str(sap_client)
                        resp = req_lib.get(csrf_url, auth=(creds['username'], creds['password']),
                                           headers=hdrs, verify=ssl, timeout=10)
                        if resp.status_code == 200:
                            result['csrf'] = bool(resp.headers.get('x-csrf-token', ''))
                        else:
                            result['csrf'] = False
                            result['message'] = f'CSRF HTTP {resp.status_code}'
            except Exception as e:
                result['csrf'] = False
                result['message'] = str(e)[:120]

        # --- 2) API endpoint reachability (HEAD with bearer or basic) ---
        apis = sys_data.get('apis', {})
        for api_name, api_info in apis.items():
            base_url = api_info.get('base_url', '')
            if not base_url:
                result['apis'][api_name] = {'reachable': False, 'status_code': 0, 'error': 'No URL'}
                continue
            try:
                hdrs = {'Accept': 'application/json'}
                auth = None
                if is_basic or is_custom:
                    creds = get_credentials(system_id)
                    if creds:
                        auth = (creds['username'], creds['password'])
                        sap_client = creds.get('sap_client') or sys_data.get('sap_client') or cfg.config_env.get(system_id, {}).get('client')
                        if sap_client:
                            hdrs['sap-client'] = str(sap_client)
                elif bearer_token:
                    hdrs['Authorization'] = 'Bearer ' + bearer_token
                    api_key = sys_data.get('api_key', '')
                    if api_key:
                        hdrs['APIKey'] = api_key

                resp = req_lib.get(base_url, headers=hdrs, auth=auth,
                                   verify=verify_ssl, timeout=10)
                result['apis'][api_name] = {
                    'reachable': resp.status_code < 500,
                    'status_code': resp.status_code,
                }
            except Exception as e:
                result['apis'][api_name] = {
                    'reachable': False,
                    'status_code': 0,
                    'error': str(e)[:80],
                }

        # --- Derive overall status ---
        result['ms'] = int((_time.time() - t0) * 1000)
        api_results = list(result['apis'].values())
        all_reachable = all(a['reachable'] for a in api_results) if api_results else None

        if result['csrf'] is True and all_reachable in (True, None):
            result['status'] = 'ok'
        elif result['csrf'] is False or all_reachable is False:
            result['status'] = 'error'
        elif result['csrf'] is None and all_reachable is True:
            result['status'] = 'ok'
        elif result['csrf'] is None and all_reachable is None:
            result['status'] = 'skip'
            result['message'] = result['message'] or 'Keine Credentials / APIs'
        else:
            result['status'] = 'warn'

        return result

    results = {}
    t_start = _time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_check_system, sid, sdata): sid
                   for sid, sdata in merged.items()}
        for future in as_completed(futures):
            sid = futures[future]
            try:
                results[sid] = future.result()
            except Exception as e:
                results[sid] = {'system_id': sid, 'status': 'error', 'message': str(e)[:120], 'csrf': None, 'apis': {}, 'ms': 0}

    total_ms = int((_time.time() - t_start) * 1000)
    ok_count = sum(1 for r in results.values() if r['status'] == 'ok')
    err_count = sum(1 for r in results.values() if r['status'] == 'error')

    return jsonify({
        'success': True,
        'total_ms': total_ms,
        'summary': {'ok': ok_count, 'error': err_count, 'total': len(results)},
        'results': results,
    })


