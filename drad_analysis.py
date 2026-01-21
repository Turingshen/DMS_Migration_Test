"""DRAD Object Type Analysis"""
from app_config import DilEngine
from sqlalchemy import text

dil_db = DilEngine.load()
engine = dil_db.engine

object_types = {
    'IFLOT': 'Functional Location / Techn. Platz',
    'MPLA': 'Maintenance Plan / Wartungsplan',
    'IMPTT': 'Measuring Point / Messpunkt',
    'PMPLKO': 'Task List / Arbeitsplan',
    'PMAUFK': 'Order / PM-Auftrag',
    'PMAFVC': 'Order Operation / Auftragsvorgang',
    'PMQMEL': 'Notification / Meldung',
    'STKO_DOC': 'BOM Header / Stuecklisten-Kopf',
    'STPO_DOC': 'BOM Item / Stuecklisten-Position',
}

query = '''
    SELECT 
        DOKOB,
        COUNT(*) as cnt,
        COUNT(DISTINCT OBJKY) as unique_objects,
        MIN(OBJKY) as example_key,
        MIN(DOKNR) as example_doc
    FROM DIL.DRAD
    WHERE DOKOB IN ('IFLOT', 'MPLA', 'IMPTT', 'PMPLKO', 'PMAUFK', 'PMAFVC', 'PMQMEL', 'STKO_DOC', 'STPO_DOC')
    AND MANDT = '100'
    GROUP BY DOKOB
    ORDER BY cnt DESC
'''

with engine.begin() as con:
    result = con.execute(text(query))
    rows = result.fetchall()
    
    print('=' * 100)
    print('Object Type   Beschreibung                           Links       Objekte    Beispiel Key')
    print('=' * 100)
    
    total_links = 0
    total_objects = 0
    for row in rows:
        dokob, cnt, unique, example_key, example_doc = row
        desc = object_types.get(dokob, '')
        ex_key = (example_key or "-")[:25]
        print(f'{dokob:<12}  {desc:<38} {cnt:>10,} {unique:>10,}  {ex_key}')
        total_links += cnt
        total_objects += unique
    
    print('=' * 100)
    print(f'{"TOTAL":<12}  {"":38} {total_links:>10,} {total_objects:>10,}')
    print('=' * 100)
