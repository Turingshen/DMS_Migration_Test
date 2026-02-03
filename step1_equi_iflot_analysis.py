"""
Step 1: Create DRAD with plant codes for EQUI and IFLOT
EQUI: OBJKY = EQUNR (18-stellig) → Join EQUZ.EQUNR → EQUZ.IWERK
IFLOT: OBJKY = TPLNR (30-stellig) → Join IFLOT.TPLNR → IFLOT.IWERK
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

# First let's check the data for EQUI in DRAD
print("=" * 80)
print("Step 1: Analyse EQUI und IFLOT")
print("=" * 80)

# Check EQUI count in DRAD
print("\n1. DRAD Einträge nach DOKOB:")
cursor.execute("""
    SELECT DOKOB, COUNT(*) as CNT 
    FROM DIL.DRAD 
    WHERE DOKOB IN ('EQUI', 'IFLOT')
    GROUP BY DOKOB
""")
for row in cursor.fetchall():
    print(f"   {row[0]}: {row[1]:,}")

# Check sample OBJKY for EQUI to understand the format
print("\n2. Beispiel OBJKY für EQUI (erste 5):")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN
    FROM DIL.DRAD 
    WHERE DOKOB = 'EQUI'
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' (Länge: {row[1]})")

# Check sample EQUNR from EQUZ
print("\n3. Beispiel EQUNR aus EQUZ (erste 5):")
cursor.execute("""
    SELECT EQUNR, IWERK, LENGTH(EQUNR) as LEN
    FROM DIL.EQUZ 
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' -> Werk: {row[1]} (Länge: {row[2]})")

# Check sample OBJKY for IFLOT
print("\n4. Beispiel OBJKY für IFLOT (erste 5):")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN
    FROM DIL.DRAD 
    WHERE DOKOB = 'IFLOT'
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' (Länge: {row[1]})")

# Check sample TPLNR from IFLOT
print("\n5. Beispiel TPLNR aus IFLOT (erste 5):")
cursor.execute("""
    SELECT TPLNR, IWERK, LENGTH(TPLNR) as LEN
    FROM DIL.IFLOT 
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' -> Werk: {row[1]} (Länge: {row[2]})")

# Now test the join for EQUI
print("\n" + "=" * 80)
print("6. Test Join DRAD-EQUI -> EQUZ:")
cursor.execute("""
    SELECT COUNT(*) 
    FROM DIL.DRAD d
    INNER JOIN DIL.EQUZ e ON e.EQUNR = d.OBJKY
    WHERE d.DOKOB = 'EQUI'
""")
equi_join_count = cursor.fetchone()[0]
print(f"   Matched records: {equi_join_count:,}")

# Test the join for IFLOT  
print("\n7. Test Join DRAD-IFLOT -> IFLOT:")
cursor.execute("""
    SELECT COUNT(*) 
    FROM DIL.DRAD d
    INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
    WHERE d.DOKOB = 'IFLOT'
""")
iflot_join_count = cursor.fetchone()[0]
print(f"   Matched records: {iflot_join_count:,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
