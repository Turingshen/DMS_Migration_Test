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
    source_object_links NVARCHAR(MAX),
    excluded_object_links NVARCHAR(MAX),
    source_document_status VARCHAR(20),
    
    -- Target document identifiers (computed from source)
    target_documentnumber VARCHAR(25),
    target_documentnumber_sanitized NVARCHAR(25),
    target_documentpart VARCHAR(3),
    target_documenttype VARCHAR(10),
    target_documentversion VARCHAR(2),
    target_document_status VARCHAR(20),
    
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
    
    -- Object link status (Phase 2)
    link_status VARCHAR(50) DEFAULT 'pending',
    link_error NVARCHAR(MAX),
    link_completed_at DATETIME2,
    
    -- Storage type: KPRO (file-based) or DB (DRAO/database-stored)
    ablage VARCHAR(10) DEFAULT 'KPRO',
    
    -- Flags
    user_approved BIT DEFAULT 0,
    skip_migration BIT DEFAULT 0,
    container_created BIT DEFAULT 0,
    
    INDEX idx_batch_id (batch_id),
    INDEX idx_validation_status (validation_status),
    INDEX idx_execution_status (execution_status),
    INDEX idx_link_status (link_status),
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
    migration_phase VARCHAR(20) DEFAULT 'upload',
    description NVARCHAR(40),
    notes NVARCHAR(MAX),
    wave VARCHAR(10),
    
    INDEX idx_status (status),
    INDEX idx_migration_phase (migration_phase),
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

CREATE_OBJECT_MAPPING_TABLE = """
CREATE TABLE dbo.migration_object_mapping (
    id INT IDENTITY(1,1) PRIMARY KEY,
    
    -- Batch reference (mapping belongs to a specific batch)
    batch_id VARCHAR(50) NOT NULL,
    
    -- Source object identification (from R/3)
    source_dokob VARCHAR(10) NOT NULL,       -- Object Type: IFLOT, PMQMEL, PMAUFK, etc.
    source_objky VARCHAR(100) NOT NULL,      -- Object Key in source system
    
    -- Target object identification (for S/4HANA)
    target_dokob VARCHAR(10) NOT NULL,       -- Target Object Type (usually same as source)
    target_objky VARCHAR(100) NOT NULL,      -- Object Key in target system
    
    -- Metadata
    description NVARCHAR(255),               -- Optional description
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    created_by VARCHAR(100),
    active BIT DEFAULT 1,
    
    -- Constraints and indexes
    INDEX idx_batch_id (batch_id),
    INDEX idx_source_lookup (batch_id, source_dokob, source_objky),
    INDEX idx_target_lookup (target_dokob, target_objky),
    INDEX idx_active (active)
);
"""

CREATE_DOKOB_STRATEGY_TABLE = """
CREATE TABLE dbo.migration_dokob_strategy (
    id INT IDENTITY(1,1) PRIMARY KEY,
    batch_id VARCHAR(50) NOT NULL,
    dokob VARCHAR(10) NOT NULL,
    source_method VARCHAR(20) NOT NULL DEFAULT 'none',  -- 'none','dil'
    target_method VARCHAR(20) NOT NULL DEFAULT 'none',  -- 'none','api','excel','1:1'
    strno_prefix_old VARCHAR(10) NULL,  -- IFLOT: old STRNO prefix (e.g. 'UTMC')
    strno_prefix_new VARCHAR(10) NULL,  -- IFLOT: new STRNO prefix (e.g. 'US1M')
    updated_at DATETIME2 DEFAULT GETUTCDATE(),
    updated_by VARCHAR(100),
    
    CONSTRAINT uq_batch_dokob UNIQUE (batch_id, dokob),
    INDEX idx_batch_id (batch_id)
);
"""

# ---------------------------------------------------------------------------
# Exclusion tables: per batch + dokob, store DIL query and excluded keys
# ---------------------------------------------------------------------------

CREATE_EXCLUSION_QUERY_TABLE = """
CREATE TABLE dbo.migration_exclusion_query (
    id INT IDENTITY(1,1) PRIMARY KEY,
    batch_id VARCHAR(50) NOT NULL,
    dokob VARCHAR(10) NOT NULL,              -- Object type: IFLOT, EQUI, PMQMEL, ...
    dil_query NVARCHAR(MAX) NOT NULL,        -- The SELECT statement run against DIL (HANA)
    updated_at DATETIME2 DEFAULT GETUTCDATE(),
    updated_by VARCHAR(100),
    
    CONSTRAINT uq_excl_query_batch_dokob UNIQUE (batch_id, dokob),
    INDEX idx_excl_query_batch (batch_id)
);
"""

CREATE_EXCLUSION_KEYS_TABLE = """
CREATE TABLE dbo.migration_exclusion_keys (
    id INT IDENTITY(1,1) PRIMARY KEY,
    batch_id VARCHAR(50) NOT NULL,
    dokob VARCHAR(10) NOT NULL,              -- Object type: IFLOT, EQUI, PMQMEL, ...
    objky VARCHAR(100) NOT NULL,             -- Object key to exclude
    label NVARCHAR(255),                     -- Human-readable label (e.g. PLTXT, description)
    excluded_at DATETIME2 DEFAULT GETUTCDATE(),
    excluded_by VARCHAR(100),
    
    CONSTRAINT uq_excl_key UNIQUE (batch_id, dokob, objky),
    INDEX idx_excl_keys_batch (batch_id),
    INDEX idx_excl_keys_batch_dokob (batch_id, dokob)
);
"""

CREATE_EXCLUSION_QUERY_RESULTS_TABLE = """
CREATE TABLE dbo.migration_exclusion_query_results (
    id INT IDENTITY(1,1) PRIMARY KEY,
    batch_id VARCHAR(50) NOT NULL,
    dokob VARCHAR(10) NOT NULL,
    objky NVARCHAR(255) NOT NULL,             -- Mapped object key from selected column
    label NVARCHAR(500),                      -- Human-readable label from other columns
    row_data NVARCHAR(MAX),                   -- Full row as JSON for display
    queried_at DATETIME2 DEFAULT GETUTCDATE(),
    INDEX idx_exqr_batch_dokob (batch_id, dokob),
    INDEX idx_exqr_objky (batch_id, dokob, objky)
);
"""

# All supported DOKOB types with labels
EXCLUSION_DOKOB_TYPES = {
    'EQUI':      'Equipment',
    'IFLOT':     'Techn. Platz',
    'MPLA':      'Wartungsplan',
    'IMPTT':     'Messpunkt',
    'PMPLKO':    'Arbeitsplan (Tasklist)',
    'PMAUFK':    'Instandhaltungsauftrag',
    'PMAFVC':    'Auftragsvorgang',
    'PMQMEL':    'Meldung (Notification)',
    'STKO_DOC':  'Stückliste Kopf (BOM)',
    'STPO_DOC':  'Stückliste Position',
}

# Exclusion Excel template: sheet definitions per DOKOB
# Each sheet has a key column that maps to DRAD.OBJKY for that type
EXCLUSION_EXCEL_SHEETS = {
    'IFLOT':    {'key_column': 'TPLNR',  'label': 'Techn. Platz',             'example': 'ES11-100040-V3-0100-V-H621'},
    'EQUI':     {'key_column': 'EQUNR',  'label': 'Equipment',                'example': '000000000010045678'},
    'MPLA':     {'key_column': 'WARPL',  'label': 'Wartungsplan',             'example': '000000015456'},
    'IMPTT':    {'key_column': 'POINT',  'label': 'Messpunkt',               'example': '000000001234'},
    'PMPLKO':   {'key_column': 'OBJKY',  'label': 'Arbeitsplan (PLNTY+PLNNR+PLNAL)',   'example': 'A00XV123401',
                 'extra_examples': [
                     ('E0005458001', 'Beispiel Typ E (Einzelplan)'),
                     ('T0006187001', 'Beispiel Typ T (Standardplan)'),
                 ]},
    'PMAUFK':   {'key_column': 'AUFNR',  'label': 'Instandhaltungsauftrag',   'example': '000004002345'},
    'PMAFVC':   {'key_column': 'OBJNR',  'label': 'Auftragsvorgang (OBJNR)',  'example': 'OV109274004300000001'},
    'PMQMEL':   {'key_column': 'QMNUM',  'label': 'Meldung (Notification)',   'example': '000300012345'},
    'STKO_DOC': {'key_column': 'STKO.GUIDX',  'label': 'Stückliste Kopf (BOM)',    'example': '000C296592A71EDB9EF2BAE31B1D442A'},
    'STPO_DOC': {'key_column': 'STPO.GUIDX',  'label': 'Stückliste Position',      'example': '000C296592A71EDC80A463380E9EC27E'},
}

# Default DIL queries per DOKOB type (used when no custom query is stored yet)
DEFAULT_EXCLUSION_QUERIES = {
    'IFLOT': """SELECT DISTINCT
    iflot.TPLNR  AS objky,
    iflot.PLTXT  AS label
FROM DIL.IFLOT iflot
JOIN DIL.DRAD  drad ON drad.OBJKY = iflot.TPLNR AND drad.DOKOB = 'IFLOT'
WHERE iflot.IWERK = '{{IWERK}}'
ORDER BY iflot.TPLNR""",

    'PMAFVC': """SELECT IFLOS.STRNO, IFLOT.TPLNR, AFVC.OBJNR
FROM DIL.AFVC
INNER JOIN DIL.AUFKO ON AUFKO.AUFPL = AFVC.AUFPL
INNER JOIN DIL.AFIH  ON AFIH.AUFNR  = AUFKO.AUFNR
INNER JOIN DIL.ILOA  ON ILOA.ILOAN  = AFIH.ILOAN
INNER JOIN DIL.IFLOT ON IFLOT.TPLNR = ILOA.TPLNR
INNER JOIN DIL.IFLOS ON IFLOS.TPLNR = IFLOT.TPLNR
INNER JOIN DIL.JEST  ON JEST.OBJNR  = IFLOT.OBJNR
WHERE IFLOT.IWERK IN ('ES11','ES19','ES1P','ES1R','ES81')
  AND IFLOS.ACTVS = 'X'
  AND JEST.STAT LIKE 'I%'
  AND (JEST.INACT = '' OR JEST.INACT IS NULL)
  AND IFLOT.OBJNR LIKE 'IF%'
  AND ILOA.OWNER = '6'
  AND AFIH.AUFNR IS NOT NULL AND AFIH.AUFNR <> ''
  AND AFVC.OBJNR LIKE 'OV%'
  AND EXISTS (
      SELECT 1 FROM DIL.IFLOS f
      WHERE f.TPLNR = IFLOT.TPLNR
        AND (
              f.STRNO LIKE 'ES11-100040%' OR
              f.STRNO LIKE 'ES11-430102%' OR
              f.STRNO LIKE 'ES11-670607%' OR
              f.STRNO LIKE 'ES11-100050%' OR
              f.STRNO LIKE 'ES11-604003%' OR
              f.STRNO LIKE 'ES11-652017%' OR
              f.STRNO LIKE 'ES11-652018%' OR
              f.STRNO LIKE 'ES11-660001%' OR
              f.STRNO LIKE 'ES11-660000%' OR
              f.STRNO LIKE 'ES11-170040%' OR
              f.STRNO LIKE 'ES11-645009%' OR
              f.STRNO LIKE 'ES11-170050%'
          )
  )
GROUP BY IFLOS.STRNO, IFLOT.TPLNR, AFVC.OBJNR
HAVING SUM(CASE WHEN JEST.STAT IN ('I0013','I0076') THEN 1 ELSE 0 END) = 0
ORDER BY IFLOT.TPLNR""",
}

CREATE_CREDENTIALS_TABLE = """
CREATE TABLE dbo.sap_credentials (
    id INT IDENTITY(1,1) PRIMARY KEY,
    system_id VARCHAR(50) NOT NULL UNIQUE,   -- e.g. 'zvfr3'
    username_enc NVARCHAR(500) NOT NULL,     -- Fernet-encrypted username
    password_enc NVARCHAR(500) NOT NULL,     -- Fernet-encrypted password
    updated_at DATETIME2 DEFAULT GETUTCDATE(),
    updated_by VARCHAR(100),
    
    INDEX idx_system_id (system_id)
);
"""

CREATE_SAP_SYSTEMS_TABLE = """
CREATE TABLE dbo.sap_systems (
    id INT IDENTITY(1,1) PRIMARY KEY,
    system_id VARCHAR(50) NOT NULL UNIQUE,     -- e.g. 'zhl', 'zvfr3'
    system_label NVARCHAR(200) NOT NULL,       -- e.g. 'ZHL Testsystem Ludwigshafen'
    system_type VARCHAR(10) NOT NULL,          -- 'R3' or 'S4'
    host VARCHAR(255),                         -- e.g. 'qa-sap.api.basf.com:443'
    auth_type VARCHAR(20) DEFAULT 'oauth',     -- 'oauth' or 'basic'
    api_key VARCHAR(255),                      -- X-API-Key (for oauth systems)
    verify_ssl BIT DEFAULT 1,                  -- SSL certificate verification
    active BIT DEFAULT 1,
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    created_by VARCHAR(100),
    updated_at DATETIME2 DEFAULT GETUTCDATE(),
    updated_by VARCHAR(100),
    
    INDEX idx_system_id (system_id),
    INDEX idx_system_type (system_type),
    INDEX idx_active (active)
);
"""

CREATE_SAP_SYSTEM_APIS_TABLE = """
CREATE TABLE dbo.sap_system_apis (
    id INT IDENTITY(1,1) PRIMARY KEY,
    system_id VARCHAR(50) NOT NULL,            -- FK to sap_systems.system_id
    api_name VARCHAR(50) NOT NULL,             -- e.g. 'document', 'attachment', 'equipment'
    api_label NVARCHAR(100),                   -- e.g. 'Document', 'Attachment'
    base_url VARCHAR(500) NOT NULL,            -- Full base URL for the API
    active BIT DEFAULT 1,
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    updated_at DATETIME2 DEFAULT GETUTCDATE(),
    
    CONSTRAINT UQ_system_api UNIQUE (system_id, api_name),
    INDEX idx_system_id (system_id),
    INDEX idx_active (active)
);
"""

CREATE_WAVE_PLAN_TABLE = """
CREATE TABLE dbo.migration_wave_plan (
    id INT IDENTITY(1,1) PRIMARY KEY,
    wave_name VARCHAR(20) NOT NULL UNIQUE,           -- e.g. 'Wave 1'
    
    -- Qual (Test system) - Load
    qual_load_start DATE,
    qual_load_end DATE,
    qual_load_status VARCHAR(20) DEFAULT 'vorbereitung',
    
    -- Qual (Test system) - Verlinkung
    qual_link_start DATE,
    qual_link_end DATE,
    qual_link_status VARCHAR(20) DEFAULT 'vorbereitung',
    
    -- Prod (Production system) - Load
    prod_load_start DATE,
    prod_load_end DATE,
    prod_load_status VARCHAR(20) DEFAULT 'vorbereitung',
    
    -- Prod (Production system) - Verlinkung
    prod_link_start DATE,
    prod_link_end DATE,
    prod_link_status VARCHAR(20) DEFAULT 'vorbereitung',
    
    notes NVARCHAR(MAX),
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    updated_at DATETIME2 DEFAULT GETUTCDATE(),
    
    INDEX idx_wave_name (wave_name)
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
        
        # Check and create object_mapping table
        check_object_mapping = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_object_mapping'
        """)
        result = con.execute(check_object_mapping).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_OBJECT_MAPPING_TABLE))
            print("[DB_INIT] Created migration_object_mapping table")
        else:
            print("[DB_INIT] migration_object_mapping table already exists")
            # Ensure batch_id column exists (migration from global to batch-specific)
            check_batch_id = text("""
                SELECT COL_LENGTH('dbo.migration_object_mapping', 'batch_id')
            """)
            col_exists = con.execute(check_batch_id).fetchone()[0]
            if col_exists is None:
                try:
                    # Add column as nullable first
                    con.execute(text("ALTER TABLE dbo.migration_object_mapping ADD batch_id VARCHAR(50) NULL"))
                    # Set default for existing rows
                    con.execute(text("UPDATE dbo.migration_object_mapping SET batch_id = 'LEGACY' WHERE batch_id IS NULL"))
                    # Make NOT NULL after setting defaults
                    con.execute(text("ALTER TABLE dbo.migration_object_mapping ALTER COLUMN batch_id VARCHAR(50) NOT NULL"))
                    print("[DB_INIT] Added batch_id column to migration_object_mapping")
                except Exception as e:
                    print(f"[DB_INIT_WARN] Could not add batch_id column: {e}")
            else:
                print("[DB_INIT] migration_object_mapping already has batch_id column")
        
        # Ensure target_dokob and target_objky columns exist in staging table
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'target_dokob') IS NULL
                    ALTER TABLE dbo.migration_staging ADD target_dokob VARCHAR(10) NULL;
                IF COL_LENGTH('dbo.migration_staging', 'target_objky') IS NULL
                    ALTER TABLE dbo.migration_staging ADD target_objky VARCHAR(100) NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has target_dokob/target_objky columns")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add target object columns: {e}")
        
        # Ensure container_created flag exists (for idempotent retries)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'container_created') IS NULL
                    ALTER TABLE dbo.migration_staging ADD container_created BIT DEFAULT 0;
            """))
            print("[DB_INIT] Ensured migration_staging has container_created column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add container_created column: {e}")
        
        # Phase 2: Object link tracking columns
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'link_status') IS NULL
                    ALTER TABLE dbo.migration_staging ADD link_status VARCHAR(50) DEFAULT 'pending';
                IF COL_LENGTH('dbo.migration_staging', 'link_error') IS NULL
                    ALTER TABLE dbo.migration_staging ADD link_error NVARCHAR(MAX) NULL;
                IF COL_LENGTH('dbo.migration_staging', 'link_completed_at') IS NULL
                    ALTER TABLE dbo.migration_staging ADD link_completed_at DATETIME2 NULL;
                -- Backfill NULL link_status to 'pending' for existing records
                UPDATE dbo.migration_staging SET link_status = 'pending' WHERE link_status IS NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has link_status/link_error/link_completed_at columns")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add link columns: {e}")
        
        # Document status columns (InternalDocumentStatus mapping)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'source_document_status') IS NULL
                    ALTER TABLE dbo.migration_staging ADD source_document_status VARCHAR(20) NULL;
                IF COL_LENGTH('dbo.migration_staging', 'target_document_status') IS NULL
                    ALTER TABLE dbo.migration_staging ADD target_document_status VARCHAR(20) NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has source/target_document_status columns")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add document_status columns: {e}")
        
        # Phase tracking for batch table
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_batch', 'migration_phase') IS NULL
                    ALTER TABLE dbo.migration_batch ADD migration_phase VARCHAR(20) DEFAULT 'upload';
            """))
            print("[DB_INIT] Ensured migration_batch has migration_phase column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add migration_phase column: {e}")

        # Execution start timestamp for scoping partial counts in progress endpoint
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_batch', 'last_execution_started_at') IS NULL
                    ALTER TABLE dbo.migration_batch ADD last_execution_started_at DATETIME2 NULL;
            """))
            print("[DB_INIT] Ensured migration_batch has last_execution_started_at column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add last_execution_started_at column: {e}")

        # Storage type column: KPRO (file-based) or DB (DRAO/database-stored)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'ablage') IS NULL
                    ALTER TABLE dbo.migration_staging ADD ablage VARCHAR(10) DEFAULT 'KPRO';
            """))
            print("[DB_INIT] Ensured migration_staging has ablage column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add ablage column: {e}")

        # Sanitized document number (DOKNR with slashes, umlauts, etc. fixed)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'target_documentnumber_sanitized') IS NULL
                    ALTER TABLE dbo.migration_staging ADD target_documentnumber_sanitized NVARCHAR(25) NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has target_documentnumber_sanitized column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add target_documentnumber_sanitized column: {e}")

        # Source object links (JSON array of all DOKOB/OBJKY pairs for a document)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'source_object_links') IS NULL
                    ALTER TABLE dbo.migration_staging ADD source_object_links NVARCHAR(MAX) NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has source_object_links column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add source_object_links column: {e}")

        # Excluded object links (JSON array of links removed by exclusion rules)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'excluded_object_links') IS NULL
                    ALTER TABLE dbo.migration_staging ADD excluded_object_links NVARCHAR(MAX) NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has excluded_object_links column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add excluded_object_links column: {e}")

        # File count columns (source vs target comparison)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'source_file_count') IS NULL
                    ALTER TABLE dbo.migration_staging ADD source_file_count INT NULL;
            """))
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'target_file_count') IS NULL
                    ALTER TABLE dbo.migration_staging ADD target_file_count INT NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has source_file_count / target_file_count columns")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add file count columns: {e}")

        # Link count columns (source / excluded / target for exclusion preview)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'source_link_count') IS NULL
                    ALTER TABLE dbo.migration_staging ADD source_link_count INT NULL;
            """))
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'excluded_link_count') IS NULL
                    ALTER TABLE dbo.migration_staging ADD excluded_link_count INT NULL;
            """))
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_staging', 'target_link_count') IS NULL
                    ALTER TABLE dbo.migration_staging ADD target_link_count INT NULL;
            """))
            print("[DB_INIT] Ensured migration_staging has source_link_count / excluded_link_count / target_link_count columns")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add link count columns: {e}")

        # Check and create sap_credentials table (encrypted Basic Auth storage)
        check_credentials = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'sap_credentials'
        """)
        result = con.execute(check_credentials).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_CREDENTIALS_TABLE))
            print("[DB_INIT] Created sap_credentials table")
        else:
            print("[DB_INIT] sap_credentials table already exists")

        # Check and create sap_systems table
        check_sap_systems = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'sap_systems'
        """)
        result = con.execute(check_sap_systems).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_SAP_SYSTEMS_TABLE))
            print("[DB_INIT] Created sap_systems table")
        else:
            print("[DB_INIT] sap_systems table already exists")

        # Check and create sap_system_apis table
        check_sap_apis = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'sap_system_apis'
        """)
        result = con.execute(check_sap_apis).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_SAP_SYSTEM_APIS_TABLE))
            print("[DB_INIT] Created sap_system_apis table")
        else:
            print("[DB_INIT] sap_system_apis table already exists")

        # Add estimated_duration_h to migration_batch if not present
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_batch', 'estimated_duration_h') IS NULL
                    ALTER TABLE dbo.migration_batch ADD estimated_duration_h FLOAT NULL;
            """))
            print("[DB_INIT] Ensured migration_batch has estimated_duration_h column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add estimated_duration_h column: {e}")

        # Add execution_stats column (separate from user notes)
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_batch', 'execution_stats') IS NULL
                    ALTER TABLE dbo.migration_batch ADD execution_stats NVARCHAR(MAX) NULL;
            """))
            print("[DB_INIT] Ensured migration_batch has execution_stats column")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add execution_stats column: {e}")

        # Add task assignment flags to migration_batch
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_batch', 'task_qual_load') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_qual_load BIT DEFAULT 0;
                IF COL_LENGTH('dbo.migration_batch', 'task_qual_link') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_qual_link BIT DEFAULT 0;
                IF COL_LENGTH('dbo.migration_batch', 'task_prod_load') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_prod_load BIT DEFAULT 0;
                IF COL_LENGTH('dbo.migration_batch', 'task_prod_link') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_prod_link BIT DEFAULT 0;
            """))
            print("[DB_INIT] Ensured migration_batch has task assignment columns")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add task assignment columns: {e}")

        # Add per-task start date and duration columns to migration_batch
        try:
            con.execute(text("""
                IF COL_LENGTH('dbo.migration_batch', 'task_qual_load_start') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_qual_load_start DATE NULL;
                IF COL_LENGTH('dbo.migration_batch', 'task_qual_load_dur') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_qual_load_dur INT NULL;
                IF COL_LENGTH('dbo.migration_batch', 'task_qual_link_start') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_qual_link_start DATE NULL;
                IF COL_LENGTH('dbo.migration_batch', 'task_qual_link_dur') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_qual_link_dur INT NULL;
                IF COL_LENGTH('dbo.migration_batch', 'task_prod_load_start') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_prod_load_start DATE NULL;
                IF COL_LENGTH('dbo.migration_batch', 'task_prod_load_dur') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_prod_load_dur INT NULL;
                IF COL_LENGTH('dbo.migration_batch', 'task_prod_link_start') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_prod_link_start DATE NULL;
                IF COL_LENGTH('dbo.migration_batch', 'task_prod_link_dur') IS NULL
                    ALTER TABLE dbo.migration_batch ADD task_prod_link_dur INT NULL;
            """))
            print("[DB_INIT] Ensured migration_batch has per-task start/duration columns")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add per-task start/duration columns: {e}")

        # Check and create wave_plan table
        check_wave_plan = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_wave_plan'
        """)
        result = con.execute(check_wave_plan).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_WAVE_PLAN_TABLE))
            # Seed default waves 0-7
            for i in range(8):
                con.execute(text("""
                    INSERT INTO dbo.migration_wave_plan (wave_name)
                    VALUES (:wn)
                """), {'wn': f'Wave {i}'})
            print("[DB_INIT] Created migration_wave_plan table with default waves 0-7")
        else:
            print("[DB_INIT] migration_wave_plan table already exists")

        # Check and create dokob_strategy table
        check_dokob_strat = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_dokob_strategy'
        """)
        result = con.execute(check_dokob_strat).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_DOKOB_STRATEGY_TABLE))
            print("[DB_INIT] Created migration_dokob_strategy table")
        else:
            print("[DB_INIT] migration_dokob_strategy table already exists")
            # Migrate from single strategy column to source_method + target_method
            try:
                con.execute(text("""
                    IF COL_LENGTH('dbo.migration_dokob_strategy', 'source_method') IS NULL
                        ALTER TABLE dbo.migration_dokob_strategy ADD source_method VARCHAR(20) NOT NULL DEFAULT 'none'
                """))
                con.execute(text("""
                    IF COL_LENGTH('dbo.migration_dokob_strategy', 'target_method') IS NULL
                        ALTER TABLE dbo.migration_dokob_strategy ADD target_method VARCHAR(20) NOT NULL DEFAULT 'none'
                """))
                con.execute(text("""
                    IF COL_LENGTH('dbo.migration_dokob_strategy', 'strategy') IS NOT NULL
                    BEGIN
                        UPDATE dbo.migration_dokob_strategy SET source_method = 'dil', target_method = strategy
                            WHERE strategy IN ('api','excel','1:1');
                        UPDATE dbo.migration_dokob_strategy SET source_method = 'dil' WHERE strategy = 'dil';
                    END
                """))
                # Add STRNO prefix columns for IFLOT
                con.execute(text("""
                    IF COL_LENGTH('dbo.migration_dokob_strategy', 'strno_prefix_old') IS NULL
                        ALTER TABLE dbo.migration_dokob_strategy ADD strno_prefix_old VARCHAR(10) NULL
                """))
                con.execute(text("""
                    IF COL_LENGTH('dbo.migration_dokob_strategy', 'strno_prefix_new') IS NULL
                        ALTER TABLE dbo.migration_dokob_strategy ADD strno_prefix_new VARCHAR(10) NULL
                """))
                print("[DB_INIT] Ensured migration_dokob_strategy has source_method/target_method/strno_prefix columns")
            except Exception as e:
                print(f"[DB_INIT_WARN] Could not add columns to migration_dokob_strategy: {e}")

        # Check and create exclusion_query table
        check_excl_query = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_exclusion_query'
        """)
        result = con.execute(check_excl_query).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_EXCLUSION_QUERY_TABLE))
            print("[DB_INIT] Created migration_exclusion_query table")
        else:
            print("[DB_INIT] migration_exclusion_query table already exists")

        # Check and create exclusion_keys table
        check_excl_keys = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_exclusion_keys'
        """)
        result = con.execute(check_excl_keys).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_EXCLUSION_KEYS_TABLE))
            print("[DB_INIT] Created migration_exclusion_keys table")
        else:
            print("[DB_INIT] migration_exclusion_keys table already exists")

        # Check and create exclusion_query_results table
        check_excl_results = text("""
        SELECT COUNT(*) as cnt 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_exclusion_query_results'
        """)
        result = con.execute(check_excl_results).fetchone()
        if result[0] == 0:
            con.execute(text(CREATE_EXCLUSION_QUERY_RESULTS_TABLE))
            print("[DB_INIT] Created migration_exclusion_query_results table")
        else:
            print("[DB_INIT] migration_exclusion_query_results table already exists")

        # Check and create migration_user_settings table
        check_settings = text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_user_settings'
        """)
        result = con.execute(check_settings).fetchone()
        if result[0] == 0:
            con.execute(text("""
                CREATE TABLE dbo.migration_user_settings (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    setting_key VARCHAR(100) NOT NULL,
                    setting_value NVARCHAR(500),
                    updated_at DATETIME2 DEFAULT GETUTCDATE(),
                    updated_by VARCHAR(200),
                    CONSTRAINT UQ_setting_key UNIQUE (setting_key)
                )
            """))
            print("[DB_INIT] Created migration_user_settings table")
        else:
            print("[DB_INIT] migration_user_settings table already exists")

        # Add result metadata columns to exclusion_query table (if missing)
        try:
            for col_def in [
                ("result_columns", "NVARCHAR(MAX)"),
                ("result_objky_column", "VARCHAR(100)"),
                ("result_count", "INT"),
                ("executed_at", "DATETIME2"),
            ]:
                col_check = con.execute(text("""
                    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'migration_exclusion_query'
                          AND COLUMN_NAME = :col
                """), {'col': col_def[0]}).fetchone()
                if col_check[0] == 0:
                    con.execute(text(f"ALTER TABLE dbo.migration_exclusion_query ADD {col_def[0]} {col_def[1]}"))
                    print(f"[DB_INIT] Added column {col_def[0]} to migration_exclusion_query")
        except Exception as e:
            print(f"[DB_INIT_WARN] Could not add result columns to migration_exclusion_query: {e}")
