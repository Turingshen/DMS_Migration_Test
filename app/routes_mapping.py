"""Object mapping and exclusion template routes."""

from flask import render_template, request, jsonify, session, Response
import pandas as pd
import os
from sqlalchemy import text

from app.blueprint import (
    migrate_bp, misc_engine, get_template_context,
)


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
                    target_objky,
                    description
                FROM dbo.migration_object_mapping
                WHERE batch_id = :batch_id AND active = 1
                ORDER BY source_dokob, source_objky
            """
            df_mappings = pd.read_sql(text(mappings_query), con, params={'batch_id': batch_id})
            
            # Get unique DOKOB/OBJKY values from staging for this batch
            # NOTE: source_dokob/source_objky are populated during EXECUTE phase from API
            # So this will only show values for records that have been executed
            staging_query = """
                SELECT 
                    source_dokob,
                    source_objky,
                    COUNT(*) as document_count,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id AND source_dokob IS NOT NULL AND source_objky IS NOT NULL
                GROUP BY source_dokob, source_objky
                ORDER BY source_dokob, source_objky
            """
            df_staging = pd.read_sql(text(staging_query), con, params={'batch_id': batch_id})
            
            # Count total and executed records for info sheet
            count_query = """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN source_dokob IS NOT NULL THEN 1 ELSE 0 END) as with_dokob,
                    SUM(CASE WHEN execution_status IN ('success', 'failed') THEN 1 ELSE 0 END) as executed
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
            """
            counts = con.execute(text(count_query), {'batch_id': batch_id}).fetchone()
            total_records = counts[0] if counts else 0
            records_with_dokob = counts[1] if counts else 0
            executed_records = counts[2] if counts else 0
            
            # Get batch info
            batch_query = """
                SELECT wave, description FROM dbo.migration_batch WHERE batch_id = :batch_id
            """
            batch_row = con.execute(text(batch_query), {'batch_id': batch_id}).fetchone()
            batch_wave = batch_row[0] if batch_row else ''
            batch_desc = batch_row[1] if batch_row else ''
        
        # Create Excel file with multiple sheets
        from io import BytesIO
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet 1: Existing Mappings
            df_mappings.to_excel(writer, sheet_name='Mappings', index=False)
            
            # Sheet 2: Source values from staging (for reference when creating mappings)
            # Add empty target columns for convenience
            if not df_staging.empty:
                df_staging['target_dokob'] = ''
                df_staging['target_objky'] = ''
                df_staging['description'] = ''
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
            'description': ['Functional Location', 'Notification', 'Order']
        })
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
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
        
        # Read Excel file
        df = pd.read_excel(file)
        
        # Validate required columns
        required_cols = ['source_dokob', 'source_objky', 'target_dokob', 'target_objky']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            return jsonify({'success': False, 'error': f'Missing columns: {missing_cols}'}), 400
        
        # Get mode: 'replace' = delete all and insert, 'append' = add only new
        mode = request.form.get('mode', 'append')
        current_user = session.get('fullName', 'system')
        
        added = 0
        skipped = 0
        updated = 0
        
        with misc_engine.begin() as con:
            if mode == 'replace':
                # Deactivate all existing mappings for this batch
                con.execute(text("UPDATE dbo.migration_object_mapping SET active = 0 WHERE batch_id = :batch_id"), 
                           {'batch_id': batch_id})
            
            for _, row in df.iterrows():
                source_dokob = str(row['source_dokob']).strip().upper()
                source_objky = str(row['source_objky']).strip()
                target_dokob = str(row['target_dokob']).strip().upper()
                target_objky = str(row['target_objky']).strip()
                description = str(row.get('description', '') or '').strip()
                
                if not source_dokob or not source_objky or not target_dokob or not target_objky:
                    skipped += 1
                    continue
                
                # Check if mapping exists in this batch
                existing = con.execute(text("""
                    SELECT id, active FROM dbo.migration_object_mapping
                    WHERE batch_id = :batch_id 
                    AND source_dokob = :source_dokob 
                    AND source_objky = :source_objky
                """), {'batch_id': batch_id, 'source_dokob': source_dokob, 'source_objky': source_objky}).fetchone()
                
                if existing:
                    # Update existing mapping
                    con.execute(text("""
                        UPDATE dbo.migration_object_mapping
                        SET target_dokob = :target_dokob, target_objky = :target_objky, 
                            description = :description, active = 1
                        WHERE id = :id
                    """), {
                        'target_dokob': target_dokob,
                        'target_objky': target_objky,
                        'description': description,
                        'id': existing[0]
                    })
                    updated += 1
                else:
                    # Insert new mapping
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
                    added += 1
        
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


