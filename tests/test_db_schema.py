"""
Unit tests for app/db_schema.py - Database schema functions.
"""
import pytest


class TestInitStagingTables:
    """Tests for init_staging_tables() function."""
    
    def test_tables_exist_after_init(self, misc_engine):
        """Verify tables are created by init function."""
        from app.db_schema import init_staging_tables
        from sqlalchemy import text
        
        # Run init
        init_staging_tables(misc_engine)
        
        # Check tables exist
        with misc_engine.connect() as con:
            result = con.execute(text("""
                SELECT TABLE_NAME 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'dbo' 
                AND TABLE_NAME IN ('migration_batch', 'migration_staging', 'migration_file_details')
            """)).fetchall()
        
        table_names = [r[0] for r in result]
        assert 'migration_batch' in table_names
        assert 'migration_staging' in table_names
    
    def test_idempotent(self, misc_engine):
        """Running init multiple times should not fail."""
        from app.db_schema import init_staging_tables
        
        # Run twice - should not raise
        init_staging_tables(misc_engine)
        init_staging_tables(misc_engine)


class TestDatabaseConnectivity:
    """Basic database connectivity tests."""
    
    def test_misc_connection(self, misc_engine):
        """Test MISC database is accessible."""
        from sqlalchemy import text
        
        with misc_engine.connect() as con:
            result = con.execute(text("SELECT 1 as test")).fetchone()
        
        assert result[0] == 1
    
    def test_dil_connection(self, dil_engine):
        """Test DIL database is accessible."""
        from sqlalchemy import text
        
        with dil_engine.connect() as con:
            result = con.execute(text("SELECT 1 as test FROM DUMMY")).fetchone()
        
        assert result[0] == 1
