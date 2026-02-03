"""
Step 7: Analyse Löschkennzeichen für EQUI und IFLOT
JEST = Status-Tabelle für SAP Objekte
Relevante Status:
  - I0320 INAC (Inactive)
  - I0013 DLT (Deleted)  
  - I0076 DLFL (Deletion Flag)

IFLOT.OBJNR -> JEST.OBJNR
JEST.INACT = '' bedeutet Status ist aktiv (gesetzt)

LO1 Produktivsystem
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
print("Step 7: Analyse Löschkennzeichen (JEST)")
print("=" * 80)

# 1. Check JEST columns
print("\n1. JEST Spalten:")
cursor.execute("""
    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH
    FROM SYS.TABLE_COLUMNS 
    WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = 'JEST'
    ORDER BY POSITION
""")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:<15} ({row[2]})")

# 2. Sample JEST data
print("\n2. Beispiel JEST Daten:")
cursor.execute("""
    SELECT OBJNR, STAT, INACT, CHGNR
    FROM DIL.JEST 
    WHERE STAT IN ('I0320', 'I0013', 'I0076')
    LIMIT 10
""")
print(f"   {'OBJNR':<25} {'STAT':<8} {'INACT':<8} {'CHGNR':<10}")
print("   " + "-" * 55)
for row in cursor.fetchall():
    print(f"   {row[0]:<25} {row[1]:<8} '{row[2]}'      {row[3]:<10}")

# 3. Check IFLOT.OBJNR
print("\n3. Beispiel IFLOT.OBJNR:")
cursor.execute("""
    SELECT TPLNR, OBJNR, IWERK
    FROM DIL.IFLOT 
    WHERE OBJNR IS NOT NULL AND OBJNR != ''
    LIMIT 5
""")
print(f"   {'TPLNR':<30} {'OBJNR':<25} {'IWERK':<6}")
print("   " + "-" * 65)
for row in cursor.fetchall():
    print(f"   {row[0]:<30} {row[1]:<25} {row[2]:<6}")

# ==================== IFLOT Löschkennzeichen ====================
print("\n" + "=" * 40)
print("IFLOT - Technische Plätze")
print("=" * 40)

# 4. Count IFLOT in DRAD
print("\n4. DRAD IFLOT Einträge:")
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'IFLOT'")
total_iflot = cursor.fetchone()[0]
print(f"   Total: {total_iflot:,}")

# 5. Count IFLOT with deletion status (aktive Löschkennzeichen)
print("\n5. IFLOT mit aktiven Löschkennzeichen (INACT = ''):")
for stat, desc in [('I0320', 'INAC'), ('I0013', 'DLT'), ('I0076', 'DLFL')]:
    cursor.execute(f"""
        SELECT COUNT(DISTINCT d.OBJKY)
        FROM DIL.DRAD d
        INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
        INNER JOIN DIL.JEST j ON j.OBJNR = i.OBJNR
        WHERE d.DOKOB = 'IFLOT'
        AND j.STAT = '{stat}'
        AND (j.INACT IS NULL OR j.INACT = '')
    """)
    count = cursor.fetchone()[0]
    print(f"   {stat} ({desc}): {count:,}")

# 6. Count IFLOT mit mindestens einem Löschkennzeichen
print("\n6. IFLOT mit mindestens einem Löschkennzeichen:")
cursor.execute("""
    SELECT COUNT(DISTINCT d.OBJKY)
    FROM DIL.DRAD d
    INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
    INNER JOIN DIL.JEST j ON j.OBJNR = i.OBJNR
    WHERE d.DOKOB = 'IFLOT'
    AND j.STAT IN ('I0320', 'I0013', 'I0076')
    AND (j.INACT IS NULL OR j.INACT = '')
""")
deleted_count = cursor.fetchone()[0]
print(f"   Gelöscht/Inaktiv: {deleted_count:,}")
print(f"   Aktiv: {total_iflot - deleted_count:,}")
print(f"   Anteil gelöscht: {(deleted_count/total_iflot*100):.1f}%")

# 7. Beispiel gelöschte IFLOT
print("\n7. Beispiel gelöschte IFLOT (erste 5):")
cursor.execute("""
    SELECT d.DOKNR, d.OBJKY, j.STAT, i.IWERK
    FROM DIL.DRAD d
    INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
    INNER JOIN DIL.JEST j ON j.OBJNR = i.OBJNR
    WHERE d.DOKOB = 'IFLOT'
    AND j.STAT IN ('I0320', 'I0013', 'I0076')
    AND (j.INACT IS NULL OR j.INACT = '')
    LIMIT 5
""")
print(f"   {'DOKNR':<25} {'TPLNR':<30} {'STAT':<8} {'WERK':<6}")
print("   " + "-" * 75)
for row in cursor.fetchall():
    print(f"   {row[0]:<25} {row[1]:<30} {row[2]:<8} {row[3]:<6}")

# ==================== EQUI Löschkennzeichen ====================
print("\n" + "=" * 40)
print("EQUI - Equipment")
print("=" * 40)

# 8. Check EQUI.OBJNR (OBJNR ist in EQUI, nicht EQUZ!)
print("\n8. Beispiel EQUI.OBJNR:")
cursor.execute("""
    SELECT EQUNR, OBJNR
    FROM DIL.EQUI
    WHERE OBJNR IS NOT NULL AND OBJNR != ''
    LIMIT 5
""")
print(f"   {'EQUNR':<20} {'OBJNR':<25}")
print("   " + "-" * 50)
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:<25}")

# 9. Count EQUI in DRAD
print("\n9. DRAD EQUI Einträge:")
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'EQUI'")
total_equi = cursor.fetchone()[0]
print(f"   Total: {total_equi:,}")

# 10. Count EQUI with deletion status (EQUI.OBJNR -> JEST)
print("\n10. EQUI mit aktiven Löschkennzeichen:")
for stat, desc in [('I0320', 'INAC'), ('I0013', 'DLT'), ('I0076', 'DLFL')]:
    cursor.execute(f"""
        SELECT COUNT(DISTINCT d.OBJKY)
        FROM DIL.DRAD d
        INNER JOIN DIL.EQUI eq ON eq.EQUNR = d.OBJKY
        INNER JOIN DIL.JEST j ON j.OBJNR = eq.OBJNR
        WHERE d.DOKOB = 'EQUI'
        AND j.STAT = '{stat}'
        AND (j.INACT IS NULL OR j.INACT = '')
    """)
    count = cursor.fetchone()[0]
    print(f"   {stat} ({desc}): {count:,}")

# 11. Count EQUI mit mindestens einem Löschkennzeichen
print("\n11. EQUI mit mindestens einem Löschkennzeichen:")
cursor.execute("""
    SELECT COUNT(DISTINCT d.OBJKY)
    FROM DIL.DRAD d
    INNER JOIN DIL.EQUI eq ON eq.EQUNR = d.OBJKY
    INNER JOIN DIL.JEST j ON j.OBJNR = eq.OBJNR
    WHERE d.DOKOB = 'EQUI'
    AND j.STAT IN ('I0320', 'I0013', 'I0076')
    AND (j.INACT IS NULL OR j.INACT = '')
""")
deleted_equi = cursor.fetchone()[0]
print(f"   Gelöscht/Inaktiv: {deleted_equi:,}")
print(f"   Aktiv: {total_equi - deleted_equi:,}")
print(f"   Anteil gelöscht: {(deleted_equi/total_equi*100):.1f}%")

print("\n" + "=" * 80)
print("Zusammenfassung:")
print(f"   IFLOT: {total_iflot:,} total, {deleted_count:,} gelöscht ({(deleted_count/total_iflot*100):.1f}%)")
print(f"   EQUI:  {total_equi:,} total, {deleted_equi:,} gelöscht ({(deleted_equi/total_equi*100):.1f}%)")
print("=" * 80)

cursor.close()
conn.close()
