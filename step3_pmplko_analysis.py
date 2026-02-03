"""
Step 3: PMPLKO - Arbeitspläne/Task Lists
DOKOB = 'PMPLKO'
OBJKY Struktur (11 Zeichen):
  - Position 1: PLNTY (1 Zeichen) - nur A, T, E interessant
  - Position 2-9: PLNNR (8 Zeichen)
  - Position 10-11: PLNAL (2 Zeichen)

Beispiele:
  AUTMLRELQ11 → PLNTY='A', PLNNR='UTMLRELQ', PLNAL='11'
  T0015150102 → PLNTY='T', PLNNR='00151501', PLNAL='02'
  E0005458001 → PLNTY='E', PLNNR='00054580', PLNAL='01'

Werk = PLKO.WERKS
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
print("Step 3: PMPLKO - Arbeitspläne Analyse")
print("=" * 80)

# 1. Count PMPLKO in DRAD
print("\n1. DRAD Einträge mit DOKOB = 'PMPLKO':")
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'PMPLKO'")
print(f"   Count: {cursor.fetchone()[0]:,}")

# 2. Sample OBJKY for PMPLKO
print("\n2. Beispiel OBJKY für PMPLKO (erste 10):")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN,
           LEFT(OBJKY, 1) as PLNTY,
           SUBSTRING(OBJKY, 2, 8) as PLNNR,
           SUBSTRING(OBJKY, 10, 2) as PLNAL
    FROM DIL.DRAD 
    WHERE DOKOB = 'PMPLKO'
    LIMIT 10
""")
print(f"   {'OBJKY':<15} {'LEN':>4} {'PLNTY':>6} {'PLNNR':<10} {'PLNAL':>5}")
print("   " + "-" * 50)
for row in cursor.fetchall():
    print(f"   {row[0]:<15} {row[1]:>4} {row[2]:>6} {row[3]:<10} {row[4]:>5}")

# 3. Distribution by PLNTY
print("\n3. Verteilung nach PLNTY (erstes Zeichen):")
cursor.execute("""
    SELECT LEFT(OBJKY, 1) as PLNTY, COUNT(*) as CNT
    FROM DIL.DRAD 
    WHERE DOKOB = 'PMPLKO'
    GROUP BY LEFT(OBJKY, 1)
    ORDER BY CNT DESC
""")
for row in cursor.fetchall():
    print(f"   {row[0]}: {row[1]:,}")

# 4. Check PLKO columns
print("\n4. PLKO relevante Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'PLKO'
    AND (COLUMN_NAME IN ('PLNTY', 'PLNNR', 'PLNAL', 'WERKS', 'IWERK'))
    ORDER BY COLUMN_NAME
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:<15} ({row[2]})")

# 5. Sample PLKO data
print("\n5. Beispiel PLKO Daten:")
cursor.execute("""
    SELECT PLNTY, PLNNR, PLNAL, WERKS
    FROM DIL.PLKO 
    WHERE PLNTY IN ('A', 'T', 'E')
    LIMIT 10
""")
print(f"   {'PLNTY':<6} {'PLNNR':<10} {'PLNAL':<6} {'WERKS':<6}")
print("   " + "-" * 35)
for row in cursor.fetchall():
    print(f"   {row[0]:<6} {row[1]:<10} {row[2]:<6} {row[3]:<6}")

# 6. Test Join - Filter only A, T, E
print("\n6. Test Join DRAD -> PLKO (nur PLNTY A, T, E):")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.PLKO p ON 
        p.PLNTY = LEFT(d.OBJKY, 1) AND
        p.PLNNR = SUBSTRING(d.OBJKY, 2, 8) AND
        p.PLNAL = SUBSTRING(d.OBJKY, 10, 2)
    WHERE d.DOKOB = 'PMPLKO'
    AND LEFT(d.OBJKY, 1) IN ('A', 'T', 'E')
""")
print(f"   Matched records: {cursor.fetchone()[0]:,}")

# 7. Sample joined data
print("\n7. Beispieldaten PMPLKO mit Werk (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'OBJKY':<15} {'PLNTY'} {'PLNNR':<10} {'PLNAL'} {'WERKS':<6}")
print("   " + "-" * 80)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, d.OBJKY, 
           LEFT(d.OBJKY, 1) as PLNTY,
           SUBSTRING(d.OBJKY, 2, 8) as PLNNR,
           SUBSTRING(d.OBJKY, 10, 2) as PLNAL,
           p.WERKS
    FROM DIL.DRAD d
    INNER JOIN DIL.PLKO p ON 
        p.PLNTY = LEFT(d.OBJKY, 1) AND
        p.PLNNR = SUBSTRING(d.OBJKY, 2, 8) AND
        p.PLNAL = SUBSTRING(d.OBJKY, 10, 2)
    WHERE d.DOKOB = 'PMPLKO'
    AND LEFT(d.OBJKY, 1) IN ('A', 'T', 'E')
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<15} {row[3]}     {row[4]:<10} {row[5]}     {row[6]:<6}")

# 8. Distribution by plant
print("\n8. PMPLKO Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT p.WERKS, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.PLKO p ON 
        p.PLNTY = LEFT(d.OBJKY, 1) AND
        p.PLNNR = SUBSTRING(d.OBJKY, 2, 8) AND
        p.PLNAL = SUBSTRING(d.OBJKY, 10, 2)
    WHERE d.DOKOB = 'PMPLKO'
    AND LEFT(d.OBJKY, 1) IN ('A', 'T', 'E')
    GROUP BY p.WERKS
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<6}: {row[1]:>10,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
