"""Quick check: Anlagenformat errors in batch DMS_20260211_143757"""
import pymssql

conn = pymssql.connect('win10240611.BASFAD.BASF.net', 'GDDDE_DATASERVICES',
                        'ltTuhEZopK0hbgZ71Ygo14JNyFkNstE4', 'MISC')
cur = conn.cursor()

# Get affected records with this error
cur.execute("""
    SELECT TOP 30 
        s.source_documentnumber, s.filename, s.execution_status,
        LEFT(s.execution_error, 150) as err_excerpt,
        s.source_description,
        s.file_size_bytes
    FROM dbo.migration_staging s
    WHERE s.batch_id = 'DMS_20260211_143757'
      AND (s.execution_error LIKE '%Anlagenformat%' OR s.execution_error LIKE '%invalid%extension%')
    ORDER BY s.id
""")
rows = cur.fetchall()
print(f"Records with Anlagenformat error: {len(rows)}\n")
for r in rows:
    fname = r[1] or '(none)'
    # Extract extension
    ext = fname.rsplit('.', 1)[-1] if '.' in fname else '(no ext)'
    print(f"  DOKNR={r[0]}  file={fname}  ext=.{ext}  status={r[2]}  size={r[5]}")
    print(f"    err={r[3]}")
    print()

# Count total by status
cur.execute("""
    SELECT execution_status, COUNT(*) as cnt
    FROM dbo.migration_staging
    WHERE batch_id = 'DMS_20260211_143757'
    GROUP BY execution_status
    ORDER BY cnt DESC
""")
print("Status overview:")
for r in cur.fetchall():
    print(f"  {r[1]:5d}x  {r[0]}")

# Error summary (group by first 100 chars of execution_error)
cur.execute("""
    SELECT LEFT(ISNULL(execution_error,'(null)'), 100) as err, COUNT(*) as cnt
    FROM dbo.migration_staging
    WHERE batch_id = 'DMS_20260211_143757'
      AND execution_status IN ('failed', 'partial')
    GROUP BY LEFT(ISNULL(execution_error,'(null)'), 100)
    ORDER BY cnt DESC
""")
print("\nError summary:")
for r in cur.fetchall():
    print(f"  {r[1]:5d}x  {r[0]}")

# Check distinct file extensions in the batch
cur.execute("""
    SELECT 
        CASE WHEN CHARINDEX('.', REVERSE(filename)) > 0
             THEN LOWER(RIGHT(filename, CHARINDEX('.', REVERSE(filename)) - 1))
             ELSE '(none)' END as ext,
        COUNT(*) as cnt,
        SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as ok,
        SUM(CASE WHEN execution_status IN ('failed','partial') THEN 1 ELSE 0 END) as err
    FROM dbo.migration_staging
    WHERE batch_id = 'DMS_20260211_143757'
    GROUP BY CASE WHEN CHARINDEX('.', REVERSE(filename)) > 0
                  THEN LOWER(RIGHT(filename, CHARINDEX('.', REVERSE(filename)) - 1))
                  ELSE '(none)' END
    ORDER BY cnt DESC
""")
print("\nFile extensions breakdown:")
for r in cur.fetchall():
    print(f"  .{r[0]:10s}  total={r[1]:4d}  ok={r[2]:4d}  err={r[3]:4d}")

conn.close()
