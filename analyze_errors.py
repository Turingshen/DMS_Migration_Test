"""Analyze error patterns in migration logs for better categorization."""
from app_config import MiscEngine
from sqlalchemy import text
from app.process import _classify_error, get_error_details
import json

misc_db = MiscEngine.load()
engine = misc_db.engine

print("=" * 80)
print("FEHLER-ANALYSE FÜR MIGRATIONS-LOGS")
print("=" * 80)

# 1. Container-level errors from migration_staging
print("\n=== CONTAINER-LEVEL ERRORS (migration_staging) ===")
with engine.connect() as con:
    result = con.execute(text("""
        SELECT 
            execution_status,
            execution_error,
            COUNT(*) as cnt
        FROM dbo.migration_staging
        WHERE execution_error IS NOT NULL 
        GROUP BY execution_status, execution_error
        ORDER BY cnt DESC
    """)).fetchall()

error_categories = {}
for row in result:
    status, error, cnt = row
    if not error:
        continue
    
    # Parse error to extract structured info
    try:
        if error.startswith('{'):
            err_json = json.loads(error)
            
            # Handle PARTIAL_SUCCESS format: {"summary": "...", "errors": [...]}
            if 'summary' in err_json and 'errors' in err_json:
                errors_list = err_json.get('errors', [])
                if errors_list and len(errors_list) > 0:
                    # Classify based on first error in list
                    first_err = errors_list[0]
                    cat = _classify_error(first_err)
                else:
                    cat = 'OTHER'
            else:
                # Regular error format
                cat = _classify_error(err_json)
        elif 'CSRF' in error.upper():
            cat = 'CSRF_FAILED'
        elif 'READ_EMPTY' in error:
            cat = 'SOURCE_EMPTY'
        elif 'READ_FAILED' in error:
            cat = 'SOURCE_READ_ERROR'
        elif 'EXCEPTION' in error:
            if 'CSRF' in error or 'csrf' in error:
                cat = 'CSRF_FAILED'
            elif '403' in error:
                cat = 'AUTH_FORBIDDEN'
            elif '401' in error:
                cat = 'TOKEN_EXPIRED'
            else:
                cat = 'OTHER'
        elif 'size' in error.lower() and 'exceed' in error.lower():
            cat = 'UPLOAD_SIZE_EXCEEDED'
        else:
            cat = 'OTHER'
            
        if cat not in error_categories:
            error_categories[cat] = {'count': 0, 'sample': error[:100]}
        error_categories[cat]['count'] += cnt
    except Exception as e:
        cat = 'PARSE_ERROR'
        if cat not in error_categories:
            error_categories[cat] = {'count': 0, 'sample': str(e)[:100]}
        error_categories[cat]['count'] += cnt

print(f"\n{'KATEGORIE':<24} | {'ANZAHL':>6} | {'BESCHREIBUNG':<28} | AKTION")
print("-" * 100)
for cat, data in sorted(error_categories.items(), key=lambda x: -x[1]['count']):
    desc, action = get_error_details(cat)
    print(f"{cat:<24} | {data['count']:>6} | {desc:<28} | {action}")

# 2. Summary by error group
print("\n\n=== FEHLER NACH GRUPPE ===")
groups = {
    'API/Auth': ['API_KEY_INVALID', 'API_KEY_MISSING', 'TOKEN_EXPIRED', 'TOKEN_INVALID', 'CSRF_FAILED', 'AUTH_NO_PERMISSION', 'AUTH_FORBIDDEN'],
    'Quelle (R/3)': ['SOURCE_NOT_FOUND', 'SOURCE_EMPTY', 'SOURCE_READ_ERROR'],
    'Ziel (S/4)': ['TARGET_CREATE_FAILED', 'TARGET_EXISTS', 'TARGET_LOCKED', 'TARGET_NOT_FOUND'],
    'Upload': ['UPLOAD_SIZE_EXCEEDED', 'UPLOAD_TIMEOUT', 'UPLOAD_FAILED'],
    'Netzwerk': ['GATEWAY_TIMEOUT', 'SERVER_UNAVAILABLE', 'RATE_LIMITED', 'SERVER_ERROR', 'NETWORK_ERROR'],
    'Sonstige': ['VALIDATION_ERROR', 'BAD_REQUEST', 'UNKNOWN', 'OTHER', 'PARSE_ERROR']
}

print(f"\n{'GRUPPE':<20} | {'ANZAHL':>8} | KATEGORIEN")
print("-" * 80)
for group_name, cats in groups.items():
    total = sum(error_categories.get(c, {}).get('count', 0) for c in cats)
    if total > 0:
        found_cats = [c for c in cats if error_categories.get(c, {}).get('count', 0) > 0]
        print(f"{group_name:<20} | {total:>8} | {', '.join(found_cats)}")

# 2. File-level errors from migration_file_details
print("\n\n=== FILE-LEVEL ERRORS (migration_file_details) ===")
with engine.connect() as con:
    result = con.execute(text("""
        SELECT 
            upload_status,
            error_category,
            http_status_code,
            LEFT(error_detail, 150) as error_short,
            COUNT(*) as cnt
        FROM dbo.migration_file_details
        WHERE upload_status NOT LIKE 'SUCCESS%'
        GROUP BY upload_status, error_category, http_status_code, LEFT(error_detail, 150)
        ORDER BY cnt DESC
    """)).fetchall()

print(f"\n{'STATUS':<30} | {'KATEGORIE':<20} | {'HTTP':>4} | {'CNT':>5} | DETAIL")
print("-" * 100)
for row in result[:25]:
    status, cat, http, detail, cnt = row
    cat_str = cat or "?"
    detail_str = (detail[:40] + "...") if detail and len(detail) > 40 else (detail or "-")
    print(f"{status:<30} | {cat_str:<20} | {http or 0:>4} | {cnt:>5} | {detail_str}")


# 3. Suggested better categories
print("\n\n" + "=" * 80)
print("VORGESCHLAGENE VERBESSERTE KATEGORIEN")
print("=" * 80)

categories = """
┌─────────────────────────────────────────────────────────────────────────────────┐
│ KATEGORIE              │ BESCHREIBUNG                    │ URSACHE / LÖSUNG    │
├─────────────────────────────────────────────────────────────────────────────────┤
│ API_KEY_INVALID        │ API-Key nicht gültig            │ APIM: API hinzufügen│
│ API_KEY_MISSING        │ API-Key fehlt im Request        │ Code-Fehler         │
│ TOKEN_EXPIRED          │ OAuth Token abgelaufen          │ Neu einloggen       │
│ CSRF_FAILED            │ CSRF-Token ungültig/fehlt       │ Session erneuern    │
│ AUTH_NO_PERMISSION     │ Keine Berechtigung (BEGRU)      │ SAP Rolle prüfen    │
├─────────────────────────────────────────────────────────────────────────────────┤
│ SOURCE_NOT_FOUND       │ Dokument in R/3 nicht gefunden  │ Quelldaten prüfen   │
│ SOURCE_EMPTY           │ Container ohne Dateien          │ Normal (leer)       │
│ SOURCE_READ_ERROR      │ Lesefehler im Quellsystem       │ R/3 API prüfen      │
├─────────────────────────────────────────────────────────────────────────────────┤
│ TARGET_CREATE_FAILED   │ Anlage im Ziel fehlgeschlagen   │ SAP Log prüfen      │
│ TARGET_EXISTS          │ Dokument existiert bereits      │ Duplikat            │
│ TARGET_LOCKED          │ Ziel-Objekt gesperrt            │ Sperre lösen        │
├─────────────────────────────────────────────────────────────────────────────────┤
│ UPLOAD_SIZE_EXCEEDED   │ Datei zu groß für Upload        │ Limit erhöhen/split │
│ UPLOAD_TIMEOUT         │ Upload-Timeout (große Datei)    │ Kleinere Datei      │
│ UPLOAD_FAILED          │ Upload aus anderem Grund        │ Details prüfen      │
├─────────────────────────────────────────────────────────────────────────────────┤
│ GATEWAY_TIMEOUT        │ API Gateway Timeout (504)       │ Retry später        │
│ RATE_LIMITED           │ Zu viele Requests (429)         │ Pacing erhöhen      │
│ SERVER_ERROR           │ SAP Serverfehler (5xx)          │ SAP Support         │
│ NETWORK_ERROR          │ Netzwerkproblem                 │ Verbindung prüfen   │
└─────────────────────────────────────────────────────────────────────────────────┘
"""
print(categories)
