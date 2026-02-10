"""
Berechne geschätzte Größe der DRAD+Werk Tabelle für SQLite
LO2 Testsystem (kleinere Datenmenge) - für LO1 extrapolieren
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
print("Größenschätzung DRAD + Werk Tabelle")
print("=" * 80)

# 1. Zähle alle relevanten DOKOB
print("\n1. LO2 - Anzahl Einträge pro DOKOB:")
cursor.execute("""
    SELECT DOKOB, COUNT(*) as CNT 
    FROM DIL.DRAD 
    WHERE DOKOB IN ('EQUI', 'IFLOT', 'MPLA', 'PMPLKO', 'PMAUFK', 'PMAFVC', 'PMQMEL', 'STKO_DOC', 'STPO_DOC')
    GROUP BY DOKOB
    ORDER BY CNT DESC
""")
lo2_counts = {}
total_lo2 = 0
print(f"   {'DOKOB':<12} {'Count':>15}")
print("   " + "-" * 30)
for row in cursor.fetchall():
    lo2_counts[row[0]] = row[1]
    total_lo2 += row[1]
    print(f"   {row[0]:<12} {row[1]:>15,}")
print(f"   {'TOTAL':<12} {total_lo2:>15,}")

# 2. Beispiel-Datensatz Größe berechnen
print("\n2. Beispiel-Datensatz (Spaltengrößen):")
cols = {
    'DOKAR': 3,
    'DOKNR': 25,
    'DOKVR': 2,
    'DOKTL': 3,
    'DOKOB': 10,
    'OBJKY': 40,  # max bei GUID
    'WERK': 4
}
row_size = sum(cols.values())
print(f"   Felder: {list(cols.keys())}")
print(f"   Größen: {list(cols.values())}")
print(f"   Summe pro Zeile: ~{row_size} Bytes (ohne SQLite Overhead)")

# SQLite overhead ca. 20-30% extra
sqlite_overhead = 1.3
row_size_with_overhead = int(row_size * sqlite_overhead)
print(f"   Mit SQLite Overhead (~30%): ~{row_size_with_overhead} Bytes/Zeile")

# 3. LO2 Schätzung
lo2_size_mb = (total_lo2 * row_size_with_overhead) / (1024 * 1024)
print(f"\n3. LO2 Geschätzte Größe:")
print(f"   {total_lo2:,} Zeilen × {row_size_with_overhead} Bytes = {lo2_size_mb:.1f} MB")

cursor.close()
conn.close()

# 4. LO1 Schätzung (Produktivsystem)
print("\n4. LO1 Schätzung (Produktivsystem):")
# Aus den früheren Analysen:
lo1_counts = {
    'EQUI': 916714,
    'IFLOT': 1924315,
    'MPLA': 0,  # keine in LO1
    'PMPLKO': 0,  # geschätzt
    'PMAUFK': 0,  # geschätzt
    'PMAFVC': 0,  # geschätzt
    'PMQMEL': 0,  # geschätzt
    'STKO_DOC': 0,
    'STPO_DOC': 0
}
# Wir haben nur EQUI und IFLOT für LO1 geprüft
# Schätzung: LO1 hat ca. 2-3x mehr Daten als LO2

ratio = 2.5  # Konservativer Faktor
total_lo1_estimated = int(total_lo2 * ratio)
lo1_size_mb = (total_lo1_estimated * row_size_with_overhead) / (1024 * 1024)

print(f"   Geschätzter Faktor LO1/LO2: ~{ratio}x")
print(f"   Geschätzte Zeilen LO1: ~{total_lo1_estimated:,}")
print(f"   Geschätzte Größe LO1: ~{lo1_size_mb:.0f} MB")

print("\n" + "=" * 80)
