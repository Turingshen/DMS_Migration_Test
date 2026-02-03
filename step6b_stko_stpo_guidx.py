"""
Step 6b: STKO_DOC und STPO_DOC - Join über GUIDX
OBJKY = 32 hex Zeichen = BINTOHEX(GUIDX)
STKO.WRKAN = Werk
STPO hat kein Werk, muss über STKO.STLNR gejoint werden
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
print("Step 6b: STKO_DOC / STPO_DOC - GUIDX Join")
print("=" * 80)

# 1. Test STKO GUIDX format
print("\n1. Beispiel STKO.GUIDX (als HEX):")
cursor.execute("""
    SELECT BINTOHEX(GUIDX) as GUIDX_HEX, STLTY, STLNR, STLAL, WRKAN
    FROM DIL.STKO 
    WHERE WRKAN IS NOT NULL AND WRKAN != ''
    LIMIT 5
""")
print(f"   {'GUIDX_HEX':<34} {'STLTY':<6} {'STLNR':<10} {'STLAL':<6} {'WRKAN':<6}")
print("   " + "-" * 70)
for row in cursor.fetchall():
    print(f"   {row[0]:<34} {row[1]:<6} {row[2]:<10} {row[3]:<6} {row[4]:<6}")

# 2. Test Join STKO_DOC -> STKO via GUIDX
print("\n2. Test Join DRAD (STKO_DOC) -> STKO via GUIDX:")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.STKO s ON UPPER(BINTOHEX(s.GUIDX)) = d.OBJKY
    WHERE d.DOKOB = 'STKO_DOC'
""")
print(f"   Matched records: {cursor.fetchone()[0]:,}")

# 3. Sample joined data STKO_DOC
print("\n3. Beispieldaten STKO_DOC mit Werk (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'STLNR':<10} {'WRKAN':<6}")
print("   " + "-" * 50)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, s.STLNR, s.WRKAN
    FROM DIL.DRAD d
    INNER JOIN DIL.STKO s ON UPPER(BINTOHEX(s.GUIDX)) = d.OBJKY
    WHERE d.DOKOB = 'STKO_DOC'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<10} {row[3]:<6}")

# 4. STKO_DOC Distribution by plant
print("\n4. STKO_DOC Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT s.WRKAN, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.STKO s ON UPPER(BINTOHEX(s.GUIDX)) = d.OBJKY
    WHERE d.DOKOB = 'STKO_DOC'
    GROUP BY s.WRKAN
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<6}: {row[1]:>10,}")

# ==================== STPO_DOC ====================
print("\n" + "=" * 40)
print("STPO_DOC")
print("=" * 40)

# 5. Test STPO GUIDX format
print("\n5. Beispiel STPO.GUIDX (als HEX):")
cursor.execute("""
    SELECT BINTOHEX(GUIDX) as GUIDX_HEX, STLTY, STLNR, STLKN
    FROM DIL.STPO 
    LIMIT 5
""")
print(f"   {'GUIDX_HEX':<34} {'STLTY':<6} {'STLNR':<10} {'STLKN':<10}")
print("   " + "-" * 65)
for row in cursor.fetchall():
    print(f"   {row[0]:<34} {row[1]:<6} {row[2]:<10} {row[3]:<10}")

# 6. Test Join STPO_DOC -> STPO via GUIDX, then -> STKO for WRKAN
print("\n6. Test Join DRAD (STPO_DOC) -> STPO -> STKO via GUIDX:")
cursor.execute("""
    SELECT COUNT(*)
    FROM DIL.DRAD d
    INNER JOIN DIL.STPO sp ON UPPER(BINTOHEX(sp.GUIDX)) = d.OBJKY
    INNER JOIN DIL.STKO sk ON sk.STLTY = sp.STLTY AND sk.STLNR = sp.STLNR
    WHERE d.DOKOB = 'STPO_DOC'
""")
print(f"   Matched records: {cursor.fetchone()[0]:,}")

# 7. Sample joined data STPO_DOC
print("\n7. Beispieldaten STPO_DOC mit Werk (erste 10):")
print(f"   {'DOKAR':<5} {'DOKNR':<25} {'STLNR':<10} {'STLKN':<10} {'WRKAN':<6}")
print("   " + "-" * 60)
cursor.execute("""
    SELECT d.DOKAR, d.DOKNR, sp.STLNR, sp.STLKN, sk.WRKAN
    FROM DIL.DRAD d
    INNER JOIN DIL.STPO sp ON UPPER(BINTOHEX(sp.GUIDX)) = d.OBJKY
    INNER JOIN DIL.STKO sk ON sk.STLTY = sp.STLTY AND sk.STLNR = sp.STLNR
    WHERE d.DOKOB = 'STPO_DOC'
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<5} {row[1]:<25} {row[2]:<10} {row[3]:<10} {row[4]:<6}")

# 8. STPO_DOC Distribution by plant
print("\n8. STPO_DOC Verteilung nach Werk (Top 10):")
cursor.execute("""
    SELECT sk.WRKAN, COUNT(*) as CNT
    FROM DIL.DRAD d
    INNER JOIN DIL.STPO sp ON UPPER(BINTOHEX(sp.GUIDX)) = d.OBJKY
    INNER JOIN DIL.STKO sk ON sk.STLTY = sp.STLTY AND sk.STLNR = sp.STLNR
    WHERE d.DOKOB = 'STPO_DOC'
    GROUP BY sk.WRKAN
    ORDER BY CNT DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<6}: {row[1]:>10,}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
