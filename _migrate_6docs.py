"""
Standalone migration test: Read 6 documents from ZHL → Create in ZVFR3.
Steps per document:
  1. GET document info from ZHL (R3 API via BTP, API-Key auth)
  2. POST create document in ZVFR3 (S4 OData, Basic Auth) as IY1
  3. GET file content from ZHL
  4. POST upload file to ZVFR3
"""
import requests
import urllib3
import json
import time
import re

urllib3.disable_warnings()

# ── CONFIG ──────────────────────────────────────────────────────────────────
ZHL_BASE = "https://qa-sap.api.basf.com:443/BASF_EM_COBALT_PM_DOCUMENT/v1"
ZHL_API_KEY = "dfEjHjOTrn22g73Ivazxoz5ydTnaitST"

ZVFR3_BASE = "https://zvfr3.basf.net/sap/opu/odata/sap/API_DMS_PROCESS_SRV"
ZVFR3_ATTACH = "https://zvfr3.basf.net/sap/opu/odata/sap/API_CV_ATTACHMENT_SRV"
ZVFR3_AUTH = ("altnict", "a!b2Dj§_01)15")

DOC_NUMBERS = [
    "10009334178",
    "10009334179",
    "10009334180",
    "10009334181",
    "10009334182",
    "10009334183",
]

# ── ZHL SESSION (OAuth via BTP — need bearer token) ────────────────────────
# We'll try API-Key only first. If 401, we need a bearer token from the app.
# Fallback: read token from the running Flask session cookie.

def get_zhl_session():
    """Create ZHL session with API-Key header."""
    s = requests.Session()
    s.headers.update({
        'X-API-Key': ZHL_API_KEY,
        'Accept': 'application/json',
    })
    return s


def get_zvfr3_session():
    """Create ZVFR3 session with Basic Auth + CSRF token."""
    s = requests.Session()
    s.auth = ZVFR3_AUTH
    s.verify = False
    
    # Fetch CSRF token
    print("[ZVFR3] Fetching CSRF token...")
    r = s.get(f"{ZVFR3_BASE}/A_DocumentInfoRecord?$top=1&$format=json",
              headers={"X-CSRF-Token": "Fetch"})
    if r.status_code != 200:
        raise Exception(f"CSRF fetch failed: {r.status_code} {r.reason}")
    
    csrf = r.headers.get("x-csrf-token", "")
    print(f"[ZVFR3] CSRF token: {csrf[:20]}...")
    s.headers.update({
        "X-CSRF-Token": csrf,
        "Accept": "application/json",
        "Accept-Language": "de",
        "sap-language": "DE",
    })
    return s


def read_from_zhl(zhl_session, doc_number):
    """Read document info + files from ZHL R3 API."""
    # ZHL uses stripped doc number
    clean = doc_number.lstrip('0') or '0'
    
    url = (f"{ZHL_BASE}/DocumentSet("
           f"Documentnumber='{clean}',"
           f"Documentpart='000',"
           f"Documenttype='ZHL',"    # Try ZHL type first, fallback to others
           f"Documentversion='00')"
           f"?$expand=DocumentfilesSet,ObjectlinksSet,DESCRIPTIONSSet")
    
    # We don't know the exact document type. Try common R3 types.
    for doctype in ['ZHL', 'ZLH', 'DRW', 'Z01', 'ZPM', 'ZIG', '']:
        if doctype:
            url = (f"{ZHL_BASE}/DocumentSet("
                   f"Documentnumber='{clean}',"
                   f"Documentpart='000',"
                   f"Documenttype='{doctype}',"
                   f"Documentversion='00')"
                   f"?$expand=DocumentfilesSet,ObjectlinksSet,DESCRIPTIONSSet")
        else:
            # Try without type filter — some APIs allow search
            url = f"{ZHL_BASE}/DocumentSet?$filter=Documentnumber eq '{clean}'&$expand=DocumentfilesSet,ObjectlinksSet,DESCRIPTIONSSet&$top=1"
        
        r = zhl_session.get(url)
        
        if r.status_code == 200 and r.content and r.content != b'':
            try:
                data = r.json()
                # EntitySet response
                if 'd' in data:
                    if 'results' in data['d']:
                        # Collection
                        if data['d']['results']:
                            return data['d']['results'][0]
                    elif 'DocumentfilesSet' in data['d']:
                        # Single entity
                        return data['d']
            except:
                pass
        elif r.status_code == 401:
            print(f"  [ZHL] 401 Unauthorized — API-Key alone not sufficient, need OAuth bearer token")
            return None
        elif r.status_code == 404:
            continue  # Try next doctype
    
    print(f"  [ZHL] Document {doc_number} not found with any document type")
    return None


def download_file_from_zhl(zhl_session, file_url):
    """Download file content from ZHL."""
    r = zhl_session.get(file_url)
    if r.status_code == 200:
        return r.content
    print(f"  [ZHL] File download failed: {r.status_code}")
    return None


def create_in_zvfr3(zvfr3_session, doc_info, doc_number):
    """Create document in ZVFR3 as IY1 (internal numbering)."""
    
    # Extract descriptions from ZHL response
    descriptions = []
    if doc_info:
        descs_raw = doc_info.get('DESCRIPTIONSSet', {}).get('results', [])
        for d in descs_raw:
            lang = d.get('Languagecode', d.get('Language', 'DE'))
            text = d.get('Dktxt', d.get('Description', d.get('DocumentDescription', '')))
            if text:
                # Map R3 language codes to S4
                lang_map = {'D': 'DE', 'E': 'EN', 'F': 'FR'}
                s4_lang = lang_map.get(lang.upper(), lang.upper())
                descriptions.append({
                    "Language": s4_lang,
                    "DocumentDescription": text[:40]  # S4 max 40 chars
                })
    
    if not descriptions:
        descriptions = [
            {"Language": "DE", "DocumentDescription": f"Migration aus ZHL {doc_number}"}
        ]
    
    # IY1 with internal numbering (no DocumentInfoRecordDocNumber)
    payload = {
        "DocumentInfoRecordDocType": "IY1",
        "DocumentInfoRecordDocVersion": "00",
        "DocumentInfoRecordDocPart": "000",
        "to_DocDesc": descriptions
    }
    
    print(f"  [ZVFR3] Creating IY1 document...")
    print(f"           Descriptions: {[d['DocumentDescription'] for d in descriptions]}")
    
    r = zvfr3_session.post(
        f"{ZVFR3_BASE}/A_DocumentInfoRecord",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    if r.status_code in (200, 201):
        data = r.json()
        d = data.get('d', {})
        new_number = d.get('DocumentInfoRecordDocNumber', '')
        new_version = d.get('DocumentInfoRecordDocVersion', '00')
        new_part = d.get('DocumentInfoRecordDocPart', '000')
        new_type = d.get('DocumentInfoRecordDocType', 'IY1')
        print(f"  [ZVFR3] ✓ Created: {new_type} / {new_number} / {new_version} / {new_part}")
        return {
            'type': new_type,
            'number': new_number, 
            'version': new_version,
            'part': new_part,
            'status': d.get('InternalDocumentStatus', '')
        }
    else:
        try:
            err = r.json()
            msg = err.get('error', {}).get('message', {}).get('value', r.text[:500])
        except:
            msg = r.text[:500]
        print(f"  [ZVFR3] ✗ CREATE failed: {r.status_code} — {msg}")
        return None


def upload_to_zvfr3(zvfr3_session, target_doc, filename, file_content):
    """Upload file to ZVFR3 via CV_ATTACHMENT_SRV."""
    if not target_doc or not file_content:
        return False
    
    doc_type = target_doc['type']
    doc_number = target_doc['number']
    doc_version = target_doc['version']
    doc_part = target_doc['part']
    
    # Sanitize filename
    safe_name = re.sub(r'[\\/:*?"<>|\n\r\t]', '_', filename or 'document.bin')
    if len(safe_name) > 80:
        name, ext = safe_name.rsplit('.', 1) if '.' in safe_name else (safe_name, '')
        safe_name = name[:80 - len(ext) - 1] + '.' + ext if ext else name[:80]
    
    url = (f"{ZVFR3_ATTACH}/A_DocumentInfoRecordAttch("
           f"DocumentInfoRecordDocType='{doc_type}',"
           f"DocumentInfoRecordDocNumber='{doc_number}',"
           f"DocumentInfoRecordDocVersion='{doc_version}',"
           f"DocumentInfoRecordDocPart='{doc_part}',"
           f"LogicalDocument='',"
           f"ArchiveDocumentID='',"
           f"LinkedSAPObjectKey='',"
           f"BusinessObjectTypeName='')/"
           f"DocumentInfoRecordAttchContent")
    
    print(f"  [ZVFR3] Uploading {safe_name} ({len(file_content):,} bytes)...")
    
    r = zvfr3_session.put(
        url,
        data=file_content,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Accept": "application/json",
        },
        timeout=120
    )
    
    if r.status_code in (200, 201, 204):
        print(f"  [ZVFR3] ✓ Upload OK")
        return True
    else:
        try:
            msg = r.json().get('error', {}).get('message', {}).get('value', r.text[:300])
        except:
            msg = r.text[:300]
        print(f"  [ZVFR3] ✗ Upload failed: {r.status_code} — {msg}")
        return False


def main():
    print("=" * 80)
    print(f"Migration Test: {len(DOC_NUMBERS)} Dokumente ZHL → ZVFR3")
    print("=" * 80)
    
    # 1. Test ZHL connectivity
    print("\n[1] ZHL-Verbindung testen...")
    zhl = get_zhl_session()
    test_r = zhl.get(f"{ZHL_BASE}/DocumentSet?$top=1&$format=json")
    zhl_available = test_r.status_code == 200
    
    if zhl_available:
        print(f"    ✓ ZHL erreichbar (Status {test_r.status_code})")
    else:
        print(f"    ✗ ZHL nicht erreichbar ohne OAuth Bearer Token (Status {test_r.status_code})")
        print(f"    → Dokumente werden ohne Datei-Download erstellt")
        print(f"    → Für vollständige Migration die Web-App nutzen")
    
    # 2. Setup ZVFR3 session
    print("\n[2] ZVFR3-Session aufbauen...")
    zvfr3 = get_zvfr3_session()
    
    # 3. Process each document
    print(f"\n[3] Migration von {len(DOC_NUMBERS)} Dokumenten...")
    results = []
    
    for i, doc_nr in enumerate(DOC_NUMBERS, 1):
        print(f"\n{'─' * 60}")
        print(f"[{i}/{len(DOC_NUMBERS)}] DOKNR: {doc_nr}")
        
        # Read from ZHL
        doc_info = None
        file_content = None
        filename = None
        
        if zhl_available:
            doc_info = read_from_zhl(zhl, doc_nr)
            if doc_info:
                files = doc_info.get('DocumentfilesSet', {}).get('results', [])
                if files:
                    filename = files[0].get('Filename', files[0].get('Description', f'{doc_nr}.bin'))
                    file_url = files[0].get('__metadata', {}).get('media_src') or files[0].get('Documentfile')
                    if file_url:
                        file_content = download_file_from_zhl(zhl, file_url)
                        if file_content:
                            print(f"  [ZHL] ✓ File: {filename} ({len(file_content):,} bytes)")
                    else:
                        print(f"  [ZHL] Kein File-Download-Link gefunden")
                else:
                    print(f"  [ZHL] Container leer (keine Dateien)")
            else:
                print(f"  [ZHL] Dokument-Info nicht verfügbar")
        
        # Create in ZVFR3
        target = create_in_zvfr3(zvfr3, doc_info, doc_nr)
        
        # Upload file
        uploaded = False
        if target and file_content and filename:
            uploaded = upload_to_zvfr3(zvfr3, target, filename, file_content)
        
        results.append({
            'source': doc_nr,
            'target': target,
            'file_uploaded': uploaded,
        })
        
        # Brief pause between records
        if i < len(DOC_NUMBERS):
            time.sleep(0.5)
    
    # 4. Summary
    print(f"\n{'=' * 80}")
    print(f"ERGEBNIS")
    print(f"{'=' * 80}")
    
    success = sum(1 for r in results if r['target'])
    uploaded = sum(1 for r in results if r['file_uploaded'])
    
    print(f"\n{'Quelle (ZHL)':<25} {'Ziel (ZVFR3)':<30} {'Datei':<10}")
    print("─" * 70)
    for r in results:
        src = r['source']
        if r['target']:
            tgt = f"{r['target']['type']}/{r['target']['number']}/{r['target']['version']}"
            file_status = "✓" if r['file_uploaded'] else "—"
        else:
            tgt = "FEHLER"
            file_status = "—"
        print(f"{src:<25} {tgt:<30} {file_status:<10}")
    
    print(f"\n✓ Erstellt: {success}/{len(DOC_NUMBERS)}")
    print(f"✓ Dateien:  {uploaded}/{len(DOC_NUMBERS)}")
    print("=" * 80)


if __name__ == '__main__':
    main()
