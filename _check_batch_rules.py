"""Check rule application on a specific batch."""
from app_config import MiscEngine
from sqlalchemy import text

engine = MiscEngine.load().engine
BATCH = 'DMS_20260211_081936'

# 1) Active rules
with engine.begin() as con:
    rules = con.execute(text("""
        SELECT id, rule_type, source_column, source_value, target_column, target_value,
               condition_column, condition_value, condition_operator, execution_order
        FROM dbo.migration_translations
        WHERE active = 1
        ORDER BY execution_order
    """)).fetchall()
    print("=== ACTIVE RULES ===")
    for r in rules:
        cond = f"  IF {r[6]} {r[8]} '{r[7]}'" if r[6] else ""
        print(f"  #{r[0]:>3} [{r[1]:<12}] {r[2] or ''} = '{r[3] or ''}' -> {r[4]} = '{r[5] or ''}'{cond}  (order={r[9]})")

# 2) DocType mapping summary
with engine.begin() as con:
    stats = con.execute(text("""
        SELECT 
            source_documenttype, target_documenttype,
            COUNT(*) as cnt,
            SUM(CASE WHEN target_documentnumber IS NOT NULL THEN 1 ELSE 0 END) as has_tgt_nr,
            SUM(CASE WHEN target_documentnumber_sanitized IS NOT NULL THEN 1 ELSE 0 END) as has_sanitized
        FROM dbo.migration_staging
        WHERE batch_id = :batch_id
        GROUP BY source_documenttype, target_documenttype
        ORDER BY cnt DESC
    """), {'batch_id': BATCH}).fetchall()
    total = sum(s[2] for s in stats)
    print(f"\n=== BATCH {BATCH}: DocType Mapping ({total} records) ===")
    print(f"  {'src_type':<10} {'tgt_type':<10} {'count':>6} {'has_tgt_nr':>10} {'has_sanitized':>14}")
    for s in stats:
        print(f"  {s[0] or '?':<10} {s[1] or '?':<10} {s[2]:>6} {s[3]:>10} {s[4]:>14}")

# 3) Check sanitization differences
with engine.begin() as con:
    diffs = con.execute(text("""
        SELECT TOP 30
            id, source_documentnumber, target_documentnumber, target_documentnumber_sanitized, target_documenttype
        FROM dbo.migration_staging
        WHERE batch_id = :batch_id
          AND target_documentnumber IS NOT NULL
          AND (target_documentnumber_sanitized IS NULL 
               OR target_documentnumber != target_documentnumber_sanitized)
        ORDER BY id
    """), {'batch_id': BATCH}).fetchall()
    print(f"\n=== SANITIZATION DIFFERENCES ({len(diffs)} shown, max 30) ===")
    if diffs:
        for r in diffs:
            san = r[3] or '(null)'
            print(f"  #{r[0]:>8}  '{r[2]}' -> '{san}'  (type={r[4]})")
    else:
        print("  No differences — all target_documentnumber values are clean or column not yet populated.")

# 4) IY1/IY2 internal numbering check
with engine.begin() as con:
    internal = con.execute(text("""
        SELECT target_documenttype, 
               COUNT(*) as cnt,
               SUM(CASE WHEN target_documentnumber IS NULL THEN 1 ELSE 0 END) as null_nr
        FROM dbo.migration_staging
        WHERE batch_id = :batch_id
          AND target_documenttype IN ('IY1', 'IY2')
        GROUP BY target_documenttype
    """), {'batch_id': BATCH}).fetchall()
    if internal:
        print(f"\n=== IY1/IY2 INTERNAL NUMBERING CHECK ===")
        for r in internal:
            pct = (r[2]/r[1]*100) if r[1] else 0
            print(f"  {r[0]}: {r[1]} records, {r[2]} have NULL target_documentnumber ({pct:.0f}%)")
    
# 5) Sample records
with engine.begin() as con:
    samples = con.execute(text("""
        SELECT TOP 15
            id, source_documentnumber, source_documenttype,
            target_documentnumber, target_documentnumber_sanitized, target_documenttype
        FROM dbo.migration_staging
        WHERE batch_id = :batch_id
        ORDER BY source_documenttype, id
    """), {'batch_id': BATCH}).fetchall()
    print(f"\n=== SAMPLE RECORDS (first 15) ===")
    print(f"  {'id':>8}  {'src_doknr':<26} {'src_type':<8} {'tgt_doknr':<26} {'tgt_sanitized':<26} {'tgt_type':<8}")
    for r in samples:
        src_nr = r[1] or ''
        tgt_nr = r[3] if r[3] is not None else '(null)'
        tgt_san = r[4] if r[4] is not None else '(null)'
        print(f"  {r[0]:>8}  {src_nr:<26} {r[2] or '':<8} {tgt_nr:<26} {tgt_san:<26} {r[5] or '':<8}")
