"""
Analyse warum PMPLKO und MPLA niedrigere Match-Rate haben
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
print("Analyse: Warum niedrige Match-Rate bei PMPLKO und MPLA?")
print("=" * 80)

# ==================== PMPLKO ====================
print("\n" + "=" * 40)
print("PMPLKO Analyse")
print("=" * 40)

# 1. Total PMPLKO in DRAD
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'PMPLKO'")
total_pmplko = cursor.fetchone()[0]
print(f"\n1. Total DRAD PMPLKO: {total_pmplko:,}")

# 2. Davon mit PLNTY A, T, E
cursor.execute("""
    SELECT COUNT(*) FROM DIL.DRAD 
    WHERE DOKOB = 'PMPLKO' AND LEFT(OBJKY, 1) IN ('A', 'T', 'E')
""")
ate_count = cursor.fetchone()[0]
print(f"   Davon PLNTY in (A,T,E): {ate_count:,}")

# 3. Welche anderen PLNTY gibt es?
print("\n2. PLNTY Verteilung (alle):")
cursor.execute("""
    SELECT LEFT(OBJKY, 1) as PLNTY, COUNT(*) as CNT
    FROM DIL.DRAD 
    WHERE DOKOB = 'PMPLKO'
    GROUP BY LEFT(OBJKY, 1)
    ORDER BY CNT DESC
""")
for row in cursor.fetchall():
    print(f"   {row[0]}: {row[1]:,}")

# 4. Matched vs Not Matched für A, T, E
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
matched = cursor.fetchone()[0]
print(f"\n3. Matched (A,T,E): {matched:,} von {ate_count:,}")
print(f"   Nicht gefunden: {ate_count - matched:,}")

# 5. Beispiele für nicht gematchte
print("\n4. Beispiele für nicht gematchte PMPLKO (A,T,E):")
cursor.execute("""
    SELECT d.OBJKY, LEFT(d.OBJKY, 1) as PLNTY, 
           SUBSTRING(d.OBJKY, 2, 8) as PLNNR,
           SUBSTRING(d.OBJKY, 10, 2) as PLNAL
    FROM DIL.DRAD d
    LEFT JOIN DIL.PLKO p ON 
        p.PLNTY = LEFT(d.OBJKY, 1) AND
        p.PLNNR = SUBSTRING(d.OBJKY, 2, 8) AND
        p.PLNAL = SUBSTRING(d.OBJKY, 10, 2)
    WHERE d.DOKOB = 'PMPLKO'
    AND LEFT(d.OBJKY, 1) IN ('A', 'T', 'E')
    AND p.PLNNR IS NULL
    LIMIT 10
""")
print(f"   {'OBJKY':<15} {'PLNTY'} {'PLNNR':<10} {'PLNAL'}")
print("   " + "-" * 35)
for row in cursor.fetchall():
    print(f"   {row[0]:<15} {row[1]}     {row[2]:<10} {row[3]}")

# 6. Check if these exist in PLKO at all
print("\n5. Prüfe ob nicht gematchte PLNNR in PLKO existieren:")
cursor.execute("""
    SELECT d.OBJKY, 
           (SELECT COUNT(*) FROM DIL.PLKO WHERE PLNNR = SUBSTRING(d.OBJKY, 2, 8)) as PLKO_EXISTS
    FROM DIL.DRAD d
    LEFT JOIN DIL.PLKO p ON 
        p.PLNTY = LEFT(d.OBJKY, 1) AND
        p.PLNNR = SUBSTRING(d.OBJKY, 2, 8) AND
        p.PLNAL = SUBSTRING(d.OBJKY, 10, 2)
    WHERE d.DOKOB = 'PMPLKO'
    AND LEFT(d.OBJKY, 1) IN ('A', 'T', 'E')
    AND p.PLNNR IS NULL
    LIMIT 10
""")
for row in cursor.fetchall():
    print(f"   {row[0]}: PLKO entries with PLNNR = {row[1]}")

# ==================== MPLA ====================
print("\n" + "=" * 40)
print("MPLA Analyse")
print("=" * 40)

# 1. Total MPLA in DRAD
cursor.execute("SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = 'MPLA'")
total_mpla = cursor.fetchone()[0]
print(f"\n1. Total DRAD MPLA: {total_mpla:,}")

# 2. Matched via MPOS
cursor.execute("""
    SELECT COUNT(DISTINCT d.OBJKY)
    FROM DIL.DRAD d
    INNER JOIN DIL.MPOS m ON m.WARPL = d.OBJKY
    WHERE d.DOKOB = 'MPLA'
""")
matched_mpos = cursor.fetchone()[0]
print(f"   Matched via MPOS: {matched_mpos:,}")

# 3. Nicht gematchte
print("\n2. Nicht gematchte MPLA:")
cursor.execute("""
    SELECT d.OBJKY
    FROM DIL.DRAD d
    LEFT JOIN DIL.MPOS m ON m.WARPL = d.OBJKY
    WHERE d.DOKOB = 'MPLA'
    AND m.WARPL IS NULL
""")
not_matched = cursor.fetchall()
print(f"   Anzahl: {len(not_matched)}")
for row in not_matched[:10]:
    print(f"   WARPL: {row[0]}")

# 4. Check if these exist in MPLA table
print("\n3. Prüfe ob nicht gematchte WARPL in MPLA existieren:")
cursor.execute("""
    SELECT d.OBJKY,
           (SELECT COUNT(*) FROM DIL.MPLA WHERE WARPL = d.OBJKY) as MPLA_EXISTS,
           (SELECT COUNT(*) FROM DIL.MPOS WHERE WARPL = d.OBJKY) as MPOS_EXISTS
    FROM DIL.DRAD d
    LEFT JOIN DIL.MPOS m ON m.WARPL = d.OBJKY
    WHERE d.DOKOB = 'MPLA'
    AND m.WARPL IS NULL
""")
for row in cursor.fetchall():
    print(f"   WARPL {row[0]}: in MPLA={row[1]}, in MPOS={row[2]}")

print("\n" + "=" * 80)
cursor.close()
conn.close()
