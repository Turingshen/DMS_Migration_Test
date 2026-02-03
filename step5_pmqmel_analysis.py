"""
Step 5: PMQMEL - Instandhaltungsmeldungen
DOKOB = 'PMQMEL'
OBJKY = QMNUM (12-stellig) → QMIH.IWERK
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
print("Step 5: PMQMEL - Instandhaltungsmeldungen Analyse")
print("=" * 80)

# 1. Count PMQMEL in DRAD
print("\n1. DRAD Einträge mit DOKOB = 'PMQMEL':")
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'PMQMEL'")
print(f"   Count: {cursor.fetchone()[0]:,}")

# 2. Sample OBJKY for PMQMEL
print("\n2. Beispiel OBJKY für PMQMEL (erste 5):")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN
    FROM DIL.DRAD 
    WHERE DOKOB = 'PMQMEL'
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' (Länge: {row[1]})")

# 3. Check QMIH columns
print("\n3. QMIH relevante Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'QMIH'
    AND COLUMN_NAME IN ('QMNUM', 'IWERK')
    ORDER BY COLUMN_NAME
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:<15} ({row[2]})")

# 4. Sample QMIH data
print("\n4. Beispiel QMIH Daten:")
cursor.execute("SELECT QMNUM, IWERK FROM DIL.QMIH WHERE IWERK IS NOT NULL AND IWERK != '' LIMIT 5")
print(f"   {'QMNUM':<15} {'IWERK':<6}")
print("   " + "-" * 25)
for row in cursor.fetchall():
    print(f"   {row[0]:<15} {row[1]:<6}")

# 5. Test Join PMQMEL -> QMIH
print("\n5. Test Join DRAD (PMQMEL) -> QMIH:")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.QMIH q ON q.QMNUM = d.OBJKY
    WHERE d.DOKOB = 'PMQMEL'
""")
print(f"   Matched records: {cursor.fetchone()[0]:,}")

# 6. Sample joined data
print("\n6. Beispieldaten PMQMEL mit Werk (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'OBJKY':<15} {'IWERK':<6}")
print("   " + "-" * 55)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, d.OBJKY, q.IWERK
    FROM DIL.DRAD d
    INNER JOIN DIL.QMIH q ON q.QMNUM = d.OBJKY
    WHERE d.DOKOB = 'PMQMEL'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<15} {row[3]:<6}")

# 7. Distribution by plant
print("\n7. PMQMEL Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT q.IWERK, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.QMIH q ON q.QMNUM = d.OBJKY
    WHERE d.DOKOB = 'PMQMEL'
    GROUP BY q.IWERK
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<6}: {row[1]:>10,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
