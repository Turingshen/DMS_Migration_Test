"""
Encrypted credential storage for SAP Direct (ZV) systems.

Uses Fernet symmetric encryption derived from FLASK_SECRET_KEY.
Credentials are stored encrypted in the MISC database (dbo.sap_credentials).
"""
import base64
import hashlib
from cryptography.fernet import Fernet
from sqlalchemy import text

from app_config import Config, MiscEngine

cfg = Config.load()
misc_db = MiscEngine.load()
misc_engine = misc_db.engine


def _get_fernet():
    """Derive a Fernet key from FLASK_SECRET_KEY."""
    secret = cfg.get('FLASK_SECRET_KEY')
    # Fernet needs a 32-byte URL-safe base64-encoded key
    key_bytes = hashlib.sha256(secret.encode('utf-8')).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64 token."""
    if not plaintext:
        return ''
    f = _get_fernet()
    return f.encrypt(plaintext.encode('utf-8')).decode('utf-8')


def decrypt(token: str) -> str:
    """Decrypt a Fernet token back to plaintext."""
    if not token:
        return ''
    f = _get_fernet()
    return f.decrypt(token.encode('utf-8')).decode('utf-8')


def save_credentials(system_id: str, username: str, password: str, updated_by: str = 'system', sap_client: str = None, description: str = None, host: str = None):
    """Save encrypted credentials for a SAP system.
    
    Upserts (inserts or updates) the credentials in dbo.sap_credentials.
    If password is empty and the entry already exists, the existing password is kept.
    sap_client: optional 3-digit SAP Mandant (e.g. '100', '200').
    description: optional custom system description.
    host: optional hostname for direct connections (e.g. 'zvfr3.basf.net').
    """
    enc_user = encrypt(username)

    with misc_engine.begin() as con:
        # Check if entry already exists
        existing = con.execute(
            text("SELECT id FROM dbo.sap_credentials WHERE system_id = :sid"),
            {'sid': system_id}
        ).fetchone()

        if existing:
            if password:
                enc_pass = encrypt(password)
                con.execute(text("""
                    UPDATE dbo.sap_credentials 
                    SET username_enc = :user, password_enc = :pw, sap_client = :client,
                        description = :desc, host = :host, updated_at = GETUTCDATE(), updated_by = :by
                    WHERE system_id = :sid
                """), {'user': enc_user, 'pw': enc_pass, 'client': sap_client, 'desc': description, 'host': host, 'by': updated_by, 'sid': system_id})
            else:
                con.execute(text("""
                    UPDATE dbo.sap_credentials 
                    SET username_enc = :user, sap_client = :client,
                        description = :desc, host = :host, updated_at = GETUTCDATE(), updated_by = :by
                    WHERE system_id = :sid
                """), {'user': enc_user, 'client': sap_client, 'desc': description, 'host': host, 'by': updated_by, 'sid': system_id})
        else:
            enc_pass = encrypt(password)
            con.execute(text("""
                INSERT INTO dbo.sap_credentials (system_id, username_enc, password_enc, sap_client, description, host, updated_by)
                VALUES (:sid, :user, :pw, :client, :desc, :host, :by)
            """), {'sid': system_id, 'user': enc_user, 'pw': enc_pass, 'client': sap_client, 'desc': description, 'host': host, 'by': updated_by})


def get_credentials(system_id: str) -> dict | None:
    """Retrieve decrypted credentials for a SAP system.
    
    Returns {'username': ..., 'password': ..., 'sap_client': ...} or None if not found.
    """
    with misc_engine.connect() as con:
        row = con.execute(
            text("SELECT username_enc, password_enc, sap_client FROM dbo.sap_credentials WHERE system_id = :sid"),
            {'sid': system_id}
        ).fetchone()

    if not row:
        return None

    return {
        'username': decrypt(row[0]),
        'password': decrypt(row[1]),
        'sap_client': row[2] or None
    }


def has_credentials(system_id: str) -> bool:
    """Check if credentials exist for a system (without decrypting)."""
    with misc_engine.connect() as con:
        row = con.execute(
            text("SELECT COUNT(*) FROM dbo.sap_credentials WHERE system_id = :sid"),
            {'sid': system_id}
        ).fetchone()
    return row[0] > 0


def get_credential_info(system_id: str) -> dict | None:
    """Get credential metadata (username plaintext, password masked, timestamps).
    
    Returns info dict or None.
    """
    with misc_engine.connect() as con:
        row = con.execute(text("""
            SELECT username_enc, updated_at, updated_by, sap_client, description, host 
            FROM dbo.sap_credentials 
            WHERE system_id = :sid
        """), {'sid': system_id}).fetchone()

    if not row:
        return None

    return {
        'username': decrypt(row[0]),
        'updated_at': row[1].isoformat() if row[1] else None,
        'updated_by': row[2],
        'sap_client': row[3] or None,
        'description': row[4] or None,
        'host': row[5] or None
    }


def delete_credentials(system_id: str) -> bool:
    """Delete credentials for a system. Returns True if deleted."""
    with misc_engine.begin() as con:
        result = con.execute(
            text("DELETE FROM dbo.sap_credentials WHERE system_id = :sid"),
            {'sid': system_id}
        )
    return result.rowcount > 0


def list_basic_auth_systems() -> list[str]:
    """Return list of system IDs that use Basic Auth (from config)."""
    systems = []
    config = cfg.config_env
    for key, value in config.items():
        if isinstance(value, dict) and value.get('auth_type') == 'basic':
            systems.append(key)
    return systems


def list_all_sap_systems() -> list[dict]:
    """Return list of all SAP systems with their auth type and system type."""
    systems = []
    config = cfg.config_env
    for key, value in config.items():
        if isinstance(value, dict) and 'system_label' in value and 'system_type' in value:
            systems.append({
                'system_id': key,
                'system_label': value['system_label'],
                'system_type': value['system_type'],
                'auth_type': value.get('auth_type', 'oauth'),
            })
    return systems


def list_db_only_credentials(known_ids: list[str]) -> list[dict]:
    """Return credential rows whose system_id is NOT in *known_ids*.

    These are "custom" systems created purely through the credentials UI.
    """
    with misc_engine.connect() as con:
        rows = con.execute(text(
            "SELECT system_id, username_enc, updated_at, updated_by, sap_client, description, host "
            "FROM dbo.sap_credentials"
        )).fetchall()
    result = []
    for r in rows:
        if r[0] not in known_ids:
            result.append({
                'system_id': r[0],
                'username': decrypt(r[1]),
                'updated_at': r[2].isoformat() if r[2] else None,
                'updated_by': r[3],
                'sap_client': r[4] or None,
                'description': r[5] or None,
                'host': r[6] or None,
            })
    return result
