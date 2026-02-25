import pymssql

conn = pymssql.connect('win10240611.BASFAD.BASF.net', 'GDDDE_DATASERVICES', 'ltTuhEZopK0hbgZ71Ygo14JNyFkNstE4', 'MISC')
cur = conn.cursor(as_dict=True)

# Find ALL records with container_created=1 AND target_documentnumber IS NULL (lost doc number)
cur.execute("""
    SELECT id, target_documentnumber, ISNULL(container_created,0) as container_created, 
           execution_status, error_category
    FROM dbo.migration_staging 
    WHERE batch_id = 'DMS_20260224_083050'
      AND ISNULL(container_created, 0) = 1
      AND target_documentnumber IS NULL
    ORDER BY id
""")
affected = cur.fetchall()
print(f"=== FOUND {len(affected)} RECORDS with container_created=1 AND target_doknr=NULL ===")
for r in affected:
    print(f"  ID={r['id']} | status={r['execution_status']} | error={r['error_category']}")

# Also check: how many total failed with RETRY_DOC_NUMBER_MISSING?
cur.execute("""
    SELECT COUNT(*) as cnt FROM dbo.migration_staging 
    WHERE batch_id = 'DMS_20260224_083050'
      AND error_category = 'RETRY_DOC_NUMBER_MISSING'
""")
retry_cnt = cur.fetchone()
print(f"\nTotal RETRY_DOC_NUMBER_MISSING: {retry_cnt['cnt']}")

STAGING_IDS = [r['id'] for r in affected]

if not STAGING_IDS:
    print("Nothing to reset!")
    conn.close()
    exit()

print(f"\n=== RESETTING {len(STAGING_IDS)} RECORDS ===")
for sid in STAGING_IDS:
    cur.execute("""UPDATE dbo.migration_staging 
                   SET container_created = 0, 
                       execution_status = 'pending',
                       execution_error = NULL,
                       error_category = NULL,
                       execution_started_at = NULL,
                       execution_completed_at = NULL,
                       target_file_count = NULL,
                       source_file_count = NULL
                   WHERE id = %s""", (sid,))
    cur.execute("DELETE FROM dbo.migration_file_details WHERE staging_id = %s", (sid,))
    fd_deleted = cur.rowcount
    print(f"  ID={sid}: reset + {fd_deleted} file_details deleted")

conn.commit()

# Verify
cur.execute("""
    SELECT COUNT(*) as cnt FROM dbo.migration_staging 
    WHERE batch_id = 'DMS_20260224_083050'
      AND ISNULL(container_created, 0) = 1
      AND target_documentnumber IS NULL
""")
remaining = cur.fetchone()
print(f"\n=== VERIFICATION: {remaining['cnt']} records remaining with container=1 + doknr=NULL ===")

conn.close()
print(f"\nDONE - {len(STAGING_IDS)} records reset to pending, ready for re-execution")
