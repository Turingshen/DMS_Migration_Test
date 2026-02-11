"""Quick analysis of migration errors for a batch."""
from app_config import MiscEngine
from sqlalchemy import text
import json

engine = MiscEngine.load().engine
BATCH = 'DMS_20260211_081936'

with engine.begin() as con:
    # Get distinct full error bodies
    rows = con.execute(text("""
        SELECT DISTINCT execution_error
        FROM dbo.migration_staging
        WHERE batch_id = :b AND execution_status NOT IN ('pending', 'success')
    """), {'b': BATCH}).fetchall()

    print(f"=== {len(rows)} distinct error messages ===\n")
    for i, r in enumerate(rows):
        raw = r[0] or ''
        print(f"--- Error #{i+1} ---")
        try:
            parsed = json.loads(raw)
            print(json.dumps(parsed, indent=2)[:2000])
        except:
            print(raw[:2000])
        print()
