"""Check ZHL API $metadata via the running Flask server's session."""
import requests
import re

# The Flask server is running on localhost:5000 and has an active OAuth session.
# We call the $metadata through a quick local proxy approach:
# Use the server's /api-proxy or just call it from the browser session.

# Actually, let's just try fetching from localhost - the server can proxy for us.
# But there's no proxy route. Let's try the direct approach with API-Key + 
# a fresh token from the callback flow... that won't work without browser.

# Alternative: Just fetch the raw XML via the server's debug endpoint.
# Let me check if we can get the bearer token from an active flask_session file.

import os
import pickle

print("Checking flask_session files for bearer token...")
session_dir = 'flask_session'
bearer = None

for fname in os.listdir(session_dir):
    if fname.startswith('oauth_states'):
        continue
    fpath = os.path.join(session_dir, fname)
    try:
        with open(fpath, 'rb') as f:
            data = pickle.load(f)
        if isinstance(data, dict) and 'bearer_token' in data:
            bearer = data['bearer_token']
            user = data.get('fullName', 'unknown')
            print(f"  Found token in {fname} (user: {user})")
            break
    except Exception as e:
        pass

if not bearer:
    print("No bearer token found in flask_session files.")
    print("Please log in to the app first, then re-run this script.")
    exit(1)

print(f"Token: {bearer[:20]}...")

url = 'https://qa-sap.api.basf.com:443/BASF_EM_COBALT_PM_DOCUMENT/v1/$metadata'
headers = {
    'X-API-Key': 'dfEjHjOTrn22g73Ivazxoz5ydTnaitST',
    'Authorization': f'Bearer {bearer}',
    'Accept': 'application/xml'
}

print(f"\nFetching: {url}")
r = requests.get(url, headers=headers, timeout=15)
print(f"Status: {r.status_code}")

if r.status_code == 200:
    xml = r.text
    
    entity_blocks = re.findall(
        r'<EntityType\s+Name="([^"]+)"[^>]*>(.*?)</EntityType>', xml, re.DOTALL
    )
    
    print(f"\n{'='*60}")
    print(f"Found {len(entity_blocks)} EntityTypes")
    print(f"{'='*60}")
    
    for name, body in entity_blocks:
        props = re.findall(r'<Property\s+Name="([^"]+)"', body)
        nav_props = re.findall(r'<NavigationProperty\s+Name="([^"]+)"', body)
        print(f"\nEntityType: {name}  ({len(props)} properties)")
        for p in props:
            marker = " <<<" if p.lower() in ('dappl', 'application', 'storagecategory', 'filetype', 'docpath', 'filename') else ""
            print(f"  - {p}{marker}")
        if nav_props:
            print(f"  NavigationProperties: {nav_props}")
    
    print(f"\n{'='*60}")
    print("Keyword search in full XML")
    print(f"{'='*60}")
    for kw in ['Dappl', 'DAPPL', 'Application', 'Storagecategory', 'Filetype', 'FileType']:
        hits = re.findall(r'Name="[^"]*' + kw + r'[^"]*"', xml, re.IGNORECASE)
        if hits:
            print(f"  '{kw}': {hits[:5]}")
        else:
            print(f"  '{kw}': not found")
else:
    print(f"Error response:\n{r.text[:1000]}")
