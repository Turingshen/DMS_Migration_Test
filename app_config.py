from flask import session
import yaml
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import os
import base64
import json

# this class uses the "singleton pattern" which means that only one instance of the class is created no matter how many times the class is called

class Config():
    _instance = None
    
    # Singleton pattern
    @classmethod
    def load(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        # Load config-env.yml
        self.config_env = self._load_config_env()

    def _load_config(self, config_name, env_var_name):
        """Generic method to load YAML config files with fallback to environment variables"""
        config_file = os.path.join(os.path.dirname(__file__), f'{config_name}.yml')
        
        # Try to read from file first
        if os.path.exists(config_file):
            print(f"Loading {config_name}.yml from file: {config_file}")
            try:
                with open(config_file, 'r', encoding='utf-8') as file:
                    config = yaml.load(file, yaml.FullLoader)
                print(f"Successfully loaded {config_name}.yml from file")
            except Exception as e:
                print(f"Error reading {config_name}.yml file: {e}")
                raise Exception(f'Error reading {config_name}.yml file: {e}')
        else:
            # Fallback to environment variable
            print(f"{config_name}.yml file not found, trying environment variable...")
            config_b64 = os.getenv(env_var_name)
            if not config_b64:
                raise Exception(f'{config_name}.yml file not found and {env_var_name} environment variable not set')
            
            try:
                config_decoded = base64.b64decode(config_b64).decode('utf-8')
                config = yaml.load(config_decoded, yaml.FullLoader)
                print(f"Successfully decoded {env_var_name} from environment variable")
            except Exception as e:
                print(f"Error decoding {env_var_name} environment variable: {e}")
                raise Exception(f'Error decoding {env_var_name} environment variable: {e}')

        return config

    def _load_config_env(self):
        """Load config-env.yml directly from file, fallback to environment variable"""
        config = self._load_config('config-env', 'CONFIG_ENV_YML')
        
        # Process SAP systems
        sap_systems = {}
        for key, value in config.items():
            if isinstance(value, dict):
                # SAP system has system_label AND (X-API-Key or auth_type)
                if 'system_label' in value and ('X-API-Key' in value or 'auth_type' in value):
                    sap_systems[key] = value['system_label']
        config['sap_systems'] = sap_systems
        
        return config


    def get(self, *keys): # multiple keys allowed
        # Only search in config_env
        configs = [self.config_env]

        # Iterate through each configuration dictionary
        for config in configs:
            current_data = config
            found = True
            
            # Traverse through nested dictionaries using the keys
            for key in keys:
                if key in current_data:
                    current_data = current_data[key]
                else:
                    found = False
                    break
            
            # If all keys are found in the current configuration, return the result
            if found:
                return current_data

        # If no configuration has all the keys, report the missing keys and exit
        raise Exception(f'keys "{'" & "'.join(keys)}" not found in config')


# Database engine classes for singleton pattern
class MiscEngine():
    _instance = None
    
    # Singleton pattern
    @classmethod
    def load(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        ECHO_SQL =  False
        cfg = Config.load()
        datastore = cfg.get('db', 'misc')
        con_str = datastore['db_con_str'].format(**datastore)
        self.engine = create_engine(con_str, echo=ECHO_SQL, pool_pre_ping=True)
        
    def __enter__(self):
        return self

class DilEngine():
    _instance = None
    
    # Singleton pattern
    @classmethod
    def load(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        ECHO_SQL =  False
        cfg = Config.load()
        try:
            datastore = cfg.get('db', 'dil')
            # URL-encode the password to handle special characters like $
            encoded_pw = quote_plus(datastore['db_pw'])
            datastore_encoded = {**datastore, 'db_pw': encoded_pw}
            con_str = datastore['db_con_str'].format(**datastore_encoded)
            self.engine = create_engine(con_str, echo=ECHO_SQL, pool_pre_ping=True)
            print("[INFO] DIL database engine initialized successfully")
        except Exception as e:
            print(f"[ERROR] Failed to initialize DIL database engine: {e}")
            self.engine = None
        
    def __enter__(self):
        return self


class SapSystemManager:
    """Manages SAP system configuration with YAML defaults + DB overrides.
    
    Merge strategy:
    - YAML provides default system definitions
    - DB table dbo.sap_systems / dbo.sap_system_apis stores user overrides and new systems
    - DB entries take priority over YAML entries (matched by system_id)
    - Inactive DB entries (active=0) are excluded
    """
    
    def __init__(self, misc_engine=None):
        self._misc_engine = misc_engine
    
    @property
    def engine(self):
        if self._misc_engine is None:
            self._misc_engine = MiscEngine.load().engine
        return self._misc_engine
    
    def _get_yaml_systems(self):
        """Extract SAP system definitions from config-env.yml."""
        cfg = Config.load()
        systems = {}
        for key, value in cfg.config_env.items():
            if isinstance(value, dict) and 'system_label' in value and ('X-API-Key' in value or 'auth_type' in value or 'system_type' in value):
                apis = {}
                for api_name, api_data in value.get('api_list', {}).items():
                    if isinstance(api_data, dict) and 'base_url' in api_data:
                        apis[api_name] = {
                            'api_name': api_name,
                            'api_label': api_data.get('label', api_name),
                            'base_url': api_data['base_url'],
                            'source': 'yaml'
                        }
                systems[key] = {
                    'system_id': key,
                    'system_label': value.get('system_label', key),
                    'system_type': value.get('system_type', 'R3'),
                    'host': value.get('host', ''),
                    'auth_type': value.get('auth_type', 'oauth'),
                    'api_key': value.get('X-API-Key', ''),
                    'verify_ssl': value.get('verify_ssl', True),
                    'apis': apis,
                    'source': 'yaml',
                    'active': True
                }
        return systems
    
    def _get_db_systems(self):
        """Load SAP system overrides from DB."""
        systems = {}
        try:
            with self.engine.begin() as con:
                check = text(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='sap_systems'"
                )
                if con.execute(check).fetchone()[0] == 0:
                    return {}
                
                rows = con.execute(text(
                    "SELECT system_id, system_label, system_type, host, auth_type, "
                    "api_key, verify_ssl, active FROM dbo.sap_systems"
                )).fetchall()
                
                for row in rows:
                    sid = row[0]
                    systems[sid] = {
                        'system_id': sid,
                        'system_label': row[1],
                        'system_type': row[2],
                        'host': row[3] or '',
                        'auth_type': row[4] or 'oauth',
                        'api_key': row[5] or '',
                        'verify_ssl': bool(row[6]) if row[6] is not None else True,
                        'apis': {},
                        'source': 'db',
                        'active': bool(row[7]) if row[7] is not None else True
                    }
                
                check_apis = text(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='sap_system_apis'"
                )
                if con.execute(check_apis).fetchone()[0] > 0:
                    api_rows = con.execute(text(
                        "SELECT system_id, api_name, api_label, base_url, active "
                        "FROM dbo.sap_system_apis"
                    )).fetchall()
                    for ar in api_rows:
                        sid = ar[0]
                        if sid in systems and (ar[4] is None or bool(ar[4])):
                            systems[sid]['apis'][ar[1]] = {
                                'api_name': ar[1],
                                'api_label': ar[2] or ar[1],
                                'base_url': ar[3],
                                'source': 'db'
                            }
        except Exception as e:
            print(f"[WARN] Could not load DB SAP systems: {e}")
        return systems
    
    def get_merged_systems(self):
        """Return merged dict: YAML defaults + DB overrides (DB wins)."""
        yaml_systems = self._get_yaml_systems()
        db_systems = self._get_db_systems()
        
        merged = {}
        for sid, sys_data in yaml_systems.items():
            merged[sid] = dict(sys_data)
        
        for sid, db_data in db_systems.items():
            if not db_data.get('active', True):
                merged.pop(sid, None)
                continue
            if sid in merged:
                yaml_apis = merged[sid].get('apis', {})
                db_apis = db_data.get('apis', {})
                merged[sid].update({k: v for k, v in db_data.items() if k != 'apis'})
                merged[sid]['source'] = 'db+yaml'
                final_apis = dict(yaml_apis)
                final_apis.update(db_apis)
                merged[sid]['apis'] = final_apis
            else:
                merged[sid] = dict(db_data)
        
        return merged
    
    def get_system(self, system_id):
        """Get a single merged system by ID."""
        return self.get_merged_systems().get(system_id)
    
    def save_system(self, system_id, system_label, system_type, host='',
                    auth_type='oauth', api_key='', verify_ssl=True, updated_by='system'):
        """Save/update a SAP system in DB."""
        with self.engine.begin() as con:
            existing = con.execute(text(
                "SELECT id FROM dbo.sap_systems WHERE system_id = :sid"
            ), {'sid': system_id}).fetchone()
            
            if existing:
                con.execute(text(
                    "UPDATE dbo.sap_systems "
                    "SET system_label = :label, system_type = :stype, host = :host, "
                    "auth_type = :auth, api_key = :key, verify_ssl = :ssl, "
                    "active = 1, updated_at = GETUTCDATE(), updated_by = :by "
                    "WHERE system_id = :sid"
                ), {
                    'sid': system_id, 'label': system_label, 'stype': system_type,
                    'host': host, 'auth': auth_type, 'key': api_key,
                    'ssl': 1 if verify_ssl else 0, 'by': updated_by
                })
            else:
                con.execute(text(
                    "INSERT INTO dbo.sap_systems "
                    "(system_id, system_label, system_type, host, auth_type, api_key, "
                    "verify_ssl, active, created_by, updated_by) "
                    "VALUES (:sid, :label, :stype, :host, :auth, :key, :ssl, 1, :by, :by)"
                ), {
                    'sid': system_id, 'label': system_label, 'stype': system_type,
                    'host': host, 'auth': auth_type, 'key': api_key,
                    'ssl': 1 if verify_ssl else 0, 'by': updated_by
                })
    
    def delete_system(self, system_id):
        """Soft-delete a system (set active=0). Only affects DB entries."""
        with self.engine.begin() as con:
            existing = con.execute(text(
                "SELECT id FROM dbo.sap_systems WHERE system_id = :sid"
            ), {'sid': system_id}).fetchone()
            
            if existing:
                con.execute(text(
                    "UPDATE dbo.sap_systems SET active = 0, updated_at = GETUTCDATE() "
                    "WHERE system_id = :sid"
                ), {'sid': system_id})
                con.execute(text(
                    "UPDATE dbo.sap_system_apis SET active = 0, updated_at = GETUTCDATE() "
                    "WHERE system_id = :sid"
                ), {'sid': system_id})
                return True
            return False
    
    def save_api(self, system_id, api_name, base_url, api_label=None):
        """Save/update an API endpoint for a system."""
        with self.engine.begin() as con:
            existing = con.execute(text(
                "SELECT id FROM dbo.sap_system_apis WHERE system_id = :sid AND api_name = :name"
            ), {'sid': system_id, 'name': api_name}).fetchone()
            
            if existing:
                con.execute(text(
                    "UPDATE dbo.sap_system_apis "
                    "SET base_url = :url, api_label = :label, active = 1, updated_at = GETUTCDATE() "
                    "WHERE system_id = :sid AND api_name = :name"
                ), {'sid': system_id, 'name': api_name, 'url': base_url, 'label': api_label or api_name})
            else:
                con.execute(text(
                    "INSERT INTO dbo.sap_system_apis (system_id, api_name, api_label, base_url, active) "
                    "VALUES (:sid, :name, :label, :url, 1)"
                ), {'sid': system_id, 'name': api_name, 'url': base_url, 'label': api_label or api_name})
    
    def delete_api(self, system_id, api_name):
        """Soft-delete an API endpoint."""
        with self.engine.begin() as con:
            con.execute(text(
                "UPDATE dbo.sap_system_apis SET active = 0, updated_at = GETUTCDATE() "
                "WHERE system_id = :sid AND api_name = :name"
            ), {'sid': system_id, 'name': api_name})
    
    def update_config_env(self):
        """Update the in-memory config_env with merged system data.
        
        This patches the Config singleton so that cfg.get('zhl', 'api_list', 'document', 'base_url')
        continues to work transparently with DB-overridden values.
        """
        cfg = Config.load()
        merged = self.get_merged_systems()
        
        sap_systems = {}
        for sid, sys_data in merged.items():
            if not sys_data.get('active', True):
                continue
            sap_systems[sid] = sys_data['system_label']
            
            system_entry = {
                'system_label': sys_data['system_label'],
                'system_type': sys_data['system_type'],
                'host': sys_data.get('host', ''),
            }
            if sys_data.get('auth_type') == 'basic':
                system_entry['auth_type'] = 'basic'
            if sys_data.get('verify_ssl') is False:
                system_entry['verify_ssl'] = False
            if sys_data.get('api_key'):
                system_entry['X-API-Key'] = sys_data['api_key']
            
            api_list = {}
            for api_name, api_data in sys_data.get('apis', {}).items():
                api_list[api_name] = {
                    'label': api_data.get('api_label', api_name),
                    'base_url': api_data['base_url']
                }
            if api_list:
                system_entry['api_list'] = api_list
            
            cfg.config_env[sid] = system_entry
        
        cfg.config_env['sap_systems'] = sap_systems