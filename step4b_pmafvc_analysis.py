"""
Step 4b: PMAFVC - Vorgänge (korrigiert)
OBJKY Struktur (20 Zeichen):
  - Position 1-2: 'OV' Prefix (nicht benötigt)
  - Position 3-12: AUFPL (10 Zeichen)
  - Position 13-20: APLZL (8 Zeichen)

Beispiel: OV105134111700000032
  - OV = Prefix
  - 1051341117 = AUFPL
  - 00000032 = APLZL

Werk = AFVC.WERKS
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
print("Step 4b: PMAFVC - Vorgänge Analyse (korrigiert)")
print("=" * 80)

# 1. Sample OBJKY zerlegt
print("\n1. Beispiel OBJKY für PMAFVC zerlegt:")
cursor.execute("""
    SELECT OBJKY,
           SUBSTRING(OBJKY, 3, 10) as AUFPL,
           SUBSTRING(OBJKY, 13, 8) as APLZL
    FROM DIL.DRAD 
    WHERE DOKOB = 'PMAFVC'
    LIMIT 5
""")
print(f"   {'OBJKY':<22} {'AUFPL':<12} {'APLZL':<10}")
print("   " + "-" * 50)
for row in cursor.fetchall():
    print(f"   {row[0]:<22} {row[1]:<12} {row[2]:<10}")

# 2. Check AFVC columns
print("\n2. AFVC relevante Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'AFVC'
    AND COLUMN_NAME IN ('AUFPL', 'APLZL', 'WERKS', 'VORNR')
    ORDER BY COLUMN_NAME
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:<15} ({row[2]})")

# 3. Sample AFVC data
print("\n3. Beispiel AFVC Daten:")
cursor.execute("SELECT AUFPL, APLZL, WERKS FROM DIL.AFVC WHERE WERKS IS NOT NULL AND WERKS != '' LIMIT 5")
print(f"   {'AUFPL':<12} {'APLZL':<10} {'WERKS':<6}")
print("   " + "-" * 35)
for row in cursor.fetchall():
    print(f"   {row[0]:<12} {row[1]:<10} {row[2]:<6}")

# 4. Test Join PMAFVC -> AFVC
print("\n4. Test Join DRAD (PMAFVC) -> AFVC:")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.AFVC a ON 
        a.AUFPL = SUBSTRING(d.OBJKY, 3, 10) AND
        a.APLZL = SUBSTRING(d.OBJKY, 13, 8)
    WHERE d.DOKOB = 'PMAFVC'
""")
print(f"   Matched records: {cursor.fetchone()[0]:,}")

# 5. Sample joined data
print("\n5. Beispieldaten PMAFVC mit Werk (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'AUFPL':<12} {'APLZL':<10} {'WERKS':<6}")
print("   " + "-" * 65)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, 
           SUBSTRING(d.OBJKY, 3, 10) as AUFPL,
           SUBSTRING(d.OBJKY, 13, 8) as APLZL,
           a.WERKS
    FROM DIL.DRAD d
    INNER JOIN DIL.AFVC a ON 
        a.AUFPL = SUBSTRING(d.OBJKY, 3, 10) AND
        a.APLZL = SUBSTRING(d.OBJKY, 13, 8)
    WHERE d.DOKOB = 'PMAFVC'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<12} {row[3]:<10} {row[4]:<6}")

# 6. Distribution by plant
print("\n6. PMAFVC Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT a.WERKS, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.AFVC a ON 
        a.AUFPL = SUBSTRING(d.OBJKY, 3, 10) AND
        a.APLZL = SUBSTRING(d.OBJKY, 13, 8)
    WHERE d.DOKOB = 'PMAFVC'
    GROUP BY a.WERKS
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<6}: {row[1]:>10,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
