"""
Create a combined table with DRAD objects and their plant (Werk) codes.
Based on DOKOB (object type), lookup the plant from the respective table.
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

# First, let's check the column names in each table
tables_to_check = {
    'DRAD': 'DRAD columns',
    'EQUZ': 'Equipment Zeit',
    'IFLOT': 'Functional Location',
    'MPLA': 'Maintenance Plan',
    'PLKO': 'Task List Header',
    'AUFK': 'Order Master',
    'QMIH': 'Maintenance Notification',
    'STPO': 'BOM Item'
}

print("=" * 80)
print("Spalten-Analyse der relevanten Tabellen")
print("=" * 80)

for table, desc in tables_to_check.items():
    print(f"\n{table} ({desc}):")
    print("-" * 40)
    try:
        cursor.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH 
            FROM SYS.TABLE_COLUMNS 
            WHERE SCHEMA_NAME = 'DIL' AND TABLE_NAME = '{table}'
            AND (COLUMN_NAME LIKE '%WERK%' 
                 OR COLUMN_NAME LIKE '%IWERK%' 
                 OR COLUMN_NAME LIKE '%PLAN%'
                 OR COLUMN_NAME LIKE '%EQUNR%'
                 OR COLUMN_NAME LIKE '%TPLNR%'
                 OR COLUMN_NAME LIKE '%AUFNR%'
                 OR COLUMN_NAME LIKE '%QMNUM%'
                 OR COLUMN_NAME LIKE '%STLNR%'
                 OR COLUMN_NAME LIKE '%DOKAR%'
                 OR COLUMN_NAME LIKE '%DOKNR%'
                 OR COLUMN_NAME LIKE '%OBJKY%'
                 OR COLUMN_NAME LIKE '%DOKOB%'
                 OR COLUMN_NAME LIKE '%WKRAN%'
                 OR COLUMN_NAME LIKE '%PLNNR%'
                 OR COLUMN_NAME LIKE '%PLNTY%')
            ORDER BY COLUMN_NAME
        """)
        cols = cursor.fetchall()
        for col in cols:
            print(f"  {col[0]:<25} {col[1]:<15} ({col[2]})")
    except Exception as e:
        print(f"  Fehler: {e}")

cursor.close()
conn.close()
