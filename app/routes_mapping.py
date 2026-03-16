"""Object mapping and exclusion template routes."""

from flask import render_template, request, jsonify, session, Response
import pandas as pd
import os
from sqlalchemy import text

from app.blueprint import (
    migrate_bp, misc_engine, get_template_context,
)


def _write_instructions_sheet(writer):
    """Write a formatted 'Instructions' sheet as the first sheet in the workbook."""
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    instructions = [
        ('Object Mapping – Anleitung / Instructions', ''),
        ('', ''),
        ('Zweck', 'Diese Datei dient der Zuordnung von Quell-Objektverknüpfungen (DOKOB/OBJKY) '
                  'zu neuen Ziel-Objektverknüpfungen im S4-System.'),
        ('', ''),
        ('Sheets in dieser Datei', ''),
        ('  Mappings', 'Bereits gespeicherte Zuordnungen aus der Datenbank.'),
        ('  Batch Objects', 'Alle DOKOB/OBJKY-Kombinationen des Batches. '
                           'target_dokob ist bereits mit dem Quellwert vorbelegt.'),
        ('  Unmapped Objects', 'Objekte, für die noch KEINE Zuordnung existiert. '
                              'Hier sollten Sie vorzugsweise arbeiten.'),
        ('  Info', 'Batch-Statistiken und Metadaten.'),
        ('', ''),
        ('So geht\'s – Schritt für Schritt', ''),
        ('1.', 'Öffnen Sie das Sheet "Unmapped Objects" (oder "Batch Objects").'),
        ('2.', 'Füllen Sie die Spalte target_objky mit dem neuen Zielwert aus. '
               'target_dokob ist bereits vorbelegt – ändern Sie es nur, wenn nötig.'),
        ('3.', 'Speichern Sie die Datei (.xlsx).'),
        ('4.', 'Laden Sie die Datei über den Upload-Button in der Anwendung hoch.'),
        ('', ''),
        ('Wichtig', ''),
        ('', '• Der Upload erkennt automatisch, welches Sheet ausgefüllte Mappings enthält.'),
        ('', '• Es wird das Sheet verwendet, das die meisten ausgefüllten target_objky-Werte hat.'),
        ('', '• Zeilen ohne target_objky werden übersprungen.'),
        ('', '• Spalten: source_dokob, source_objky, target_dokob, target_objky (alle erforderlich).'),
        ('', '• Groß-/Kleinschreibung bei DOKOB wird automatisch korrigiert (→ Großbuchstaben).'),
        ('', ''),
        ('Typische Werte für DOKOB', ''),
        ('  IFLOT', 'Technischer Platz (Functional Location)'),
        ('  EQUNR', 'Equipment'),
        ('  PMQMEL', 'Meldung (Notification)'),
        ('  PMAUFK', 'Auftrag (Order)'),
        ('  BUS2032', 'Stückliste (BOM)'),
    ]

    df_instr = pd.DataFrame(instructions, columns=['Thema', 'Beschreibung'])
    df_instr.to_excel(writer, sheet_name='Instructions', index=False)

    # -- format the sheet --
    ws = writer.sheets['Instructions']
    ws.column_dimensions['A'].width = 32
    ws.column_dimensions['B'].width = 90

    header_font = Font(bold=True, size=14, color='FFFFFF')
    header_fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
    section_font = Font(bold=True, size=11, color='2F5496')
    normal_font = Font(size=11)
    wrap = Alignment(wrap_text=True, vertical='top')

    # style header row (row 1 = pandas header)
    for cell in ws[1]:
        cell.font = Font(bold=True, size=11, color='FFFFFF')
        cell.fill = header_fill

    # title row (row 2 in Excel = index 0 in data)
    title_cell = ws.cell(row=2, column=1)
    title_cell.font = Font(bold=True, size=14, color='2F5496')

    section_labels = {
        'Zweck', 'Sheets in dieser Datei', 'So geht\'s – Schritt für Schritt',
        'Wichtig', 'Typische Werte für DOKOB',
    }
    for row_idx in range(2, ws.max_row + 1):
        a_val = ws.cell(row=row_idx, column=1).value or ''
        if a_val in section_labels:
            ws.cell(row=row_idx, column=1).font = section_font
        else:
            ws.cell(row=row_idx, column=1).font = normal_font
        ws.cell(row=row_idx, column=2).font = normal_font
        ws.cell(row=row_idx, column=2).alignment = wrap


@migrate_bp.route('/batch/<batch_id>/object-mapping')
def batch_object_mapping_page(batch_id):
    """Object mapping management page for a specific batch."""
    return render_template('object_mapping.html', batch_id=batch_id, **get_template_context())


@migrate_bp.route('/batch/<batch_id>/object-mapping/list', methods=['GET'])
def list_batch_object_mappings(batch_id):
    """Get all object mappings for a specific batch."""
    try:
        with misc_engine.begin() as con:
            # Get batch info
            batch_query = """
                SELECT batch_id, wave, description, total_records, status
                FROM dbo.migration_batch
                WHERE batch_id = :batch_id
            """
            batch_row = con.execute(text(batch_query), {'batch_id': batch_id}).fetchone()
            batch_info = None
            if batch_row:
                batch_info = {
                    'batch_id': batch_row[0],
                    'wave': batch_row[1],
                    'description': batch_row[2],
                    'total_records': batch_row[3],
                    'status': batch_row[4]
                }
            
            # Get mappings for this batch
            query = """
                SELECT 
                    id,
                    batch_id,
                    source_dokob,
                    source_objky,
                    target_dokob,
                    target_objky,
                    description,
                    created_at,
                    created_by,
                    active
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
                ORDER BY source_dokob, source_objky
            """
            df = pd.read_sql(text(query), con, params={'batch_id': batch_id})
        
        mappings = df.to_dict(orient='records')
        return jsonify({'success': True, 'mappings': mappings, 'total': len(mappings), 'batch': batch_info})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/add', methods=['POST'])
def add_batch_object_mapping(batch_id):
    """Add a new object mapping to a specific batch."""
    try:
        data = request.get_json()
        
        source_dokob = data.get('source_dokob', '').strip().upper()
        source_objky = data.get('source_objky', '').strip()
        target_dokob = data.get('target_dokob', '').strip().upper()
        target_objky = data.get('target_objky', '').strip()
        description = data.get('description', '').strip()
        
        if not source_dokob or not source_objky or not target_dokob or not target_objky:
            return jsonify({'success': False, 'error': 'All fields are required: source_dokob, source_objky, target_dokob, target_objky'}), 400
        
        current_user = session.get('fullName', 'system')
        
        with misc_engine.begin() as con:
            # Check for duplicate in this batch
            existing = con.execute(text("""
                SELECT id FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id 
                AND source_dokob = :source_dokob 
                AND source_objky = :source_objky 
                AND active = 1
            """), {'batch_id': batch_id, 'source_dokob': source_dokob, 'source_objky': source_objky}).fetchone()
            
            if existing:
                return jsonify({'success': False, 'error': f'Mapping for {source_dokob}/{source_objky} already exists in this batch'}), 400
            
            con.execute(text("""
                INSERT INTO dbo.migration_object_mapping 
                (batch_id, source_dokob, source_objky, target_dokob, target_objky, description, created_by, active)
                VALUES (:batch_id, :source_dokob, :source_objky, :target_dokob, :target_objky, :description, :created_by, 1)
            """), {
                'batch_id': batch_id,
                'source_dokob': source_dokob,
                'source_objky': source_objky,
                'target_dokob': target_dokob,
                'target_objky': target_objky,
                'description': description,
                'created_by': current_user
            })
        
        return jsonify({'success': True, 'message': 'Mapping added successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/<int:mapping_id>/update', methods=['POST', 'PUT'])
def update_batch_object_mapping(batch_id, mapping_id):
    """Update an existing object mapping."""
    try:
        data = request.get_json()
        
        source_dokob = data.get('source_dokob', '').strip().upper()
        source_objky = data.get('source_objky', '').strip()
        target_dokob = data.get('target_dokob', '').strip().upper()
        target_objky = data.get('target_objky', '').strip()
        description = data.get('description', '').strip()
        
        if not source_dokob or not source_objky or not target_dokob or not target_objky:
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_object_mapping
                SET source_dokob = :source_dokob,
                    source_objky = :source_objky,
                    target_dokob = :target_dokob,
                    target_objky = :target_objky,
                    description = :description
                WHERE id = :id AND batch_id = :batch_id
            """), {
                'source_dokob': source_dokob,
                'source_objky': source_objky,
                'target_dokob': target_dokob,
                'target_objky': target_objky,
                'description': description,
                'id': mapping_id,
                'batch_id': batch_id
            })
        
        return jsonify({'success': True, 'message': 'Mapping updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/<int:mapping_id>/delete', methods=['POST', 'DELETE'])
def delete_batch_object_mapping(batch_id, mapping_id):
    """Delete (deactivate) an object mapping."""
    try:
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_object_mapping SET active = 0 
                WHERE id = :id AND batch_id = :batch_id
            """), {'id': mapping_id, 'batch_id': batch_id})
        
        return jsonify({'success': True, 'message': 'Mapping deleted successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/download', methods=['GET'])
def download_batch_object_mapping(batch_id):
    """Download object mappings for a batch as Excel file with source values from staging."""
    try:
        with misc_engine.begin() as con:
            # Get existing mappings
            mappings_query = """
                SELECT 
                    source_dokob,
                    source_objky,
                    target_dokob,
                    target_objky
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
                ORDER BY source_dokob, source_objky
            """
            df_mappings = pd.read_sql(text(mappings_query), con, params={'batch_id': batch_id})
            
            # Get ALL unique DOKOB/OBJKY values from staging for this batch.
            # Includes primary source_dokob/source_objky AND all links from
            # source_object_links JSON (which can contain multiple links per record).
            # If the batch has a DOKOB filter, only include matching DOKOB types.
            
            # Load batch DOKOB filter
            bf_row = con.execute(text(
                "SELECT dokob_filter FROM dbo.migration_batch WHERE batch_id = :batch_id"
            ), {'batch_id': batch_id}).fetchone()
            dokob_filter_list = []
            if bf_row and bf_row[0]:
                dokob_filter_list = [d.strip() for d in bf_row[0].split(',') if d.strip()]
            
            # Build optional DOKOB filter clause
            dokob_where = ""
            query_params = {'batch_id': batch_id}
            if dokob_filter_list:
                placeholders = ','.join(f':df{i}' for i in range(len(dokob_filter_list)))
                dokob_where = f" AND dokob IN ({placeholders})"
                for i, val in enumerate(dokob_filter_list):
                    query_params[f'df{i}'] = val
            
            staging_query = f"""
                WITH all_links AS (
                    -- Primary DOKOB/OBJKY from staging columns
                    SELECT source_dokob AS dokob, source_objky AS objky,
                           execution_status
                    FROM dbo.migration_staging
                    WHERE batch_id = :batch_id
                      AND source_dokob IS NOT NULL AND source_objky IS NOT NULL

                    UNION

                    -- Additional links from source_object_links JSON
                    SELECT j.dokob, j.objky,
                           ms.execution_status
                    FROM dbo.migration_staging ms
                    CROSS APPLY OPENJSON(ms.source_object_links)
                        WITH (dokob VARCHAR(10), objky VARCHAR(100)) j
                    WHERE ms.batch_id = :batch_id
                      AND ms.source_object_links IS NOT NULL
                      AND LEN(ms.source_object_links) > 2
                      AND j.dokob IS NOT NULL AND j.objky IS NOT NULL
                )
                SELECT
                    dokob  AS source_dokob,
                    objky  AS source_objky,
                    COUNT(*) AS document_count,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) AS success_count,
                    SUM(CASE WHEN execution_status IN ('failed', 'partial')  THEN 1 ELSE 0 END) AS failed_count
                FROM all_links
                WHERE 1=1 {dokob_where}
                GROUP BY dokob, objky
                ORDER BY dokob, objky
            """
            df_staging = pd.read_sql(text(staging_query), con, params=query_params)
            
            # Count total and executed records for info sheet
            count_query = """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN source_dokob IS NOT NULL THEN 1 ELSE 0 END) as with_dokob,
                    SUM(CASE WHEN execution_status IN ('success', 'failed', 'partial') THEN 1 ELSE 0 END) as executed
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
            """
            counts = con.execute(text(count_query), {'batch_id': batch_id}).fetchone()
            total_records = counts[0] if counts else 0
            records_with_dokob = counts[1] if counts else 0
            executed_records = counts[2] if counts else 0
            
            # Get batch info
            batch_query = """
                SELECT wave, description, dokob_filter FROM dbo.migration_batch WHERE batch_id = :batch_id
            """
            batch_row = con.execute(text(batch_query), {'batch_id': batch_id}).fetchone()
            batch_wave = batch_row[0] if batch_row else ''
            batch_desc = batch_row[1] if batch_row else ''
        
        # Create Excel file with multiple sheets
        from io import BytesIO
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet 0: Instructions
            _write_instructions_sheet(writer)

            # Sheet 1: Existing Mappings
            df_mappings.to_excel(writer, sheet_name='Mappings', index=False)
            
            # Sheet 2: Source values from staging (for reference when creating mappings)
            # Add empty target columns for convenience
            if not df_staging.empty:
                df_staging['target_dokob'] = df_staging['source_dokob']
                df_staging['target_objky'] = ''
            df_staging.to_excel(writer, sheet_name='Batch Objects', index=False)
            
            # Sheet 3: Unmapped objects (objects in staging without a mapping)
            if not df_staging.empty and not df_mappings.empty:
                # Find unmapped by comparing (df_staging uses source_dokob/source_objky after renaming)
                mapped_keys = set(zip(df_mappings['source_dokob'], df_mappings['source_objky']))
                unmapped_mask = ~df_staging.apply(
                    lambda row: (row['source_dokob'], row['source_objky']) in mapped_keys, axis=1
                )
                df_unmapped = df_staging[unmapped_mask].copy()
            elif df_mappings.empty and not df_staging.empty:
                df_unmapped = df_staging.copy()
            else:
                df_unmapped = pd.DataFrame()
            
            if not df_unmapped.empty:
                df_unmapped.to_excel(writer, sheet_name='Unmapped Objects', index=False)
            
            # Sheet 4: Info sheet with batch statistics and notes
            info_data = {
                'Info': [
                    'Batch ID',
                    'Wave',
                    'Description',
                    '',
                    'Total Records',
                    'Records with DOKOB/OBJKY',
                    'Executed Records',
                    '',
                    'Note'
                ],
                'Value': [
                    batch_id,
                    batch_wave,
                    batch_desc,
                    '',
                    str(total_records),
                    str(records_with_dokob),
                    str(executed_records),
                    '',
                    'DOKOB/OBJKY values are fetched from API during EXECUTE phase. '
                    'If "Batch Objects" sheet is empty, start migration first to populate values.'
                ]
            }
            df_info = pd.DataFrame(info_data)
            df_info.to_excel(writer, sheet_name='Info', index=False)
        
        output.seek(0)
        
        filename = f'object_mapping_{batch_id}.xlsx'
        if batch_wave:
            filename = f'object_mapping_{batch_wave}_{batch_id[:20]}.xlsx'
        
        return Response(
            output.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/object-mapping/download-template', methods=['GET'])
def download_object_mapping_template():
    """Download empty Excel template for object mapping."""
    try:
        from io import BytesIO
        
        # Create template with headers and example
        df = pd.DataFrame({
            'source_dokob': ['IFLOT', 'PMQMEL', 'PMAUFK'],
            'source_objky': ['DE-LU-E-B211-MA10', '000100012345', '000012345678'],
            'target_dokob': ['IFLOT', 'PMQMEL', 'PMAUFK'],
            'target_objky': ['DE-LU-E-B211-MA10', '000100012345', '000012345678'],
        })
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            _write_instructions_sheet(writer)
            df.to_excel(writer, sheet_name='Object Mapping', index=False)
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': 'attachment; filename=object_mapping_template.xlsx'}
        )
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/upload', methods=['POST'])
def upload_batch_object_mapping(batch_id):
    """Upload Excel file with object mappings for a specific batch."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Read Excel file – smart scan: check headers first, then read best sheet
        required_cols = ['source_dokob', 'source_objky', 'target_dokob', 'target_objky']
        xls = pd.ExcelFile(file)
        
        # Phase 1: identify candidate sheets by reading ONLY the header row (fast)
        candidate_sheets = []
        for sheet in xls.sheet_names:
            header_df = pd.read_excel(xls, sheet_name=sheet, nrows=0)
            if all(c in header_df.columns for c in required_cols):
                candidate_sheets.append(sheet)
        
        # Phase 2: read candidates fully, pick the one with the most filled target_objky
        df = pd.DataFrame()
        used_sheet = None
        for sheet in candidate_sheets:
            df_sheet = pd.read_excel(xls, sheet_name=sheet)
            mask = df_sheet['target_objky'].notna() & (df_sheet['target_objky'].astype(str).str.strip() != '')
            df_filled = df_sheet[mask]
            if len(df_filled) > len(df):
                df = df_filled.copy()
                used_sheet = sheet
        
        if df.empty:
            return jsonify({'success': False,
                            'error': 'Keine Mappings gefunden. Bitte target_objky in einem der Sheets ausfüllen.'}), 400
        
        print(f"[UPLOAD] Using sheet '{used_sheet}' with {len(df)} mapping rows")
        
        # Get mode: 'replace' = delete all and insert, 'append' = add only new
        mode = request.form.get('mode', 'append')
        current_user = session.get('fullName', 'system')
        
        added = 0
        skipped = 0
        updated = 0
        
        # Clean and validate all rows in pandas (vectorized, fast)
        df['source_dokob'] = df['source_dokob'].astype(str).str.strip().str.upper()
        df['source_objky'] = df['source_objky'].astype(str).str.strip()
        df['target_dokob'] = df['target_dokob'].astype(str).str.strip().str.upper()
        df['target_objky'] = df['target_objky'].astype(str).str.strip()
        if 'description' in df.columns:
            df['description'] = df['description'].fillna('').astype(str).str.strip()
        else:
            df['description'] = ''
        
        # Filter out invalid rows (missing required fields)
        valid_mask = (
            (df['source_dokob'] != '') & (df['source_dokob'] != 'NAN') &
            (df['source_objky'] != '') & (df['source_objky'] != 'NAN') &
            (df['target_dokob'] != '') & (df['target_dokob'] != 'NAN') &
            (df['target_objky'] != '') & (df['target_objky'] != 'NAN')
        )
        skipped = int((~valid_mask).sum())
        df_valid = df[valid_mask].copy()
        
        with misc_engine.begin() as con:
            if mode == 'replace':
                # Deactivate all existing mappings for this batch
                con.execute(text("UPDATE dbo.migration_object_mapping SET active = 0 WHERE batch_id = :batch_id"), 
                           {'batch_id': batch_id})
            
            if not df_valid.empty:
                # Load existing mappings in ONE query → build lookup dict
                existing_rows = con.execute(text("""
                    SELECT id, source_dokob, source_objky 
                    FROM dbo.migration_object_mapping
                    WHERE batch_id = :batch_id
                """), {'batch_id': batch_id}).fetchall()
                existing_map = {(r[1], r[2]): r[0] for r in existing_rows}  # (dokob, objky) → id
                
                # Split into update vs insert batches
                insert_rows = []
                update_rows = []
                for _, row in df_valid.iterrows():
                    key = (row['source_dokob'], row['source_objky'])
                    if key in existing_map:
                        update_rows.append({
                            'id': existing_map[key],
                            'target_dokob': row['target_dokob'],
                            'target_objky': row['target_objky'],
                            'description': row['description'],
                        })
                    else:
                        insert_rows.append({
                            'batch_id': batch_id,
                            'source_dokob': row['source_dokob'],
                            'source_objky': row['source_objky'],
                            'target_dokob': row['target_dokob'],
                            'target_objky': row['target_objky'],
                            'description': row['description'],
                            'created_by': current_user,
                        })
                
                print(f"[UPLOAD] insert={len(insert_rows)}, update={len(update_rows)}")
                # Bulk UPDATE existing rows via temp table + JOIN (pymssql executemany is too slow)
                if update_rows:
                    con.execute(text("""
                        CREATE TABLE #tmp_upd (
                            id INT, target_dokob NVARCHAR(100),
                            target_objky NVARCHAR(200), description NVARCHAR(500)
                        )
                    """))
                    CHUNK = 1000
                    upd_cols = ['id', 'target_dokob', 'target_objky', 'description']
                    for i in range(0, len(update_rows), CHUNK):
                        chunk = update_rows[i:i+CHUNK]
                        value_clauses = []
                        params = {}
                        for j, row in enumerate(chunk):
                            placeholders = ', '.join(f':u{j}_{c}' for c in upd_cols)
                            value_clauses.append(f'({placeholders})')
                            for c in upd_cols:
                                params[f'u{j}_{c}'] = row[c]
                        sql = "INSERT INTO #tmp_upd (id, target_dokob, target_objky, description) VALUES " + ', '.join(value_clauses)
                        con.execute(text(sql), params)
                    con.execute(text("""
                        UPDATE m
                        SET m.target_dokob = t.target_dokob,
                            m.target_objky = t.target_objky,
                            m.description  = t.description,
                            m.active       = 1
                        FROM dbo.migration_object_mapping m
                        INNER JOIN #tmp_upd t ON t.id = m.id
                    """))
                    con.execute(text("DROP TABLE #tmp_upd"))
                    updated = len(update_rows)
                
                # Bulk INSERT new rows – use multi-row VALUES (max 1000 per statement for SQL Server)
                if insert_rows:
                    CHUNK = 1000
                    cols = ['batch_id', 'source_dokob', 'source_objky', 'target_dokob',
                            'target_objky', 'description', 'created_by']
                    for i in range(0, len(insert_rows), CHUNK):
                        chunk = insert_rows[i:i+CHUNK]
                        # Build multi-row VALUES clause with numbered params
                        value_clauses = []
                        params = {}
                        for j, row in enumerate(chunk):
                            placeholders = ', '.join(f':c{j}_{c}' for c in cols)
                            value_clauses.append(f'({placeholders}, 1)')
                            for c in cols:
                                params[f'c{j}_{c}'] = row[c]
                        sql = (
                            "INSERT INTO dbo.migration_object_mapping "
                            "(batch_id, source_dokob, source_objky, target_dokob, target_objky, description, created_by, active) "
                            "VALUES " + ', '.join(value_clauses)
                        )
                        con.execute(text(sql), params)
                    added = len(insert_rows)
        
        # Auto-apply mappings to staging records immediately after upload
        staging_applied = 0
        try:
            from app.prepare import apply_object_mappings_for_batch
            staging_applied = apply_object_mappings_for_batch(batch_id)
        except Exception as e:
            print(f"[WARN] Auto-apply after upload failed: {e}")
        
        apply_msg = f', {staging_applied} auf Staging angewendet' if staging_applied > 0 else ''
        return jsonify({
            'success': True,
            'message': f'Upload complete: {added} added, {updated} updated, {skipped} skipped{apply_msg}',
            'added': added,
            'updated': updated,
            'skipped': skipped,
            'staging_applied': staging_applied
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/stats', methods=['GET'])
def batch_object_mapping_stats(batch_id):
    """Get statistics about object mappings for a batch."""
    try:
        with misc_engine.begin() as con:
            # Count total mappings
            mapping_count_query = """
                SELECT COUNT(*) as cnt
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
            """
            total_mappings = con.execute(text(mapping_count_query), {'batch_id': batch_id}).fetchone()[0] or 0
            
            # Count unique sources and targets
            unique_query = """
                SELECT 
                    COUNT(DISTINCT source_dokob + '|' + source_objky) as unique_sources,
                    COUNT(DISTINCT target_dokob + '|' + target_objky) as unique_targets
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
            """
            unique_row = con.execute(text(unique_query), {'batch_id': batch_id}).fetchone()
            unique_sources = unique_row[0] if unique_row else 0
            unique_targets = unique_row[1] if unique_row else 0
            
            # Count unmapped objects in staging
            unmapped_query = """
                SELECT COUNT(DISTINCT s.source_dokob + '|' + s.source_objky) as cnt
                FROM dbo.migration_staging s
                LEFT JOIN dbo.migration_object_mapping m 
                    ON m.batch_id = s.batch_id
                    AND s.source_dokob = m.source_dokob 
                    AND s.source_objky = m.source_objky 
                    AND m.active = 1
                WHERE s.batch_id = :batch_id
                AND s.source_dokob IS NOT NULL
                AND m.id IS NULL
            """
            unmapped_count = con.execute(text(unmapped_query), {'batch_id': batch_id}).fetchone()[0] or 0
        
        return jsonify({
            'success': True, 
            'total_mappings': total_mappings,
            'unique_sources': unique_sources,
            'unique_targets': unique_targets,
            'unmapped_count': unmapped_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/unmapped', methods=['GET'])
def batch_object_mapping_unmapped(batch_id):
    """
    Get list of source objects in this batch that have no mapping.
    """
    try:
        with misc_engine.begin() as con:
            query = """
                SELECT 
                    s.source_dokob as dokob,
                    s.source_objky as objky,
                    COUNT(*) as count
                FROM dbo.migration_staging s
                LEFT JOIN dbo.migration_object_mapping m 
                    ON m.batch_id = s.batch_id
                    AND s.source_dokob = m.source_dokob 
                    AND s.source_objky = m.source_objky 
                    AND m.active = 1
                WHERE s.batch_id = :batch_id
                AND s.source_dokob IS NOT NULL
                AND m.id IS NULL
                GROUP BY s.source_dokob, s.source_objky
                ORDER BY s.source_dokob, s.source_objky
            """
            df = pd.read_sql(text(query), con, params={'batch_id': batch_id})
        
        unmapped = df.to_dict(orient='records')
        
        return jsonify({'success': True, 'unmapped': unmapped, 'total': len(unmapped)})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/object-mapping/all-batches', methods=['GET'])
def object_mapping_all_batches():
    """
    Get overview of all batches and their mapping status.
    """
    try:
        with misc_engine.begin() as con:
            query = """
                SELECT 
                    b.batch_id,
                    b.wave,
                    b.description,
                    b.total_records,
                    b.status,
                    COUNT(DISTINCT m.id) as mapping_count,
                    COUNT(DISTINCT CASE WHEN s.source_dokob IS NOT NULL AND m.id IS NULL 
                                        THEN CONCAT(s.source_dokob, '|', s.source_objky) END) as unmapped_count
                FROM dbo.migration_batch b
                LEFT JOIN dbo.migration_staging s ON b.batch_id = s.batch_id
                LEFT JOIN dbo.migration_object_mapping m 
                    ON m.batch_id = b.batch_id
                    AND s.source_dokob = m.source_dokob 
                    AND s.source_objky = m.source_objky 
                    AND m.active = 1
                GROUP BY b.batch_id, b.wave, b.description, b.total_records, b.status
                ORDER BY b.wave, b.batch_id
            """
            df = pd.read_sql(query, con)
        
        batches = df.to_dict(orient='records')
        
        return jsonify({'success': True, 'batches': batches})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/apply', methods=['POST'])
def apply_batch_object_mappings(batch_id):
    """
    Apply object mappings to staging records for a batch.
    
    NOTE: Since source_dokob/source_objky are now fetched from API during EXECUTE phase,
    this endpoint will only work for records that have already been (partially) executed.
    For new batches, object mappings are applied ON-THE-FLY during EXECUTE.
    
    This endpoint is kept for backward compatibility with manually-set source values.
    """
    try:
        from app.prepare import apply_object_mappings_for_batch
        
        updated = apply_object_mappings_for_batch(batch_id)
        
        # Add a note if no updates were made
        message = f'Applied mappings to {updated} staging records'
        if updated == 0:
            message += '. Note: Object mappings are now applied on-the-fly during EXECUTE (source_dokob/source_objky come from API).'
        
        return jsonify({
            'success': True, 
            'message': message,
            'updated': updated
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@migrate_bp.route('/api/exclusion-template/download', methods=['GET'])
def download_exclusion_template():
    """Download an empty Excel exclusion template.
    One sheet per DOKOB type with the key column and an example row."""
    from flask import send_file
    from app.db_schema import EXCLUSION_EXCEL_SHEETS
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='2E75B6', end_color='2E75B6', fill_type='solid')
    example_font = Font(italic=True, color='888888')
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    for dokob, sheet_def in EXCLUSION_EXCEL_SHEETS.items():
        ws = wb.create_sheet(title=dokob)
        key_col = sheet_def['key_column']
        label = sheet_def['label']
        example = sheet_def.get('example', '')

        # Header row
        ws.cell(row=1, column=1, value=key_col).font = header_font
        ws.cell(row=1, column=1).fill = header_fill
        ws.cell(row=1, column=1).alignment = Alignment(horizontal='center')
        ws.cell(row=1, column=1).border = thin_border

        # Description column
        ws.cell(row=1, column=2, value='Beschreibung (optional)').font = header_font
        ws.cell(row=1, column=2).fill = header_fill
        ws.cell(row=1, column=2).alignment = Alignment(horizontal='center')
        ws.cell(row=1, column=2).border = thin_border

        # Example row
        ws.cell(row=2, column=1, value=example).font = example_font
        ws.cell(row=2, column=2, value=f'Beispiel {label}').font = example_font

        # Additional example rows (e.g. PMPLKO has multiple format types)
        extra_examples = sheet_def.get('extra_examples', [])
        for i, (ex_val, ex_desc) in enumerate(extra_examples, start=3):
            ws.cell(row=i, column=1, value=ex_val).font = example_font
            ws.cell(row=i, column=2, value=ex_desc).font = example_font

        # Auto-width
        all_examples = [example] + [e[0] for e in extra_examples]
        ws.column_dimensions['A'].width = max(len(key_col), max(len(e) for e in all_examples)) + 4
        ws.column_dimensions['B'].width = 30

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name='exclusion_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@migrate_bp.route('/api/exclusion-template/upload', methods=['POST'])
def upload_exclusion_template():
    """Upload a filled Excel exclusion template.
    Parses all sheets matching DOKOB names and returns the exclusion keys per type.
    Also stores the parsed keys in a temp JSON file so the batch creation SSE stream
    can read them (SSE uses GET, so we can't POST data with it)."""
    from app.db_schema import EXCLUSION_EXCEL_SHEETS

    if 'file' not in request.files:
        return jsonify(success=False, error='Keine Datei hochgeladen'), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify(success=False, error='Keine Datei ausgewählt'), 400

    try:
        # Read all sheets
        xl = pd.ExcelFile(file, engine='openpyxl')
        result = {}
        total_keys = 0

        for dokob, sheet_def in EXCLUSION_EXCEL_SHEETS.items():
            if dokob not in xl.sheet_names:
                continue
            df = xl.parse(dokob)
            key_col = sheet_def['key_column']

            # Find the key column (case-insensitive)
            col_map = {c.strip().upper(): c for c in df.columns}
            actual_col = col_map.get(key_col.upper())
            if not actual_col:
                continue

            # Extract non-empty keys, skip example row (italic font not detectable in pandas)
            keys = df[actual_col].dropna().astype(str).str.strip()
            keys = keys[keys != '']
            # Remove the example value(s)
            example_val = sheet_def.get('example', '')
            if example_val:
                keys = keys[keys != example_val]
            for ex_val, _ in sheet_def.get('extra_examples', []):
                keys = keys[keys != ex_val]

            keys_list = keys.unique().tolist()

            # Also check for description column
            desc_col = col_map.get('BESCHREIBUNG (OPTIONAL)') or col_map.get('BESCHREIBUNG')
            descriptions = {}
            if desc_col:
                for _, row in df.iterrows():
                    k = str(row.get(actual_col, '')).strip()
                    d = str(row.get(desc_col, '')).strip()
                    if k and k != example_val and d and d != f'Beispiel {sheet_def["label"]}':
                        descriptions[k] = d

            if keys_list:
                result[dokob] = {
                    'key_column': key_col,
                    'keys': keys_list,
                    'count': len(keys_list),
                    'descriptions': descriptions
                }
                total_keys += len(keys_list)

        # Store exclusion keys in temp file for batch creation SSE stream
        os.makedirs('userdata', exist_ok=True)
        temp_path = os.path.join('userdata', 'pending_exclusion_keys.json')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)

        return jsonify(success=True, exclusions=result, total_keys=total_keys,
                       sheets_found=list(result.keys()))

    except Exception as e:
        import traceback
        return jsonify(success=False, error=str(e), detail=traceback.format_exc()), 500


@migrate_bp.route('/api/exclusion-template/clear', methods=['POST'])
def clear_pending_exclusion_keys():
    """Clear the pending exclusion keys (e.g. when user removes upload)."""
    temp_path = os.path.join('userdata', 'pending_exclusion_keys.json')
    if os.path.exists(temp_path):
        os.remove(temp_path)
    return jsonify(success=True)


