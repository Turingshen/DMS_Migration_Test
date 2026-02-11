"""Query ZHL API for document description - reads bearer token from Flask session."""
import os
import pickle
import requests
import json

# Step 1: Get bearer token from most recent Flask session
sd = "flask_session"
files = [f for f in os.listdir(sd) if not os.path.isdir(os.path.join(sd, f))]
files.sort(key=lambda f: os.path.getmtime(os.path.join(sd, f)), reverse=True)

bearer_token = None
for fname in files:
    fpath = os.path.join(sd, fname)
    try:
        raw = open(fpath, "rb").read()
        # Flask-Session filesystem format: skip header bytes, find pickle start
        idx = raw.find(b'\x80\x05')  # pickle protocol 5
        if idx < 0:
            idx = raw.find(b'\x80\x04')  # pickle protocol 4
        if idx < 0:
            idx = raw.find(b'\x80\x03')
        if idx >= 0:
            data = pickle.loads(raw[idx:])
        else:
            data = pickle.loads(raw)
        bt = data.get("bearer_token")
        if bt:
            bearer_token = bt
            print(f"Got token from session: {fname} (user: {data.get('user_email', '?')})")
            break
    except Exception as e:
        continue

if not bearer_token:
    print("ERROR: No bearer_token found in any Flask session. Log in via browser first.")
    exit(1)

# Step 2: Check batch source_file (how was the batch created?)
import pymssql

conn = pymssql.connect(
    server="win10240611.BASFAD.BASF.net",
    port=1433,
    user="GDDDE_DATASERVICES",
    password="ltTuhEZopK0hbgZ71Ygo14JNyFkNstE4",
    database="MISC"
)
cur = conn.cursor(as_dict=True)

cur.execute("""
    SELECT *
    FROM dbo.migration_batch
    WHERE batch_id = 'DMS_20260211_081936'
""")
batch = cur.fetchone()
print("=== Batch metadata ===")
for k, v in batch.items():
    print(f"  {k}: {v}")

# Check: how many have source_description filled vs NULL
cur.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN source_description IS NULL OR source_description = '' THEN 1 ELSE 0 END) as desc_null,
        SUM(CASE WHEN source_description IS NOT NULL AND source_description != '' AND source_description != 'None' THEN 1 ELSE 0 END) as desc_filled
    FROM dbo.migration_staging
    WHERE batch_id = 'DMS_20260211_081936'
""")
row = cur.fetchone()
print(f"\n=== Description stats ===")
print(f"  Total: {row['total']}, Desc NULL/empty: {row['desc_null']}, Desc filled: {row['desc_filled']}")

conn.close()
row = cur.fetchone()
print(f"  Total: {row['total']}")
print(f"  Description NULL/empty: {row['desc_null']}")
print(f"  Description filled: {row['desc_filled']}")
print(f"  Description = Filename: {row['desc_equals_filename']}")

# Show some examples with NULL description
cur.execute("""
    SELECT TOP 10
        source_documentnumber, source_description, filename
    FROM dbo.migration_staging
    WHERE batch_id = 'DMS_20260211_081936'
      AND (source_description IS NULL OR source_description = '')
    ORDER BY source_documentnumber
""")
print(f"\n=== Examples with NULL/empty source_description ===")
for r in cur.fetchall():
    print(f"  {r['source_documentnumber']}  desc='{r['source_description']}'  file='{r['filename']}'")

# Show some examples with filled description
cur.execute("""
    SELECT TOP 10
        source_documentnumber, source_description, filename
    FROM dbo.migration_staging
    WHERE batch_id = 'DMS_20260211_081936'
      AND source_description IS NOT NULL AND source_description != ''
    ORDER BY source_documentnumber
""")
print(f"\n=== Examples with filled source_description ===")
for r in cur.fetchall():
    print(f"  {r['source_documentnumber']}  desc='{r['source_description']}'  file='{r['filename']}'")

conn.close()
print("\nDone.")
