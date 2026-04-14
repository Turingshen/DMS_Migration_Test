"""
Logging utility for document migration operations.
Stores structured logs in database and provides console output.
"""

import datetime as dt
from datetime import timezone
import json
from sqlalchemy import text
from app_config import MiscEngine

misc_db = MiscEngine.load()
misc_engine = misc_db.engine


class MigrationLogger:
    """Logger for migration operations."""
    
    LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    
    # Minimal console logging: Only show WARNING+ on console, store all in DB
    # Set to 'DEBUG' for verbose output, 'WARNING' for minimal, 'ERROR' for errors only
    CONSOLE_MIN_LEVEL = 'WARNING'
    
    def __init__(self, batch_id=None, staging_id=None, console_output=True):
        self.batch_id = batch_id
        self.staging_id = staging_id
        self.console_output = console_output
    
    def _should_print(self, level):
        """Check if level should be printed to console."""
        level_order = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'CRITICAL': 4}
        return level_order.get(level, 0) >= level_order.get(self.CONSOLE_MIN_LEVEL, 2)
    
    def _log(self, level, message, category=None, details=None):
        """Write log entry to database and optionally console."""
        try:
            # Console output - only for WARNING+ by default
            if self.console_output and self._should_print(level):
                timestamp = dt.datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                prefix = f"[{timestamp}] [{level}]"
                if category:
                    prefix += f" [{category}]"
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
