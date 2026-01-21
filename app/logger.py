"""
Logging utility for document migration operations.
Stores structured logs in database and provides console output.
"""

import datetime as dt
import json
from sqlalchemy import text
from app_config import MiscEngine

misc_db = MiscEngine.load()
misc_engine = misc_db.engine


class MigrationLogger:
    """Logger for migration operations."""
    
    LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    
    def __init__(self, batch_id=None, staging_id=None, console_output=True):
        self.batch_id = batch_id
        self.staging_id = staging_id
        self.console_output = console_output
    
    def _log(self, level, message, category=None, details=None):
        """Write log entry to database and optionally console."""
        try:
            # Console output
            if self.console_output:
                timestamp = dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                prefix = f"[{timestamp}] [{level}]"
                if category:
                    prefix += f" [{category}]"
                if self.batch_id:
                    prefix += f" [Batch:{self.batch_id}]"
                if self.staging_id:
                    prefix += f" [Record:{self.staging_id}]"
                print(f"{prefix} {message}")
            
            # Database storage
            details_json = None
            if details:
                if isinstance(details, (dict, list)):
                    details_json = json.dumps(details)
                else:
                    details_json = str(details)
            
            insert_query = text("""
                INSERT INTO dbo.migration_logs 
                (batch_id, staging_id, log_level, log_category, message, details)
                VALUES (:batch_id, :staging_id, :log_level, :log_category, :message, :details)
            """)
            
            with misc_engine.begin() as con:
                con.execute(insert_query, {
                    'batch_id': self.batch_id,
                    'staging_id': self.staging_id,
                    'log_level': level,
                    'log_category': category,
                    'message': message,
                    'details': details_json
                })
        except Exception as e:
            # Fallback to console if database fails
            print(f"[LOGGER_ERROR] Failed to write log: {e}")
            print(f"[{level}] {message}")
    
    def debug(self, message, category=None, details=None):
        """Log debug message."""
        self._log('DEBUG', message, category, details)
    
    def info(self, message, category=None, details=None):
        """Log info message."""
        self._log('INFO', message, category, details)
    
    def warning(self, message, category=None, details=None):
        """Log warning message."""
        self._log('WARNING', message, category, details)
    
    def error(self, message, category=None, details=None):
        """Log error message."""
        self._log('ERROR', message, category, details)
    
    def critical(self, message, category=None, details=None):
        """Log critical message."""
        self._log('CRITICAL', message, category, details)


def get_logger(batch_id=None, staging_id=None, console_output=True):
    """Factory function to create a logger instance."""
    return MigrationLogger(batch_id, staging_id, console_output)
