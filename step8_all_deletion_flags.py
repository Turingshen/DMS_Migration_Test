"""
Step 8: Analyse Löschkennzeichen für ALLE DOKOB-Typen
=====================================================

Logik:
- Ein DMS-Dokument (DOKAR/DOKNR/DOKVR/DOKTL) kann mehrere Objektverknüpfungen haben
- Dokument soll nur ausgeschlossen werden wenn ALLE verknüpften Objekte gelöscht sind
- JEST: INACT = '' (leer) → Status ist AKTIV (Löschkennzeichen gesetzt)
- JEST: INACT = 'X' → Status ist INAKTIV (Löschkennzeichen zurückgenommen)

Relevante Status:
  - I0320 INAC (Inactive)
  - I0013 DLT (Deleted)  
  - I0076 DLFL (Deletion Flag)

DOKOB-Typen und ihre OBJNR-Quellen:
  - EQUI: EQUI.OBJNR
  - IFLOT: IFLOT.OBJNR
  - PMAUFK: AUFK.OBJNR
  - PMAFVC: AFVC - hat AUFPL/APLZL, prüfen ob OBJNR existiert
  - PMQMEL: QMIH - prüfen ob OBJNR existiert oder QMEL
  - MPLA: MPLA - prüfen
  - PMPLKO: PLKO - prüfen
  - STKO_DOC / STPO_DOC: Stücklisten - prüfen

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
print("Step 8: Analyse Löschkennzeichen für ALLE DOKOB-Typen")
print("=" * 80)

def check_objnr_column(table_name):
    """Prüft ob eine Tabelle OBJNR Spalte hat"""
    cursor.execute(f"""
        SELECT COUNT(*) FROM SYS.TABLE_COLUMNS 
        WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = '{table_name}'
        AND COLUMN_NAME = 'OBJNR'
    """)
    return cursor.fetchone()[0] > 0

def analyze_deletion_flags(dokob, join_table, join_condition, objnr_expr):
    """Analysiere Löschkennzeichen für einen DOKOB-Typ"""
    print(f"\n{'=' * 40}")
    print(f"{dokob}")
    print(f"{'=' * 40}")
    
    # Total count
    cursor.execute(f"SELECT COUNT(*) FROM DIL.DRAD WHERE DOKOB = '{dokob}'")
    total = cursor.fetchone()[0]
    print(f"   Total DRAD: {total:,}")
    
    if total == 0:
        return {'total': 0, 'deleted': 0}
    
    # Count with each deletion status
    for stat, desc in [('I0320', 'INAC'), ('I0013', 'DLT'), ('I0076', 'DLFL')]:
        try:
            query = f"""
                SELECT COUNT(DISTINCT d.OBJKY)
                FROM DIL.DRAD d
                {join_table}
                INNER JOIN DIL.JEST j ON j.OBJNR = {objnr_expr}
                WHERE d.DOKOB = '{dokob}'
                AND j.STAT = '{stat}'
                AND (j.INACT IS NULL OR j.INACT = '')
            """
            cursor.execute(query)
            count = cursor.fetchone()[0]
            print(f"   {stat} ({desc}): {count:,}")
        except Exception as e:
            print(f"   {stat} ({desc}): ERROR - {str(e)[:50]}")
    
    # Total deleted
    try:
        query = f"""
            SELECT COUNT(DISTINCT d.OBJKY)
            FROM DIL.DRAD d
            {join_table}
            INNER JOIN DIL.JEST j ON j.OBJNR = {objnr_expr}
            WHERE d.DOKOB = '{dokob}'
            AND j.STAT IN ('I0320', 'I0013', 'I0076')
            AND (j.INACT IS NULL OR j.INACT = '')
        """
        cursor.execute(query)
        deleted = cursor.fetchone()[0]
        print(f"\n   → Gelöscht: {deleted:,} ({(deleted/total*100):.1f}%)")
        print(f"   → Aktiv: {total - deleted:,}")
        return {'total': total, 'deleted': deleted}
    except Exception as e:
        print(f"   → ERROR: {str(e)[:80]}")
        return {'total': total, 'deleted': 0, 'error': str(e)}

# ==================== Prüfe welche Tabellen OBJNR haben ====================
print("\n1. Prüfe OBJNR Spalten in relevanten Tabellen:")
tables_to_check = ['EQUI', 'IFLOT', 'AUFK', 'AFVC', 'QMIH', 'QMEL', 'MPLA', 'MPOS', 'PLKO', 'STKO', 'STPO']
for table in tables_to_check:
    has_objnr = check_objnr_column(table)
    print(f"   {table}: {'✓ OBJNR' if has_objnr else '✗ kein OBJNR'}")

# ==================== Analyse pro DOKOB ====================
results = {}

# EQUI
results['EQUI'] = analyze_deletion_flags(
    'EQUI',
    'INNER JOIN DIL.EQUI eq ON eq.EQUNR = d.OBJKY',
    '',
    'eq.OBJNR'
)

# IFLOT
results['IFLOT'] = analyze_deletion_flags(
    'IFLOT',
    'INNER JOIN DIL.IFLOT i ON i.TPLNR = d.OBJKY',
    '',
    'i.OBJNR'
)

# PMAUFK - prüfe ob AUFK.OBJNR existiert
print("\n" + "=" * 40)
print("PMAUFK - Prüfe OBJNR")
print("=" * 40)
cursor.execute("SELECT AUFNR, OBJNR FROM DIL.AUFK WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
print("   Sample AUFK.OBJNR:")
for row in cursor.fetchall():
    print(f"     {row[0]} -> {row[1]}")
    
results['PMAUFK'] = analyze_deletion_flags(
    'PMAUFK',
    'INNER JOIN DIL.AUFK a ON a.AUFNR = d.OBJKY',
    '',
    'a.OBJNR'
)

# PMAFVC
print("\n" + "=" * 40)
print("PMAFVC - Prüfe OBJNR")
print("=" * 40)
if check_objnr_column('AFVC'):
    cursor.execute("SELECT AUFPL, APLZL, OBJNR FROM DIL.AFVC WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
    print("   Sample AFVC.OBJNR:")
    for row in cursor.fetchall():
        print(f"     {row[0]}/{row[1]} -> {row[2]}")
    
    results['PMAFVC'] = analyze_deletion_flags(
        'PMAFVC',
        '''INNER JOIN DIL.AFVC a ON 
            a.AUFPL = SUBSTRING(d.OBJKY, 3, 10) AND
            a.APLZL = SUBSTRING(d.OBJKY, 13, 8)''',
        '',
        'a.OBJNR'
    )
else:
    print("   AFVC hat kein OBJNR!")
    results['PMAFVC'] = {'total': 0, 'deleted': 0, 'note': 'kein OBJNR'}

# PMQMEL
print("\n" + "=" * 40)
print("PMQMEL - Prüfe OBJNR")
print("=" * 40)
# Prüfe QMIH
if check_objnr_column('QMIH'):
    cursor.execute("SELECT QMNUM, OBJNR FROM DIL.QMIH WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
    print("   Sample QMIH.OBJNR:")
    for row in cursor.fetchall():
        print(f"     {row[0]} -> {row[1]}")
    
    results['PMQMEL'] = analyze_deletion_flags(
        'PMQMEL',
        'INNER JOIN DIL.QMIH q ON q.QMNUM = d.OBJKY',
        '',
        'q.OBJNR'
    )
else:
    # Fallback: QMEL
    cursor.execute("SELECT QMNUM, OBJNR FROM DIL.QMEL WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
    print("   Sample QMEL.OBJNR:")
    for row in cursor.fetchall():
        print(f"     {row[0]} -> {row[1]}")
    
    results['PMQMEL'] = analyze_deletion_flags(
        'PMQMEL',
        'INNER JOIN DIL.QMEL q ON q.QMNUM = d.OBJKY',
        '',
        'q.OBJNR'
    )

# MPLA
print("\n" + "=" * 40)
print("MPLA - Prüfe OBJNR")
print("=" * 40)
if check_objnr_column('MPLA'):
    cursor.execute("SELECT WARPL, OBJNR FROM DIL.MPLA WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
    print("   Sample MPLA.OBJNR:")
    for row in cursor.fetchall():
        print(f"     {row[0]} -> {row[1]}")
    
    results['MPLA'] = analyze_deletion_flags(
        'MPLA',
        'INNER JOIN DIL.MPLA m ON m.WARPL = d.OBJKY',
        '',
        'm.OBJNR'
    )
else:
    print("   MPLA hat kein OBJNR - prüfe MPOS")
    if check_objnr_column('MPOS'):
        cursor.execute("SELECT WARPL, OBJNR FROM DIL.MPOS WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
        print("   Sample MPOS.OBJNR:")
        for row in cursor.fetchall():
            print(f"     {row[0]} -> {row[1]}")
    results['MPLA'] = {'total': 0, 'deleted': 0, 'note': 'prüfen'}

# PMPLKO
print("\n" + "=" * 40)
print("PMPLKO - Prüfe OBJNR")
print("=" * 40)
if check_objnr_column('PLKO'):
    cursor.execute("SELECT PLNTY, PLNNR, PLNAL, OBJNR FROM DIL.PLKO WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
    print("   Sample PLKO.OBJNR:")
    for row in cursor.fetchall():
        print(f"     {row[0]}/{row[1]}/{row[2]} -> {row[3]}")
    
    results['PMPLKO'] = analyze_deletion_flags(
        'PMPLKO',
        '''INNER JOIN DIL.PLKO p ON 
            p.PLNTY = LEFT(d.OBJKY, 1) AND
            p.PLNNR = SUBSTRING(d.OBJKY, 2, 8) AND
            p.PLNAL = SUBSTRING(d.OBJKY, 10, 2)''',
        '',
        'p.OBJNR'
    )
else:
    print("   PLKO hat kein OBJNR!")
    results['PMPLKO'] = {'total': 0, 'deleted': 0, 'note': 'kein OBJNR'}

# STKO_DOC / STPO_DOC
print("\n" + "=" * 40)
print("STKO_DOC / STPO_DOC - Prüfe OBJNR")
print("=" * 40)
if check_objnr_column('STKO'):
    cursor.execute("SELECT STLNR, OBJNR FROM DIL.STKO WHERE OBJNR IS NOT NULL AND OBJNR != '' LIMIT 3")
    print("   Sample STKO.OBJNR:")
    for row in cursor.fetchall():
        print(f"     {row[0]} -> {row[1]}")
    
    results['STKO_DOC'] = analyze_deletion_flags(
        'STKO_DOC',
        'INNER JOIN DIL.STKO s ON UPPER(BINTOHEX(s.GUIDX)) = d.OBJKY',
        '',
        's.OBJNR'
    )
else:
    print("   STKO hat kein OBJNR!")
    results['STKO_DOC'] = {'total': 0, 'deleted': 0, 'note': 'kein OBJNR'}

if check_objnr_column('STPO'):
    results['STPO_DOC'] = analyze_deletion_flags(
        'STPO_DOC',
        'INNER JOIN DIL.STPO sp ON UPPER(BINTOHEX(sp.GUIDX)) = d.OBJKY',
        '',
        'sp.OBJNR'
    )
else:
    print("   STPO hat kein OBJNR!")
    results['STPO_DOC'] = {'total': 0, 'deleted': 0, 'note': 'kein OBJNR'}

# ==================== Zusammenfassung ====================
print("\n" + "=" * 80)
print("ZUSAMMENFASSUNG")
print("=" * 80)
print(f"\n{'DOKOB':<12} {'Total':>12} {'Gelöscht':>12} {'Anteil':>8} {'Note':<20}")
print("-" * 70)

total_all = 0
deleted_all = 0
for dokob, data in results.items():
    total = data.get('total', 0)
    deleted = data.get('deleted', 0)
    note = data.get('note', '') or data.get('error', '')[:20] if 'error' in data else ''
    percent = f"{(deleted/total*100):.1f}%" if total > 0 else "n/a"
    print(f"{dokob:<12} {total:>12,} {deleted:>12,} {percent:>8} {note:<20}")
    total_all += total
    deleted_all += deleted

print("-" * 70)
print(f"{'GESAMT':<12} {total_all:>12,} {deleted_all:>12,} {(deleted_all/total_all*100):.1f}%")

cursor.close()
conn.close()
