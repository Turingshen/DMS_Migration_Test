"""One-time script to reset record 1037992 (including file_details)."""
from sqlalchemy import create_engine, text

engine = create_engine('mssql+pymssql://GDDDE_DATASERVICES:ltTuhEZopK0hbgZ71Ygo14JNyFkNstE4@win10240611.BASFAD.BASF.net:1433/MISC')

RECORD_ID = 1037992

# Check current state
with engine.begin() as con:
    r = con.execute(text(
        "SELECT id, target_documenttype, target_documentnumber, "
        "container_created, execution_status "
        "FROM dbo.migration_staging WHERE id = :id"
    ), {'id': RECORD_ID}).fetchone()
    print(f"=== BEFORE ===")
    print(f"  ID={r[0]}, type={r[1]}, tgt_doknr={r[2]}, container={r[3]}, status={r[4]}")

    # Check file_details
    fd = con.execute(text(
        "SELECT file_index, upload_status FROM dbo.migration_file_details "
        "WHERE staging_id = :id ORDER BY file_index"
    ), {'id': RECORD_ID}).fetchall()
    print(f"  file_details: {len(fd)} entries")
    for f in fd:
        print(f"    idx={f[0]}, status={f[1]}")

# Reset staging + delete file_details
with engine.begin() as con:
    con.execute(text(
        "DELETE FROM dbo.migration_file_details WHERE staging_id = :id"
    ), {'id': RECORD_ID})
    con.execute(text(
        "UPDATE dbo.migration_staging "
        "SET container_created = 0, "
        "    execution_status = 'pending', "
        "    execution_error = NULL, "
        "    execution_started_at = NULL, "
        "    execution_completed_at = NULL "
        "WHERE id = :id"
    ), {'id': RECORD_ID})
    print(f"\n=== RESET DONE === (staging + file_details cleared)")

# Verify
with engine.begin() as con:
    r = con.execute(text(
        "SELECT id, target_documenttype, target_documentnumber, container_created, execution_status "
        "FROM dbo.migration_staging WHERE id = :id"
    ), {'id': RECORD_ID}).fetchone()
    fd_count = con.execute(text(
        "SELECT COUNT(*) FROM dbo.migration_file_details WHERE staging_id = :id"
    ), {'id': RECORD_ID}).fetchone()[0]
    print(f"\n=== AFTER ===")
    print(f"  ID={r[0]}, type={r[1]}, tgt_doknr={r[2]}, container={r[3]}, status={r[4]}")
    print(f"  file_details: {fd_count} entries")
