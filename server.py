from flask import Flask, render_template, send_from_directory, request, redirect, url_for
from flask import session as http_session
from flask_session import Session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import datetime
import warnings
import urllib3

# Suppress InsecureRequestWarning for direct SAP connections (verify_ssl=false)
# Both methods needed: warnings.filterwarnings for all threads, urllib3 for direct usage
warnings.filterwarnings('ignore', message='Unverified HTTPS request')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app_config import Config
cfg = Config.load()

deployment_env = (cfg.get('deployment_environment') or '').lower().strip() or 'local'
valid_envs = {'local', 'iis'}
if deployment_env not in valid_envs:
    print(f"[WARN] Unknown deployment_environment '{deployment_env}', falling back to 'local'.")
    deployment_env = 'local'


app = Flask(__name__)

"""Session / proxy profile selection
Supported deployment profiles (set via config key 'deployment_environment'):
    - local: Developer workstation (http://localhost:5000)
                    -> Secure=False, SameSite=Lax, no ProxyFix
    - iis:   Behind Microsoft IIS / ARR (X-ARR-SSL, optional X-Forwarded-Proto)
                    -> IISProxyFix, Secure cookies, SameSite=None

If 'deployment_environment' is absent or empty, default is 'local'.
"""

# Use a stable secret key (set in config; fall back to env if preferred)
app.secret_key = cfg.get('FLASK_SECRET_KEY')

class IISProxyFix:
    """Minimal middleware to recognize IIS / ARR headers.
    - If X-ARR-SSL present, force https scheme.
    - Honor X-Forwarded-Proto if provided (some IIS setups add it via URL Rewrite).
    This runs before Flask's own routing, similar to ProxyFix.
    """
    def __init__(self, app):
        self.app = app
    def __call__(self, environ, start_response):
        if 'HTTP_X_ARR_SSL' in environ:
            environ['wsgi.url_scheme'] = 'https'
        proto = environ.get('HTTP_X_FORWARDED_PROTO')
        if proto:
            environ['wsgi.url_scheme'] = proto.split(',')[0]
        return self.app(environ, start_response)

def apply_session_profile(mode: str):
    # Common base
    base = {
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_NAME': (cfg.get('SESSION_COOKIE_NAME') if hasattr(cfg, 'get') else None) or 'session'
    }
    # Decide backend & per-env settings
    if mode == 'local':
        base.update({
            'SESSION_COOKIE_SECURE': False,
            'SESSION_COOKIE_SAMESITE': 'Lax',
            'SESSION_COOKIE_DOMAIN': None,
            'PREFERRED_URL_SCHEME': 'http',
            'SESSION_TYPE': 'filesystem'
        })
        print('[INFO] Session profile: local (filesystem sessions).')

    elif mode == 'iis':
        app.wsgi_app = IISProxyFix(app.wsgi_app)
        base.update({
            'SESSION_COOKIE_SECURE': True,
            'SESSION_COOKIE_SAMESITE': 'None',
            'SESSION_COOKIE_DOMAIN': None,
            'PREFERRED_URL_SCHEME': 'https',
            'SESSION_TYPE': 'filesystem'
        })
        print('[INFO] Session profile: iis (IISProxyFix enabled, Secure + SameSite=None, filesystem sessions).')
    else:
        raise ValueError(f'Unknown session profile mode: {mode}')

    app.config.update(base)

apply_session_profile(deployment_env)

# Session + CORS setup
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(hours=12)
app.config["SESSION_FILE_DIR"] = os.path.join(os.getcwd(), 'flask_session')

# Initialize Flask-Session only for filesystem mode (local)
if app.config.get('SESSION_TYPE') == 'filesystem':
    # Ensure session directory exists
    os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
    Session(app)
    print(f'[INFO] Flask-Session initialized for filesystem storage at {app.config["SESSION_FILE_DIR"]}')

CORS(app, supports_credentials=True)

# Prevent browser caching of HTML pages (ensures template changes are picked up)
@app.after_request
def add_no_cache_headers(response):
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# Import authentication routes
import authentication as auth
app.add_url_rule('/login', view_func=auth.login)
app.add_url_rule('/callback', view_func=auth.callback)

# Register app blueprint
from app.routes import migrate_bp
app.register_blueprint(migrate_bp)

# Cleanup on startup: Reset any orphaned "executing" records from previous crashes
def cleanup_orphaned_migrations():
    """Reset records stuck in 'executing' status from previous crashed executions."""
    try:
        from app_config import MiscEngine
        from sqlalchemy import text
        misc_engine = MiscEngine.load().engine
        
        with misc_engine.begin() as con:
            # Reset executing records to pending
            result = con.execute(text("""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending'
                WHERE execution_status = 'executing'
            """))
            if result.rowcount > 0:
                print(f"[STARTUP CLEANUP] Reset {result.rowcount} orphaned 'executing' records to 'pending'")
            
            # Reset executing batch status
            batch_result = con.execute(text("""
                UPDATE dbo.migration_batch
                SET status = 'prepared'
                WHERE status = 'executing'
            """))
            if batch_result.rowcount > 0:
                print(f"[STARTUP CLEANUP] Reset {batch_result.rowcount} batches from 'executing' to 'prepared'")
                
    except Exception as e:
        print(f"[STARTUP CLEANUP] Warning: Could not cleanup orphaned migrations: {e}")

# Run cleanup on startup
cleanup_orphaned_migrations()

# Initialize / migrate DB schema once at startup
from app.db_schema import init_staging_tables
from app_config import MiscEngine as _MiscStartup
try:
    init_staging_tables(_MiscStartup.load().engine)
    print("[STARTUP] DB schema initialized")
except Exception as e:
    print(f"[STARTUP] Warning: DB schema init failed: {e}")

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# Run the application
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
