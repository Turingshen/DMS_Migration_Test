"""
Einmaliger Load der Werke aus DIL für die DMS Migration.
Speichert die Ergebnisse in userdata/werke_cache.json
"""

import json
import os
from hdbcli import dbapi
import pandas as pd
from datetime import datetime

# DIL Verbindung (LO1 Produktion)
DIL_HOST = "lo1hdb.dmz.basf-ag.de"
DIL_PORT = 30015
DIL_USER = "altnict"
DIL_PW = "FinJaleymie99:99"

def get_connection():
    return dbapi.connect(
        address=DIL_HOST,
        port=DIL_PORT,
        user=DIL_USER,
        password=DIL_PW,
        encrypt=True,
        sslValidateCertificate=True
    )

def load_werke():
    """Lade alle Werke mit Dokumentenzählung aus DIL."""
    
    print("Verbinde mit DIL (LO1)...")
    conn = get_connection()
    cursor = conn.cursor()
    
    # Die komplette Query für alle DOKOB-Typen
    # Zählt DRAD-Einträge (nicht DISTINCT Dokumente) mit Ausschlussfilter
    query = """
        SELECT WERK, COUNT(*) as CNT FROM (
            -- EQUI -> EQUZ (current records only, excluding deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, equz.IWERK as WERK
            FROM DIL.DRAD drad
            JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231'
            JOIN DIL.EQUI equi ON drad.OBJKY = equi.EQUNR
            WHERE drad.DOKOB = 'EQUI'
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j 
                  WHERE j.OBJNR = equi.OBJNR 
                  AND j.STAT IN ('I0320', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
            
            UNION ALL
            
            -- IFLOT -> IFLOT (excluding deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, iflot.IWERK as WERK
            FROM DIL.DRAD drad
            JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR
            WHERE drad.DOKOB = 'IFLOT'
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j 
                  WHERE j.OBJNR = iflot.OBJNR 
                  AND j.STAT IN ('I0320', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
            
            UNION ALL
            
            -- MPLA -> MPOS (with fallback to PLAN_SORT)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, 
                COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) as WERK
            FROM DIL.DRAD drad
            JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
            LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
            WHERE drad.DOKOB = 'MPLA'
            
            UNION ALL
            
            -- PMPLKO -> PLKO (excluding deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, plko.WERKS as WERK
            FROM DIL.DRAD drad
            JOIN DIL.PLKO plko ON 
                LEFT(drad.OBJKY, 1) = plko.PLNTY AND
                SUBSTRING(drad.OBJKY, 2, 8) = plko.PLNNR AND
                RIGHT(drad.OBJKY, 2) = plko.PLNAL
            WHERE drad.DOKOB = 'PMPLKO'
              AND (plko.LOEKZ IS NULL OR plko.LOEKZ = '')
            
            UNION ALL
            
            -- PMAUFK -> AUFK (excluding TECO/deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, aufk.WERKS as WERK
            FROM DIL.DRAD drad
            JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR
            WHERE drad.DOKOB = 'PMAUFK'
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j 
                  WHERE j.OBJNR = aufk.OBJNR 
                  AND j.STAT IN ('I0045', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
            
            UNION ALL
            
            -- PMAFVC -> AFVC (excluding parent order TECO/deleted via AFKO)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, afvc.WERKS as WERK
            FROM DIL.DRAD drad
            JOIN DIL.AFVC afvc ON 
                SUBSTRING(drad.OBJKY, 3, 10) = afvc.AUFPL AND
                SUBSTRING(drad.OBJKY, 13, 8) = afvc.APLZL
            JOIN DIL.AFKO afko ON afvc.AUFPL = afko.AUFPL
            JOIN DIL.AUFK aufk ON afko.AUFNR = aufk.AUFNR
            WHERE drad.DOKOB = 'PMAFVC'
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j 
                  WHERE j.OBJNR = aufk.OBJNR 
                  AND j.STAT IN ('I0045', 'I0013', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
            
            UNION ALL
            
            -- PMQMEL -> QMIH (excluding closed/deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, qmih.IWERK as WERK
            FROM DIL.DRAD drad
            JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
            JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
            WHERE drad.DOKOB = 'PMQMEL'
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j 
                  WHERE j.OBJNR = qmel.OBJNR 
                  AND j.STAT IN ('I0072', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
            
            UNION ALL
            
            -- SMQMEL -> QMIH (excluding closed/deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, qmih.IWERK as WERK
            FROM DIL.DRAD drad
            JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
            JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
            WHERE drad.DOKOB = 'SMQMEL'
              AND NOT EXISTS (
                  SELECT 1 FROM DIL.JEST j 
                  WHERE j.OBJNR = qmel.OBJNR 
                  AND j.STAT IN ('I0072', 'I0076')
                  AND (j.INACT IS NULL OR j.INACT = '')
              )
            
            UNION ALL
            
            -- STKO_DOC -> STKO (excluding deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, stko.WRKAN as WERK
            FROM DIL.DRAD drad
            JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
            WHERE drad.DOKOB = 'STKO_DOC'
              AND (stko.LOEKZ IS NULL OR stko.LOEKZ = '')
            
            UNION ALL
            
            -- STPO_DOC -> STPO -> STKO (excluding deleted)
            SELECT drad.DOKNR, drad.DOKVR, drad.DOKTL, stko.WRKAN as WERK
            FROM DIL.DRAD drad
            JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX)
            JOIN DIL.STKO stko ON stpo.STLNR = stko.STLNR
            WHERE drad.DOKOB = 'STPO_DOC'
              AND (stpo.LKENZ IS NULL OR stpo.LKENZ = '')
        ) combined
        WHERE WERK IS NOT NULL AND WERK != ''
        GROUP BY WERK
        ORDER BY CNT DESC
    """
    
    print("Führe Query aus (kann einige Minuten dauern)...")
    start = datetime.now()
    cursor.execute(query)
    rows = cursor.fetchall()
    duration = (datetime.now() - start).total_seconds()
    
    print(f"Query abgeschlossen in {duration:.1f} Sekunden")
    print(f"Gefunden: {len(rows)} Werke")
    
    # Konvertiere zu Liste von Dicts
    werke = []
    total_objects = 0
    for row in rows:
        werk_code = row[0].strip() if row[0] else ''
        count = row[1]
        if werk_code:
            werke.append({
                'code': werk_code,
                'count': count
            })
            total_objects += count
    
    # Speichere als JSON
    os.makedirs('userdata', exist_ok=True)
    cache_data = {
        'generated_at': datetime.now().isoformat(),
        'source': 'DIL LO1',
        'total_werke': len(werke),
        'total_objects': total_objects,
        'werke': werke
    }
    
    cache_file = 'userdata/werke_cache.json'
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nGespeichert in: {cache_file}")
    print(f"Werke: {len(werke)}")
    print(f"Objekte gesamt: {total_objects:,}")
    print("\nTop 10 Werke:")
    for w in werke[:10]:
        print(f"  {w['code']}: {w['count']:,}")
    
    cursor.close()
    conn.close()
    
    return cache_data

if __name__ == '__main__':
    load_werke()
