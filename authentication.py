"""Authentication / OAuth helper.
Version marker to verify deployment.
Modify this value to confirm the running container picked up new code.
"""

# Inspired by https://gist.github.com/ib-lundgren/6507798.

from flask import request, redirect, url_for, Response, current_app
from flask import session as http_session
from functools import wraps
from urllib.parse import urlencode, urlparse
import secrets
import requests, json
import time
import yaml
import os
import hashlib

from app_config import Config
cfg = Config.load()
Oauth_config = cfg.get('auth')

# File-based state backup (for when session cookie isn't available yet)
STATE_BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'flask_session', 'oauth_states')

def _save_state_backup(state: str, session_data: dict):
    """Save OAuth state to a file as backup when session cookie fails."""
    try:
        os.makedirs(STATE_BACKUP_DIR, exist_ok=True)
        state_hash = hashlib.sha256(state.encode()).hexdigest()[:32]
        filepath = os.path.join(STATE_BACKUP_DIR, f'{state_hash}.json')
        with open(filepath, 'w') as f:
            json.dump({'state': state, 'created': time.time(), 'data': session_data}, f)
    except Exception as e:
        print(f'[WARN] Could not save state backup: {e}')

def _load_state_backup(state: str) -> dict:
    """Load OAuth state from backup file."""
    try:
        state_hash = hashlib.sha256(state.encode()).hexdigest()[:32]
        filepath = os.path.join(STATE_BACKUP_DIR, f'{state_hash}.json')
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
            # Delete after use (single-use)
            os.remove(filepath)
            # Check if not too old (5 minutes max)
            if time.time() - data.get('created', 0) < 300:
                return data
    except Exception as e:
        print(f'[WARN] Could not load state backup: {e}')
    return None

def _cleanup_old_states():
    """Clean up state files older than 10 minutes."""
    try:
        if not os.path.exists(STATE_BACKUP_DIR):
            return
        for filename in os.listdir(STATE_BACKUP_DIR):
            filepath = os.path.join(STATE_BACKUP_DIR, filename)
            if os.path.isfile(filepath) and time.time() - os.path.getmtime(filepath) > 600:
                os.remove(filepath)
    except Exception:
        pass

def _record(*_a, **_k):
    # no-op recorder (for future use)
    return None

def _session_cookie_name():
    try:
        return current_app.config.get('SESSION_COOKIE_NAME') or 'session'
    except Exception:
        return 'session'

def check(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        # if user is not logged in, redirect to login page
        if not 'bearer_token' in http_session:
            _record('guard_login_required', path=request.path)
            http_session['next'] = request.url # Store the original URL
            http_session.modified = True  # Force session save in cloud mode
            return redirect(url_for('login'))
        # All authenticated users have access
        return f(*args, **kwargs)
    return wrap

def admin_check(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        # if user is not logged in, redirect to login page
        if not 'bearer_token' in http_session:
            _record('guard_login_required', path=request.path)
            http_session['next'] = request.url  # Store the original URL
            http_session.modified = True  # Force session save in cloud mode
            return redirect(url_for('login'))
        # All authenticated users have access
        return f(*args, **kwargs)
    return wrap

def groups_required(*groups):
    """Decorator that requires login (ignores group parameter for backward compatibility)."""
    def decorator(f):
        @wraps(f)
        def wrap(*args, **kwargs):
            if not 'bearer_token' in http_session:
                _record('guard_login_required', path=request.path)
                http_session['next'] = request.url
                http_session.modified = True  # Force session save in cloud mode
                return redirect(url_for('login'))
            # All authenticated users have access
            return f(*args, **kwargs)
        return wrap
    return decorator


def is_token_expiring_soon(buffer_seconds=300):
    """Check if the token will expire within buffer_seconds (default 5 minutes)."""
    expires_at = http_session.get('token_expires_at')
    if not expires_at:
        return False  # Unknown expiry, assume OK
    return time.time() + buffer_seconds >= expires_at


def get_token_remaining_seconds():
    """Get remaining seconds until token expires. Returns None if unknown."""
    expires_at = http_session.get('token_expires_at')
    if not expires_at:
        return None
    remaining = expires_at - time.time()
    return max(0, int(remaining))


def refresh_token():
    """Attempt to refresh the bearer token using the refresh token.
    Returns (success, error_message).
    """
    refresh_tok = http_session.get('refresh_token')
    if not refresh_tok:
        return False, "No refresh token available"
    
    try:
        payload = {
            'client_id': Oauth_config['payload']['client_id'],
            'client_secret': Oauth_config['payload'].get('client_secret', ''),
            'grant_type': 'refresh_token',
            'refresh_token': refresh_tok,
        }
        
        response = requests.post(Oauth_config['auth_url'] + '/token', data=payload, timeout=30)
        
        if response.status_code != 200:
            return False, f"Refresh failed: HTTP {response.status_code}"
        
        data = response.json()
        
        # Update session with new tokens
        http_session['bearer_token'] = data['access_token']
        
        if 'refresh_token' in data:
            http_session['refresh_token'] = data['refresh_token']
        
        if 'expires_in' in data:
            expires_in = int(data['expires_in'])
            http_session['token_expires_at'] = time.time() + expires_in
            print(f"[AUTH] Token refreshed, expires in {expires_in}s ({expires_in // 60} minutes)")
        
        http_session.modified = True
        return True, None
        
    except Exception as e:
        return False, f"Refresh error: {str(e)}"


def ensure_valid_token():
    """Ensure the token is valid, refreshing if needed.
    Returns (is_valid, error_message).
    """
    if not http_session.get('bearer_token'):
        return False, "Not logged in"
    
    # Check if token is expiring soon (within 5 minutes)
    if is_token_expiring_soon(buffer_seconds=300):
        remaining = get_token_remaining_seconds()
        print(f"[AUTH] Token expiring in {remaining}s, attempting refresh...")
        
        success, error = refresh_token()
        if not success:
            return False, f"Token expired and refresh failed: {error}"
        
        return True, None
    
    return True, None


# Step 1: Initiate User Authorization.
def login():
    """User Authorization.
    Redirect the user to federation service.
    Adds state + in-progress guard to avoid duplicate parallel flows behind a reverse proxy.
    """
    sap_system = request.args.get('sap_system')
    if sap_system:
        http_session['sap_system'] = sap_system
        http_session['system_type'] = cfg.get(sap_system, 'system_type')
        http_session.modified = True  # Force session save in cloud mode
    http_session.pop('x-csrf-token', None)  # remove csrf token from http_session during login to make sure it is renewed

    # Handle external `callback_url` ensuring it matches current root domain
    callback_url = request.args.get('callback_url')
    if callback_url:
        try:
            parsed_cb = urlparse(callback_url)
            if parsed_cb.scheme in ('http', 'https'):
                def _base_domain(host):
                    if not host:
                        return ''
                    host = host.split(':', 1)[0]  # strip port if present
                    parts = host.split('.')
                    if len(parts) >= 2:
                        return '.'.join(parts[-2:])  # naive; ignores multi-part TLDs
                    return host
                current_host = urlparse(request.url_root).hostname
                if _base_domain(parsed_cb.hostname) == _base_domain(current_host):
                    http_session['next'] = callback_url
                    http_session.modified = True
        except Exception:
            pass

    # Redirect to the federation service for authentication
    try:
        cookie_name = _session_cookie_name()
        incoming_cookie = request.cookies.get(cookie_name)
        _record(
            'login_entry',
            session_keys=list(http_session.keys()),
            cookie_present=bool(incoming_cookie),
            cookie_name=cookie_name,
            cookie_prefix=(incoming_cookie or '')[:12],
            base_url=cfg.get('base_url'),
            deploy_env=cfg.get('deployment_environment'),
            sess_conf={
                'name': current_app.config.get('SESSION_COOKIE_NAME'),
                'domain': current_app.config.get('SESSION_COOKIE_DOMAIN'),
                'secure': current_app.config.get('SESSION_COOKIE_SECURE'),
                'samesite': current_app.config.get('SESSION_COOKIE_SAMESITE'),
                'type': current_app.config.get('SESSION_TYPE'),
            },
        )
    except Exception as _e:
        _record('login_diag_fail', error=str(_e))

    # Reuse existing redirect during an in-progress flow (covers most duplicate parallel hits)
    if http_session.get('auth_in_progress') and http_session.get('auth_redirect'):
        _record('login_reuse_redirect')
        return redirect(http_session['auth_redirect'])

    # Race mitigation: mark auth_in_progress immediately so parallel requests arriving
    # between state generation & flag set do not generate a second state.
    http_session['auth_in_progress'] = True
    http_session.modified = True  # Force session save

    # If a (recent) state already exists (e.g., second /login landed during race before redirect happened)
    # and we have no stored redirect, reuse the existing state instead of generating a new one.
    existing_state = http_session.get('oauth_state')
    state_age = time.time() - http_session.get('oauth_state_issued_at', 0)
    if existing_state and state_age < 180 and not http_session.get('auth_redirect'):
        _record('login_reuse_state', state_prefix=existing_state[:10], age=round(state_age,2))
        state = existing_state
    else:
        # CSRF protection/state correlation (fresh generation)
        state = secrets.token_urlsafe(24)
        http_session['oauth_state'] = state
        http_session['oauth_state_issued_at'] = time.time()
        http_session.modified = True  # Force session save

    payload = dict(Oauth_config['payload'])  # make a copy of Oauth_config
    payload.pop('client_secret', None)
    payload.pop('grant_type', None)

    # Attach (possibly reused) state to outbound auth request
    payload['state'] = state

    # Force externally correct https redirect_uri (IIS may report http internally)
    public_base = cfg.get('base_url') or request.url_root.replace('http://', 'https://')
    public_base = public_base.rstrip('/')
    # Overwrite redirect_uri if present / required by provider
    if 'redirect_uri' in payload:
        payload['redirect_uri'] = public_base + url_for('callback')
    _record('login_redirect', state_prefix=state[:10], redirect_uri=payload.get('redirect_uri'))
    
    # Save state backup to file (in case session cookie isn't set yet when callback arrives)
    _save_state_backup(state, {
        'sap_system': http_session.get('sap_system'),
        'system_type': http_session.get('system_type'),
        'next': http_session.get('next')
    })
    _cleanup_old_states()  # Housekeeping
    
    if '.basf.com' in Oauth_config['auth_url']:
        auth_string = '/authz/?'
    else:
        auth_string = '/authorize/?'
    redirect_url = Oauth_config['auth_url'] + auth_string + urlencode(payload)
    http_session['auth_redirect'] = redirect_url
    http_session.modified = True  # Ensure session changes are persisted
    return redirect(redirect_url)


def logout():
    """Log the user out by clearing the local session.

    Clears the OAuth bearer token and all user data, then shows a standalone
    "logged out" landing page. We deliberately do NOT redirect to /login here:
    that would immediately re-start the OAuth flow and a still-active corporate
    SSO session would silently log the user straight back in. The landing page
    requires an explicit click to log in again.
    """
    _record('logout', user=http_session.get('fullName'))
    http_session.clear()
    login_url = url_for('login')
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Abgemeldet / Logged out</title>
    <style>
        body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
               background:#f5f6f8; margin:0; display:flex; min-height:100vh;
               align-items:center; justify-content:center; }}
        .card {{ background:#fff; padding:2.5rem 3rem; border-radius:8px;
                box-shadow:0 2px 12px rgba(0,0,0,.1); text-align:center; max-width:420px; }}
        .icon {{ font-size:2.5rem; }}
        h1 {{ font-size:1.4rem; margin:.75rem 0 .25rem; color:#222; }}
        p {{ color:#666; margin:.25rem 0 1.5rem; }}
        a.btn {{ display:inline-block; background:#0d6efd; color:#fff; text-decoration:none;
                padding:.6rem 1.4rem; border-radius:6px; font-weight:600; }}
        a.btn:hover {{ background:#0b5ed7; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#128075;</div>
        <h1>Abgemeldet</h1>
        <p>Sie wurden abgemeldet. / You have been logged out.</p>
        <a class="btn" href="{login_url}">Erneut anmelden / Log in again</a>
    </div>
</body>
</html>"""
    resp = Response(html, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

# Step 2: User authorization, this happens on the federation service side.


# Step 3: Retrieving the authorization code
def callback():
    """Retrieving an authorization code.
    Validates state to prevent replay/duplicate flows; clears in-progress markers.
    """

    _record('callback_entry', args=dict(request.args))
    # print(f"Request URL: {request.url}")

    # Validate state
    try:
        cookie_name = _session_cookie_name()
        incoming_cookie = request.cookies.get(cookie_name)
        print(f'[DEBUG callback] cookie_name={cookie_name}, cookie_present={bool(incoming_cookie)}, cookie_prefix={(incoming_cookie or "")[:12]}')
        print(f'[DEBUG callback] session_keys={list(http_session.keys())}')
        print(f'[DEBUG callback] all_cookies={list(request.cookies.keys())}')
        _record('callback_pre_state', session_keys=list(http_session.keys()), cookie_name=cookie_name,
                cookie_present=bool(incoming_cookie), cookie_prefix=(incoming_cookie or '')[:12])
    except Exception:
        pass
    returned_state = request.args.get('state')
    expected_state = http_session.get('oauth_state')
    print(f'[DEBUG callback] returned_state={returned_state[:20] if returned_state else None}..., expected_state={expected_state[:20] if expected_state else None}...')
    
    # If no state in session, try to recover from file backup
    if not expected_state and returned_state:
        backup = _load_state_backup(returned_state)
        if backup and backup.get('state') == returned_state:
            print(f'[DEBUG callback] Recovered state from file backup!')
            expected_state = backup['state']
            # Restore session data from backup
            backup_data = backup.get('data', {})
            if backup_data.get('sap_system'):
                http_session['sap_system'] = backup_data['sap_system']
            if backup_data.get('system_type'):
                http_session['system_type'] = backup_data['system_type']
            if backup_data.get('next'):
                http_session['next'] = backup_data['next']
            http_session.modified = True
    
    # Idempotent / duplicate callback handling: if auth already completed (bearer + user info present)
    if expected_state is None and 'bearer_token' in http_session:
        # Duplicate callback (e.g. browser retry, IdP silent second redirect). Ignore and continue.
        _record('callback_duplicate_state_consumed')
        return redirect(http_session.pop('next', url_for('app.index')))

    if not expected_state:
        http_session.clear()
        return Response('Invalid state (missing session). Restart login.', status=400, mimetype='text/plain')

    if returned_state != expected_state:
        http_session.clear()
        return Response('Invalid state (mismatch). Restart login.', status=400, mimetype='text/plain')

    # Single-use: remove after successful validation
    http_session.pop('oauth_state', None)
    http_session.pop('oauth_state_issued_at', None)
    _record('callback_state_valid')
    http_session.pop('auth_in_progress', None)
    http_session.pop('auth_redirect', None)
    http_session.modified = True  # Force session save
    
# required check if bearer_token is expired
    # if 'bearer_token' in http_session:
    #     print('user already logged in')
    #     return redirect(url_for('.userinfo'))

    authorization_code = request.args.get('code') # get authorization code from URL

    if authorization_code is None: # did not receive an authorization code.
        _record('callback_no_code')
        error_description = request.args.get('error_description', 'No authorization code received')
        error_code = request.args.get('error', 'authorization_error')
        
        http_session.clear()
        return Response(
            response=f"Authentication failed: {error_code}\nDescription: {error_description}", 
            status=400, 
            mimetype="text/plain"
        )

# Step 4: Get Bearer token.
    payload = dict(Oauth_config['payload']) # make a copy of Oauth_config
    payload.pop('scope', None)
    payload.pop('response_type', None)
    payload['code'] = authorization_code

    response = requests.post(Oauth_config['auth_url']+'/token', data=payload) # send "code" with POST call to recieve bearer token

    if not response.status_code == 200:
        _record('callback_token_error', status=response.status_code, text=response.text[:160])
        
        http_session.clear()
        return Response(
            response=f"Error loading bearer token!\nStatus: {response.status_code}\nResponse: {response.text}", 
            status=response.status_code, 
            mimetype="text/plain"
        )

    else:
        try:
            response = response.json()
            http_session['bearer_token'] = response['access_token']
            
            # Store refresh token and expiry for automatic token refresh
            if 'refresh_token' in response:
                http_session['refresh_token'] = response['refresh_token']
                print(f"[AUTH] Refresh token saved")
            
            # Store token expiry time (expires_in is in seconds)
            if 'expires_in' in response:
                expires_in = int(response['expires_in'])
                http_session['token_expires_at'] = time.time() + expires_in
                print(f"[AUTH] Token expires in {expires_in}s ({expires_in // 60} minutes)")
            
            _record('callback_token_ok')
        except Exception as e_tok:
            _record('callback_token_parse_fail', error=str(e_tok))
            r = Response(response=f"error in function callback reading bearer token\n\n{response.text}", status=response.status_code, mimetype="text/plain")
            r.headers["Content-Type"] = "text/plain; charset=utf-8"
            http_session.clear()
            return r

# Step 5: Get Userinfo.
    payload.clear()
    payload = {
        'Authorization': 'Bearer ' + http_session['bearer_token'],
    }

    if '.microsoftonline.com' in Oauth_config['auth_url']:
        response = requests.get('https://graph.microsoft.com/oidc/userinfo', headers=payload)
    else:
        response = requests.get(Oauth_config['auth_url']+'/userinfo', headers=payload)
    
    if not response.status_code == 200:
        _record('callback_userinfo_error', status=response.status_code, text=response.text[:160])
        
        http_session.clear()
        return Response(
            response=f"Error loading userinfo!\nStatus: {response.status_code}\nResponse: {response.text}", 
            status=response.status_code, 
            mimetype="text/plain"
        )
    
    try:
        response = json.loads(response.content)
    except json.JSONDecodeError:
        http_session.clear()
        return Response(
            response="Failed to parse userinfo response as JSON", 
            status=500, 
            mimetype="text/plain"
        )

    ## remember userdata for later use
    try:
        if '.basf.com' in Oauth_config['auth_url']:
            http_session['cn'] = response['cn']
            http_session['firstName'] = response['firstName']
            http_session['lastName'] = response['lastName']
            http_session['fullName'] = response['fullName']
            http_session['mail'] = response['mail']
            http_session['site'] = 'Ludwigshafen'

        else:
            http_session['cn'] = response['email']
            http_session['firstName'] = response['given_name']
            http_session['lastName'] = response['family_name']
            http_session['fullName'] = response['name']
            http_session['mail'] = response['email']
            http_session['user_sub'] = response['sub']
            http_session['site'] = 'Ludwigshafen'

    except Exception as e:
        http_session.clear()
        return Response(
            response=f"Error processing userinfo: {str(e)}", 
            status=500, 
            mimetype="text/plain"
        )
    
    # Ensure we always have a valid fullName for the final steps
    if 'fullName' not in http_session or not http_session['fullName']:
        http_session['fullName'] = http_session.get('cn', 'Unknown User')

    next_url = http_session.pop('next', url_for('app.index'))
    http_session.modified = True  # Ensure session changes are persisted
    return redirect(next_url)


def renew_csrf_token(server_http_session):
    """get csrf token"""

    current_time = time.time()
    token_age = current_time - http_session.get('csrf_token_time', 0)

    if 'x-csrf-token' not in http_session or token_age > 600:  # 600 seconds = 10 minutes
        payload = {
            'Authorization': 'Bearer ' + http_session['bearer_token'],
            'X-API-Key': cfg.get(http_session['sap_system'], 'X-API-Key'),
            'X-CSRF-Token': 'fetch',
            'Accept': 'application/json'
        }
        
        # get first element in api_list for a ranrom base_url
        api_list = cfg.get(http_session['sap_system'], 'api_list')
        first_element = next(iter(api_list))
        
        call = server_http_session.get(f"{cfg.get(http_session['sap_system'], 'api_list', first_element, 'base_url')}", headers=payload)
        if call.status_code != 200:
            _record('renew_csrf_token_error', url=call.url, status=call.status_code)
            return redirect(url_for('error', error_type=call.status_code))
        
        http_session['x-csrf-token'] = call.headers.get('x-csrf-token')
        http_session['cookies'] = call.cookies
        http_session['csrf_token_time'] = current_time  # Update the timestamp
        http_session.modified = True  # Force session save in cloud mode
        # print('x-csrf-token:', http_session['x-csrf-token'])

    # create header with csrf token
    header_dict = {
        'Authorization': 'Bearer ' + http_session['bearer_token'],
        'X-API-Key': cfg.get(http_session['sap_system'], 'X-API-Key'),
        'Content-Type': 'application/json',  # default, will be overwritten when uploading files
        'Accept': 'application/json',
        'X-CSRF-Token': http_session['x-csrf-token']
    }
    server_http_session.headers.update(header_dict)
    server_http_session.cookies.update(http_session['cookies'])

    return

if __name__ == "__main__":
    print('this is only a module')