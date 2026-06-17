"""Batch management, prepare, and data refresh routes."""

from flask import render_template, request, jsonify, session, Response
import pandas as pd
import os
import json
from werkzeug.utils import secure_filename
from sqlalchemy import text

from app.blueprint import (
    migrate_bp, misc_engine, get_template_context,
    allowed_file, UPLOAD_FOLDER,
)
from app.prepare import prepare_migration


@migrate_bp.route('/')
def index():
    """Main migration dashboard - shows batches and status."""
    return render_template('index.html', **get_template_context())


@migrate_bp.route('/batches', methods=['GET'])
def get_batches():
    """Get list of all migration batches."""
    try:
        # Get batch info with actual record counts from staging table
        query = """
            SELECT 
                b.batch_id,
                b.created_at,
                b.created_by,
                b.source_file,
                b.description,
                b.notes,
                b.wave,
                b.migration_phase,
                b.estimated_duration_h,
                ISNULL(b.task_qual_load, 0) as task_qual_load,
                ISNULL(b.task_qual_link, 0) as task_qual_link,
                ISNULL(b.task_prod_load, 0) as task_prod_load,
                ISNULL(b.task_prod_link, 0) as task_prod_link,
                b.task_qual_load_start, b.task_qual_load_dur,
                b.task_qual_link_start, b.task_qual_link_dur,
                b.task_prod_load_start, b.task_prod_load_dur,
                b.task_prod_link_start, b.task_prod_link_dur,
                COALESCE(s.total_count, b.total_records) as total_records,
                b.approved_records,
                COALESCE(s.executed_count, b.executed_records) as executed_records,
                COALESCE(s.success_count, b.successful_records) as successful_records,
                COALESCE(s.failed_count, b.failed_records) as failed_records,
                b.status,
                COALESCE(s.link_pending, 0) as link_pending,
                COALESCE(s.link_linked, 0) as link_linked,
                COALESCE(s.link_exists, 0) as link_exists,
                COALESCE(s.link_failed, 0) as link_failed,
                COALESCE(s.link_skipped, 0) as link_skipped,
                COALESCE(s.link_total, 0) as link_total
            FROM dbo.migration_batch b
            LEFT JOIN (
                SELECT 
                    batch_id,
                    COUNT(*) as total_count,
                    SUM(CASE WHEN execution_status IN ('success', 'failed', 'partial') THEN 1 ELSE 0 END) as executed_count,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN execution_status IN ('failed', 'partial') THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN ISNULL(link_status, 'pending') = 'pending' AND execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1 ELSE 0 END) as link_pending,
                    SUM(CASE WHEN link_status = 'linked' THEN 1 ELSE 0 END) as link_linked,
                    SUM(CASE WHEN link_status = 'link_exists' THEN 1 ELSE 0 END) as link_exists,
                    SUM(CASE WHEN link_status = 'link_failed' THEN 1 ELSE 0 END) as link_failed,
                    SUM(CASE WHEN link_status = 'link_skipped' THEN 1 ELSE 0 END) as link_skipped,
                    SUM(CASE WHEN link_status IN ('linked', 'link_exists', 'link_failed', 'link_skipped') THEN 1
                         WHEN ISNULL(link_status, 'pending') = 'pending' AND execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1
                         ELSE 0 END) as link_total
                FROM dbo.migration_staging
                GROUP BY batch_id
            ) s ON b.batch_id = s.batch_id
            ORDER BY b.created_at DESC
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(text(query), con)
        
        # Replace NaN/NaT with None for JSON serialization
        df = df.where(pd.notnull(df), None)
        # Extra safety: replace any remaining NaN/inf values
        import numpy as np
        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
        # Convert date columns to string for JSON
        for col in ['task_qual_load_start','task_qual_link_start','task_prod_load_start','task_prod_link_start']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: str(x)[:10] if x is not None and pd.notnull(x) else None)
        batches = df.to_dict(orient='records')
        return jsonify({'success': True, 'batches': batches})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch_statistics', methods=['GET'])
def get_batch_statistics():
    """Get statistics for a specific batch."""
    try:
        batch_id = request.args.get('batch_id')
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        query = """
            SELECT 
                batch_id,
                total_records,
                executed_records,
                successful_records,
                failed_records,
                notes,
                execution_stats
            FROM dbo.migration_batch
            WHERE batch_id = :batch_id
        """
        
        with misc_engine.begin() as con:
            result = con.execute(text(query), {'batch_id': batch_id}).fetchone()
        
        if not result:
            return jsonify({'success': False, 'error': 'Batch not found'}), 404
        
        # Parse execution_stats as JSON for statistics (fall back to notes for legacy data)
        import json
        statistics = {}
        stats_source = result.execution_stats if hasattr(result, 'execution_stats') and result.execution_stats else result.notes
        if stats_source:
            try:
                statistics = json.loads(stats_source)
            except json.JSONDecodeError:
                pass
        
        # Add fallback values if no statistics available
        if not statistics:
            statistics = {
                'batch_duration_seconds': 0,
                'batch_duration_formatted': '-',
                'total_documents': result.executed_records or 0,
                'total_files': 0,
                'total_bytes': 0,
                'total_mb': 0,
                'avg_time_per_document_seconds': 0,
                'avg_time_per_mb_seconds': 0,
                'throughput_mb_per_minute': 0,
                'workers': '-',
                'pacing_seconds': '-',
                'message': 'Statistics not available for this batch (executed before statistics feature)'
            }
        
        return jsonify({'success': True, 'statistics': statistics})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/download_template', methods=['GET'])
def download_template():
    """Generate and download the Excel template for the DMS-key upload.

    One sheet with the four key columns (Documenttype / Documentversion /
    Documentpart / Documentnumber). The number columns are text-formatted so
    leading zeros and long internal numbers are preserved.
    """
    import io
    from flask import send_file
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = 'DMS_Keys'

    headers = ['Documenttype', 'Documentversion', 'Documentpart', 'Documentnumber']
    ws.append(headers)

    # Example rows: one internal (25-digit) key, one external key.
    examples = [
        ['I71', '00', '000', '0000000000000010002152984'],
        ['IY1', '00', '000', 'EQUI330171928'],
    ]
    for row in examples:
        ws.append(row)

    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='2E5C8A', end_color='2E5C8A', fill_type='solid')
    widths = [16, 16, 14, 30]
    for idx, (header, width) in enumerate(zip(headers, widths), start=1):
        col = ws.cell(row=1, column=idx)
        col.font = header_font
        col.fill = header_fill
        col.alignment = Alignment(horizontal='center')
        letter = col.column_letter
        ws.column_dimensions[letter].width = width
        # Force text format for the whole column so leading zeros survive.
        for r in range(1, ws.max_row + 1):
            ws.cell(row=r, column=idx).number_format = '@'

    ws.freeze_panes = 'A2'

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name='migration_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@migrate_bp.route('/prepare', methods=['GET', 'POST'])
def prepare():
    """Step 1: Prepare migration data."""
    if request.method == 'GET':
        return render_template('prepare.html', **get_template_context())
    
    try:
        # Check if file upload or database query
        use_file = request.form.get('use_file', 'false') == 'true'
        
        # Get batch metadata
        wave = request.form.get('wave', '').strip() or None
        description = request.form.get('description', '').strip()[:40] or None
        notes = request.form.get('notes', '').strip() or None
        
        if use_file:
            # Handle file upload
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'No file uploaded'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'}), 400
            
            if not allowed_file(file.filename):
                return jsonify({'success': False, 'error': 'Invalid file type. Use Excel or CSV.'}), 400
            
            # Save uploaded file
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # Prepare migration from file
            # Pass session snapshot so prepare can call source API for descriptions
            snap = dict(session)
            result = prepare_migration(filepath, wave=wave, description=description, notes=notes, session_snapshot=snap)
        else:
            # Prepare migration from database query
            custom_query = request.form.get('custom_query', '').strip()
            query_source = request.form.get('query_source', 'dil')  # 'dil' or 'datastore'
            snap = dict(session)
            result = prepare_migration(custom_query=custom_query if custom_query else None, query_source=query_source, wave=wave, description=description, notes=notes, session_snapshot=snap)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>', methods=['PUT'])
def update_batch(batch_id):
    """Update batch description, notes and wave."""
    try:
        data = request.get_json()
        description = data.get('description', '').strip()[:40] if data.get('description') else None
        notes = data.get('notes', '').strip() if data.get('notes') else None
        wave = data.get('wave', '').strip() if data.get('wave') else None
        estimated_duration_h = data.get('estimated_duration_h')
        if estimated_duration_h is not None:
            try:
                estimated_duration_h = float(estimated_duration_h) if estimated_duration_h != '' else None
            except (ValueError, TypeError):
                estimated_duration_h = None

        task_qual_load = 1 if data.get('task_qual_load') else 0
        task_qual_link = 1 if data.get('task_qual_link') else 0
        task_prod_load = 1 if data.get('task_prod_load') else 0
        task_prod_link = 1 if data.get('task_prod_link') else 0

        # Per-task start dates and durations
        task_qual_load_start = data.get('task_qual_load_start') or None
        task_qual_load_dur = int(data['task_qual_load_dur']) if data.get('task_qual_load_dur') else None
        task_qual_link_start = data.get('task_qual_link_start') or None
        task_qual_link_dur = int(data['task_qual_link_dur']) if data.get('task_qual_link_dur') else None
        task_prod_load_start = data.get('task_prod_load_start') or None
        task_prod_load_dur = int(data['task_prod_load_dur']) if data.get('task_prod_load_dur') else None
        task_prod_link_start = data.get('task_prod_link_start') or None
        task_prod_link_dur = int(data['task_prod_link_dur']) if data.get('task_prod_link_dur') else None
        
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_batch
                SET description = :description,
                    notes = :notes,
                    wave = :wave,
                    estimated_duration_h = :estimated_duration_h,
                    task_qual_load = :task_qual_load,
                    task_qual_link = :task_qual_link,
                    task_prod_load = :task_prod_load,
                    task_prod_link = :task_prod_link,
                    task_qual_load_start = :tqls, task_qual_load_dur = :tqld,
                    task_qual_link_start = :tkls, task_qual_link_dur = :tkld,
                    task_prod_load_start = :tpls, task_prod_load_dur = :tpld,
                    task_prod_link_start = :tpks, task_prod_link_dur = :tpkd
                WHERE batch_id = :batch_id
            """), {'description': description, 'notes': notes, 'wave': wave,
                   'estimated_duration_h': estimated_duration_h,
                   'task_qual_load': task_qual_load, 'task_qual_link': task_qual_link,
                   'task_prod_load': task_prod_load, 'task_prod_link': task_prod_link,
                   'tqls': task_qual_load_start, 'tqld': task_qual_load_dur,
                   'tkls': task_qual_link_start, 'tkld': task_qual_link_dur,
                   'tpls': task_prod_load_start, 'tpld': task_prod_load_dur,
                   'tpks': task_prod_link_start, 'tpkd': task_prod_link_dur,
                   'batch_id': batch_id})
        
        return jsonify({'success': True, 'message': 'Batch updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/estimate-duration', methods=['POST'])
def estimate_batch_duration(batch_id):
    """Auto-calculate estimated duration based on file count and total size."""
    try:
        with misc_engine.begin() as con:
            result = con.execute(text("""
                SELECT 
                    COUNT(*) as doc_count,
                    COALESCE(SUM(CAST(file_size_bytes AS BIGINT)), 0) as total_bytes
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
            """), {'batch_id': batch_id}).fetchone()

            doc_count = result[0] or 0
            total_bytes = result[1] or 0
            total_gb = total_bytes / (1024 * 1024 * 1024)

            # Estimation: ~100 docs/hour API throughput + ~2 GB/hour upload speed
            time_by_docs = doc_count / 100.0
            time_by_size = total_gb / 2.0
            estimated_h = round(max(time_by_docs, time_by_size, 0.5), 1)

            con.execute(text("""
                UPDATE dbo.migration_batch
                SET estimated_duration_h = :dur
                WHERE batch_id = :batch_id
            """), {'dur': estimated_h, 'batch_id': batch_id})

        return jsonify({
            'success': True,
            'estimated_duration_h': estimated_h,
            'doc_count': doc_count,
            'total_gb': round(total_gb, 2)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>', methods=['DELETE'])
def delete_batch(batch_id):
    """Delete a batch and all associated records."""
    try:
        # Check if batch exists
        with misc_engine.begin() as con:
            result = con.execute(text("""
                SELECT batch_id, status FROM dbo.migration_batch WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            batch = result.fetchone()
            
            if not batch:
                return jsonify({'success': False, 'error': 'Batch not found'}), 404
            
            # Don't allow deleting executing batches
            if batch[1] == 'executing':
                return jsonify({'success': False, 'error': 'Cannot delete batch while executing'}), 400
            
            # Delete file details first (foreign key constraint)
            r1 = con.execute(text("""
                DELETE FROM dbo.migration_file_details WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete logs
            r2 = con.execute(text("""
                DELETE FROM dbo.migration_logs WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete object mappings
            r3 = con.execute(text("""
                DELETE FROM dbo.migration_object_mapping WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete staging records
            r4 = con.execute(text("""
                DELETE FROM dbo.migration_staging WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete batch
            con.execute(text("""
                DELETE FROM dbo.migration_batch WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
        
        return jsonify({
            'success': True, 
            'message': f'Batch {batch_id} gelöscht',
            'deleted': {
                'file_details': r1.rowcount,
                'logs': r2.rowcount,
                'object_mappings': r3.rowcount,
                'staging_records': r4.rowcount
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/refresh-data-stream', methods=['GET'])
def refresh_batch_data_stream(batch_id):
    """SSE streaming endpoint that combines:
    1. Fetch metadata (LOIO, file sizes) from DIL
    2. Fetch filenames from DIL.DRAW (for file extension workaround)
    3. Apply migration rules
    
    This replaces the separate 'Fetch Metadata' and 'Apply Rules' buttons.
    """
    
    def generate():
        try:
            from app_config import DilEngine
            from app.prepare import load_translations
            
            dil_db = DilEngine.load()
            dil_engine = dil_db.engine
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Loading batch records...'})}\n\n"
            
            # Get all records for this batch
            query = """
                SELECT id, source_documentnumber, source_documentpart, source_documenttype, source_documentversion,
                       file_size_bytes, source_loioid, filename
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
                  AND skip_migration = 0
            """
            
            with misc_engine.begin() as con:
                df = pd.read_sql(text(query), con, params={'batch_id': batch_id})
            
            if len(df) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No records found'})}\n\n"
                return
            
            total_records = int(len(df))
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'init', 'total': total_records, 'percent': 5, 'message': f'Found {total_records} records'})}\n\n"
            
            # ========== PHASE 1: LOIO Lookup ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'loio', 'message': 'Phase 1/4: Looking up LOIO_IDs from DIL...'})}\n\n"
            
            # Build conditions for batch lookup - VECTORIZED approach
            df['dokvr_padded'] = df['source_documentversion'].astype(str).str.zfill(2)
            df['doktl_padded'] = df['source_documentpart'].astype(str).str.zfill(3)
            df['doknr_escaped'] = df['source_documentnumber'].astype(str).str.replace("'", "''", regex=False)
            df['dokar_escaped'] = df['source_documenttype'].astype(str).str.replace("'", "''", regex=False)
            
            conditions = (
                "(DOKNR='" + df['doknr_escaped'] + 
                "' AND DOKAR='" + df['dokar_escaped'] + 
                "' AND DOKVR='" + df['dokvr_padded'] + 
                "' AND DOKTL='" + df['doktl_padded'] + "')"
            ).tolist()
            
            # Keep doknr_escaped/dokar_escaped for reuse in DRAW/DRAT phases (dropped after DRAT)
            
            # Query LOIO_IDs in chunks (1000 per query for fewer round-trips)
            chunk_size = 1000
            all_loios = []
            total_conditions = len(conditions)
            
            for i in range(0, total_conditions, chunk_size):
                chunk = conditions[i:i + chunk_size]
                where_clause = " OR ".join(chunk)
                loio_query = f"""
                    SELECT DOKNR, DOKAR, DOKVR, DOKTL, LO_OBJID
                    FROM DIL.DMS_DOC2LOIO
                    WHERE MANDT = '100'
                    AND ({where_clause})
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(text(loio_query), con)
                all_loios.append(chunk_df)
                
                if i % 2000 == 0:
                    pct = 5 + int((i / total_conditions) * 15)  # 5-20%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'loio', 'percent': pct, 'message': f'LOIO lookup: {i}/{total_conditions}'})}\n\n"
            
            loio_df = pd.DataFrame()
            if all_loios and not all(len(c) == 0 for c in all_loios):
                loio_df = pd.concat(all_loios, ignore_index=True)
                loio_df.columns = [c.lower() for c in loio_df.columns]
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'loio', 'percent': 20, 'message': f'Found {len(loio_df)} LOIO_IDs'})}\n\n"
            
            # ========== PHASE 2: File Size Lookup ==========
            loio_ids = loio_df['lo_objid'].dropna().unique().tolist() if len(loio_df) > 0 else []
            total_size_records = 0
            size_df = pd.DataFrame()
            
            if loio_ids:
                yield f"data: {json.dumps({'type': 'status', 'phase': 'size', 'message': f'Phase 2/4: Looking up file sizes for {len(loio_ids)} LOIOs...'})}\n\n"
                
                all_sizes = []
                chunk_size = 2000
                total_loios = len(loio_ids)
                
                for i in range(0, total_loios, chunk_size):
                    chunk = loio_ids[i:i + chunk_size]
                    placeholders = ",".join(["'" + str(lid).replace("'", "''") + "'" for lid in chunk])
                    size_query = f"""
                        SELECT LOIO_ID, FILE_SIZE, FILE_NAME
                        FROM DIL.DMS_FILE_SIZE
                        WHERE LOIO_ID IN ({placeholders})
                    """
                    with dil_engine.begin() as con:
                        chunk_df = pd.read_sql(text(size_query), con)
                    all_sizes.append(chunk_df)
                    
                    if i % 4000 == 0:
                        pct = 20 + int((i / total_loios) * 15)  # 20-35%
                        yield f"data: {json.dumps({'type': 'progress', 'phase': 'size', 'percent': pct, 'message': f'File sizes: {i}/{total_loios}'})}\n\n"
                
                total_size_records = sum(len(c) for c in all_sizes)
                if total_size_records > 0:
                    size_df = pd.concat(all_sizes, ignore_index=True)
                    size_df.columns = [c.lower() for c in size_df.columns]
                    size_df = size_df.sort_values('file_size', ascending=False).drop_duplicates(subset=['loio_id'], keep='first')
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'size', 'percent': 35, 'message': f'Found {total_size_records} file sizes'})}\n\n"
            
            # ========== PHASE 3: Filename Lookup from DRAW ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'draw', 'message': 'Phase 3/4: Looking up filenames from DIL.DRAW...'})}\n\n"
            
            # Build document keys for DRAW lookup - VECTORIZED (no iterrows!)
            draw_conditions = (
                "(doknr = '" + df['doknr_escaped'] +
                "' AND dokar = '" + df['dokar_escaped'] +
                "' AND dokvr = '" + df['dokvr_padded'] +
                "' AND doktl = '" + df['doktl_padded'] + "')"
            ).tolist()
            
            all_filenames = []
            chunk_size = 1000
            total_draw = len(draw_conditions)
            
            for i in range(0, total_draw, chunk_size):
                chunk = draw_conditions[i:i + chunk_size]
                where_clause = " OR ".join(chunk)
                
                draw_query = f"""
                    SELECT doknr, dokar, dokvr, doktl, filep, dokst, begru, dwnam
                    FROM dil.DRAW
                    WHERE {where_clause}
"""
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(text(draw_query), con)
                all_filenames.append(chunk_df)
                
                if i % 3000 == 0:
                    pct = 35 + int((i / total_draw) * 15)  # 35-50%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'draw', 'percent': pct, 'message': f'DRAW lookup: {i}/{total_draw}'})}\n\n"
            
            filename_df = pd.DataFrame()
            filenames_found = 0
            if all_filenames:
                filename_df = pd.concat(all_filenames, ignore_index=True)
                filename_df.columns = [c.lower() for c in filename_df.columns]
                # Deduplicate: DRAW can have multiple rows per document
                filename_df = filename_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')
                filenames_found = int(filename_df['filep'].notna().sum())
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'draw', 'percent': 50, 'message': f'Found {filenames_found} filenames from DRAW'})}\n\n"
            
            # ========== PHASE 3b: Description Lookup from DRAT ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'drat', 'message': 'Phase 3b/4: Looking up descriptions from DIL.DRAT...'})}\n\n"
            
            # Reuse vectorized conditions from DRAW (same keys)
            all_descriptions = []
            drat_chunk_size = 1000
            total_drat = len(draw_conditions)
            
            for i in range(0, total_drat, drat_chunk_size):
                chunk = draw_conditions[i:i + drat_chunk_size]
                # Uppercase column names for DRAT (SAP convention)
                where_clause = " OR ".join(c.replace('doknr', 'DOKNR').replace('dokar', 'DOKAR').replace('dokvr', 'DOKVR').replace('doktl', 'DOKTL') for c in chunk)
                drat_query = f"""
                    SELECT DOKNR, DOKAR, DOKVR, DOKTL, LANGU, DKTXT
                    FROM DIL.DRAT
                    WHERE MANDT = '100' AND ({where_clause})
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(text(drat_query), con)
                all_descriptions.append(chunk_df)
                
                if i % 3000 == 0:
                    pct = 50 + int((i / total_drat) * 5)  # 50-55%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'drat', 'percent': pct, 'message': f'DRAT lookup: {i}/{total_drat}'})}\n\n"
            
            drat_df = pd.DataFrame()
            descriptions_found = 0
            if all_descriptions:
                drat_df = pd.concat(all_descriptions, ignore_index=True)
                drat_df.columns = [c.lower() for c in drat_df.columns]
                # Language priority: E (English) > D (German) > any
                drat_df['_lang_prio'] = drat_df['langu'].map({'E': 0, 'D': 1}).fillna(2).astype(int)
                drat_df = drat_df.sort_values('_lang_prio')
                drat_final = drat_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')[['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt']].copy()
                descriptions_found = int(drat_final['dktxt'].notna().sum())
            else:
                drat_final = pd.DataFrame(columns=['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt'])
            
            # Clean up temp escaped columns (no longer needed)
            df = df.drop(['doknr_escaped', 'dokar_escaped'], axis=1, errors='ignore')
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'drat', 'percent': 55, 'message': f'Found {descriptions_found} descriptions from DRAT'})}\n\n"
            
            # ========== PHASE 4: Apply Rules ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'rules', 'message': 'Phase 4/4: Applying migration rules...'})}\n\n"
            
            from app.prepare import apply_translations as _apply_translations
            rules = load_translations()
            rules_applied = len(rules)
            
            # Get full records for rule application
            with misc_engine.begin() as con:
                full_df = pd.read_sql(text("""
                    SELECT id, source_documenttype, source_documentnumber, source_documentversion,
                           source_documentpart, source_description, authorization_group,
                           source_dokob, source_objky, filename,
                           target_documenttype, target_documentnumber, target_documentversion,
                           target_documentpart, target_dokob, target_objky,
                           source_document_status, target_document_status, execution_status
                    FROM dbo.migration_staging
                    WHERE batch_id = :batch_id
                """), con, params={'batch_id': batch_id})
            
            # Reset target_documenttype from source before applying rules
            # BUT only for records that are NOT already successful (preserve successful migrations)
            not_successful = (full_df['execution_status'] != 'success') | full_df['execution_status'].isna()
            full_df.loc[not_successful, 'target_documenttype'] = full_df.loc[not_successful, 'source_documenttype']
            print(f"[REFRESH] Reset target_documenttype for {not_successful.sum()} non-successful records")
            
            # Add alias columns so rules referencing short names work
            # against staging column names (e.g. 'documenttype' -> 'source_documenttype')
            _ALIASES = {
                'documenttype': 'source_documenttype',
                'documentnumber': 'source_documentnumber',
                'documentversion': 'source_documentversion',
                'documentpart': 'source_documentpart',
                'description': 'source_description',
            }
            for alias, real_col in _ALIASES.items():
                if alias not in full_df.columns and real_col in full_df.columns:
                    full_df[alias] = full_df[real_col]
            
            # Apply rules ONLY to non-successful records (preserve successful migrations)
            # Filter to non-successful, apply rules, then merge back
            not_successful_mask = (full_df['execution_status'] != 'success') | full_df['execution_status'].isna()
            if not_successful_mask.any():
                non_success_df = full_df.loc[not_successful_mask].copy()
                non_success_df = _apply_translations(non_success_df, rules)
                # Update only the non-successful rows in full_df
                for col in non_success_df.columns:
                    if col in full_df.columns:
                        full_df.loc[not_successful_mask, col] = non_success_df[col].to_numpy()
                print(f"[REFRESH] Applied rules to {not_successful_mask.sum()} non-successful records")
            
            # Recompute target_documentnumber based on VALUE (numeric vs alphanumeric)
            # NOT based on document type!
            # - Numeric value (e.g. "123456") → Internal numbering (SAP generates) → target = None
            # - Alphanumeric value (e.g. "ABLAGEORT") → External numbering → target = value
            # - Translation rule applied → Has priority, preserve the translated value
            from app.process import sanitize_doknr as _sanitize_doknr
            
            if 'target_documentnumber_sanitized' not in full_df.columns:
                full_df['target_documentnumber_sanitized'] = None
            
            # Apply sanitize_doknr vectorized via .apply (function has branching logic, not purely vectorizable)
            # ONLY for non-successful records - successful records keep their existing values untouched
            def _compute_doknr_row(row):
                current_tgt_nr = row.get('target_documentnumber')
                source_nr = str(row.get('source_documentnumber') or '').strip()
                
                current_tgt_str = str(current_tgt_nr).strip() if pd.notna(current_tgt_nr) else ''
                
                # PRIORITY 1: If translation rules already changed target_documentnumber (different from source),
                # preserve that translated value - rules have highest priority
                if current_tgt_str and current_tgt_str != source_nr:
                    # Translation was applied - preserve it
                    sanitized, _ = _sanitize_doknr(current_tgt_str)
                    if sanitized and sanitized.strip():
                        return sanitized, sanitized
                    return current_tgt_str[:25], current_tgt_str[:25]
                
                # PRIORITY 2: Determine based on VALUE (not document type)
                # - Numeric source → Internal numbering (SAP generates number)
                # - Alphanumeric source → External numbering (keep the value)
                if source_nr:
                    if source_nr.isdigit():
                        # Numeric → Internal numbering → SAP generates, we pass None
                        return None, None
                    else:
                        # Alphanumeric → External numbering → Use source value
                        tgt_nr = source_nr[:25]
                        sanitized, _ = _sanitize_doknr(tgt_nr)
                        if sanitized and sanitized.strip():
                            return sanitized, sanitized
                        return tgt_nr, tgt_nr
                
                return None, None
            
            # CRITICAL: Apply ONLY to non-successful records to preserve successful migrations' target fields
            non_success_mask = (full_df['execution_status'] != 'success') | full_df['execution_status'].isna()
            if non_success_mask.any():
                non_success_subset = full_df.loc[non_success_mask].copy()
                doknr_results = non_success_subset.apply(_compute_doknr_row, axis=1, result_type='expand')
                full_df.loc[non_success_mask, 'target_documentnumber'] = doknr_results[0].to_numpy()
                full_df.loc[non_success_mask, 'target_documentnumber_sanitized'] = doknr_results[1].to_numpy()
                print(f"[REFRESH] Computed target_documentnumber for {non_success_mask.sum()} non-successful records, preserved {(~non_success_mask).sum()} successful records")
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'rules', 'percent': 60, 'message': f'Applied {rules_applied} rules'})}\n\n"
            
            # ========== MERGE AND UPDATE ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'update', 'message': 'Merging data and updating database...'})}\n\n"
            
            # Merge LOIO data with file sizes
            if len(loio_df) > 0 and len(size_df) > 0:
                loio_df = loio_df.merge(
                    size_df[['loio_id', 'file_size', 'file_name']],
                    how='left',
                    left_on='lo_objid',
                    right_on='loio_id'
                )
            elif len(loio_df) > 0:
                loio_df['file_size'] = None
                loio_df['file_name'] = None
            
            # Remove duplicates
            if len(loio_df) > 0:
                loio_df = loio_df.sort_values('file_size', ascending=False, na_position='last')
                loio_df = loio_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')
            
            # Prepare merge with staging IDs
            df_merged = df.copy()
            if len(loio_df) > 0:
                df_merged = df.merge(
                    loio_df,
                    how='left',
                    left_on=['source_documentnumber', 'source_documenttype', 'dokvr_padded', 'doktl_padded'],
                    right_on=['doknr', 'dokar', 'dokvr', 'doktl']
                )
                df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            
            # Merge filenames from DRAW
            if len(filename_df) > 0:
                df_merged['_doknr'] = df_merged['source_documentnumber'].astype(str)
                df_merged['_dokar'] = df_merged['source_documenttype'].astype(str)
                df_merged['_dokvr'] = df_merged['source_documentversion'].astype(str).str.zfill(2)
                df_merged['_doktl'] = df_merged['source_documentpart'].astype(str).str.zfill(3)
                
                df_merged = df_merged.merge(
                    filename_df[['doknr', 'dokar', 'dokvr', 'doktl', 'filep', 'dokst', 'begru', 'dwnam']],
                    how='left',
                    left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
                    right_on=['doknr', 'dokar', 'dokvr', 'doktl'],
                    suffixes=('', '_draw')
                )
                df_merged = df_merged.drop(columns=['_doknr', '_dokar', '_dokvr', '_doktl',
                                        'doknr_draw', 'dokar_draw', 'dokvr_draw', 'doktl_draw'],
                               errors='ignore')
                df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            
            # Merge descriptions from DRAT
            if len(drat_final) > 0:
                df_merged['_doknr'] = df_merged['source_documentnumber'].astype(str)
                df_merged['_dokar'] = df_merged['source_documenttype'].astype(str)
                df_merged['_dokvr'] = df_merged['source_documentversion'].astype(str).str.zfill(2)
                df_merged['_doktl'] = df_merged['source_documentpart'].astype(str).str.zfill(3)
                
                df_merged = df_merged.merge(
                    drat_final[['doknr', 'dokar', 'dokvr', 'doktl', 'dktxt']],
                    how='left',
                    left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
                    right_on=['doknr', 'dokar', 'dokvr', 'doktl'],
                    suffixes=('', '_drat')
                )
                df_merged = df_merged.drop(columns=['_doknr', '_dokar', '_dokvr', '_doktl',
                                        'doknr_drat', 'dokar_drat', 'dokvr_drat', 'doktl_drat'],
                               errors='ignore')
                df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 70, 'message': 'Preparing bulk update...'})}\n\n"
            
            # Prepare update data
            update_data = []
            for _, row in df_merged.iterrows():
                staging_id = int(row['id'])
                source_loioid = str(row.get('lo_objid', '')) if pd.notna(row.get('lo_objid')) else None
                file_size_bytes = int(row.get('file_size')) if pd.notna(row.get('file_size')) else None
                
                # Filename: prefer DRAW.filep if available
                draw_filename = str(row.get('filep', '')) if pd.notna(row.get('filep')) else None
                dil_filename = str(row.get('file_name', '')) if pd.notna(row.get('file_name')) else None
                filename = draw_filename or dil_filename
                
                # Document status from DRAW.DOKST
                dokst = str(row.get('dokst', '')) if pd.notna(row.get('dokst')) else None
                
                # Source authorization group (BEGRU) from DRAW
                begru = str(row.get('begru', '')) if pd.notna(row.get('begru')) else None
                if begru:
                    begru = begru.strip()[:20] or None
                
                # Source user (DWNAM) from DRAW
                dwnam = str(row.get('dwnam', '')) if pd.notna(row.get('dwnam')) else None
                if dwnam:
                    dwnam = dwnam.strip()[:12] or None
                
                # Description from DRAT.DKTXT
                drat_desc = str(row.get('dktxt', '')) if pd.notna(row.get('dktxt')) else None
                if drat_desc and drat_desc.strip():
                    drat_desc = drat_desc.strip()[:200]
                else:
                    drat_desc = None
                
                update_data.append({
                    'staging_id': staging_id,
                    'source_loioid': source_loioid,
                    'file_size_bytes': file_size_bytes,
                    'filename': filename,
                    'source_document_status': dokst if dokst else None,
                    'source_description': drat_desc,
                    'source_authorization_group': begru,
                    'pers_resp_source': dwnam
                })
            
            # Also get rule updates - ONLY for non-successful records (preserve successful migrations)
            rule_updates = {}
            for _, row in full_df.iterrows():
                # Skip successful records - don't override their target fields
                if row.get('execution_status') == 'success':
                    continue
                rule_updates[int(row['id'])] = {
                    'target_documenttype': row.get('target_documenttype'),
                    'target_documentnumber': row.get('target_documentnumber'),
                    'target_documentnumber_sanitized': row.get('target_documentnumber_sanitized'),
                    'target_documentversion': row.get('target_documentversion'),
                    'target_documentpart': row.get('target_documentpart'),
                    'authorization_group': row.get('authorization_group'),
                    'target_dokob': row.get('target_dokob'),
                    'target_objky': row.get('target_objky'),
                    'target_document_status': row.get('target_document_status')
                }
            
            print(f"[REFRESH] Rule updates prepared for {len(rule_updates)} non-successful records")
            
            # Bulk update using temp table
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 75, 'message': 'Bulk updating via temp table...'})}\n\n"
            
            updated_count = 0
            with misc_engine.begin() as con:
                # Create temp table for metadata
                con.execute(text("""
                    IF OBJECT_ID('tempdb..#refresh_update') IS NOT NULL DROP TABLE #refresh_update;
                    CREATE TABLE #refresh_update (
                        staging_id INT PRIMARY KEY,
                        source_loioid NVARCHAR(100),
                        file_size_bytes BIGINT,
                        filename NVARCHAR(500),
                        source_document_status NVARCHAR(20),
                        source_description NVARCHAR(200),
                        source_authorization_group NVARCHAR(20),
                        pers_resp_source NVARCHAR(12)
                    );
                """))
                
                # Insert metadata updates
                update_df = pd.DataFrame(update_data)
                update_df = update_df[update_df['source_loioid'].notna() | update_df['filename'].notna() | update_df['source_document_status'].notna() | update_df['source_description'].notna() | update_df['source_authorization_group'].notna() | update_df['pers_resp_source'].notna()]
                
                if len(update_df) > 0:
                    chunk_size = 900
                    for i in range(0, len(update_df), chunk_size):
                        chunk = update_df.iloc[i:i + chunk_size]
                        chunk.to_sql('#refresh_update', con, if_exists='append', index=False, method='multi')
                        
                        if i % 5000 == 0:
                            pct = 75 + int((i / len(update_df)) * 10)  # 75-85%
                            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': pct, 'message': f'Temp table: {i}/{len(update_df)}'})}\n\n"
                    
                    # Update metadata
                    result = con.execute(text("""
                        UPDATE s
                        SET s.source_loioid = COALESCE(t.source_loioid, s.source_loioid),
                            s.file_size_bytes = COALESCE(t.file_size_bytes, s.file_size_bytes),
                            s.filename = CASE WHEN t.filename IS NOT NULL AND t.filename != 'None' AND t.filename != '' 
                                              THEN t.filename ELSE s.filename END,
                            s.source_document_status = COALESCE(t.source_document_status, s.source_document_status),
                            s.source_description = CASE WHEN t.source_description IS NOT NULL AND t.source_description != ''
                                                        AND (s.source_description IS NULL OR s.source_description = '')
                                                        THEN t.source_description ELSE s.source_description END,
                            s.source_authorization_group = COALESCE(t.source_authorization_group, s.source_authorization_group),
                            s.pers_resp_source = COALESCE(t.pers_resp_source, s.pers_resp_source)
                        FROM dbo.migration_staging s
                        INNER JOIN #refresh_update t ON s.id = t.staging_id
                    """))
                    updated_count = result.rowcount
                
                con.execute(text("DROP TABLE #refresh_update"))
                
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 85, 'message': f'Updated {updated_count} metadata records'})}\n\n"
                
                # Update rule results via BULK temp table (not row-by-row!)
                # Only if there are non-successful records to update
                if len(rule_updates) > 0:
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 86, 'message': f'Bulk updating {len(rule_updates)} rule results...'})}\n\n"
                    
                    con.execute(text("""
                        IF OBJECT_ID('tempdb..#rules_update') IS NOT NULL DROP TABLE #rules_update;
                        CREATE TABLE #rules_update (
                            staging_id INT PRIMARY KEY,
                            target_documenttype NVARCHAR(10),
                            target_documentnumber NVARCHAR(50),
                            target_documentnumber_sanitized NVARCHAR(50),
                            target_documentversion NVARCHAR(10),
                            target_documentpart NVARCHAR(10),
                            authorization_group NVARCHAR(10),
                            target_dokob NVARCHAR(20),
                            target_objky NVARCHAR(100),
                            target_document_status NVARCHAR(10)
                        );
                    """))
                    
                    # Build DataFrame from rule_updates dict
                    rules_rows = []
                    for staging_id, vals in rule_updates.items():
                        rules_rows.append({
                            'staging_id': staging_id,
                            'target_documenttype': vals.get('target_documenttype'),
                            'target_documentnumber': vals.get('target_documentnumber'),
                            'target_documentnumber_sanitized': vals.get('target_documentnumber_sanitized'),
                            'target_documentversion': vals.get('target_documentversion'),
                            'target_documentpart': vals.get('target_documentpart'),
                            'authorization_group': vals.get('authorization_group'),
                            'target_dokob': vals.get('target_dokob'),
                            'target_objky': vals.get('target_objky'),
                            'target_document_status': vals.get('target_document_status')
                        })
                    
                    rules_df = pd.DataFrame(rules_rows)
                    # Replace NaN with None for SQL compatibility
                    rules_df = rules_df.where(pd.notnull(rules_df), None)
                    
                    # Bulk insert into temp table
                    rules_chunk_size = 900
                    for i in range(0, len(rules_df), rules_chunk_size):
                        chunk = rules_df.iloc[i:i + rules_chunk_size]
                        chunk.to_sql('#rules_update', con, if_exists='append', index=False, method='multi')
                        
                        if i % 5000 == 0 and i > 0:
                            pct = 86 + int((i / len(rules_df)) * 4)  # 86-90%
                            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': pct, 'message': f'Rules temp table: {i}/{len(rules_df)}'})}\n\n"
                    
                    # Single UPDATE JOIN — replaces 100k individual UPDATEs!
                    con.execute(text("""
                        UPDATE s
                        SET s.target_documenttype = t.target_documenttype,
                            s.target_documentnumber = t.target_documentnumber,
                            s.target_documentnumber_sanitized = t.target_documentnumber_sanitized,
                            s.target_documentversion = t.target_documentversion,
                            s.target_documentpart = t.target_documentpart,
                            s.authorization_group = t.authorization_group,
                            s.target_dokob = t.target_dokob,
                            s.target_objky = t.target_objky,
                            s.target_document_status = t.target_document_status
                        FROM dbo.migration_staging s
                        INNER JOIN #rules_update t ON s.id = t.staging_id
                    """))
                    
                    con.execute(text("DROP TABLE #rules_update"))
                    
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 90, 'message': 'Rule updates complete'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 90, 'message': 'Skipped rule updates (all records already successful)'})}\n\n"
            
            # ========== PHASE 4b: Non-Latin Character Validation ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'validate', 'message': 'Validating character sets (non-Latin detection)...'})}\n\n"
            
            from app.process import validate_non_latin_fields
            
            # Reload current description + filename from staging (after metadata update)
            with misc_engine.begin() as con:
                val_rows = con.execute(text("""
                    SELECT id, source_description, filename
                    FROM dbo.migration_staging
                    WHERE batch_id = :bid AND skip_migration = 0
                """), {'bid': batch_id}).fetchall()
            
            validation_updates = []
            non_latin_count = 0
            for vrow in val_rows:
                vid, vdesc, vfn = vrow[0], vrow[1], vrow[2]
                warnings = validate_non_latin_fields(vdesc, vfn)
                if warnings:
                    non_latin_count += 1
                    note_text = ' | '.join(warnings)
                    validation_updates.append({'staging_id': vid, 'validation_notes': note_text})
                else:
                    # Clear any previous warnings (re-validation)
                    validation_updates.append({'staging_id': vid, 'validation_notes': None})
            
            if validation_updates:
                with misc_engine.begin() as con:
                    con.execute(text("""
                        IF OBJECT_ID('tempdb..#val_update') IS NOT NULL DROP TABLE #val_update;
                        CREATE TABLE #val_update (
                            staging_id INT PRIMARY KEY,
                            validation_notes NVARCHAR(MAX)
                        );
                    """))
                    val_df = pd.DataFrame(validation_updates)
                    for i in range(0, len(val_df), 900):
                        chunk = val_df.iloc[i:i + 900]
                        chunk.to_sql('#val_update', con, if_exists='append', index=False, method='multi')
                    con.execute(text("""
                        UPDATE s
                        SET s.validation_notes = t.validation_notes
                        FROM dbo.migration_staging s
                        INNER JOIN #val_update t ON s.id = t.staging_id
                    """))
                    con.execute(text("DROP TABLE #val_update"))
            
            if non_latin_count > 0:
                print(f"[REFRESH] Non-Latin character warnings: {non_latin_count} records")
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'validate', 'percent': 91, 'message': f'Validation: {non_latin_count} records with non-Latin characters'})}\n\n"
            
            # ========== PHASE 4c: Local Link Detection (DAPPL=HTM without file content) ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'validate_local', 'message': 'Detecting local links (DAPPL check)...'})}\n\n"
            
            local_link_count = 0
            try:
                # Find candidates: records with no filename or no file_size (potential local links)
                with misc_engine.begin() as con:
                    candidates = con.execute(text("""
                        SELECT id, source_documentnumber, source_documenttype,
                               source_documentversion, source_documentpart,
                               filename, file_size_bytes, source_loioid
                        FROM dbo.migration_staging
                        WHERE batch_id = :bid AND skip_migration = 0
                          AND (filename IS NULL OR file_size_bytes IS NULL)
                    """), {'bid': batch_id}).fetchall()
                
                if candidates:
                    # Build bulk query for DMS_DOC_FILES DAPPL lookup
                    conditions = []
                    for c in candidates:
                        doknr = str(c[1] or '').strip()
                        dokar = str(c[2] or '').strip()
                        dokvr = str(c[3] or '').zfill(2)
                        doktl = str(c[4] or '').zfill(3)
                        doknr_e = doknr.replace("'", "''")
                        dokar_e = dokar.replace("'", "''")
                        conditions.append(
                            f"(DOKNR='{doknr_e}' AND DOKAR='{dokar_e}' AND DOKVR='{dokvr}' AND DOKTL='{doktl}')"
                        )
                    
                    # Query DIL.DMS_DOC_FILES for DAPPL in chunks
                    dappl_results = {}  # (doknr, dokar, dokvr, doktl) -> DAPPL
                    chunk_sz = 200
                    for ci in range(0, len(conditions), chunk_sz):
                        chunk = conditions[ci:ci + chunk_sz]
                        where_clause = " OR ".join(chunk)
                        dappl_query = f"""
                            SELECT DOKNR, DOKAR, DOKVR, DOKTL, DAPPL
                            FROM DIL.DMS_DOC_FILES
                            WHERE ({where_clause})
                        """
                        with dil_engine.begin() as con:
                            dappl_rows = con.execute(text(dappl_query)).fetchall()
                        for dr in dappl_rows:
                            dk = (str(dr[0]).strip(), str(dr[1]).strip(),
                                  str(dr[2]).strip(), str(dr[3]).strip())
                            dappl_results[dk] = str(dr[4] or '').strip().upper()
                    
                    # Detect local links: DAPPL='HTM' with no file content
                    local_link_updates = []
                    for c in candidates:
                        sid = c[0]
                        doknr = str(c[1] or '').strip()
                        dokar = str(c[2] or '').strip()
                        dokvr = str(c[3] or '').zfill(2)
                        doktl = str(c[4] or '').zfill(3)
                        fn = c[5]      # filename
                        fsz = c[6]     # file_size_bytes
                        key = (doknr, dokar, dokvr, doktl)
                        dappl = dappl_results.get(key, '')
                        
                        if dappl == 'HTM' and ((fn is None or fn == '') or (fsz is None or fsz == 0)):
                            local_link_count += 1
                            warning = f"Lokaler Link vermutet (DAPPL=HTM, keine Datei im Content Repository)"
                            local_link_updates.append({'staging_id': sid, 'note': warning})
                    
                    # Append warnings to validation_notes (don't overwrite non-Latin warnings)
                    if local_link_updates:
                        with misc_engine.begin() as con:
                            for upd in local_link_updates:
                                con.execute(text("""
                                    UPDATE dbo.migration_staging
                                    SET validation_notes = CASE
                                        WHEN validation_notes IS NULL THEN :note
                                        WHEN validation_notes LIKE '%Lokaler Link%' THEN validation_notes
                                        ELSE validation_notes + ' | ' + :note
                                    END
                                    WHERE id = :sid
                                """), {'note': upd['note'], 'sid': upd['staging_id']})
                
                if local_link_count > 0:
                    print(f"[REFRESH] Local link warnings (DAPPL=HTM): {local_link_count} records")
            except Exception as e:
                print(f"[REFRESH] Local link detection failed: {e}")
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'validate_local', 'percent': 92, 'message': f'Validation: {local_link_count} lokale Links erkannt (DAPPL=HTM)'})}\n\n"
            
            # ========== PHASE 5: Object-Link Counts ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'link_counts', 'message': 'Phase 5/5: Calculating object link counts...'})}\n\n"
            
            import json as _json
            
            # Load batch DOKOB filter (if any)
            batch_dokob_filter = None
            with misc_engine.begin() as con:
                bf_row = con.execute(text(
                    "SELECT dokob_filter FROM dbo.migration_batch WHERE batch_id = :bid"
                ), {'bid': batch_id}).fetchone()
            if bf_row and bf_row[0]:
                batch_dokob_filter = set(d.strip().upper() for d in bf_row[0].split(',') if d.strip())
            
            # Load staging records with their object links
            with misc_engine.begin() as con:
                link_rows = con.execute(text("""
                    SELECT id, source_object_links, source_dokob, source_objky
                    FROM dbo.migration_staging
                    WHERE batch_id = :batch_id AND skip_migration = 0
                """), {'batch_id': batch_id}).fetchall()
            
            link_updates = []  # list of {staging_id, src, excl, tgt}
            for row in link_rows:
                rec_id = row[0]
                links_json = row[1]
                primary_dokob = row[2]
                primary_objky = row[3]
                
                # Parse links
                links = []
                if links_json:
                    try:
                        links = _json.loads(links_json)
                    except (ValueError, TypeError):
                        pass
                if not links and primary_dokob and primary_objky:
                    links = [{'dokob': primary_dokob, 'objky': primary_objky}]
                
                # Apply DOKOB filter
                if batch_dokob_filter and links:
                    kept = [lk for lk in links if str(lk.get('dokob', '')).strip().upper() in batch_dokob_filter]
                    excluded_count = len(links) - len(kept)
                    src_count = len(kept)
                else:
                    excluded_count = 0
                    src_count = len(links)
                
                link_updates.append({
                    'staging_id': rec_id,
                    'source_link_count': src_count,
                    'excluded_link_count': excluded_count,
                })
            
            # Bulk update via temp table
            if link_updates:
                link_df = pd.DataFrame(link_updates)
                with misc_engine.begin() as con:
                    con.execute(text("""
                        IF OBJECT_ID('tempdb..#link_counts') IS NOT NULL DROP TABLE #link_counts;
                        CREATE TABLE #link_counts (
                            staging_id INT PRIMARY KEY,
                            source_link_count INT,
                            excluded_link_count INT
                        );
                    """))
                    
                    for i in range(0, len(link_df), 900):
                        chunk = link_df.iloc[i:i + 900]
                        chunk.to_sql('#link_counts', con, if_exists='append', index=False, method='multi')
                    
                    con.execute(text("""
                        UPDATE s
                        SET s.source_link_count = t.source_link_count,
                            s.excluded_link_count = t.excluded_link_count
                        FROM dbo.migration_staging s
                        INNER JOIN #link_counts t ON s.id = t.staging_id
                    """))
                    con.execute(text("DROP TABLE #link_counts"))
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'link_counts', 'percent': 95, 'message': f'Link counts updated: {len(link_updates)} records'})}\n\n"
            
            # Calculate statistics
            total_bytes = size_df['file_size'].dropna().sum() if len(size_df) > 0 else 0
            max_bytes = size_df['file_size'].dropna().max() if len(size_df) > 0 else 0
            links_excluded_total = sum(lu['excluded_link_count'] for lu in link_updates)
            records_zero_links = sum(1 for lu in link_updates if lu['source_link_count'] == 0)
            
            # Convert numpy types to native Python types for JSON serialization
            yield f"data: {json.dumps({'type': 'complete', 'message': 'Refresh complete', 'metadata_updated': int(updated_count), 'rules_applied': int(rules_applied), 'filenames_found': int(filenames_found), 'descriptions_found': int(descriptions_found), 'total_records': int(total_records), 'total_size_mb': round(float(total_bytes) / (1024 * 1024), 1) if total_bytes else 0, 'max_file_mb': round(float(max_bytes) / (1024 * 1024), 1) if max_bytes else 0, 'links_excluded': int(links_excluded_total), 'records_zero_links': int(records_zero_links), 'non_latin_warnings': int(non_latin_count), 'local_link_warnings': int(local_link_count)})}\n\n"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


