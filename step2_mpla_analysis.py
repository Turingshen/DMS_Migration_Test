"""
Step 2: MPLA - Wartungsplan
DOKOB = 'MPLA'
OBJKY = WARPL (Wartungsplan-Nummer)
Werk = LEFT(PLAN_SORT, 4) aus MPLA
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
print("Step 2: MPLA - Wartungsplan Analyse")
print("=" * 80)

# 1. Count MPLA in DRAD
print("\n1. DRAD Einträge mit DOKOB = 'MPLA':")
cursor.execute("""
    SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'MPLA'
""")
print(f"   Count: {cursor.fetchone()[0]:,}")

# 2. Sample OBJKY for MPLA
print("\n2. Beispiel OBJKY für MPLA (erste 5):")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN
    FROM DIL.DRAD 
    WHERE DOKOB = 'MPLA'
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' (Länge: {row[1]})")

# 3. Check MPLA columns
print("\n3. MPLA relevante Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'MPLA'
    AND (COLUMN_NAME LIKE '%WARPL%' 
         OR COLUMN_NAME LIKE '%WERK%' 
         OR COLUMN_NAME LIKE '%SORT%'
         OR COLUMN_NAME LIKE '%IWERK%')
    ORDER BY COLUMN_NAME
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:<15} ({row[2]})")

# 4. Sample MPLA data
print("\n4. Beispiel MPLA Daten:")
cursor.execute("""
    SELECT WARPL, PLAN_SORT, LEFT(PLAN_SORT, 4) as WERK_FROM_SORT
    FROM DIL.MPLA 
    LIMIT 10
""")
print(f"   {'WARPL':<15} {'PLAN_SORT':<30} {'WERK (LEFT 4)':<10}")
print("   " + "-" * 60)
for row in cursor.fetchall():
    print(f"   {row[0]:<15} {row[1]:<30} {row[2]:<10}")

# 5. Test Join DRAD -> MPLA
print("\n5. Test Join DRAD -> MPLA (OBJKY = WARPL):")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.MPLA m ON m.WARPL = d.OBJKY
    WHERE d.DOKOB = 'MPLA'
""")
print(f"   Matched records: {cursor.fetchone()[0]:,}")

# 6. Sample joined data
print("\n6. Beispieldaten MPLA mit Werk (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'DOKVR':<5} {'DOKOB':<6} {'OBJKY':<15} {'WERK':<6}")
print("   " + "-" * 70)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, d.DOKVR, d.DOKOB, d.OBJKY, LEFT(m.PLAN_SORT, 4) as WERK
    FROM DIL.DRAD d
    INNER JOIN DIL.MPLA m ON m.WARPL = d.OBJKY
    WHERE d.DOKOB = 'MPLA'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<5} {row[3]:<6} {row[4]:<15} {row[5]:<6}")

# 7. Distribution by plant
print("\n7. MPLA Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT LEFT(m.PLAN_SORT, 4) as WERK, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.MPLA m ON m.WARPL = d.OBJKY
    WHERE d.DOKOB = 'MPLA'
    GROUP BY LEFT(m.SORT, 4)
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   '{row[0]:<6}': {row[1]:>10,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
