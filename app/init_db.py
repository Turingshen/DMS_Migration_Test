"""
Initialization script for document migration module.
Run this once to set up database tables.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app_config import MiscEngine
from app.db_schema import init_staging_tables

def initialize():
    """Initialize migration staging tables in the database."""
    try:
        print("="*60)
        print("Document Migration - Database Initialization")
        print("="*60)
        print()
        
        print("[1/2] Loading database engine...")
        misc_db = MiscEngine.load()
        misc_engine = misc_db.engine
        print("✓ Database engine loaded")
        print()
        
        print("[2/2] Creating staging tables...")
        init_staging_tables(misc_engine)
        print("✓ Staging tables created/verified")
        print()
        
        print("="*60)
        print("Initialization completed successfully!")
        print("="*60)
        print()
        print("Next steps:")
        print("1. Navigate to /prepare in your browser")
        print("2. Prepare your first migration batch")
        print("3. Validate and approve records")
        print("4. Execute the migration")
        print()
        
        return True
        
    except Exception as e:
        print()
        print("="*60)
        print("ERROR: Initialization failed")
        print("="*60)
        print()
        print(f"Error message: {e}")
        print()
        print("Troubleshooting:")
        print("- Check database connection in app_config.py")
        print("- Ensure 'misc' database engine is configured")
        print("- Verify database user has CREATE TABLE permissions")
        print()
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = initialize()
    sys.exit(0 if success else 1)
