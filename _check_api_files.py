"""Query ZHL API for document 10001401312 to see what files come back."""
import requests
import json
import yaml

# Load config
with open('config-env.yml') as f:
    cfg = yaml.safe_load(f)

API_KEY = cfg['zhl']['X-API-Key']
BASE_URL = cfg['zhl']['api_list']['document']['base_url']

# Get fresh token via OAuth
auth_cfg = cfg['auth']
auth_url = auth_cfg['auth_url']

# We need to use a stored session token - try reading from running server
# Alternative: query the API using the last requests session
# Since we can't easily get OAuth token, let's check what execute.py sends

# Actually look at what our code does with these files
# Let's check the staging data for these records instead
import pymssql
conn = pymssql.connect('win10240611.BASFAD.BASF.net', 'GDDDE_DATASERVICES',
                        'ltTuhEZopK0hbgZ71Ygo14JNyFkNstE4', 'MISC')
cur = conn.cursor()

# Get the full staging record for these docs
cur.execute("""
    SELECT s.source_documentnumber, s.filename, s.mime_type, s.ablage,
           s.file_size_bytes, s.execution_status, s.source_description,
           LEFT(s.execution_error, 300) as err
    FROM dbo.migration_staging s
    WHERE s.batch_id = 'DMS_20260211_143757'
      AND s.source_documentnumber IN (
        '0000000000000010001401312',
        '0000000000000010001404283',
        '0000000000000010001404282',
        '0000000000000010001397670',
        '0000000000000010001400405',
        '0000000000000010001402064',
        '0000000000000010001405378'
      )
    ORDER BY s.source_documentnumber, s.filename
""")
rows = cur.fetchall()
print(f"Staging records: {len(rows)}\n")
for r in rows:
    fname = r[1] or '(none)'
    has_ext = '.' in fname if fname else False
    print(f"  DOKNR={r[0]}  ablage={r[3]}  mime={r[2]}  size={r[4]}")
    print(f"    filename={fname}  has_ext={has_ext}")
    print(f"    status={r[5]}  desc={r[6]}")
    if r[7]:
        print(f"    error={r[7][:200]}")
    print()

# Compare: these docs have 2+ files in DMS_DOC_FILES but what's in staging?
print("=" * 60)
print("Count files per document in staging:")
cur.execute("""
    SELECT source_documentnumber, COUNT(*) as cnt, 
           STRING_AGG(filename, ' | ') as filenames
    FROM dbo.migration_staging
    WHERE batch_id = 'DMS_20260211_143757'
      AND source_documentnumber IN (
        '0000000000000010001401312',
        '0000000000000010001404283',
        '0000000000000010001404282',
        '0000000000000010001397670',
        '0000000000000010001400405',
        '0000000000000010001402064',
        '0000000000000010001405378'
      )
    GROUP BY source_documentnumber
""")
for r in cur.fetchall():
    print(f"  DOKNR={r[0]}  files={r[1]}")
    print(f"    names: {r[2][:200]}")
    print()

conn.close()
