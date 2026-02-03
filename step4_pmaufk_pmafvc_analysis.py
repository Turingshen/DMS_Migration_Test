"""
Step 4: PMAUFK und PMAFVC - Aufträge und Vorgänge
PMAUFK: OBJKY = AUFNR (12-stellig) → AUFK.WERKS
PMAFVC: OBJKY = AUFNR (12) + VORNR (4) → AUFK.WERKS (über AUFNR)
LO2 Testsystem
"""
from hdbcli import dbapi

conn = dbapi.connect(
    address='lo2hdb.dmz.basf-ag.de',
    port=30015,
    user='altnict',
    password='FinJaleymie22:22',
    encrypt=True,
    sslValidateCertificate=True
)

cursor = conn.cursor()

print("=" * 80)
print("Step 4: PMAUFK und PMAFVC - Aufträge Analyse")
print("=" * 80)

# ==================== PMAUFK ====================
print("\n" + "=" * 40)
print("PMAUFK - Aufträge")
print("=" * 40)

# 1. Count PMAUFK in DRAD
print("\n1. DRAD Einträge mit DOKOB = 'PMAUFK':")
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'PMAUFK'")
print(f"   Count: {cursor.fetchone()[0]:,}")

# 2. Sample OBJKY for PMAUFK
print("\n2. Beispiel OBJKY für PMAUFK (erste 5):")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN
    FROM DIL.DRAD 
    WHERE DOKOB = 'PMAUFK'
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' (Länge: {row[1]})")

# 3. Check AUFK columns
print("\n3. AUFK relevante Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'AUFK'
    AND COLUMN_NAME IN ('AUFNR', 'WERKS')
    ORDER BY COLUMN_NAME
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:<15} ({row[2]})")

# 4. Sample AUFK data
print("\n4. Beispiel AUFK Daten:")
cursor.execute("SELECT AUFNR, WERKS FROM DIL.AUFK LIMIT 5")
print(f"   {'AUFNR':<15} {'WERKS':<6}")
print("   " + "-" * 25)
for row in cursor.fetchall():
    print(f"   {row[0]:<15} {row[1]:<6}")

# 5. Test Join PMAUFK -> AUFK
print("\n5. Test Join DRAD (PMAUFK) -> AUFK:")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.AUFK a ON a.AUFNR = d.OBJKY
    WHERE d.DOKOB = 'PMAUFK'
""")
print(f"   Matched records: {cursor.fetchone()[0]:,}")

# 6. Sample joined data PMAUFK
print("\n6. Beispieldaten PMAUFK mit Werk (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'OBJKY':<15} {'WERKS':<6}")
print("   " + "-" * 55)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, d.OBJKY, a.WERKS
    FROM DIL.DRAD d
    INNER JOIN DIL.AUFK a ON a.AUFNR = d.OBJKY
    WHERE d.DOKOB = 'PMAUFK'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<15} {row[3]:<6}")

# 7. PMAUFK Distribution by plant
print("\n7. PMAUFK Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT a.WERKS, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.AUFK a ON a.AUFNR = d.OBJKY
    WHERE d.DOKOB = 'PMAUFK'
    GROUP BY a.WERKS
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<6}: {row[1]:>10,}")

# ==================== PMAFVC ====================
print("\n" + "=" * 40)
print("PMAFVC - Vorgänge")
print("=" * 40)

# 8. Count PMAFVC in DRAD
print("\n8. DRAD Einträge mit DOKOB = 'PMAFVC':")
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'PMAFVC'")
print(f"   Count: {cursor.fetchone()[0]:,}")

# 9. Sample OBJKY for PMAFVC
print("\n9. Beispiel OBJKY für PMAFVC (erste 5):")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN,
           LEFT(OBJKY, 12) as AUFNR,
           SUBSTRING(OBJKY, 13, 4) as VORNR
    FROM DIL.DRAD 
    WHERE DOKOB = 'PMAFVC'
    LIMIT 5
""")
print(f"   {'OBJKY':<18} {'LEN':>4} {'AUFNR':<14} {'VORNR':<6}")
print("   " + "-" * 50)
for row in cursor.fetchall():
    print(f"   {row[0]:<18} {row[1]:>4} {row[2]:<14} {row[3]:<6}")

# 10. Test Join PMAFVC -> AUFK (über AUFNR)
print("\n10. Test Join DRAD (PMAFVC) -> AUFK:")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.AUFK a ON a.AUFNR = LEFT(d.OBJKY, 12)
    WHERE d.DOKOB = 'PMAFVC'
""")
print(f"    Matched records: {cursor.fetchone()[0]:,}")

# 11. Sample joined data PMAFVC
print("\n11. Beispieldaten PMAFVC mit Werk (erste 10):")
print(f"    {'DOKAR':<5} {'DOKNR':<25} {'AUFNR':<14} {'VORNR':<6} {'WERKS':<6}")
print("    " + "-" * 60)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, LEFT(d.OBJKY, 12) as AUFNR, 
           SUBSTRING(d.OBJKY, 13, 4) as VORNR, a.WERKS
    FROM DIL.DRAD d
    INNER JOIN DIL.AUFK a ON a.AUFNR = LEFT(d.OBJKY, 12)
    WHERE d.DOKOB = 'PMAFVC'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"    {row[0]:<5} {row[1]:<25} {row[2]:<14} {row[3]:<6} {row[4]:<6}")

# 12. PMAFVC Distribution by plant
print("\n12. PMAFVC Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT a.WERKS, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.AUFK a ON a.AUFNR = LEFT(d.OBJKY, 12)
    WHERE d.DOKOB = 'PMAFVC'
    GROUP BY a.WERKS
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"    {row[0]:<6}: {row[1]:>10,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
