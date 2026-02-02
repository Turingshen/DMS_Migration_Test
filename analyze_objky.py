"""Analyze OBJKY structure for each object type in DRAD"""
from app_config import DilEngine
from sqlalchemy import text

dil_db = DilEngine.load()
engine = dil_db.engine

print('=== Object ID Mapping Vorschläge ===')
print()

# Analysiere OBJKY-Struktur für jeden Objekttyp
object_types = ['IFLOT', 'PMQMEL', 'PMAUFK', 'PMAFVC', 'STKO_DOC', 'STPO_DOC', 'IMPTT']

descriptions = {
    'IFLOT': 'Functional Location / Technischer Platz',
    'PMQMEL': 'Notification / Meldung (PM/QM)',
    'PMAUFK': 'Order / PM-Auftrag',
    'PMAFVC': 'Order Operation / Auftragsvorgang',
    'STKO_DOC': 'BOM Header / Stücklisten-Kopf',
    'STPO_DOC': 'BOM Item / Stücklisten-Position',
    'IMPTT': 'Measuring Point / Messpunkt'
}

# SAP S/4HANA Target Object Mapping
target_mapping = {
    'IFLOT': {
        'target_object': 'FunctionalLocation',
        'api': 'API_FUNCTIONALLOCATION',
        'key_field': 'FunctionalLocation',
        'objky_format': 'Functional Location ID (z.B. DE-LU-E-B211-MA10)',
        'notes': 'OBJKY = Technischer Platz ID, direkt als FunctionalLocation verwendbar'
    },
    'PMQMEL': {
        'target_object': 'MaintenanceNotification',
        'api': 'API_MAINTNOTIFICATION',
        'key_field': 'MaintenanceNotification',
        'objky_format': 'Meldungsnummer (12-stellig numerisch)',
        'notes': 'OBJKY = Meldungsnummer, direkt als MaintenanceNotification verwendbar'
    },
    'PMAUFK': {
        'target_object': 'MaintenanceOrder',
        'api': 'API_MAINTENANCEORDER',
        'key_field': 'MaintenanceOrder',
        'objky_format': 'Auftragsnummer (12-stellig numerisch)',
        'notes': 'OBJKY = PM-Auftragsnummer, direkt als MaintenanceOrder verwendbar'
    },
    'PMAFVC': {
        'target_object': 'MaintenanceOrderOperation',
        'api': 'API_MAINTENANCEORDER',
        'key_field': 'MaintenanceOrder + MaintenanceOrderOperation',
        'objky_format': 'Auftrag + Vorgang (zusammengesetzt)',
        'notes': 'OBJKY enthält Auftrag + Vorgangsnummer, muss aufgesplittet werden'
    },
    'STKO_DOC': {
        'target_object': 'BillOfMaterial',
        'api': 'API_BILL_OF_MATERIAL_SRV',
        'key_field': 'BillOfMaterial',
        'objky_format': 'Stücklisten-Kopf ID',
        'notes': 'OBJKY = BOM Header Key'
    },
    'STPO_DOC': {
        'target_object': 'BillOfMaterialItem',
        'api': 'API_BILL_OF_MATERIAL_SRV',
        'key_field': 'BillOfMaterial + BillOfMaterialItemNodeNumber',
        'objky_format': 'Stücklisten-Position',
        'notes': 'OBJKY = BOM Item Key (Header + Position)'
    },
    'IMPTT': {
        'target_object': 'MeasuringPoint',
        'api': 'API_MEASURINGPOINT',
        'key_field': 'MeasuringPoint',
        'objky_format': 'Messpunkt ID',
        'notes': 'OBJKY = Messpunkt-Nummer'
    }
}

with engine.begin() as con:
    for obj_type in object_types:
        result = con.execute(text(f"""
            SELECT OBJKY, COUNT(*) as cnt
            FROM DIL.DRAD
            WHERE DOKOB = :obj_type
            GROUP BY OBJKY
            ORDER BY cnt DESC
            LIMIT 5
        """), {'obj_type': obj_type})
        
        print(f'=== {obj_type}: {descriptions.get(obj_type, "?")} ===')
        print()
        
        # Mapping Info
        mapping = target_mapping.get(obj_type, {})
        print(f'  Target Object:  {mapping.get("target_object", "?")}')
        print(f'  SAP API:        {mapping.get("api", "?")}')
        print(f'  Key Field(s):   {mapping.get("key_field", "?")}')
        print(f'  OBJKY Format:   {mapping.get("objky_format", "?")}')
        print(f'  Hinweis:        {mapping.get("notes", "")}')
        print()
        
        print('  Beispiel OBJKY Werte:')
        rows = result.fetchall()
        for row in rows:
            objky = row[0]
            cnt = row[1]
            objky_len = len(objky) if objky else 0
            print(f'    "{objky}" (Länge: {objky_len}, {cnt:,}x)')
        print()
        print('-' * 70)
        print()

print()
print('=== ZUSAMMENFASSUNG: Object Link Mapping ===')
print()
print('| DOKOB    | S/4 Target Object            | OBJKY → Key Field              |')
print('|----------|------------------------------|--------------------------------|')
print('| IFLOT    | FunctionalLocation           | OBJKY → FunctionalLocation     |')
print('| PMQMEL   | MaintenanceNotification      | OBJKY → MaintenanceNotification|')
print('| PMAUFK   | MaintenanceOrder             | OBJKY → MaintenanceOrder       |')
print('| PMAFVC   | MaintenanceOrderOperation    | OBJKY → Order + Operation      |')
print('| STKO_DOC | BillOfMaterial               | OBJKY → BillOfMaterial         |')
print('| STPO_DOC | BillOfMaterialItem           | OBJKY → BOM + ItemNode         |')
print('| IMPTT    | MeasuringPoint               | OBJKY → MeasuringPoint         |')
