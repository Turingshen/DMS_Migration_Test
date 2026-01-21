from flask import session
import yaml
import pandas as pd
from sqlalchemy import create_engine
from urllib.parse import quote_plus
import os
import base64

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
                api_header = ['system_label', 'X-API-Key'] # items to identify the api entry
                if all(item in value for item in api_header):
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