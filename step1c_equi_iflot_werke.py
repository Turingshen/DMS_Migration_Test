"""
Create DRAD with plant codes for EQUI and IFLOT
EQUI: OBJKY = EQUNR → Join EQUZ (DATBI = 9999-12-31) → IWERK
IFLOT: OBJKY = TPLNR → Join IFLOT → IWERK
"""
from hdbcli import dbapi

conn = dbapi.connect(
    address='lo1hdb.dmz.basf-ag.de',
    port=30015,
    user='altnict',
    password='FinJaleymie99:99',
    encrypt=True,
    sslValidateCertificate=True
)

cursor = conn.cursor()

print("=" * 80)
print("DRAD mit Werkszuordnung - EQUI und IFLOT")
print("=" * 80)

# EQUI Query
print("\n1. EQUI - Join mit EQUZ (DATBI = 99991231):")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.EQUZ e ON e.EQUNR = d.OBJKY AND e.DATBI = '99991231'
    WHERE d.DOKOB = 'EQUI'
""")
equi_count = cursor.fetchone()[0]
print(f"   Matched EQUI records: {equi_count:,}")

# IFLOT Query
print("\n2. IFLOT - Join mit IFLOT:")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
    WHERE d.DOKOB = 'IFLOT'
""")
iflot_count = cursor.fetchone()[0]
print(f"   Matched IFLOT records: {iflot_count:,}")

# Sample output EQUI
print("\n3. Beispieldaten EQUI (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'DOKVR':<5} {'DOKTL':<5} {'DOKOB':<8} {'OBJKY':<20} {'WERK':<6}")
print("   " + "-" * 85)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, d.DOKVR, d.DOKTL, d.DOKOB, d.OBJKY, e.IWERK
    FROM DIL.DRAD d
    INNER JOIN DIL.EQUZ e ON e.EQUNR = d.OBJKY AND e.DATBI = '99991231'
    WHERE d.DOKOB = 'EQUI'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<5} {row[3]:<5} {row[4]:<8} {row[5]:<20} {row[6]:<6}")

# Sample output IFLOT
print("\n4. Beispieldaten IFLOT (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'DOKVR':<5} {'DOKTL':<5} {'DOKOB':<8} {'OBJKY':<22} {'WERK':<6}")
print("   " + "-" * 87)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, d.DOKVR, d.DOKTL, d.DOKOB, d.OBJKY, i.IWERK
    FROM DIL.DRAD d
    INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
    WHERE d.DOKOB = 'IFLOT'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<5} {row[3]:<5} {row[4]:<8} {row[5]:<22} {row[6]:<6}")

# Check distribution by plant for EQUI
print("\n5. EQUI Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT e.IWERK, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.EQUZ e ON e.EQUNR = d.OBJKY AND e.DATBI = '99991231'
    WHERE d.DOKOB = 'EQUI'
    GROUP BY e.IWERK
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<6}: {row[1]:>10,}")

# Check distribution by plant for IFLOT
print("\n6. IFLOT Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT i.IWERK, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
    WHERE d.DOKOB = 'IFLOT'
    GROUP BY i.IWERK
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   '{row[0]:<6}': {row[1]:>10,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
