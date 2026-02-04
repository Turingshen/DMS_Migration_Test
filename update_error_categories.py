"""
Update error categories for existing records based on new classification.
Only updates the error_category column - technical details in error_detail remain unchanged.
"""
import json
from app_config import MiscEngine
from sqlalchemy import text
from app.process import _classify_error, get_error_details

misc_db = MiscEngine.load()
engine = misc_db.engine

def update_file_details_categories():
    """Re-classify error_category in migration_file_details based on stored error_detail."""
    print("=== Updating migration_file_details.error_category ===")
    
    # Get records with errors that need re-classification
    with engine.connect() as con:
        result = con.execute(text("""
            SELECT id, upload_status, http_status_code, error_detail, error_category
            FROM dbo.migration_file_details
            WHERE upload_status NOT LIKE 'SUCCESS%'
        """)).fetchall()
    
    print(f"Found {len(result)} records with errors")
    
    updates = []
    for row in result:
        record_id, status, http_code, detail, old_cat = row
        
        # Build error_info dict from stored data
        error_info = {
            'status_code': http_code,
            'detail': detail or ''
        }
        
        # Also parse status for additional info (e.g. "UPLOAD_FAIL_403: Invalid ApiKey")
        if ':' in (status or ''):
            parts = status.split(':', 1)
            if len(parts) > 1:
                error_info['detail'] = parts[1].strip() + ' ' + (detail or '')
        
        # Classify with new logic
        new_cat = _classify_error(error_info)
        
        if new_cat != old_cat:
            updates.append({
                'id': record_id,
                'old_cat': old_cat,
                'new_cat': new_cat
            })
    
    print(f"Need to update {len(updates)} records")
    
    # Apply updates in batches
    if updates:
        with engine.begin() as con:
            for upd in updates:
                con.execute(text("""
                    UPDATE dbo.migration_file_details
                    SET error_category = :new_cat
                    WHERE id = :id
                """), {'new_cat': upd['new_cat'], 'id': upd['id']})
        
        # Show statistics
        cat_counts = {}
        for upd in updates:
            cat = upd['new_cat']
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        
        print("\nUpdated categories:")
        for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
            desc, action = get_error_details(cat)
            print(f"  {cat:25} | {cnt:5} | {desc}")
    
    return len(updates)


def show_summary():
    """Show current error distribution after update."""
    print("\n=== AKTUELLE FEHLERVERTEILUNG ===\n")
    
    # File-level errors
    with engine.connect() as con:
        result = con.execute(text("""
            SELECT error_category, COUNT(*) as cnt
            FROM dbo.migration_file_details
            WHERE upload_status NOT LIKE 'SUCCESS%'
            GROUP BY error_category
            ORDER BY cnt DESC
        """)).fetchall()
    
    print("KATEGORIE                 | ANZAHL | BESCHREIBUNG                 | AKTION")
    print("-" * 100)
    for row in result:
        cat, cnt = row
        cat_str = cat if cat else 'NULL'
        desc, action = get_error_details(cat_str)
        print(f"{cat_str:25} | {cnt:6} | {desc:28} | {action}")


if __name__ == "__main__":
    print("=" * 80)
    print("ERROR CATEGORY UPDATE SCRIPT")
    print("Technische Details in error_detail bleiben unverändert!")
    print("Nur error_category wird aktualisiert für bessere Filterung.")
    print("=" * 80)
    print()
    
    updated = update_file_details_categories()
    print(f"\n✓ {updated} Datensätze aktualisiert")
    
    show_summary()
