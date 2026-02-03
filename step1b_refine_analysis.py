"""
Step 1b: Refine EQUI join - use current valid EQUZ entry (DATBI filter)
Check IFLOT for empty IWERK - maybe we need ILOA table instead
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
print("Step 1b: Verfeinerte Analyse")
print("=" * 80)

# Check EQUZ columns for date validity
print("\n1. EQUZ Spalten mit Datum:")
cursor.execute("""
    SELECT COLUMN_NAME 
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'EQUZ'
    AND (COLUMN_NAME LIKE '%DAT%' OR COLUMN_NAME LIKE '%BIS%' OR COLUMN_NAME LIKE '%VON%')
""")
for row in cursor.fetchall():
    print(f"   {row[0]}")

# Check if EQUZ has DATBI (valid to)
print("\n2. EQUZ mit aktuell gültigem Eintrag (DATBI >= heute):")
cursor.execute("""
    SELECT COUNT(DISTINCT d.OBJKY)
    FROM DIL.DRAD d
    INNER JOIN DIL.EQUZ e ON e.EQUNR = d.OBJKY
    WHERE d.DOKOB = 'EQUI'
    AND e.DATBI >= CURRENT_DATE
""")
print(f"   Gültige EQUI Einträge: {cursor.fetchone()[0]:,}")

# Sample with DATBI
print("\n3. Beispiel EQUZ mit DATBI:")
cursor.execute("""
    SELECT e.EQUNR, e.IWERK, e.DATBI
    FROM DIL.EQUZ e
    WHERE e.DATBI >= CURRENT_DATE
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   {row[0]} -> Werk: {row[1]}, Gültig bis: {row[2]}")

# Check IFLOT - why is IWERK empty?
print("\n" + "=" * 80)
print("4. IFLOT Analyse - leere IWERK:")
cursor.execute("""
    SELECT COUNT(*) as TOTAL,
           SUM(CASE WHEN IWERK IS NULL OR IWERK = '' THEN 1 ELSE 0 END) as EMPTY_IWERK
    FROM DIL.IFLOT
""")
row = cursor.fetchone()
print(f"   Total: {row[0]:,}, Leere IWERK: {row[1]:,}")

# Check if there's ILOA table for functional location assignment
print("\n5. Gibt es ILOA Tabelle (FL Assignment)?")
cursor.execute("""
    SELECT COUNT(*) FROM SYS.TABLES 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'ILOA'
""")
iloa_exists = cursor.fetchone()[0]
print(f"   ILOA existiert: {'Ja' if iloa_exists else 'Nein'}")

if iloa_exists:
    print("\n6. ILOA Spalten:")
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM SYS.TABLE_COLUMNS 
        WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'ILOA'
        AND (COLUMN_NAME LIKE '%WERK%' OR COLUMN_NAME LIKE '%TPLNR%' OR COLUMN_NAME LIKE '%ILOAN%')
    """)
    for row in cursor.fetchall():
        print(f"   {row[0]}")

# Alternative: Check IFLOT for SWERK (planning plant) or other plant fields
print("\n7. IFLOT Werk-relevante Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME 
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'IFLOT'
    AND (COLUMN_NAME LIKE '%WERK%' OR COLUMN_NAME LIKE '%SWERK%' OR COLUMN_NAME LIKE '%PLANT%')
""")
for row in cursor.fetchall():
    print(f"   {row[0]}")

# Check sample IFLOT with all plant fields
print("\n8. Beispiel IFLOT mit allen Werk-Feldern:")
cursor.execute("""
    SELECT TPLNR, IWERK, SWERK, INGRP
    FROM DIL.IFLOT
    WHERE IWERK != '' OR SWERK != ''
    LIMIT 5
""")
for row in cursor.fetchall():
    print(f"   {row[0]} -> IWERK: '{row[1]}', SWERK: '{row[2]}', INGRP: '{row[3]}'")

print("\n" + "=" * 80)
cursor.close()
conn.close()
