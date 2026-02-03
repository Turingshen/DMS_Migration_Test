"""
Ermittle alle verschiedenen Werk-Codes im LO1 über alle DOKOB-Typen
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
print("LO1 - Alle Werk-Codes über alle DOKOB-Typen")
print("=" * 80)

# Große UNION Query über alle DOKOB-Typen mit ihren Werk-Verknüpfungen
query = """
SELECT WERK, DOKOB, COUNT(*) as CNT FROM (
    -- EQUI: OBJKY = EQUNR → EQUZ.IWERK (DATBI = 99991231)
    SELECT e.IWERK as WERK, d.DOKOB
    FROM DIL.DRAD d
    INNER JOIN DIL.EQUZ e ON e.EQUNR = d.OBJKY AND e.DATBI = '99991231'
    WHERE d.DOKOB = 'EQUI'
    
    UNION ALL
    
    -- IFLOT: OBJKY = TPLNR → IFLOT.IWERK
    SELECT i.IWERK as WERK, d.DOKOB
    FROM DIL.DRAD d
    INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY
    WHERE d.DOKOB = 'IFLOT'
    
    UNION ALL
    
    -- PMAUFK: OBJKY = AUFNR → AUFK.WERKS
    SELECT a.WERKS as WERK, d.DOKOB
    FROM DIL.DRAD d
    INNER JOIN DIL.AUFK a ON a.AUFNR = d.OBJKY
    WHERE d.DOKOB = 'PMAUFK'
    
    UNION ALL
    
    -- PMAFVC: OV + AUFPL(10) + APLZL(8) → AFVC.WERKS
    SELECT a.WERKS as WERK, d.DOKOB
    FROM DIL.DRAD d
    INNER JOIN DIL.AFVC a ON 
        a.AUFPL = SUBSTRING(d.OBJKY, 3, 10) AND
        a.APLZL = SUBSTRING(d.OBJKY, 13, 8)
    WHERE d.DOKOB = 'PMAFVC'
    
    UNION ALL
    
    -- PMQMEL: OBJKY = QMNUM → QMIH.IWERK
    SELECT q.IWERK as WERK, d.DOKOB
    FROM DIL.DRAD d
    INNER JOIN DIL.QMIH q ON q.QMNUM = d.OBJKY
    WHERE d.DOKOB = 'PMQMEL'
    
    UNION ALL
    
    -- STKO_DOC: OBJKY = BINTOHEX(GUIDX) → STKO.WRKAN
    SELECT s.WRKAN as WERK, d.DOKOB
    FROM DIL.DRAD d
    INNER JOIN DIL.STKO s ON UPPER(BINTOHEX(s.GUIDX)) = d.OBJKY
    WHERE d.DOKOB = 'STKO_DOC'
    
    UNION ALL
    
    -- STPO_DOC: OBJKY = BINTOHEX(GUIDX) → STPO → STKO.WRKAN
    SELECT sk.WRKAN as WERK, d.DOKOB
    FROM DIL.DRAD d
    INNER JOIN DIL.STPO sp ON UPPER(BINTOHEX(sp.GUIDX)) = d.OBJKY
    INNER JOIN DIL.STKO sk ON sk.STLTY = sp.STLTY AND sk.STLNR = sp.STLNR
    WHERE d.DOKOB = 'STPO_DOC'
) combined
GROUP BY WERK, DOKOB
ORDER BY WERK, DOKOB
"""

print("\n1. Abfrage läuft... (kann etwas dauern)")
cursor.execute(query)
results = cursor.fetchall()

# Sammle Werke und Counts
werk_counts = {}
dokob_werk_counts = {}

for row in results:
    werk = row[0] if row[0] else '(LEER)'
    dokob = row[1]
    cnt = row[2]
    
    if werk not in werk_counts:
        werk_counts[werk] = 0
    werk_counts[werk] += cnt
    
    if werk not in dokob_werk_counts:
        dokob_werk_counts[werk] = {}
    dokob_werk_counts[werk][dokob] = cnt

# Sortiere nach Anzahl
sorted_werke = sorted(werk_counts.items(), key=lambda x: x[1], reverse=True)

print(f"\n2. Anzahl verschiedener Werk-Codes: {len(werk_counts)}")

print(f"\n3. Werk-Codes nach Häufigkeit (Top 30):")
print(f"   {'WERK':<8} {'Gesamt':>12} | EQUI | IFLOT | PMAUFK | PMAFVC | PMQMEL | STKO | STPO")
print("   " + "-" * 90)

for werk, total in sorted_werke[:30]:
    dokobs = dokob_werk_counts.get(werk, {})
    equi = dokobs.get('EQUI', 0)
    iflot = dokobs.get('IFLOT', 0)
    pmaufk = dokobs.get('PMAUFK', 0)
    pmafvc = dokobs.get('PMAFVC', 0)
    pmqmel = dokobs.get('PMQMEL', 0)
    stko = dokobs.get('STKO_DOC', 0)
    stpo = dokobs.get('STPO_DOC', 0)
    print(f"   {werk:<8} {total:>12,} | {equi:>4} | {iflot:>5} | {pmaufk:>6} | {pmafvc:>6} | {pmqmel:>6} | {stko:>4} | {stpo:>4}")

# Leere Werke?
if '(LEER)' in werk_counts:
    print(f"\n   Hinweis: {werk_counts['(LEER)']:,} Einträge haben leeres Werk!")

print(f"\n4. Alle Werk-Codes (alphabetisch):")
all_werke = sorted([w for w in werk_counts.keys() if w != '(LEER)'])
# In Spalten ausgeben
cols = 10
for i in range(0, len(all_werke), cols):
    row = all_werke[i:i+cols]
    print("   " + " ".join(f"{w:<6}" for w in row))

print(f"\n   Gesamt: {len(all_werke)} verschiedene Werk-Codes")

print("\n" + "=" * 80)
cursor.close()
conn.close()
