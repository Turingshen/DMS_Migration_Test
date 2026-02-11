"""Check DAPPL from DIL.DMS_DOC_FILES and ZHL API response for GUID-filename records."""
import hdbcli.dbapi
import requests
import json

# ── 1. Check DIL.DMS_DOC_FILES for these documents ──
print("=" * 80)
print("1. DIL.DMS_DOC_FILES — DAPPL and filename info")
print("=" * 80)

dil = hdbcli.dbapi.connect(
    address='lo1hdb.dmz.basf-ag.de', port=30015,
    user='altnict', password='FinJaleymie99:99',
    encrypt=True, sslValidateCertificate=True, sslCryptoProvider='commoncrypto'
)
cur = dil.cursor()

doknrs = [
    '0000000010001401312',
    '0000000010001404283',
    '0000000010001404282',
    '0000000010001397670',
    '0000000010001400405',
    '0000000010001402064',
    '0000000010001405378',
]

# Zero-pad to 25 chars
doknrs_padded = [d.zfill(25) for d in doknrs]
placeholders = ','.join([f"'{d}'" for d in doknrs_padded])

cur.execute(f"""
    SELECT DOKNR, DOKVR, DOKTL, DAPPL, FILENAME, FILE_IDX
    FROM DIL.DMS_DOC_FILES
    WHERE MANDT = '100' AND DOKAR = 'IY1'
      AND DOKNR IN ({placeholders})
    ORDER BY DOKNR, DOKVR, DOKTL
""")
rows = cur.fetchall()
print(f"\nFound {len(rows)} file records:\n")
for r in rows:
    print(f"  DOKNR={r[0].strip()}  VR={r[1]}  TL={r[2]}  DAPPL={r[3]}  FILENAME={r[4]}  FILE_IDX={r[5]}")
    print()

dil.close()

# ── 2. Check ZHL API response for one of these documents ──
print("=" * 80)
print("2. ZHL API response for 10001401312")
print("=" * 80)

# Get OAuth token first
import pymssql
conn = pymssql.connect('win10240611.BASFAD.BASF.net', 'GDDDE_DATASERVICES',
                        'ltTuhEZopK0hbgZ71Ygo14JNyFkNstE4', 'MISC')
c = conn.cursor()
c.execute("SELECT TOP 1 batch_id FROM dbo.migration_batch WHERE batch_id = 'DMS_20260211_143757'")
row = c.fetchone()
print(f"Batch exists: {row is not None}")
conn.close()

# Use the ZHL custom API
API_KEY = 'dfEjHjOTrn22g73Ivazxoz5ydTnaitST'
BASE_URL = 'https://qa-sap.api.basf.com:443/BASF_EM_COBALT_PM_DOCUMENT/v1'

# We need a bearer token - let's read from flask_session
import glob, pickle, os

session_dir = 'flask_session'
token = None
for sf in sorted(glob.glob(os.path.join(session_dir, '*')), key=os.path.getmtime, reverse=True):
    if os.path.basename(sf).startswith('oauth'):
        continue
    try:
        with open(sf, 'rb') as f:
            sess_data = pickle.load(f)
        if isinstance(sess_data, dict) and 'bearer_token' in sess_data:
            token = sess_data['bearer_token']
            print(f"Found token in {os.path.basename(sf)}")
            break
    except:
        pass

if not token:
    print("No bearer token found in flask sessions, skipping API check")
else:
    headers = {
        'Authorization': f'Bearer {token}',
        'X-API-Key': API_KEY,
        'Accept': 'application/json',
    }
    
    # Query for document 10001401312
    doknr = '10001401312'
    url = f"{BASE_URL}/ET_DOCUMENT?$filter=Documentnumber eq '{doknr}' and Documenttype eq 'IY1'&$expand=Documentfiles,Objectlinks,DESCRIPTIONSSet&$format=json"
    
    print(f"\nGET {url[:120]}...")
    resp = requests.get(url, headers=headers)
    print(f"Status: {resp.status_code}")
    
    if resp.status_code == 200:
        data = resp.json()
        results = data.get('d', {}).get('results', [])
        print(f"Results: {len(results)}")
        for doc in results:
            print(f"\n  Documentnumber: {doc.get('Documentnumber')}")
            print(f"  Documentversion: {doc.get('Documentversion')}")
            print(f"  Documentpart: {doc.get('Documentpart')}")
            print(f"  Description: '{doc.get('Description')}'")
            
            files = doc.get('Documentfiles', {}).get('results', [])
            print(f"  Files ({len(files)}):")
            for fi in files:
                print(f"    Application: '{fi.get('Application')}'")
                print(f"    Filename: '{fi.get('Filename')}'")
                print(f"    Filepath: '{fi.get('Filepath')}'")
                print(f"    MimeType: '{fi.get('MimeType')}'")
                print(f"    Storagecategory: '{fi.get('Storagecategory')}'")
                # Print all keys
                for k, v in fi.items():
                    if k not in ('Application', 'Filename', 'Filepath', 'MimeType', 'Storagecategory', '__metadata'):
                        print(f"    {k}: '{v}'")
                print()
    else:
        print(f"Error: {resp.text[:500]}")
