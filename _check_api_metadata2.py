"""Check ZHL API $metadata via bearer token from flask_session."""
import requests
import re
import os
import pickle

session_dir = 'flask_session'
bearer_token = None
api_key = 'dfEjHjOTrn22g73Ivazxoz5ydTnaitST'

for fname in os.listdir(session_dir):
    fpath = os.path.join(session_dir, fname)
    if os.path.isdir(fpath):
        continue
    try:
        with open(fpath, 'rb') as f:
            data = pickle.load(f)
        if isinstance(data, dict) and data.get('bearer_token'):
            bearer_token = data['bearer_token']
            print(f"Found bearer token in {fname} (length={len(bearer_token)})")
            break
    except Exception:
        pass

if not bearer_token:
    print("ERROR: No bearer token found. Please login first.")
    exit(1)

BASE_URL = 'https://qa-sap.api.basf.com:443/BASF_EM_COBALT_PM_DOCUMENT/v1'

headers = {
    'X-API-Key': api_key,
    'Authorization': f'Bearer {bearer_token}',
    'Accept': 'application/xml'
}

print("=" * 80)
print("Fetching $metadata...")
print("=" * 80)

resp = requests.get(f"{BASE_URL}/$metadata", headers=headers)
print(f"Status: {resp.status_code}")

if resp.status_code == 200:
    xml_text = resp.text
    
    # Find all EntityType definitions
    entity_types = re.findall(r'EntityType\s+Name="(\w+)"', xml_text)
    print(f"\nAll EntityTypes: {entity_types}")
    
    # Find Documentfiles-related entities
    for pattern in [
        r'<EntityType\s+Name="[^"]*[Dd]ocument[Ff]ile[^"]*".*?</EntityType>',
        r'<EntityType\s+Name="[^"]*FILE[^"]*".*?</EntityType>',
        r'<EntityType\s+Name="[^"]*Documentfiles[^"]*".*?</EntityType>',
    ]:
        matches = re.findall(pattern, xml_text, re.DOTALL | re.IGNORECASE)
        for match in matches:
            name = re.search(r'Name="(\w+)"', match)
            print(f"\n{'='*60}")
            print(f"EntityType: {name.group(1) if name else '?'}")
            print(f"{'='*60}")
            props = re.findall(r'<Property\s+Name="(\w+)"\s+Type="([^"]+)"', match)
            for pname, ptype in props:
                marker = " <<<" if pname.lower() in ('dappl', 'application', 'storagecategory', 'docpath', 'filepath', 'filename', 'wsapplication') else ""
                print(f"  {pname:30s} {ptype}{marker}")
    
    # Search for key fields across ALL entities
    print(f"\n{'='*60}")
    print("Search for key fields across ALL entities:")
    print(f"{'='*60}")
    for keyword in ['Dappl', 'DAPPL', 'Application', 'Storagecategory', 'Docpath', 'Filename', 'Filepath', 'Wsapplication']:
        found = re.findall(rf'Property\s+Name="{keyword}"', xml_text, re.IGNORECASE)
        if found:
            ctx = re.findall(rf'EntityType\s+Name="(\w+)".*?Property\s+Name="{keyword}"', xml_text, re.DOTALL | re.IGNORECASE)
            print(f"  {keyword:25s} found {len(found)}x  (in: {ctx})")
        else:
            print(f"  {keyword:25s} NOT FOUND")
else:
    print(f"Error {resp.status_code}: {resp.text[:500]}")
