"""Quick test script for direct zvfr3 API call."""
import requests
import urllib3
import json

urllib3.disable_warnings()

BASE = "https://zvfr3.basf.net/sap/opu/odata/sap/API_DMS_PROCESS_SRV"
AUTH = ("altnict", "a!b2Dj§_01)15")

# Use a session to keep cookies
session = requests.Session()
session.auth = AUTH
session.verify = False

# 1. Fetch CSRF token
print("=== Fetching CSRF token ===")
r = session.get(f"{BASE}/A_DocumentInfoRecord?$top=1&$format=json", 
                headers={"x-csrf-token": "Fetch"})
print(f"Status: {r.status_code}")
csrf_token = r.headers.get("x-csrf-token", "")
print(f"CSRF Token: {csrf_token[:20]}..." if csrf_token else "NO CSRF TOKEN!")

if not csrf_token:
    print("Cannot proceed without CSRF token")
    exit(1)

headers = {"Content-Type": "application/json", "Accept": "application/json", "x-csrf-token": csrf_token}

print()

# 2. Test 1: IY1 mit interner Nummernvergabe (ohne DocumentInfoRecordDocNumber)
print("=== Test 1: IY1 interne Nummernvergabe (ohne Nummer) ===")
payload1 = {
    "DocumentInfoRecordDocType": "IY1",
    "DocumentInfoRecordDocVersion": "00",
    "DocumentInfoRecordDocPart": "000",
    "to_DocDesc": [
        {"Language": "DE", "DocumentDescription": "Test interne Nummernvergabe"},
        {"Language": "EN", "DocumentDescription": "Test internal numbering"}
    ]
}
r1 = session.post(f"{BASE}/A_DocumentInfoRecord", json=payload1, headers=headers, timeout=30)
print(f"Status: {r1.status_code}")
try:
    data = r1.json()
    if r1.status_code in (200, 201) and "d" in data:
        d = data["d"]
        print(f"  SUCCESS!")
        print(f"  DocType:    {d.get('DocumentInfoRecordDocType')}")
        print(f"  DocNumber:  {d.get('DocumentInfoRecordDocNumber')}")
        print(f"  DocVersion: {d.get('DocumentInfoRecordDocVersion')}")
        print(f"  DocPart:    {d.get('DocumentInfoRecordDocPart')}")
        print(f"  Status:     {d.get('InternalDocumentStatus')}")
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
except:
    print(r1.text[:2000])

print()

# 3. Test 2: IY1 mit expliziter Nummer DMS_DIRECT_TEST
print("=== Test 2: IY1 mit Nummer DMS_DIRECT_TEST ===")
payload2 = {
    "DocumentInfoRecordDocType": "IY1",
    "DocumentInfoRecordDocNumber": "DMS_DIRECT_TEST",
    "DocumentInfoRecordDocVersion": "00",
    "DocumentInfoRecordDocPart": "000",
    "to_DocDesc": [
        {"Language": "DE", "DocumentDescription": "Test manuelle Nummernvergabe"},
        {"Language": "EN", "DocumentDescription": "Test manual numbering"}
    ]
}
r2 = session.post(f"{BASE}/A_DocumentInfoRecord", json=payload2, headers=headers, timeout=30)
print(f"Status: {r2.status_code}")
try:
    data2 = r2.json()
    if r2.status_code in (200, 201) and "d" in data2:
        d2 = data2["d"]
        print(f"  SUCCESS!")
        print(f"  DocType:    {d2.get('DocumentInfoRecordDocType')}")
        print(f"  DocNumber:  {d2.get('DocumentInfoRecordDocNumber')}")
        print(f"  DocVersion: {d2.get('DocumentInfoRecordDocVersion')}")
        print(f"  DocPart:    {d2.get('DocumentInfoRecordDocPart')}")
        print(f"  Status:     {d2.get('InternalDocumentStatus')}")
    else:
        print(json.dumps(data2, indent=2, ensure_ascii=False)[:2000])
except:
    print(r2.text[:2000])
