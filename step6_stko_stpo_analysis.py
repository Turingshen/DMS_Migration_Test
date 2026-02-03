"""
Step 6: STKO_DOC und STPO_DOC - Stücklisten Analyse
OBJKY = 32 hex Zeichen (GUID16/RAW16)
Generiert aus STLTY + STLNR + STLAL

Prüfe ob STKO/STPO ein GUID-Feld haben
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
print("Step 6: STKO_DOC / STPO_DOC - Stücklisten Analyse")
print("=" * 80)

# 1. Count STKO_DOC and STPO_DOC in DRAD
print("\n1. DRAD Einträge:")
cursor.execute("""
    SELECT DOKOB, COUNT(*) as CNT 
    FROM DIL.DRAD 
    WHERE DOKOB IN ('STKO_DOC', 'STPO_DOC')
    GROUP BY DOKOB
""")
for row in cursor.fetchall():
    print(f"   {row[0]}: {row[1]:,}")

# 2. Sample OBJKY
print("\n2. Beispiel OBJKY für STKO_DOC:")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN
    FROM DIL.DRAD 
    WHERE DOKOB = 'STKO_DOC'
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' (Länge: {row[1]})")

print("\n3. Beispiel OBJKY für STPO_DOC:")
cursor.execute("""
    SELECT OBJKY, LENGTH(OBJKY) as LEN
    FROM DIL.DRAD 
    WHERE DOKOB = 'STPO_DOC'
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   '{row[0]}' (Länge: {row[1]})")

# 3. Check STKO columns - looking for GUID fields
print("\n4. STKO alle Spalten (suche nach GUID/RAW Felder):")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'STKO'
    ORDER BY COLUMN_NAME
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<25} {row[1]:<15} ({row[2]})")

# 4. Check STPO columns
print("\n5. STPO alle Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'STPO'
    ORDER BY COLUMN_NAME
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<25} {row[1]:<15} ({row[2]})")

# 5. Sample STKO data with key fields
print("\n6. Beispiel STKO Daten (STLTY, STLNR, STLAL, WERKS):")
cursor.execute("""
    SELECT STLTY, STLNR, STLAL, WERKS
    FROM DIL.STKO 
    WHERE WERKS IS NOT NULL AND WERKS != ''
    LIMIT 5
""")
print(f"   {'STLTY':<6} {'STLNR':<12} {'STLAL':<6} {'WERKS':<6}")
print("   " + "-" * 35)
for row in cursor.fetchall():
    print(f"   {row[0]:<6} {row[1]:<12} {row[2]:<6} {row[3]:<6}")

# 6. Sample STPO data with key fields
print("\n7. Beispiel STPO Daten (STLTY, STLNR, STLKN, WERKS):")
cursor.execute("""
    SELECT STLTY, STLNR, STLKN, WERKS
    FROM DIL.STPO 
    WHERE WERKS IS NOT NULL AND WERKS != ''
    LIMIT 5
""")
print(f"   {'STLTY':<6} {'STLNR':<12} {'STLKN':<10} {'WERKS':<6}")
print("   " + "-" * 40)
for row in cursor.fetchall():
    print(f"   {row[0]:<6} {row[1]:<12} {row[2]:<10} {row[3]:<6}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
