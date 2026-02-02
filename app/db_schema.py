"""
Database schema for migration staging tables.
Supports two-step migration: prepare -> validate -> execute
"""

from sqlalchemy import text

CREATE_STAGING_TABLE = """
CREATE TABLE dbo.migration_staging (
    id INT IDENTITY(1,1) PRIMARY KEY,
    batch_id VARCHAR(50) NOT NULL,
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    created_by VARCHAR(100),
    
    -- Source document identifiers
    source_documentnumber VARCHAR(25),
    source_documentpart VARCHAR(3),
    source_documenttype VARCHAR(10),
    source_documentversion VARCHAR(2),
    source_loioid VARCHAR(100),
    source_description NVARCHAR(255),
    source_dokob VARCHAR(10),
    source_objky VARCHAR(100),
    
    -- Target document identifiers (computed from source)
    target_documentnumber VARCHAR(25),
    target_documentpart VARCHAR(3),
    target_documenttype VARCHAR(10),
    target_documentversion VARCHAR(2),
    
    -- File metadata
    filename NVARCHAR(255),
    file_size_bytes INT,
    mime_type VARCHAR(100),
    authorization_group VARCHAR(20),
    
    -- Validation status
    validation_status VARCHAR(50) DEFAULT 'pending',
    validation_notes NVARCHAR(MAX),
    validated_at DATETIME2,
    validated_by VARCHAR(100),
    
    -- Execution status
    execution_status VARCHAR(50) DEFAULT 'pending',
    execution_started_at DATETIME2,
    execution_completed_at DATETIME2,
    execution_error NVARCHAR(MAX),
    
    -- Flags
    user_approved BIT DEFAULT 0,
    skip_migration BIT DEFAULT 0,
    
    INDEX idx_batch_id (batch_id),
    INDEX idx_validation_status (validation_status),
    INDEX idx_execution_status (execution_status),
    INDEX idx_user_approved (user_approved)
);
"""

CREATE_BATCH_TABLE = """
CREATE TABLE dbo.migration_batch (
    batch_id VARCHAR(50) PRIMARY KEY,
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    created_by VARCHAR(100),
    source_file NVARCHAR(255),
    total_records INT DEFAULT 0,
    approved_records INT DEFAULT 0,
    executed_records INT DEFAULT 0,
    successful_records INT DEFAULT 0,
    failed_records INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'prepared',
    description NVARCHAR(40),
    notes NVARCHAR(MAX),
    wave VARCHAR(10),
    
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
);
"""

CREATE_TRANSLATION_TABLE = """
CREATE TABLE dbo.migration_translations (
    id INT IDENTITY(1,1) PRIMARY KEY,
    -- Rule type: 'translation' (map source->target) | 'overwrite' (fixed value)
    rule_type VARCHAR(20) NOT NULL DEFAULT 'translation',
    
    -- Core mapping/target
    source_column VARCHAR(100) NOT NULL,
    target_column VARCHAR(100) NOT NULL,
    source_value NVARCHAR(255),
    target_value NVARCHAR(255) NOT NULL,
    
    -- Optional condition support (applies when column contains value)
    condition_column VARCHAR(100),
    condition_value NVARCHAR(255),
    condition_operator VARCHAR(20) DEFAULT 'contains',
    
    -- Execution order (lower numbers execute first)
    execution_order INT DEFAULT 100,
    
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    created_by VARCHAR(100),
    active BIT DEFAULT 1,
    notes NVARCHAR(MAX),
    
    INDEX idx_source_mapping (source_column, source_value),
    INDEX idx_condition (condition_column, condition_value),
    INDEX idx_active (active),
    INDEX idx_execution_order (execution_order)
);
"""

CREATE_LOG_TABLE = """
CREATE TABLE dbo.migration_logs (
    id INT IDENTITY(1,1) PRIMARY KEY,
    batch_id VARCHAR(50),
    staging_id INT,
    log_level VARCHAR(20) NOT NULL,
    log_category VARCHAR(50),
    message NVARCHAR(MAX) NOT NULL,
    details NVARCHAR(MAX),
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    
    INDEX idx_batch_id (batch_id),
    INDEX idx_staging_id (staging_id),
    INDEX idx_log_level (log_level),
    INDEX idx_created_at (created_at)
);
"""

CREATE_FILE_DETAILS_TABLE = """
CREATE TABLE dbo.migration_file_details (
    id INT IDENTITY(1,1) PRIMARY KEY,
    staging_id INT NOT NULL,
    batch_id VARCHAR(50) NOT NULL,
    
    -- File identification
    file_index INT NOT NULL,
    filename NVARCHAR(255),
    loio_id VARCHAR(100),
    
    -- File metadata
    file_size_bytes BIGINT,
    file_size_mb DECIMAL(10, 2),
    mime_type VARCHAR(100),
    
    -- Upload result
    upload_status VARCHAR(50) NOT NULL,  -- SUCCESS, UPLOAD_FAIL_xxx, SIZE_LIMIT_EXCEEDED_xxx
    http_status_code INT,
    upload_time_seconds DECIMAL(10, 2),
    
    -- Error details (from API response)
    error_category VARCHAR(50),        -- AUTH_ERROR, RATE_LIMIT, PAYLOAD_TOO_LARGE, etc.
    error_code VARCHAR(50),            -- SAP error code
    error_detail NVARCHAR(MAX),        -- Detailed error message
    error_messages NVARCHAR(MAX),      -- JSON array of SAP messages
    is_size_error BIT DEFAULT 0,
    
    -- Timestamps
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    
    -- Foreign key constraint
    CONSTRAINT FK_file_details_staging FOREIGN KEY (staging_id) 
        REFERENCES dbo.migration_staging(id) ON DELETE CASCADE,
    
    INDEX idx_staging_id (staging_id),
    INDEX idx_batch_id (batch_id),
    INDEX idx_upload_status (upload_status),
    INDEX idx_error_category (error_category),
    INDEX idx_filename (filename)
);
"""

def init_staging_tables(engine):
    """Initialize migration staging tables if they don't exist."""
    with engine.begin() as con:
        # Check and create staging table
        check_staging = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_staging'
        """)
        result = con.execute(check_staging).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_STAGING_TABLE))
            print("[DB_INIT] Created migration_staging table")
        else:
            print("[DB_INIT] migration_staging table already exists")
        
        # Check and create batch table
        check_batch = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_batch'
        """)
        result = con.execute(check_batch).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_BATCH_TABLE))
            print("[DB_INIT] Created migration_batch table")
        else:
            print("[DB_INIT] migration_batch table already exists")
        
        # Check and create translations table
        check_translations = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_translations'
        """)
        result = con.execute(check_translations).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_TRANSLATION_TABLE))
            print("[DB_INIT] Created migration_translations table")
        else:
            print("[DB_INIT] migration_translations table already exists")
            # Ensure new columns exist for migration rules
            try:
                # Drop any unique constraints that might exist
                con.execute(text("""
                    DECLARE @ConstraintName nvarchar(200)
                    SELECT @ConstraintName = CONSTRAINT_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
                    WHERE TABLE_NAME = 'migration_translations' AND CONSTRAINT_TYPE = 'UNIQUE'
                    IF @ConstraintName IS NOT NULL
                        EXEC('ALTER TABLE dbo.migration_translations DROP CONSTRAINT ' + @ConstraintName)
                """))
                
                con.execute(text("""
                    IF COL_LENGTH('dbo.migration_translations', 'rule_type') IS NULL
                        ALTER TABLE dbo.migration_translations ADD rule_type VARCHAR(20) NOT NULL DEFAULT 'translation';
                    IF COL_LENGTH('dbo.migration_translations', 'condition_column') IS NULL
                        ALTER TABLE dbo.migration_translations ADD condition_column VARCHAR(100) NULL;
                    IF COL_LENGTH('dbo.migration_translations', 'condition_value') IS NULL
                        ALTER TABLE dbo.migration_translations ADD condition_value NVARCHAR(255) NULL;
                    IF COL_LENGTH('dbo.migration_translations', 'condition_operator') IS NULL
                        ALTER TABLE dbo.migration_translations ADD condition_operator VARCHAR(20) NULL DEFAULT 'contains';
                    IF COL_LENGTH('dbo.migration_translations', 'execution_order') IS NULL
                        ALTER TABLE dbo.migration_translations ADD execution_order INT DEFAULT 100;
                """))
                print("[DB_INIT] Ensured migration_translations rule columns exist")
            except Exception as e:
                print(f"[DB_INIT_WARN] Could not alter migration_translations: {e}")
        
        # Check and create logs table
        check_logs = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_logs'
        """)
        result = con.execute(check_logs).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_LOG_TABLE))
            print("[DB_INIT] Created migration_logs table")
        else:
            print("[DB_INIT] migration_logs table already exists")
        
        # Check and create file_details table
        check_file_details = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_file_details'
        """)
        result = con.execute(check_file_details).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_FILE_DETAILS_TABLE))
            print("[DB_INIT] Created migration_file_details table")
        else:
            print("[DB_INIT] migration_file_details table already exists")
