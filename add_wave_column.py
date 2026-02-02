"""Add wave column to migration_batch table."""
from sqlalchemy import text
from app.prepare import misc_engine

# Add wave column if it doesn't exist
with misc_engine.begin() as con:
    # Check if column exists
    result = con.execute(text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = 'migration_batch' 
        AND COLUMN_NAME = 'wave'
    """))
    exists = result.fetchone()[0] > 0
    
    if not exists:
        con.execute(text('ALTER TABLE dbo.migration_batch ADD wave VARCHAR(10)'))
        print('Wave column added successfully')
    else:
        print('Wave column already exists')
