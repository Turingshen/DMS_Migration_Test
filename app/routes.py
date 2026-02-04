"""
Flask routes for document migration workflow.
Implements two-step migration: prepare -> validate -> execute
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, Response
import pandas as pd
import os
import json
from werkzeug.utils import secure_filename
from sqlalchemy import text

from app.prepare import prepare_migration
from app.execute import execute_migration, request_cancel, is_cancel_requested, is_migration_running
from app.process import read_sap_system, write_sap_system
from app_config import Config, MiscEngine
from app.db_schema import init_staging_tables

cfg = Config.load()
migrate_bp = Blueprint('app', __name__)

misc_db = MiscEngine.load()
misc_engine = misc_db.engine

UPLOAD_FOLDER = 'userdata/migration_uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def df_to_json_safe(df):
    """Convert DataFrame to JSON-safe list of dicts, handling NaN/NaT properly.
    
    Standard pd.to_dict('records') can leave NaN values that break JSON serialization.
    This function ensures all NaN/NaT/None values are converted to Python None.
    """
    import math
    
    def safe_value(val):
        """Convert a value to JSON-safe format."""
        if val is None:
            return None
        if pd.isna(val):
            return None
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return val
    
    records = df.to_dict('records')
    return [{k: safe_value(v) for k, v in record.items()} for record in records]


def get_template_context():
    """Get common template context variables."""
    # Ensure sap_system is set (use default if not present)
    if 'sap_system' not in session:
        # Try to get first available SAP system as default
        sap_systems = cfg.get('sap_systems') or {}
        if sap_systems:
            session['sap_system'] = next(iter(sap_systems.keys()))
        else:
            session['sap_system'] = 'zbq'  # fallback default
    
    return {
        'sap_system': session.get('sap_system', 'zbq'),
        'sap_systems': cfg.get('sap_systems') or {},
        'au_name': session.get('fullName', 'User'),
        'site': session.get('site', 'Unknown'),
        'source_system': read_sap_system,
        'source_system_label': cfg.get(read_sap_system, 'system_label') if read_sap_system else 'Unknown',
        'target_system': write_sap_system,
        'target_system_label': cfg.get(write_sap_system, 'system_label') if write_sap_system else 'Unknown',
        'max_workers': session.get('max_workers', DEFAULT_SETTINGS.get('max_workers', 2)),
        'pacing_seconds': session.get('pacing_seconds', DEFAULT_SETTINGS.get('pacing_seconds', 0))
    }


@migrate_bp.route('/test-api-structure')
def test_api_structure_route():
    """Test route to inspect R/3 API response structure for description fields."""
    from app.process import prepare_session_headers
    from authentication import check
    import requests as req_lib
    
    # Check if authenticated
    if 'bearer_token' not in session:
        return jsonify({'error': 'Not authenticated. Please login first.'}), 401
    
    server_session = req_lib.Session()
    prepare_session_headers(server_session, session, read_sap_system)
    
    # Make test request - accept query params for custom document lookup
    base_url = cfg.get(read_sap_system, "api_list", "document", "base_url")
    test_params = {
        "Documentnumber": request.args.get('doknr', "0000000000000010002159971"),
        "Documentpart": request.args.get('part', "000"),
        "Documenttype": request.args.get('type', "IY1"),
        "Documentversion": request.args.get('version', "00")
    }
    formatted_args = ",".join(f"{key}='{value}'" for key, value in test_params.items())
    request_url = f"{base_url}/DocumentSet({formatted_args})?$expand=DocumentfilesSet"
    
    response = server_session.get(request_url)
    
    result = {
        "request_url": request_url,
        "status": response.status_code,
        "reason": response.reason,
        "top_level_keys": [],
        "description_fields_found": {},
        "attachment_sample_keys": [],
        "raw_response_sample": None
    }
    
    if response.status_code == 200:
        data = response.json()
        if 'd' in data:
            d = data['d']
            result["top_level_keys"] = [k for k in d.keys() if k != '__metadata']
            
            # Look for description fields
            desc_candidates = ['DocumentDescription', 'Description', 'DocDescription', 
                              'DOCUMENTDESCRIPTION', 'Dktxt', 'DKTXT', 'Longtext',
                              'DocumentdescSet', 'to_DocumentDescription', 'to_DocDesc']
            for key in desc_candidates:
                if key in d and d[key]:
                    val = d[key]
                    if isinstance(val, dict) and 'results' in val:
                        result["description_fields_found"][key] = val['results']
                    else:
                        result["description_fields_found"][key] = val
            
            # Get attachment structure
            if 'DocumentfilesSet' in d and 'results' in d['DocumentfilesSet']:
                results = d['DocumentfilesSet']['results']
                if results:
                    first_item = {k: v for k, v in results[0].items() if k != '__metadata'}
                    result["attachment_sample_keys"] = list(first_item.keys())
                    result["attachment_sample"] = first_item
            
            # Include raw 'd' without large nested arrays for inspection
            result["raw_d_summary"] = {k: (type(v).__name__ if isinstance(v, dict) else repr(v)[:100]) 
                                        for k, v in d.items() if k != '__metadata'}
    else:
        result["error_response"] = response.text[:500]
    
    # Try to get description from DIL database (DRAT table)
    try:
        from app_config import DilEngine
        dil_db = DilEngine.load()
        dil_engine = dil_db.engine
        
        # Query matching the example document
        dil_query = """
            SELECT TOP 10
                drad.doknr as documentnumber,
                drad.dokob,
                drad.objky,
                drad.dokar as documenttype,
                drad.dokvr as documentversion,
                drad.doktl as documentpart,
                drad.longtext_id,
                iflos.strno
            FROM dil.drad AS drad
            LEFT JOIN dil.iflos AS iflos ON drad.objky = iflos.strno
            WHERE drad.doknr = '0000000000000010002229751'
                AND drad.dokar = 'IY2'
                AND drad.dokvr = '00'
                AND drad.doktl = '000'
        """
        import pandas as pd
        with dil_engine.begin() as con:
            df = pd.read_sql(dil_query, con)
        
        if len(df) > 0:
            result["dil_description"] = df.to_dict(orient='records')
        else:
            result["dil_description"] = "No records found in DIL"
            
    except Exception as e:
        result["dil_error"] = str(e)
    
    return jsonify(result)


# Default settings - can be overridden via /settings
# pacing_seconds=0 means dynamic pacing based on file size (5-45s)
DEFAULT_SETTINGS = {
    'max_workers': 2,
    'pacing_seconds': 0  # 0 = dynamic pacing (recommended)
}


@migrate_bp.route('/settings/json', methods=['GET'])
def settings_json():
    """Return current settings as JSON."""
    current_settings = {
        'max_workers': session.get('max_workers', DEFAULT_SETTINGS['max_workers']),
        'pacing_seconds': session.get('pacing_seconds', DEFAULT_SETTINGS['pacing_seconds'])
    }
    return jsonify(current_settings)


@migrate_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page for migration configuration."""
    if request.method == 'GET':
        # Get current settings from session or defaults
        current_settings = {
            'max_workers': session.get('max_workers', DEFAULT_SETTINGS['max_workers']),
            'pacing_seconds': session.get('pacing_seconds', DEFAULT_SETTINGS['pacing_seconds'])
        }
        return render_template('settings.html', settings=current_settings, **get_template_context())
    
    # POST - save settings
    try:
        data = request.get_json()
        max_workers = int(data.get('max_workers', DEFAULT_SETTINGS['max_workers']))
        pacing_seconds = float(data.get('pacing_seconds', DEFAULT_SETTINGS['pacing_seconds']))
        
        # Validate
        if max_workers < 1 or max_workers > 50:
            return jsonify({'success': False, 'error': 'Max Workers must be between 1 and 50'}), 400
        if pacing_seconds < 0 or pacing_seconds > 60:
            return jsonify({'success': False, 'error': 'Pacing must be between 0 and 60 seconds'}), 400
        
        # Save to session
        session['max_workers'] = max_workers
        session['pacing_seconds'] = pacing_seconds
        
        return jsonify({'success': True, 'max_workers': max_workers, 'pacing_seconds': pacing_seconds})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/pacing_stats', methods=['GET'])
def pacing_stats():
    """Get historical pacing statistics for optimization."""
    try:
        from app.execute import get_historical_pacing_stats
        stats = get_historical_pacing_stats()
        # Return stats directly for frontend consumption
        return jsonify(stats)
    except Exception as e:
        return jsonify({'has_data': False, 'error': str(e)}), 500


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
                COALESCE(s.total_count, b.total_records) as total_records,
                b.approved_records,
                COALESCE(s.executed_count, b.executed_records) as executed_records,
                COALESCE(s.success_count, b.successful_records) as successful_records,
                COALESCE(s.failed_count, b.failed_records) as failed_records,
                b.status
            FROM dbo.migration_batch b
            LEFT JOIN (
                SELECT 
                    batch_id,
                    COUNT(*) as total_count,
                    SUM(CASE WHEN execution_status IN ('success', 'failed', 'partial') THEN 1 ELSE 0 END) as executed_count,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count
                FROM dbo.migration_staging
                GROUP BY batch_id
            ) s ON b.batch_id = s.batch_id
            ORDER BY b.created_at DESC
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        # Replace NaN/NaT with None for JSON serialization
        df = df.where(pd.notnull(df), None)
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
                notes
            FROM dbo.migration_batch
            WHERE batch_id = :batch_id
        """
        
        with misc_engine.begin() as con:
            result = con.execute(text(query), {'batch_id': batch_id}).fetchone()
        
        if not result:
            return jsonify({'success': False, 'error': 'Batch not found'}), 404
        
        # Parse notes as JSON for statistics
        import json
        statistics = {}
        if result.notes:
            try:
                statistics = json.loads(result.notes)
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
    """Download the Excel template for migration data upload."""
    import os
    from flask import send_file
    
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migration_template.xlsx')
    
    if os.path.exists(template_path):
        return send_file(
            template_path,
            as_attachment=True,
            download_name='migration_template.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        return jsonify({'success': False, 'error': 'Template file not found'}), 404


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
            result = prepare_migration(filepath, wave=wave, description=description, notes=notes)
        else:
            # Prepare migration from database query
            custom_query = request.form.get('custom_query', '').strip()
            query_source = request.form.get('query_source', 'dil')  # 'dil' or 'datastore'
            result = prepare_migration(custom_query=custom_query if custom_query else None, query_source=query_source, wave=wave, description=description, notes=notes)
        
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
        
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_batch
                SET description = :description,
                    notes = :notes,
                    wave = :wave
                WHERE batch_id = :batch_id
            """), {'description': description, 'notes': notes, 'wave': wave, 'batch_id': batch_id})
        
        return jsonify({'success': True, 'message': 'Batch updated successfully'})
        
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
            con.execute(text("""
                DELETE FROM dbo.migration_file_details WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete staging records
            con.execute(text("""
                DELETE FROM dbo.migration_staging WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
            
            # Delete batch
            con.execute(text("""
                DELETE FROM dbo.migration_batch WHERE batch_id = :batch_id
            """), {'batch_id': batch_id})
        
        return jsonify({'success': True, 'message': f'Batch {batch_id} deleted successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/fetch-metadata', methods=['POST'])
def fetch_batch_metadata(batch_id):
    """Fetch file metadata (size, LOIO) for all records in a batch from DIL database.
    This is useful for Excel-based batches where file sizes are not available.
    Uses optimized batch updates instead of row-by-row."""
    try:
        from app_config import DilEngine
        dil_db = DilEngine.load()
        dil_engine = dil_db.engine
        
        # Get records that need metadata
        query = f"""
            SELECT id, source_documentnumber, source_documentpart, source_documenttype, source_documentversion,
                   file_size_bytes, source_loioid
            FROM dbo.migration_staging
            WHERE batch_id = '{batch_id}'
              AND skip_migration = 0
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        if len(df) == 0:
            return jsonify({'success': False, 'error': 'No records found'}), 404
        
        # Count how many already have metadata
        records_with_size = df[df['file_size_bytes'].notna()].shape[0]
        records_without_size = df[df['file_size_bytes'].isna()].shape[0]
        
        if records_without_size == 0:
            return jsonify({
                'success': True,
                'message': 'All records already have file sizes',
                'updated': 0,
                'errors': 0,
                'already_had_metadata': records_with_size,
                'total_processed': 0
            })
        
        # Step 1: Look up LOIO_IDs from DIL.DMS_DOC2LOIO
        print(f"[FETCH-META] Looking up LOIO_IDs for {len(df)} documents...")
        
        # Build conditions for batch lookup - VECTORIZED approach (FAST!)
        # This replaces slow iterrows() loop with pandas string operations
        df['dokvr_padded'] = df['source_documentversion'].astype(str).str.zfill(2)
        df['doktl_padded'] = df['source_documentpart'].astype(str).str.zfill(3)
        df['doknr_escaped'] = df['source_documentnumber'].astype(str).str.replace("'", "''", regex=False)
        df['dokar_escaped'] = df['source_documenttype'].astype(str).str.replace("'", "''", regex=False)
        
        # Build conditions using vectorized string concatenation (100x faster than iterrows!)
        conditions = (
            "(DOKNR='" + df['doknr_escaped'] + 
            "' AND DOKAR='" + df['dokar_escaped'] + 
            "' AND DOKVR='" + df['dokvr_padded'] + 
            "' AND DOKTL='" + df['doktl_padded'] + "')"
        ).tolist()
        
        # Clean up temp columns
        df.drop(['doknr_escaped', 'dokar_escaped'], axis=1, inplace=True, errors='ignore')
        
        # Query LOIO_IDs in chunks
        chunk_size = 200
        all_loios = []
        
        for i in range(0, len(conditions), chunk_size):
            chunk = conditions[i:i + chunk_size]
            where_clause = " OR ".join(chunk)
            loio_query = f"""
                SELECT DOKNR, DOKAR, DOKVR, DOKTL, LO_OBJID
                FROM DIL.DMS_DOC2LOIO
                WHERE MANDT = '100'
                AND ({where_clause})
            """
            with dil_engine.begin() as con:
                chunk_df = pd.read_sql(loio_query, con)
            all_loios.append(chunk_df)
            if i % 1000 == 0:
                print(f"[FETCH-META] LOIO lookup: {i}/{len(conditions)} done")
        
        if not all_loios or all(len(c) == 0 for c in all_loios):
            return jsonify({
                'success': False,
                'error': 'No LOIO_IDs found in DIL database for these documents'
            }), 404
        
        loio_df = pd.concat(all_loios, ignore_index=True)
        loio_df.columns = [c.lower() for c in loio_df.columns]
        print(f"[FETCH-META] Found {len(loio_df)} LOIO_IDs")
        
        # Step 2: Look up file sizes from DIL.DMS_FILE_SIZE
        loio_ids = loio_df['lo_objid'].dropna().unique().tolist()
        
        if not loio_ids:
            return jsonify({
                'success': False,
                'error': 'No LOIO_IDs available for file size lookup'
            }), 404
        
        print(f"[FETCH-META] Looking up file sizes for {len(loio_ids)} LOIOs...")
        
        all_sizes = []
        chunk_size = 500
        
        for i in range(0, len(loio_ids), chunk_size):
            chunk = loio_ids[i:i + chunk_size]
            placeholders = ",".join([f"'{lid}'" for lid in chunk])
            size_query = f"""
                SELECT LOIO_ID, FILE_SIZE, FILE_NAME
                FROM DIL.DMS_FILE_SIZE
                WHERE LOIO_ID IN ({placeholders})
            """
            with dil_engine.begin() as con:
                chunk_df = pd.read_sql(size_query, con)
            all_sizes.append(chunk_df)
            if i % 2000 == 0:
                print(f"[FETCH-META] File size lookup: {i}/{len(loio_ids)} done")
        
        # Check if any file sizes were found
        total_size_records = sum(len(c) for c in all_sizes)
        
        # Step 3: Merge LOIO_IDs with file sizes (even if no sizes found)
        if total_size_records > 0:
            size_df = pd.concat(all_sizes, ignore_index=True)
            size_df.columns = [c.lower() for c in size_df.columns]
            print(f"[FETCH-META] Found {len(size_df)} file sizes (before dedup)")
            
            # Remove duplicates - keep first (largest file size) per LOIO
            size_df = size_df.sort_values('file_size', ascending=False).drop_duplicates(subset=['loio_id'], keep='first')
            print(f"[FETCH-META] After dedup: {len(size_df)} unique file sizes")
            
            loio_df = loio_df.merge(
                size_df[['loio_id', 'file_size', 'file_name']],
                how='left',
                left_on='lo_objid',
                right_on='loio_id'
            )
        else:
            loio_df['file_size'] = None
            loio_df['file_name'] = None
            print(f"[FETCH-META] No file sizes found")
        
        # Remove duplicate LOIO entries per document (keep first with file_size if available)
        print(f"[FETCH-META] LOIO records before dedup: {len(loio_df)}")
        loio_df = loio_df.sort_values('file_size', ascending=False, na_position='last')
        loio_df = loio_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')
        print(f"[FETCH-META] LOIO records after dedup: {len(loio_df)}")
        
        # Step 4: Merge with original df to get staging IDs
        df_merged = df.merge(
            loio_df,
            how='left',
            left_on=['source_documentnumber', 'source_documenttype', 'dokvr_padded', 'doktl_padded'],
            right_on=['doknr', 'dokar', 'dokvr', 'doktl']
        )
        
        # Safety check: df_merged should have same length as df
        if len(df_merged) != len(df):
            print(f"[FETCH-META] WARNING: Merge produced {len(df_merged)} rows from {len(df)} - possible duplicates!")
            # Remove duplicates by staging ID, keep first (with file_size)
            df_merged = df_merged.sort_values('file_size', ascending=False, na_position='last')
            df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            print(f"[FETCH-META] After final dedup: {len(df_merged)} rows")
        
        # Step 5: BULK UPDATE using temp table approach (much faster than row-by-row)
        print(f"[FETCH-META] Preparing bulk update for {len(df_merged)} staging records...")
        
        # Prepare update DataFrame - only rows with LOIO
        update_df = df_merged[df_merged['lo_objid'].notna()][['id', 'lo_objid', 'file_size', 'file_name']].copy()
        update_df.columns = ['staging_id', 'source_loioid', 'file_size_bytes', 'filename']
        update_df['staging_id'] = update_df['staging_id'].astype(int)
        update_df['source_loioid'] = update_df['source_loioid'].astype(str)
        update_df['file_size_bytes'] = pd.to_numeric(update_df['file_size_bytes'], errors='coerce').astype('Int64')
        update_df['filename'] = update_df['filename'].astype(str).replace('nan', None)
        
        print(f"[FETCH-META] Bulk updating {len(update_df)} records via temp table...")
        
        with misc_engine.begin() as con:
            # Create temp table
            con.execute(text("""
                IF OBJECT_ID('tempdb..#metadata_update') IS NOT NULL DROP TABLE #metadata_update;
                CREATE TABLE #metadata_update (
                    staging_id INT PRIMARY KEY,
                    source_loioid NVARCHAR(100),
                    file_size_bytes BIGINT,
                    filename NVARCHAR(500)
                );
            """))
            
            # Bulk insert into temp table in chunks
            chunk_size = 900
            for i in range(0, len(update_df), chunk_size):
                chunk = update_df.iloc[i:i + chunk_size]
                chunk.to_sql('#metadata_update', con, if_exists='append', index=False, method='multi')
                if i % 10000 == 0:
                    print(f"[FETCH-META] Inserted {i}/{len(update_df)} into temp table")
            
            print(f"[FETCH-META] Temp table ready, executing UPDATE JOIN...")
            
            # Single UPDATE with JOIN - much faster than 200k individual updates!
            result = con.execute(text("""
                UPDATE s
                SET s.source_loioid = t.source_loioid,
                    s.file_size_bytes = t.file_size_bytes,
                    s.filename = CASE WHEN t.filename IS NOT NULL AND t.filename != 'None' THEN t.filename ELSE s.filename END
                FROM dbo.migration_staging s
                INNER JOIN #metadata_update t ON s.id = t.staging_id
            """))
            
            updated_count = result.rowcount
            print(f"[FETCH-META] UPDATE JOIN complete: {updated_count} rows affected")
            
            # Drop temp table
            con.execute(text("DROP TABLE #metadata_update"))
        
        error_count = len(df) - len(update_df)
        
        # Calculate statistics
        if total_size_records > 0:
            total_bytes = size_df['file_size'].dropna().sum()
            max_bytes = size_df['file_size'].dropna().max()
        else:
            total_bytes = 0
            max_bytes = 0
        
        print(f"[FETCH-META] Complete: {updated_count} updated, {error_count} not found")
        
        return jsonify({
            'success': True,
            'message': f'Metadata fetched from DIL database',
            'updated': updated_count,
            'errors': error_count,
            'already_had_metadata': records_with_size,
            'total_processed': len(df),
            'total_size_mb': round(total_bytes / (1024 * 1024), 1) if total_bytes else 0,
            'max_file_mb': round(max_bytes / (1024 * 1024), 1) if max_bytes else 0
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/apply-rules', methods=['POST'])
def apply_batch_rules(batch_id):
    """Apply migration rules to all records in a batch.
    This updates target_documenttype, authorization_group, etc. based on configured rules."""
    try:
        from app.prepare import load_translations
        
        # Load all active rules
        rules = load_translations()
        if not rules:
            return jsonify({'success': True, 'updated': 0, 'rules_applied': 0, 'message': 'No active rules found'})
        
        # Get all records for this batch
        with misc_engine.begin() as con:
            records = con.execute(text("""
                SELECT id, source_documenttype, source_documentnumber, source_documentversion, 
                       source_documentpart, source_description, authorization_group,
                       source_dokob, source_objky, filename,
                       target_documenttype, target_documentnumber, target_documentversion,
                       target_documentpart, target_dokob, target_objky
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
            """), {'batch_id': batch_id}).fetchall()
        
        if not records:
            return jsonify({'success': True, 'updated': 0, 'message': 'No records in batch'})
        
        # Convert to DataFrame for rule application
        import pandas as pd
        columns = ['id', 'source_documenttype', 'source_documentnumber', 'source_documentversion',
                   'source_documentpart', 'source_description', 'authorization_group',
                   'source_dokob', 'source_objky', 'filename',
                   'target_documenttype', 'target_documentnumber', 'target_documentversion',
                   'target_documentpart', 'target_dokob', 'target_objky']
        df = pd.DataFrame(records, columns=columns)
        
        # Initialize target columns from source if not set
        if 'target_documenttype' not in df.columns or df['target_documenttype'].isna().all():
            df['target_documenttype'] = df['source_documenttype']
        
        # Apply each rule
        rules_applied = 0
        for rule in rules:
            rtype = (rule.get('rule_type') or 'translation').lower()
            source_col = rule.get('source_column')
            target_col = rule.get('target_column')
            source_val = rule.get('source_value')
            target_val = rule.get('target_value')
            
            if not target_col or target_val is None:
                continue
            
            # Ensure target column exists
            if target_col not in df.columns:
                df[target_col] = None
            
            # Build mask
            if rtype == 'translation' and source_col and source_col in df.columns and source_val:
                mask = df[source_col].astype(str).str.contains(str(source_val), case=False, na=False)
                df.loc[mask, target_col] = target_val
                matched = mask.sum()
                if matched > 0:
                    rules_applied += 1
                    print(f"[RULE] {source_col}={source_val} -> {target_col}={target_val}: {matched} records")
            elif rtype == 'overwrite':
                # Overwrite all records
                df[target_col] = target_val
                rules_applied += 1
                print(f"[RULE] Overwrite {target_col}={target_val}: all records")
        
        # Update database
        updated = 0
        with misc_engine.begin() as con:
            for _, row in df.iterrows():
                con.execute(text("""
                    UPDATE dbo.migration_staging
                    SET target_documenttype = :target_documenttype,
                        target_documentnumber = :target_documentnumber,
                        target_documentversion = :target_documentversion,
                        target_documentpart = :target_documentpart,
                        authorization_group = :authorization_group,
                        target_dokob = :target_dokob,
                        target_objky = :target_objky
                    WHERE id = :id
                """), {
                    'id': row['id'],
                    'target_documenttype': row.get('target_documenttype'),
                    'target_documentnumber': row.get('target_documentnumber'),
                    'target_documentversion': row.get('target_documentversion'),
                    'target_documentpart': row.get('target_documentpart'),
                    'authorization_group': row.get('authorization_group'),
                    'target_dokob': row.get('target_dokob'),
                    'target_objky': row.get('target_objky')
                })
                updated += 1
        
        return jsonify({
            'success': True, 
            'updated': updated, 
            'rules_applied': rules_applied,
            'message': f'{updated} records updated with {rules_applied} rules'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/fetch-metadata-stream', methods=['GET'])
def fetch_batch_metadata_stream(batch_id):
    """SSE streaming endpoint for fetching file metadata from DIL database.
    Provides real-time progress updates."""
    
    def generate():
        try:
            from app_config import DilEngine
            dil_db = DilEngine.load()
            dil_engine = dil_db.engine
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Loading batch records...'})}\n\n"
            
            # Get records that need metadata
            query = f"""
                SELECT id, source_documentnumber, source_documentpart, source_documenttype, source_documentversion,
                       file_size_bytes, source_loioid
                FROM dbo.migration_staging
                WHERE batch_id = '{batch_id}'
                  AND skip_migration = 0
            """
            
            with misc_engine.begin() as con:
                df = pd.read_sql(query, con)
            
            if len(df) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No records found'})}\n\n"
                return
            
            total_records = len(df)
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'init', 'total': total_records, 'message': f'Found {total_records} records'})}\n\n"
            
            # Count how many already have metadata
            records_with_size = df[df['file_size_bytes'].notna()].shape[0]
            records_without_size = df[df['file_size_bytes'].isna()].shape[0]
            
            if records_without_size == 0:
                yield f"data: {json.dumps({'type': 'complete', 'message': 'All records already have file sizes', 'updated': 0, 'errors': 0, 'already_had_metadata': records_with_size})}\n\n"
                return
            
            # Step 1: Look up LOIO_IDs from DIL.DMS_DOC2LOIO
            yield f"data: {json.dumps({'type': 'status', 'phase': 'loio', 'message': 'Looking up LOIO_IDs from DIL...'})}\n\n"
            
            # Build conditions for batch lookup - VECTORIZED approach (FAST!)
            # This replaces slow iterrows() loop with pandas string operations
            df['dokvr_padded'] = df['source_documentversion'].astype(str).str.zfill(2)
            df['doktl_padded'] = df['source_documentpart'].astype(str).str.zfill(3)
            df['doknr_escaped'] = df['source_documentnumber'].astype(str).str.replace("'", "''", regex=False)
            df['dokar_escaped'] = df['source_documenttype'].astype(str).str.replace("'", "''", regex=False)
            
            # Build conditions using vectorized string concatenation (100x faster than iterrows!)
            conditions = (
                "(DOKNR='" + df['doknr_escaped'] + 
                "' AND DOKAR='" + df['dokar_escaped'] + 
                "' AND DOKVR='" + df['dokvr_padded'] + 
                "' AND DOKTL='" + df['doktl_padded'] + "')"
            ).tolist()
            
            # Clean up temp columns
            df.drop(['doknr_escaped', 'dokar_escaped'], axis=1, inplace=True, errors='ignore')
            
            # Query LOIO_IDs in chunks
            chunk_size = 200
            all_loios = []
            
            for i in range(0, len(conditions), chunk_size):
                chunk = conditions[i:i + chunk_size]
                where_clause = " OR ".join(chunk)
                loio_query = f"""
                    SELECT DOKNR, DOKAR, DOKVR, DOKTL, LO_OBJID
                    FROM DIL.DMS_DOC2LOIO
                    WHERE MANDT = '100'
                    AND ({where_clause})
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(loio_query, con)
                all_loios.append(chunk_df)
                
                if i % 1000 == 0:
                    pct = int((i / len(conditions)) * 50)  # First 50% is LOIO lookup
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'loio', 'current': i, 'total': len(conditions), 'percent': pct, 'message': f'LOIO lookup: {i}/{len(conditions)}'})}\n\n"
            
            if not all_loios or all(len(c) == 0 for c in all_loios):
                yield f"data: {json.dumps({'type': 'error', 'message': 'No LOIO_IDs found in DIL database for these documents'})}\n\n"
                return
            
            loio_df = pd.concat(all_loios, ignore_index=True)
            loio_df.columns = [c.lower() for c in loio_df.columns]
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'loio', 'percent': 50, 'message': f'Found {len(loio_df)} LOIO_IDs'})}\n\n"
            
            # Step 2: Look up file sizes from DIL.DMS_FILE_SIZE
            loio_ids = loio_df['lo_objid'].dropna().unique().tolist()
            
            if not loio_ids:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No LOIO_IDs available for file size lookup'})}\n\n"
                return
            
            yield f"data: {json.dumps({'type': 'status', 'phase': 'size', 'message': f'Looking up file sizes for {len(loio_ids)} LOIOs...'})}\n\n"
            
            all_sizes = []
            chunk_size = 500
            
            for i in range(0, len(loio_ids), chunk_size):
                chunk = loio_ids[i:i + chunk_size]
                placeholders = ",".join([f"'{lid}'" for lid in chunk])
                size_query = f"""
                    SELECT LOIO_ID, FILE_SIZE, FILE_NAME
                    FROM DIL.DMS_FILE_SIZE
                    WHERE LOIO_ID IN ({placeholders})
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(size_query, con)
                all_sizes.append(chunk_df)
                
                if i % 2000 == 0:
                    pct = 50 + int((i / len(loio_ids)) * 25)  # Next 25% is file size lookup
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'size', 'current': i, 'total': len(loio_ids), 'percent': pct, 'message': f'File sizes: {i}/{len(loio_ids)}'})}\n\n"
            
            # Check if any file sizes were found
            total_size_records = sum(len(c) for c in all_sizes)
            
            # Step 3: Merge LOIO_IDs with file sizes (even if no sizes found)
            if total_size_records > 0:
                size_df = pd.concat(all_sizes, ignore_index=True)
                size_df.columns = [c.lower() for c in size_df.columns]
                
                # Remove duplicates - keep first (largest file size) per LOIO
                size_df = size_df.sort_values('file_size', ascending=False).drop_duplicates(subset=['loio_id'], keep='first')
                
                loio_df = loio_df.merge(
                    size_df[['loio_id', 'file_size', 'file_name']],
                    how='left',
                    left_on='lo_objid',
                    right_on='loio_id'
                )
            else:
                loio_df['file_size'] = None
                loio_df['file_name'] = None
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'merge', 'percent': 75, 'message': f'Found {total_size_records} file sizes, merging...'})}\n\n"
            
            # Remove duplicate LOIO entries per document (keep first with file_size if available)
            loio_df = loio_df.sort_values('file_size', ascending=False, na_position='last')
            loio_df = loio_df.drop_duplicates(subset=['doknr', 'dokar', 'dokvr', 'doktl'], keep='first')
            
            # Step 4: Merge with original df to get staging IDs
            df_merged = df.merge(
                loio_df,
                how='left',
                left_on=['source_documentnumber', 'source_documenttype', 'dokvr_padded', 'doktl_padded'],
                right_on=['doknr', 'dokar', 'dokvr', 'doktl']
            )
            
            # Safety check: df_merged should have same length as df
            if len(df_merged) != len(df):
                df_merged = df_merged.sort_values('file_size', ascending=False, na_position='last')
                df_merged = df_merged.drop_duplicates(subset=['id'], keep='first')
            
            yield f"data: {json.dumps({'type': 'status', 'phase': 'update', 'message': f'Preparing bulk update for {len(df_merged)} records...'})}\n\n"
            
            # Prepare update DataFrame - only rows with LOIO (BULK UPDATE approach)
            update_df = df_merged[df_merged['lo_objid'].notna()][['id', 'lo_objid', 'file_size', 'file_name']].copy()
            update_df.columns = ['staging_id', 'source_loioid', 'file_size_bytes', 'filename']
            update_df['staging_id'] = update_df['staging_id'].astype(int)
            update_df['source_loioid'] = update_df['source_loioid'].astype(str)
            update_df['file_size_bytes'] = pd.to_numeric(update_df['file_size_bytes'], errors='coerce').astype('Int64')
            update_df['filename'] = update_df['filename'].astype(str).replace('nan', None)
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 78, 'message': f'Bulk updating {len(update_df)} records via temp table...'})}\n\n"
            
            with misc_engine.begin() as con:
                # Create temp table
                con.execute(text("""
                    IF OBJECT_ID('tempdb..#metadata_update') IS NOT NULL DROP TABLE #metadata_update;
                    CREATE TABLE #metadata_update (
                        staging_id INT PRIMARY KEY,
                        source_loioid NVARCHAR(100),
                        file_size_bytes BIGINT,
                        filename NVARCHAR(500)
                    );
                """))
                
                # Bulk insert into temp table in chunks
                chunk_size = 900
                for i in range(0, len(update_df), chunk_size):
                    chunk = update_df.iloc[i:i + chunk_size]
                    chunk.to_sql('#metadata_update', con, if_exists='append', index=False, method='multi')
                    
                    if i % 10000 == 0:
                        pct = 78 + int((i / len(update_df)) * 15)  # 78-93%
                        yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'current': i, 'total': len(update_df), 'percent': pct, 'message': f'Temp table: {i}/{len(update_df)}'})}\n\n"
                
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 95, 'message': 'Executing UPDATE JOIN...'})}\n\n"
                
                # Single UPDATE with JOIN - much faster than 200k individual updates!
                result = con.execute(text("""
                    UPDATE s
                    SET s.source_loioid = t.source_loioid,
                        s.file_size_bytes = t.file_size_bytes,
                        s.filename = CASE WHEN t.filename IS NOT NULL AND t.filename != 'None' THEN t.filename ELSE s.filename END
                    FROM dbo.migration_staging s
                    INNER JOIN #metadata_update t ON s.id = t.staging_id
                """))
                
                updated_count = result.rowcount
                
                # Drop temp table
                con.execute(text("DROP TABLE #metadata_update"))
            
            error_count = len(df) - len(update_df)
            
            # Calculate statistics
            if total_size_records > 0:
                total_bytes = size_df['file_size'].dropna().sum()
                max_bytes = size_df['file_size'].dropna().max()
            else:
                total_bytes = 0
                max_bytes = 0
            
            yield f"data: {json.dumps({'type': 'complete', 'message': 'Metadata fetch complete', 'updated': updated_count, 'errors': error_count, 'already_had_metadata': records_with_size, 'total_processed': total_records, 'total_size_mb': round(total_bytes / (1024 * 1024), 1) if total_bytes else 0, 'max_file_mb': round(max_bytes / (1024 * 1024), 1) if max_bytes else 0})}\n\n"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


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
            query = f"""
                SELECT id, source_documentnumber, source_documentpart, source_documenttype, source_documentversion,
                       file_size_bytes, source_loioid, filename
                FROM dbo.migration_staging
                WHERE batch_id = '{batch_id}'
                  AND skip_migration = 0
            """
            
            with misc_engine.begin() as con:
                df = pd.read_sql(query, con)
            
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
            
            df.drop(['doknr_escaped', 'dokar_escaped'], axis=1, inplace=True, errors='ignore')
            
            # Query LOIO_IDs in chunks
            chunk_size = 200
            all_loios = []
            
            for i in range(0, len(conditions), chunk_size):
                chunk = conditions[i:i + chunk_size]
                where_clause = " OR ".join(chunk)
                loio_query = f"""
                    SELECT DOKNR, DOKAR, DOKVR, DOKTL, LO_OBJID
                    FROM DIL.DMS_DOC2LOIO
                    WHERE MANDT = '100'
                    AND ({where_clause})
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(loio_query, con)
                all_loios.append(chunk_df)
                
                if i % 500 == 0:
                    pct = 5 + int((i / len(conditions)) * 15)  # 5-20%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'loio', 'percent': pct, 'message': f'LOIO lookup: {i}/{len(conditions)}'})}\n\n"
            
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
                chunk_size = 500
                
                for i in range(0, len(loio_ids), chunk_size):
                    chunk = loio_ids[i:i + chunk_size]
                    placeholders = ",".join([f"'{lid}'" for lid in chunk])
                    size_query = f"""
                        SELECT LOIO_ID, FILE_SIZE, FILE_NAME
                        FROM DIL.DMS_FILE_SIZE
                        WHERE LOIO_ID IN ({placeholders})
                    """
                    with dil_engine.begin() as con:
                        chunk_df = pd.read_sql(size_query, con)
                    all_sizes.append(chunk_df)
                    
                    if i % 1000 == 0:
                        pct = 20 + int((i / len(loio_ids)) * 15)  # 20-35%
                        yield f"data: {json.dumps({'type': 'progress', 'phase': 'size', 'percent': pct, 'message': f'File sizes: {i}/{len(loio_ids)}'})}\n\n"
                
                total_size_records = sum(len(c) for c in all_sizes)
                if total_size_records > 0:
                    size_df = pd.concat(all_sizes, ignore_index=True)
                    size_df.columns = [c.lower() for c in size_df.columns]
                    size_df = size_df.sort_values('file_size', ascending=False).drop_duplicates(subset=['loio_id'], keep='first')
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'size', 'percent': 35, 'message': f'Found {total_size_records} file sizes'})}\n\n"
            
            # ========== PHASE 3: Filename Lookup from DRAW ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'draw', 'message': 'Phase 3/4: Looking up filenames from DIL.DRAW...'})}\n\n"
            
            # Build document keys for DRAW lookup
            doc_keys = []
            for _, row in df.iterrows():
                doknr = str(row['source_documentnumber'])
                dokar = str(row['source_documenttype'])
                dokvr = str(row['source_documentversion']).zfill(2)
                doktl = str(row['source_documentpart']).zfill(3)
                doc_keys.append((doknr.replace("'", "''"), dokar.replace("'", "''"), dokvr, doktl))
            
            all_filenames = []
            chunk_size = 300
            
            for i in range(0, len(doc_keys), chunk_size):
                chunk = doc_keys[i:i + chunk_size]
                conditions_draw = [
                    f"(doknr = '{k[0]}' AND dokar = '{k[1]}' AND dokvr = '{k[2]}' AND doktl = '{k[3]}')"
                    for k in chunk
                ]
                where_clause = " OR ".join(conditions_draw)
                
                draw_query = f"""
                    SELECT doknr, dokar, dokvr, doktl, filep
                    FROM dil.DRAW
                    WHERE {where_clause}
                """
                with dil_engine.begin() as con:
                    chunk_df = pd.read_sql(draw_query, con)
                all_filenames.append(chunk_df)
                
                if i % 600 == 0:
                    pct = 35 + int((i / len(doc_keys)) * 15)  # 35-50%
                    yield f"data: {json.dumps({'type': 'progress', 'phase': 'draw', 'percent': pct, 'message': f'DRAW lookup: {i}/{len(doc_keys)}'})}\n\n"
            
            filename_df = pd.DataFrame()
            filenames_found = 0
            if all_filenames:
                filename_df = pd.concat(all_filenames, ignore_index=True)
                filename_df.columns = [c.lower() for c in filename_df.columns]
                filenames_found = int(filename_df['filep'].notna().sum())
            
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'draw', 'percent': 50, 'message': f'Found {filenames_found} filenames from DRAW'})}\n\n"
            
            # ========== PHASE 4: Apply Rules ==========
            yield f"data: {json.dumps({'type': 'status', 'phase': 'rules', 'message': 'Phase 4/4: Applying migration rules...'})}\n\n"
            
            rules = load_translations()
            rules_applied = 0
            
            # Get full records for rule application
            with misc_engine.begin() as con:
                full_df = pd.read_sql(f"""
                    SELECT id, source_documenttype, source_documentnumber, source_documentversion,
                           source_documentpart, source_description, authorization_group,
                           source_dokob, source_objky, filename,
                           target_documenttype, target_documentnumber, target_documentversion,
                           target_documentpart, target_dokob, target_objky
                    FROM dbo.migration_staging
                    WHERE batch_id = '{batch_id}'
                """, con)
            
            # Initialize target columns from source if not set
            if full_df['target_documenttype'].isna().all():
                full_df['target_documenttype'] = full_df['source_documenttype']
            
            # Apply each rule
            for rule in rules:
                rtype = (rule.get('rule_type') or 'translation').lower()
                source_col = rule.get('source_column')
                target_col = rule.get('target_column')
                source_val = rule.get('source_value')
                target_val = rule.get('target_value')
                
                if not target_col or target_val is None:
                    continue
                
                if target_col not in full_df.columns:
                    full_df[target_col] = None
                
                if rtype == 'translation' and source_col and source_col in full_df.columns and source_val:
                    mask = full_df[source_col].astype(str).str.contains(str(source_val), case=False, na=False)
                    full_df.loc[mask, target_col] = target_val
                    if mask.sum() > 0:
                        rules_applied += 1
                elif rtype == 'overwrite':
                    full_df[target_col] = target_val
                    rules_applied += 1
            
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
                    filename_df[['doknr', 'dokar', 'dokvr', 'doktl', 'filep']],
                    how='left',
                    left_on=['_doknr', '_dokar', '_dokvr', '_doktl'],
                    right_on=['doknr', 'dokar', 'dokvr', 'doktl'],
                    suffixes=('', '_draw')
                )
                df_merged.drop(columns=['_doknr', '_dokar', '_dokvr', '_doktl',
                                        'doknr_draw', 'dokar_draw', 'dokvr_draw', 'doktl_draw'],
                               errors='ignore', inplace=True)
            
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
                
                update_data.append({
                    'staging_id': staging_id,
                    'source_loioid': source_loioid,
                    'file_size_bytes': file_size_bytes,
                    'filename': filename
                })
            
            # Also get rule updates
            rule_updates = {}
            for _, row in full_df.iterrows():
                rule_updates[int(row['id'])] = {
                    'target_documenttype': row.get('target_documenttype'),
                    'target_documentnumber': row.get('target_documentnumber'),
                    'target_documentversion': row.get('target_documentversion'),
                    'target_documentpart': row.get('target_documentpart'),
                    'authorization_group': row.get('authorization_group'),
                    'target_dokob': row.get('target_dokob'),
                    'target_objky': row.get('target_objky')
                }
            
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
                        filename NVARCHAR(500)
                    );
                """))
                
                # Insert metadata updates
                update_df = pd.DataFrame(update_data)
                update_df = update_df[update_df['source_loioid'].notna() | update_df['filename'].notna()]
                
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
                                              THEN t.filename ELSE s.filename END
                        FROM dbo.migration_staging s
                        INNER JOIN #refresh_update t ON s.id = t.staging_id
                    """))
                    updated_count = result.rowcount
                
                con.execute(text("DROP TABLE #refresh_update"))
                
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'update', 'percent': 90, 'message': f'Updated {updated_count} metadata records'})}\n\n"
                
                # Update rule results
                for staging_id, vals in rule_updates.items():
                    con.execute(text("""
                        UPDATE dbo.migration_staging
                        SET target_documenttype = :target_documenttype,
                            target_documentnumber = :target_documentnumber,
                            target_documentversion = :target_documentversion,
                            target_documentpart = :target_documentpart,
                            authorization_group = :authorization_group,
                            target_dokob = :target_dokob,
                            target_objky = :target_objky
                        WHERE id = :id
                    """), {
                        'id': staging_id,
                        'target_documenttype': vals.get('target_documenttype'),
                        'target_documentnumber': vals.get('target_documentnumber'),
                        'target_documentversion': vals.get('target_documentversion'),
                        'target_documentpart': vals.get('target_documentpart'),
                        'authorization_group': vals.get('authorization_group'),
                        'target_dokob': vals.get('target_dokob'),
                        'target_objky': vals.get('target_objky')
                    })
            
            # Calculate statistics
            total_bytes = size_df['file_size'].dropna().sum() if len(size_df) > 0 else 0
            max_bytes = size_df['file_size'].dropna().max() if len(size_df) > 0 else 0
            
            # Convert numpy types to native Python types for JSON serialization
            yield f"data: {json.dumps({'type': 'complete', 'message': 'Refresh complete', 'metadata_updated': int(updated_count), 'rules_applied': int(rules_applied), 'filenames_found': int(filenames_found), 'total_records': int(total_records), 'total_size_mb': round(float(total_bytes) / (1024 * 1024), 1) if total_bytes else 0, 'max_file_mb': round(float(max_bytes) / (1024 * 1024), 1) if max_bytes else 0})}\n\n"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


@migrate_bp.route('/batch/<batch_id>/progress', methods=['GET'])
def get_batch_progress(batch_id):
    """Get execution progress for a batch (for live polling during execution)."""
    try:
        query = f"""
            SELECT 
                batch_id,
                status,
                total_records,
                executed_records,
                successful_records,
                failed_records,
                created_at
            FROM dbo.migration_batch
            WHERE batch_id = '{batch_id}'
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        if len(df) == 0:
            return jsonify({'success': False, 'error': 'Batch not found'}), 404
        
        row = df.iloc[0]
        total = row['total_records'] or 0
        executed = row['executed_records'] or 0
        success = row['successful_records'] or 0
        failed = row['failed_records'] or 0
        
        # Get partial count from staging table (container created but upload incomplete)
        partial = 0
        try:
            with misc_engine.begin() as con:
                partial_result = con.execute(text(f"""
                    SELECT COUNT(*) FROM dbo.migration_staging
                    WHERE batch_id = '{batch_id}' AND execution_status = 'partial'
                """)).fetchone()
                partial = partial_result[0] if partial_result else 0
        except:
            pass
        
        # Calculate progress percentage
        progress_pct = (executed / total * 100) if total > 0 else 0
        
        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'status': row['status'],
            'total': int(total),
            'executed': int(executed),
            'success': int(success),
            'failed': int(failed),
            'partial': int(partial),
            'remaining': int(total - executed),
            'progress_pct': round(progress_pct, 1),
            'is_running': row['status'] == 'executing'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/preview-stats', methods=['GET'])
def get_batch_preview_stats(batch_id):
    """Get aggregated statistics for batch preview (computed on DB level for performance).
    Returns counts and file size buckets without loading all records.
    Buckets only count non-success records (pending/failed/partial) for runtime estimation."""
    try:
        # Aggregate stats in single SQL query - much faster than loading all records
        # Use CAST to BIGINT for file_size_bytes to avoid integer overflow on large batches
        # Buckets only count non-success records for accurate runtime estimation
        query = text("""
            SELECT 
                COUNT(*) as total_records,
                SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN execution_status = 'pending' THEN 1 ELSE 0 END) as pending_count,
                SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                SUM(CASE WHEN execution_status = 'partial' THEN 1 ELSE 0 END) as partial_count,
                -- Buckets count only non-success records for runtime estimation
                SUM(CASE WHEN execution_status != 'success' AND (file_size_bytes IS NULL OR file_size_bytes = 0) THEN 1 ELSE 0 END) as unknown_size_count,
                SUM(CASE WHEN execution_status != 'success' AND file_size_bytes > 0 AND file_size_bytes <= 1048576 THEN 1 ELSE 0 END) as tiny_count,
                SUM(CASE WHEN execution_status != 'success' AND file_size_bytes > 1048576 AND file_size_bytes <= 10485760 THEN 1 ELSE 0 END) as small_count,
                SUM(CASE WHEN execution_status != 'success' AND file_size_bytes > 10485760 AND file_size_bytes <= 52428800 THEN 1 ELSE 0 END) as medium_count,
                SUM(CASE WHEN execution_status != 'success' AND file_size_bytes > 52428800 THEN 1 ELSE 0 END) as large_count,
                -- Total size also only for non-success records
                SUM(CAST(CASE WHEN execution_status != 'success' AND file_size_bytes > 0 THEN file_size_bytes ELSE 0 END AS BIGINT)) as total_size_bytes,
                MAX(CASE WHEN execution_status != 'success' THEN file_size_bytes ELSE 0 END) as max_file_size
            FROM dbo.migration_staging
            WHERE batch_id = :batch_id
        """)
        
        with misc_engine.begin() as con:
            result = con.execute(query, {'batch_id': batch_id}).fetchone()
        
        if not result or result.total_records == 0:
            return jsonify({'success': False, 'error': 'Batch not found or empty'}), 404
        
        # Use actual pending count from DB (records with execution_status = 'pending')
        actual_pending_count = result.pending_count or 0
        # Also calculate "to execute" count (all non-success = pending + failed + partial)
        to_execute_count = (result.total_records or 0) - (result.success_count or 0)
        
        return jsonify({
            'success': True,
            'stats': {
                'total': result.total_records or 0,
                'success': result.success_count or 0,
                'pending': actual_pending_count,  # Real pending from DB
                'to_execute': to_execute_count,   # All non-success (for runtime estimation)
                'failed': result.failed_count or 0,
                'partial': result.partial_count or 0,
                'buckets': {
                    'tiny': result.tiny_count or 0,
                    'small': result.small_count or 0,
                    'medium': result.medium_count or 0,
                    'large': result.large_count or 0,
                    'unknown': result.unknown_size_count or 0
                },
                'total_size_bytes': int(result.total_size_bytes or 0),
                'max_file_size': int(result.max_file_size or 0)
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/error-categories', methods=['GET'])
def get_batch_error_categories(batch_id):
    """Get distinct error categories for a batch with counts.
    
    Reads directly from migration_staging.error_category column.
    """
    try:
        categories_dict = {}
        
        with misc_engine.connect() as con:
            # Get categories directly from staging table (covers all cases)
            result = con.execute(text("""
                SELECT error_category, COUNT(*) as cnt
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id
                    AND execution_status = 'failed'
                    AND error_category IS NOT NULL
                GROUP BY error_category
                ORDER BY cnt DESC
            """), {'batch_id': batch_id}).fetchall()
            
            for row in result:
                categories_dict[row[0]] = row[1]
        
        # Convert to list sorted by count
        categories = [{'category': cat, 'count': cnt} for cat, cnt in categories_dict.items()]
        categories.sort(key=lambda x: -x['count'])
        
        return jsonify({
            'success': True,
            'categories': categories
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/records', methods=['GET'])
def get_batch_records(batch_id):
    """Get staging records for a batch with optional pagination for large datasets.
    
    Query params:
        page: Page number (1-based), default=1
        per_page: Records per page, default=5000 (0 = all records)
        status_filter: Filter by execution_status (optional)
        error_category: Filter by error category (applied in Python after dynamic classification)
    """
    try:
        # Parse pagination params
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 5000, type=int)  # Default 5000 for large batches
        status_filter = request.args.get('status_filter', '')
        error_category_filter = request.args.get('error_category', '')
        
        # Build WHERE clause with ms. prefix for JOIN
        where_conditions = [f"ms.batch_id = '{batch_id}'"]
        if status_filter:
            where_conditions.append(f"ms.execution_status = '{status_filter}'")
        # If filtering by error_category, filter by failed status AND the category in staging table
        if error_category_filter:
            where_conditions.append("ms.execution_status = 'failed'")
            where_conditions.append(f"ms.error_category = '{error_category_filter}'")
        where_clause = " AND ".join(where_conditions)
        
        # First get total count (with all filters applied)
        count_conditions = [f"ms.batch_id = '{batch_id}'"]
        if status_filter:
            count_conditions.append(f"ms.execution_status = '{status_filter}'")
        if error_category_filter:
            count_conditions.append("ms.execution_status = 'failed'")
            count_conditions.append(f"ms.error_category = '{error_category_filter}'")
        count_query = "SELECT COUNT(*) FROM dbo.migration_staging ms WHERE " + " AND ".join(count_conditions)
        
        # Build paginated query using OFFSET/FETCH for SQL Server
        # Use ms.error_category from staging table (set during execution)
        if per_page > 0:
            offset = (page - 1) * per_page
            query = f"""
                SELECT 
                    ms.id,
                    ms.source_documentnumber,
                    ms.source_documentpart,
                    ms.source_documenttype,
                    ms.source_documentversion,
                    ms.source_loioid,
                    ms.source_description,
                    ms.source_dokob,
                    ms.source_objky,
                    ms.target_documentnumber,
                    ms.target_documentpart,
                    ms.target_documenttype,
                    ms.target_documentversion,
                    ms.filename,
                    ms.file_size_bytes,
                    ms.mime_type,
                    ms.authorization_group,
                    ms.validation_status,
                    ms.validation_notes,
                    ms.execution_status,
                    ms.execution_error,
                    ms.user_approved,
                    ms.skip_migration,
                    ms.error_category
                FROM dbo.migration_staging ms
                WHERE {where_clause}
                ORDER BY ms.source_documenttype, ms.source_documentnumber, ms.source_documentversion, ms.source_documentpart, ms.source_dokob
                OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY
            """
        else:
            # per_page=0 means get all records (for backwards compatibility)
            query = f"""
                SELECT 
                    ms.id,
                    ms.source_documentnumber,
                    ms.source_documentpart,
                    ms.source_documenttype,
                    ms.source_documentversion,
                    ms.source_loioid,
                    ms.source_description,
                    ms.source_dokob,
                    ms.source_objky,
                    ms.target_documentnumber,
                    ms.target_documentpart,
                    ms.target_documenttype,
                    ms.target_documentversion,
                    ms.filename,
                    ms.file_size_bytes,
                    ms.mime_type,
                    ms.authorization_group,
                    ms.validation_status,
                    ms.validation_notes,
                    ms.execution_status,
                    ms.execution_error,
                    ms.user_approved,
                    ms.skip_migration,
                    ms.error_category
                FROM dbo.migration_staging ms
                WHERE {where_clause}
                ORDER BY ms.source_documenttype, ms.source_documentnumber, ms.source_documentversion, ms.source_documentpart, ms.source_dokob
            """
        
        with misc_engine.begin() as con:
            total_count = con.execute(text(count_query)).scalar()
            df = pd.read_sql(query, con)
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        records = df_to_json_safe(df)
        
        # If error_category is NULL but execution_error exists, classify dynamically
        from app.process import _classify_error
        for record in records:
            if not record.get('error_category') and record.get('execution_error'):
                try:
                    error_str = record['execution_error']
                    if isinstance(error_str, str):
                        import json
                        try:
                            error_info = json.loads(error_str)
                        except:
                            # Legacy format like "Error during getinfo: unexpexted Error"
                            error_info = {'status_code': error_str, 'reason': error_str}
                    else:
                        error_info = error_str
                    record['error_category'] = _classify_error(error_info)
                except:
                    record['error_category'] = 'UNKNOWN'
        
        # Apply error_category filter in Python (after dynamic classification)
        if error_category_filter:
            records = [r for r in records if r.get('error_category') == error_category_filter]
        
        # Calculate pagination info
        filtered_count = len(records) if error_category_filter else total_count
        total_pages = (filtered_count + per_page - 1) // per_page if per_page > 0 else 1
        
        return jsonify({
            'success': True, 
            'records': records,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': filtered_count,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/preview', methods=['GET'])
def preview_view():
    """Show preview interface for a batch."""
    batch_id = request.args.get('batch_id')
    if not batch_id:
        return "Batch ID required", 400
    
    context = get_template_context()
    context['batch_id'] = batch_id
    return render_template('preview.html', **context)





@migrate_bp.route('/execute', methods=['POST'])
def execute():
    """Step 2: Execute migration for approved records."""
    try:
        # Check if user is logged in (has bearer token)
        if not session.get('bearer_token'):
            return jsonify({
                'success': False, 
                'error': 'Not logged in. Please login to SAP first.',
                'login_required': True
            }), 401
        
        data = request.get_json()
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        # Execute migration
        result = execute_migration(batch_id)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/execute_selected', methods=['POST'])
def execute_selected():
    """Execute migration for selected records only."""
    try:
        # Check if user is logged in (has bearer token)
        if not session.get('bearer_token'):
            return jsonify({
                'success': False, 
                'error': 'Not logged in. Please login to SAP first.',
                'login_required': True
            }), 401
        
        data = request.get_json()
        batch_id = data.get('batch_id')
        record_ids = data.get('record_ids', [])
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        if not record_ids:
            return jsonify({'success': False, 'error': 'No records selected'}), 400
        
        # Reset selected records to pending for execution
        record_ids_str = ','.join(str(id) for id in record_ids)
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND id IN ({record_ids_str})
                    AND skip_migration = 0
            """))
        
        # Execute migration ONLY for the selected record IDs
        result = execute_migration(batch_id, record_ids=record_ids)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/cancel', methods=['POST'])
def cancel_migration(batch_id):
    """Cancel a running migration for the given batch."""
    try:
        # Check if migration is actually running
        if not is_migration_running(batch_id):
            return jsonify({
                'success': False, 
                'error': 'No migration is currently running for this batch'
            }), 400
        
        # Request cancellation
        request_cancel(batch_id)
        
        return jsonify({
            'success': True,
            'message': f'Cancellation requested for batch {batch_id}. Migration will stop after current operations complete.',
            'cancel_requested': True
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/status', methods=['GET'])
def get_batch_status(batch_id):
    """Get current status of a batch including whether migration is running or cancelled."""
    try:
        with misc_engine.begin() as con:
            batch = con.execute(text("""
                SELECT status, total_records, executed_records, successful_records, failed_records
                FROM dbo.migration_batch
                WHERE batch_id = :batch_id
            """), {'batch_id': batch_id}).fetchone()
        
        if not batch:
            return jsonify({'success': False, 'error': 'Batch not found'}), 404
        
        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'status': batch[0],
            'total_records': batch[1] or 0,
            'executed_records': batch[2] or 0,
            'successful_records': batch[3] or 0,
            'failed_records': batch[4] or 0,
            'is_running': is_migration_running(batch_id),
            'cancel_requested': is_cancel_requested(batch_id)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/token-status', methods=['GET'])
def get_token_status():
    """Get current authentication token status for monitoring."""
    try:
        from authentication import get_token_remaining_seconds, is_token_expiring_soon
        
        bearer_token = session.get('bearer_token')
        has_refresh_token = bool(session.get('refresh_token'))
        remaining_seconds = get_token_remaining_seconds()
        
        if not bearer_token:
            return jsonify({
                'success': True,
                'logged_in': False,
                'message': 'Not logged in'
            })
        
        return jsonify({
            'success': True,
            'logged_in': True,
            'has_refresh_token': has_refresh_token,
            'token_remaining_seconds': remaining_seconds,
            'token_remaining_minutes': remaining_seconds // 60 if remaining_seconds else None,
            'is_expiring_soon': is_token_expiring_soon(300),
            'can_auto_refresh': has_refresh_token,
            'message': f"Token valid for {remaining_seconds // 60}min" if remaining_seconds else "Token expiry unknown"
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/skip_records', methods=['POST'])
def skip_records():
    """Mark records as skipped (excluded from migration)."""
    try:
        data = request.get_json()
        batch_id = data.get('batch_id')
        record_ids = data.get('record_ids', [])
        skip = data.get('skip', True)
        reason = data.get('reason', '')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        if not record_ids:
            return jsonify({'success': False, 'error': 'No record IDs provided'}), 400
        
        # Build the IN clause for record IDs
        ids_str = ','.join(str(int(rid)) for rid in record_ids)
        skip_value = 1 if skip else 0
        
        with misc_engine.begin() as con:
            # Update skip_migration flag
            result = con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET skip_migration = {skip_value},
                    execution_error = CASE 
                        WHEN {skip_value} = 1 THEN 'Skipped: {reason}'
                        ELSE execution_error
                    END
                WHERE batch_id = '{batch_id}'
                    AND id IN ({ids_str})
            """))
            updated_count = result.rowcount
        
        return jsonify({
            'success': True,
            'updated': updated_count,
            'skip': skip,
            'reason': reason
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/error_overview', methods=['GET'])
def get_error_overview():
    """Get overview of all errors grouped by category for dashboard display."""
    try:
        from app.process import get_error_details
        
        with misc_engine.connect() as con:
            # Get error counts grouped by category across all batches
            result = con.execute(text("""
                SELECT 
                    fd.error_category,
                    COUNT(*) as cnt
                FROM dbo.migration_file_details fd
                INNER JOIN dbo.migration_staging ms ON fd.staging_id = ms.id
                WHERE fd.upload_status NOT LIKE 'SUCCESS%'
                    AND ms.execution_status = 'failed'
                    AND ms.skip_migration = 0
                    AND fd.error_category IS NOT NULL
                GROUP BY fd.error_category
                ORDER BY cnt DESC
            """)).fetchall()
            
            errors = []
            total = 0
            for row in result:
                cat, cnt = row
                total += cnt
                errors.append({
                    'category': cat,
                    'count': cnt
                })
        
        return jsonify({
            'success': True,
            'errors': errors,
            'total_errors': total
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/retry_by_category', methods=['POST'])
def retry_by_category():
    """Reset and retry all failed records with a specific error category."""
    try:
        data = request.get_json()
        category = data.get('category')
        
        if not category:
            return jsonify({'success': False, 'error': 'Category required'}), 400
        
        # Get staging IDs with this error category
        with misc_engine.begin() as con:
            # Find staging_ids from file_details with this category
            result = con.execute(text("""
                SELECT DISTINCT fd.staging_id
                FROM dbo.migration_file_details fd
                INNER JOIN dbo.migration_staging ms ON fd.staging_id = ms.id
                WHERE fd.error_category = :category
                    AND ms.execution_status = 'failed'
                    AND ms.skip_migration = 0
            """), {'category': category}).fetchall()
            
            staging_ids = [row[0] for row in result]
            
            if not staging_ids:
                return jsonify({'success': True, 'reset_count': 0, 'message': 'No records to retry'})
            
            ids_str = ','.join(str(id) for id in staging_ids)
            
            # Reset these staging records to pending
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE id IN ({ids_str})
            """))
            
            reset_count = len(staging_ids)
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} records with category {category} reset to pending'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/retry_all_errors', methods=['POST'])
def retry_all_errors():
    """Reset all failed records across all batches."""
    try:
        with misc_engine.begin() as con:
            result = con.execute(text("""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE execution_status = 'failed'
                    AND skip_migration = 0
            """))
            reset_count = result.rowcount
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} failed records reset to pending'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/reset_failed', methods=['POST'])
def reset_failed():
    """Reset all failed records to pending status (without re-executing)."""
    try:
        data = request.get_json()
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        # Reset all failed records to pending
        with misc_engine.begin() as con:
            result = con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND execution_status = 'failed'
                    AND skip_migration = 0
            """))
            reset_count = result.rowcount
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} failed records reset to pending'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/retry_failed', methods=['POST'])
def retry_failed():
    """Re-execute all failed records in a batch."""
    try:
        data = request.get_json()
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        # Reset failed records to pending state
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND execution_status = 'failed'
                    AND skip_migration = 0
            """))
            
            # Get count of records being retried
            result = con.execute(text(f"""
                SELECT COUNT(*) as cnt
                FROM dbo.migration_staging
                WHERE batch_id = '{batch_id}'
                    AND execution_status = 'pending'
                    AND skip_migration = 0
            """))
            retried_count = result.fetchone()[0]
        
        # Execute migration for pending records
        result = execute_migration(batch_id)
        
        # Add retried count to result
        result['retried'] = retried_count
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/results', methods=['GET'])
def get_results(batch_id):
    """Get execution results for a batch."""
    try:
        query = f"""
            SELECT 
                id,
                source_documentnumber,
                target_documentnumber,
                source_documenttype,
                target_documenttype,
                source_loioid,
                source_description,
                execution_status,
                execution_error,
                execution_started_at,
                execution_completed_at,
                validation_notes,
                validated_by,
                validated_at,
                authorization_group,
                filename,
                file_size_bytes,
                mime_type
            FROM dbo.migration_staging
            WHERE batch_id = '{batch_id}'
                AND execution_status != 'pending'
            ORDER BY source_documenttype, source_documentnumber, source_documentversion, source_documentpart, source_dokob
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        results = df_to_json_safe(df)
        
        # Parse execution_error JSON strings into objects
        for record in results:
            if record.get('execution_error'):
                try:
                    import json
                    record['execution_error'] = json.loads(record['execution_error'])
                except (json.JSONDecodeError, TypeError):
                    pass  # Keep as string if not valid JSON
        
        return jsonify({'success': True, 'results': results})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Translation Management Routes ====================

@migrate_bp.route('/rules')
def migration_rules_page():
    """Migration rules management page (renamed from Translation Rules)."""
    return render_template('translations.html', **get_template_context())


@migrate_bp.route('/rules/list', methods=['GET'])
def list_migration_rules():
    """Get all active migration rules (translation/overwrite)."""
    try:
        # Ensure schema has latest columns (rule_type, condition_*)
        init_staging_tables(misc_engine)
        
        # Check if execution_order column exists
        with misc_engine.begin() as con:
            col_check = con.execute(text("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'migration_translations' 
                AND COLUMN_NAME = 'execution_order'
            """)).fetchone()
            
            has_exec_order = col_check[0] > 0 if col_check else False
            
            if has_exec_order:
                query = """
                    SELECT 
                        id,
                        rule_type,
                        source_column,
                        target_column,
                        source_value,
                        target_value,
                        condition_column,
                        condition_value,
                        condition_operator,
                        execution_order,
                        created_at,
                        created_by,
                        active,
                        notes
                    FROM dbo.migration_translations
                    WHERE active = 1
                    ORDER BY execution_order, id
                """
            else:
                query = """
                    SELECT 
                        id,
                        rule_type,
                        source_column,
                        target_column,
                        source_value,
                        target_value,
                        condition_column,
                        condition_value,
                        condition_operator,
                        100 as execution_order,
                        created_at,
                        created_by,
                        active,
                        notes
                    FROM dbo.migration_translations
                    WHERE active = 1
                    ORDER BY id
                """
            
            df = pd.read_sql(query, con)
        
        translations = df.to_dict(orient='records')
        return jsonify({'success': True, 'rules': translations})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/add', methods=['POST'])
def add_migration_rule():
    """Add a new migration rule (translation or overwrite)."""
    try:
        # Ensure schema has latest columns (rule_type, condition_*)
        init_staging_tables(misc_engine)
        data = request.get_json()
        rule_type = (data.get('rule_type') or 'translation').strip().lower()
        source_column = data.get('source_column', '').strip()
        target_column = data.get('target_column', '').strip()
        source_value = (data.get('source_value') or '').strip()
        target_value = data.get('target_value', '')  # Allow empty string, only check for None
        notes = data.get('notes', '').strip()
        condition_column = (data.get('condition_column') or '').strip()
        condition_value = (data.get('condition_value') or '').strip()
        condition_operator = (data.get('condition_operator') or 'contains').strip().lower()
        
        # Auto-assign execution_order: add at the bottom (max + 10)
        with misc_engine.begin() as con:
            max_order_result = con.execute(text("SELECT ISNULL(MAX(execution_order), 0) FROM dbo.migration_translations")).fetchone()
            execution_order = (max_order_result[0] if max_order_result else 0) + 10
        
        if rule_type not in ('translation', 'overwrite'):
            return jsonify({'success': False, 'error': 'Invalid rule_type'}), 400

        if rule_type == 'translation':
            if not source_column or not target_column or target_value is None:
                return jsonify({'success': False, 'error': 'source_column, target_column and target_value are required'}), 400
        else:  # overwrite
            if not target_column or target_value is None:
                return jsonify({'success': False, 'error': 'target_column and target_value are required for overwrite'}), 400
        
        user_email = session.get('user_email', 'system')
        
        insert_query = text("""
            INSERT INTO dbo.migration_translations 
            (rule_type, source_column, target_column, source_value, target_value, 
             condition_column, condition_value, condition_operator,
             execution_order, created_by, notes)
            VALUES (:rule_type, :source_column, :target_column, :source_value, :target_value,
                    :condition_column, :condition_value, :condition_operator,
                    :execution_order, :created_by, :notes)
        """)
        
        with misc_engine.begin() as con:
            con.execute(insert_query, {
                'rule_type': rule_type,
                'source_column': source_column,
                'target_column': target_column,
                'source_value': source_value,
                'target_value': target_value,
                'condition_column': condition_column or None,
                'condition_value': condition_value or None,
                'condition_operator': condition_operator,
                'execution_order': execution_order,
                'created_by': user_email,
                'notes': notes
            })
        
        return jsonify({'success': True, 'message': 'Migration rule added successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/update', methods=['POST'])
def update_migration_rule(rule_id):
    """Update an existing migration rule."""
    try:
        # Ensure schema has latest columns (rule_type, condition_*)
        init_staging_tables(misc_engine)
        data = request.get_json()
        source_column = (data.get('source_column') or '').strip()
        target_column = (data.get('target_column') or '').strip()
        target_value = data.get('target_value', '')  # Allow empty string, only check for None
        notes = data.get('notes', '').strip()
        condition_column = (data.get('condition_column') or '').strip()
        condition_value = (data.get('condition_value') or '').strip()
        condition_operator = (data.get('condition_operator') or '').strip()
        execution_order = data.get('execution_order', 100)
        
        if target_value is None:
            return jsonify({'success': False, 'error': 'Target value is required'}), 400
        
        update_query = text("""
            UPDATE dbo.migration_translations
            SET source_column = :source_column,
                target_column = :target_column,
                target_value = :target_value,
                condition_column = :condition_column,
                condition_value = :condition_value,
                condition_operator = :condition_operator,
                execution_order = :execution_order,
                notes = :notes
            WHERE id = :id
        """)
        
        with misc_engine.begin() as con:
            con.execute(update_query, {
                'source_column': source_column or None,
                'target_column': target_column or None,
                'target_value': target_value,
                'condition_column': condition_column or None,
                'condition_value': condition_value or None,
                'condition_operator': condition_operator or None,
                'execution_order': execution_order,
                'notes': notes,
                'id': rule_id
            })
        
        return jsonify({'success': True, 'message': 'Migration rule updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/delete', methods=['POST'])
def delete_migration_rule(rule_id):
    """Delete (deactivate) a migration rule."""
    try:
        # Ensure schema has latest columns (rule_type, condition_*)
        init_staging_tables(misc_engine)
        delete_query = text("""
            UPDATE dbo.migration_translations
            SET active = 0
            WHERE id = :id
        """)
        
        with misc_engine.begin() as con:
            con.execute(delete_query, {'id': rule_id})
        
        return jsonify({'success': True, 'message': 'Migration rule deleted successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/move_up', methods=['POST'])
def move_rule_up(rule_id):
    """Move a rule up in execution order."""
    try:
        init_staging_tables(misc_engine)
        with misc_engine.begin() as con:
            # Get current rule and the one above it
            current = con.execute(text("""
                SELECT id, execution_order FROM dbo.migration_translations
                WHERE id = :id AND active = 1
            """), {'id': rule_id}).fetchone()
            
            if not current:
                return jsonify({'success': False, 'error': 'Rule not found'}), 404
            
            prev = con.execute(text("""
                SELECT TOP 1 id, execution_order FROM dbo.migration_translations
                WHERE active = 1 AND execution_order < :order
                ORDER BY execution_order DESC, id DESC
            """), {'order': current[1]}).fetchone()
            
            if not prev:
                return jsonify({'success': False, 'error': 'Already at top'}), 400
            
            # Swap execution orders
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': prev[1], 'id': current[0]})
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': current[1], 'id': prev[0]})
        
        return jsonify({'success': True, 'message': 'Rule moved up'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/rules/<int:rule_id>/move_down', methods=['POST'])
def move_rule_down(rule_id):
    """Move a rule down in execution order."""
    try:
        init_staging_tables(misc_engine)
        with misc_engine.begin() as con:
            # Get current rule and the one below it
            current = con.execute(text("""
                SELECT id, execution_order FROM dbo.migration_translations
                WHERE id = :id AND active = 1
            """), {'id': rule_id}).fetchone()
            
            if not current:
                return jsonify({'success': False, 'error': 'Rule not found'}), 404
            
            next_rule = con.execute(text("""
                SELECT TOP 1 id, execution_order FROM dbo.migration_translations
                WHERE active = 1 AND execution_order > :order
                ORDER BY execution_order ASC, id ASC
            """), {'order': current[1]}).fetchone()
            
            if not next_rule:
                return jsonify({'success': False, 'error': 'Already at bottom'}), 400
            
            # Swap execution orders
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': next_rule[1], 'id': current[0]})
            con.execute(text("UPDATE dbo.migration_translations SET execution_order = :order WHERE id = :id"),
                       {'order': current[1], 'id': next_rule[0]})
        
        return jsonify({'success': True, 'message': 'Rule moved down'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@migrate_bp.route('/batch/<batch_id>/logs', methods=['GET'])
def get_batch_logs(batch_id):
    """Get execution logs/results for a specific batch."""
    try:
        print(f"[LOGS] Fetching logs for batch: {batch_id}")
        
        query = f"""
            SELECT 
                id,
                source_documentnumber,
                target_documentnumber,
                source_documenttype,
                target_documenttype,
                source_description,
                authorization_group,
                execution_status,
                execution_error,
                execution_started_at,
                execution_completed_at,
                validation_status,
                user_approved,
                skip_migration,
                validated_at,
                validated_by,
                validation_notes,
                filename,
                mime_type
            FROM dbo.migration_staging
            WHERE batch_id = '{batch_id}'
            ORDER BY execution_completed_at DESC, id DESC
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        print(f"[LOGS] Found {len(df)} records for batch {batch_id}")
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        logs = df_to_json_safe(df)
        
        # Parse execution_error JSON if present
        for log in logs:
            if log.get('execution_error'):
                try:
                    log['execution_error'] = json.loads(log['execution_error'])
                except:
                    pass
        
        return jsonify({'success': True, 'logs': logs})
        
    except Exception as e:
        print(f"[LOGS_ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/details')
def details_page():
    """Migration details page - combined document and file view."""
    batch_id = request.args.get('batch_id')
    return render_template('migration_details.html', batch_id=batch_id, **get_template_context())


# Legacy routes - redirect to new details page
@migrate_bp.route('/logs')
def logs_page():
    """Redirect to new details page."""
    batch_id = request.args.get('batch_id')
    return redirect(f'/details?batch_id={batch_id}' if batch_id else '/details')


@migrate_bp.route('/file-report')
def file_report_page():
    """Redirect to new details page."""
    batch_id = request.args.get('batch_id')
    return redirect(f'/details?batch_id={batch_id}' if batch_id else '/details')


# =============================================================================
# FILE DETAILS API
# =============================================================================

@migrate_bp.route('/batch/<batch_id>/file-details', methods=['GET'])
def get_batch_file_details(batch_id):
    """
    Get detailed file-level migration results for a batch.
    
    Query Parameters:
        - status: Filter by upload_status (SUCCESS, UPLOAD_FAIL, etc.)
        - error_category: Filter by error category (AUTH_ERROR, TIMEOUT, etc.)
        - staging_id: Filter by specific container/staging ID
        - filename: Filter by filename (partial match)
        - has_error: Filter for files with errors (true/false)
        - page: Page number (default 1)
        - per_page: Results per page (default 100, max 1000)
    """
    try:
        print(f"[FILE_DETAILS] Fetching file details for batch: {batch_id}")
        
        # Parse filter parameters
        status_filter = request.args.get('status')
        error_category_filter = request.args.get('error_category')
        staging_id_filter = request.args.get('staging_id')
        filename_filter = request.args.get('filename')
        has_error_filter = request.args.get('has_error')
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(1000, max(10, int(request.args.get('per_page', 100))))
        
        # Build dynamic WHERE clause
        where_clauses = ["fd.batch_id = :batch_id"]
        params = {'batch_id': batch_id}
        
        if status_filter:
            where_clauses.append("fd.upload_status LIKE :status")
            params['status'] = f"%{status_filter}%"
        
        if error_category_filter:
            where_clauses.append("fd.error_category = :error_category")
            params['error_category'] = error_category_filter
        
        if staging_id_filter:
            where_clauses.append("fd.staging_id = :staging_id")
            params['staging_id'] = int(staging_id_filter)
        
        if filename_filter:
            where_clauses.append("fd.filename LIKE :filename")
            params['filename'] = f"%{filename_filter}%"
        
        if has_error_filter:
            if has_error_filter.lower() == 'true':
                where_clauses.append("fd.upload_status <> 'SUCCESS'")
            else:
                where_clauses.append("fd.upload_status = 'SUCCESS'")
        
        where_sql = " AND ".join(where_clauses)
        
        # Get total count for pagination
        count_query = f"""
            SELECT COUNT(*) as total
            FROM dbo.migration_file_details fd
            WHERE {where_sql}
        """
        
        # Main query with staging info join
        offset = (page - 1) * per_page
        query = f"""
            SELECT 
                fd.id,
                fd.staging_id,
                fd.file_index,
                fd.filename,
                fd.loio_id,
                fd.file_size_bytes,
                fd.file_size_mb,
                fd.mime_type,
                fd.upload_status,
                fd.http_status_code,
                fd.upload_time_seconds,
                fd.error_category,
                fd.error_code,
                fd.error_detail,
                fd.error_messages,
                fd.is_size_error,
                fd.created_at,
                s.source_documentnumber,
                s.source_documenttype,
                s.target_documentnumber,
                s.source_description
            FROM dbo.migration_file_details fd
            LEFT JOIN dbo.migration_staging s ON fd.staging_id = s.id
            WHERE {where_sql}
            ORDER BY fd.staging_id, fd.file_index
            OFFSET :offset ROWS FETCH NEXT :per_page ROWS ONLY
        """
        params['offset'] = offset
        params['per_page'] = per_page
        
        with misc_engine.begin() as con:
            # Get total count
            count_result = con.execute(text(count_query), params).fetchone()
            total_count = count_result[0] if count_result else 0
            
            # Get file details
            df = pd.read_sql(text(query), con, params=params)
        
        print(f"[FILE_DETAILS] Found {len(df)} file records (page {page}, total: {total_count})")
        
        # Convert to JSON-safe records (handles NaN/NaT properly)
        file_details = df_to_json_safe(df)
        
        # Parse JSON error_messages if present
        for detail in file_details:
            if detail.get('error_messages'):
                try:
                    detail['error_messages'] = json.loads(detail['error_messages'])
                except:
                    pass
        
        return jsonify({
            'success': True, 
            'file_details': file_details,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'total_pages': (total_count + per_page - 1) // per_page
            }
        })
        
    except Exception as e:
        print(f"[FILE_DETAILS_ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/file-details/summary', methods=['GET'])
def get_batch_file_summary(batch_id):
    """
    Get aggregated summary statistics for file-level migration results.
    Useful for populating filter dropdowns and showing overview stats.
    """
    try:
        summary_query = """
            SELECT 
                COUNT(*) as total_files,
                SUM(CASE WHEN upload_status = 'SUCCESS' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN upload_status <> 'SUCCESS' THEN 1 ELSE 0 END) as error_count,
                SUM(CASE WHEN is_size_error = 1 THEN 1 ELSE 0 END) as size_error_count,
                COUNT(DISTINCT staging_id) as container_count,
                SUM(file_size_bytes) as total_bytes,
                AVG(CAST(upload_time_seconds AS FLOAT)) as avg_upload_time
            FROM dbo.migration_file_details
            WHERE batch_id = :batch_id
        """
        
        status_query = """
            SELECT upload_status, COUNT(*) as count
            FROM dbo.migration_file_details
            WHERE batch_id = :batch_id
            GROUP BY upload_status
            ORDER BY count DESC
        """
        
        error_category_query = """
            SELECT error_category, COUNT(*) as count
            FROM dbo.migration_file_details
            WHERE batch_id = :batch_id AND error_category IS NOT NULL
            GROUP BY error_category
            ORDER BY count DESC
        """
        
        containers_with_errors_query = """
            SELECT 
                fd.staging_id,
                s.source_documentnumber,
                COUNT(*) as file_count,
                SUM(CASE WHEN fd.upload_status <> 'SUCCESS' THEN 1 ELSE 0 END) as error_count
            FROM dbo.migration_file_details fd
            LEFT JOIN dbo.migration_staging s ON fd.staging_id = s.id
            WHERE fd.batch_id = :batch_id
            GROUP BY fd.staging_id, s.source_documentnumber
            HAVING SUM(CASE WHEN fd.upload_status <> 'SUCCESS' THEN 1 ELSE 0 END) > 0
            ORDER BY error_count DESC
        """
        
        with misc_engine.begin() as con:
            # Main summary
            summary_result = con.execute(text(summary_query), {'batch_id': batch_id}).fetchone()
            
            # Status distribution
            status_df = pd.read_sql(text(status_query), con, params={'batch_id': batch_id})
            status_dist = df_to_json_safe(status_df)
            
            # Error category distribution
            error_df = pd.read_sql(text(error_category_query), con, params={'batch_id': batch_id})
            error_dist = df_to_json_safe(error_df)
            
            # Containers with errors
            containers_df = pd.read_sql(text(containers_with_errors_query), con, params={'batch_id': batch_id})
            containers_with_errors = df_to_json_safe(containers_df)
        
        summary = {
            'total_files': summary_result[0] or 0,
            'success_count': summary_result[1] or 0,
            'error_count': summary_result[2] or 0,
            'size_error_count': summary_result[3] or 0,
            'container_count': summary_result[4] or 0,
            'total_bytes': summary_result[5] or 0,
            'total_mb': round((summary_result[5] or 0) / 1024 / 1024, 2),
            'avg_upload_time': round(summary_result[6] or 0, 2)
        }
        
        return jsonify({
            'success': True,
            'summary': summary,
            'status_distribution': status_dist,
            'error_categories': error_dist,
            'containers_with_errors': containers_with_errors
        })
        
    except Exception as e:
        print(f"[FILE_SUMMARY_ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/file-details/export/<batch_id>', methods=['GET'])
def export_file_details(batch_id):
    """Export file details as CSV for external analysis."""
    try:
        query = """
            SELECT 
                fd.staging_id,
                s.source_documentnumber,
                s.source_documenttype,
                s.source_description,
                fd.file_index,
                fd.filename,
                fd.loio_id,
                fd.file_size_bytes,
                fd.file_size_mb,
                fd.mime_type,
                fd.upload_status,
                fd.http_status_code,
                fd.upload_time_seconds,
                fd.error_category,
                fd.error_code,
                fd.error_detail,
                fd.is_size_error,
                fd.created_at
            FROM dbo.migration_file_details fd
            LEFT JOIN dbo.migration_staging s ON fd.staging_id = s.id
            WHERE fd.batch_id = :batch_id
            ORDER BY fd.staging_id, fd.file_index
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(text(query), con, params={'batch_id': batch_id})
        
        # Generate CSV
        from io import StringIO
        from flask import Response
        
        output = StringIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=file_details_{batch_id}.csv'}
        )
        
    except Exception as e:
        print(f"[EXPORT_ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# OBJECT MAPPING API (per Batch)
# =============================================================================

@migrate_bp.route('/api/batch/<batch_id>')
def get_batch_info_api(batch_id):
    """Get batch info for API calls."""
    try:
        with misc_engine.begin() as con:
            batch_query = """
                SELECT batch_id, wave, description, total_records, status, created_at
                FROM dbo.migration_batch
                WHERE batch_id = :batch_id
            """
            batch_row = con.execute(text(batch_query), {'batch_id': batch_id}).fetchone()
            if batch_row:
                batch_info = {
                    'batch_id': batch_row[0],
                    'wave': batch_row[1],
                    'description': batch_row[2],
                    'total_records': batch_row[3],
                    'status': batch_row[4],
                    'created_at': str(batch_row[5]) if batch_row[5] else None
                }
                return jsonify({'success': True, 'batch': batch_info})
            else:
                return jsonify({'success': False, 'error': 'Batch not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping')
def batch_object_mapping_page(batch_id):
    """Object mapping management page for a specific batch."""
    return render_template('object_mapping.html', batch_id=batch_id, **get_template_context())


@migrate_bp.route('/batch/<batch_id>/object-mapping/list', methods=['GET'])
def list_batch_object_mappings(batch_id):
    """Get all object mappings for a specific batch."""
    try:
        init_staging_tables(misc_engine)
        
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
        init_staging_tables(misc_engine)
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
        init_staging_tables(misc_engine)
        
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
            staging_query = """
                SELECT 
                    source_dokob,
                    source_objky,
                    COUNT(*) as document_count
                FROM dbo.migration_staging
                WHERE batch_id = :batch_id AND source_dokob IS NOT NULL AND source_objky IS NOT NULL
                GROUP BY source_dokob, source_objky
                ORDER BY source_dokob, source_objky
            """
            df_staging = pd.read_sql(text(staging_query), con, params={'batch_id': batch_id})
            
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
        init_staging_tables(misc_engine)
        
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
        
        return jsonify({
            'success': True,
            'message': f'Upload complete: {added} added, {updated} updated, {skipped} skipped',
            'added': added,
            'updated': updated,
            'skipped': skipped
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/object-mapping/stats', methods=['GET'])
def batch_object_mapping_stats(batch_id):
    """Get statistics about object mappings for a batch."""
    try:
        init_staging_tables(misc_engine)
        
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
        init_staging_tables(misc_engine)
        
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
        init_staging_tables(misc_engine)
        
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
    This updates target_dokob and target_objky in the staging table based on mappings.
    Should be called after uploading mappings and before execution.
    """
    try:
        from app.prepare import apply_object_mappings_for_batch
        
        updated = apply_object_mappings_for_batch(batch_id)
        
        return jsonify({
            'success': True, 
            'message': f'Applied mappings to {updated} staging records',
            'updated': updated
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==============================================================================
# DMS OBJEKTE - Routes für die Werksfilterung und DMS-Daten-Ladung aus DIL
# ==============================================================================

@migrate_bp.route('/dms-objects')
def dms_objects():
    """Display DMS Objects page with plant/Werk filter."""
    context = get_template_context()
    return render_template('dms_objects.html', **context)


@migrate_bp.route('/api/dms/werke', methods=['GET'])
def get_dms_werke():
    """
    Get list of all Werke (plants) from cached JSON file.
    Run load_werke_cache.py to refresh the cache.
    """
    try:
        cache_file = 'userdata/werke_cache.json'
        
        if not os.path.exists(cache_file):
            return jsonify({
                'success': False, 
                'error': 'Werke-Cache nicht gefunden. Bitte load_werke_cache.py ausführen.'
            }), 404
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        return jsonify({
            'success': True,
            'werke': cache_data['werke'],
            'total_werke': cache_data['total_werke'],
            'total_objects': cache_data['total_objects'],
            'generated_at': cache_data.get('generated_at', 'unknown'),
            'source': cache_data.get('source', 'unknown')
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'success': False, 
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@migrate_bp.route('/api/dms/load', methods=['POST'])
def load_dms_objects():
    """
    Load DMS objects from DIL for selected Werke.
    Returns DRAD records with their Werk assignment.
    Executes queries sequentially per DOKOB for better performance.
    """
    import time
    start_time = time.time()
    
    try:
        from app_config import DilEngine
        import pandas as pd
        
        print(f"[DMS Load] Starting load_dms_objects...")
        
        data = request.get_json()
        selected_werke = data.get('werke', [])
        
        if not selected_werke:
            return jsonify({'success': False, 'error': 'Keine Werke ausgewählt'}), 400
        
        print(f"[DMS Load] Selected Werke: {selected_werke}")
        
        dil_db = DilEngine.load()
        if dil_db.engine is None:
            return jsonify({'success': False, 'error': 'DIL database not connected'}), 500
        
        # Build the filter for Werke
        werke_filter = "', '".join(selected_werke)
        
        # Define queries per DOKOB - executed sequentially for better performance
        # Exclusion rules applied:
        # - EQUI/IFLOT: Exclude if JEST status I0320, I0013, I0076 (deleted)
        # - PMAUFK: Exclude if JEST status I0045 (TECO) or I0013, I0076 (deleted)
        # - PMQMEL/SMQMEL: Exclude if JEST status I0072 (closed) or I0076 (deleted)
        # - PMAFVC: Exclude if parent order is TECO/deleted
        # - STKO_DOC: Exclude if STKO.LOEKZ = 'X'
        # - STPO_DOC: Exclude if STPO.LKENZ = 'X'
        # - PLKO: Exclude if PLKO.LOEKZ = 'X'
        queries = {
            'EQUI': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY, 
                       equz.IWERK as WERK
                FROM DIL.DRAD drad
                JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231'
                JOIN DIL.EQUI equi ON drad.OBJKY = equi.EQUNR
                WHERE drad.DOKOB = 'EQUI' AND equz.IWERK IN ('{werke_filter}')
                  AND NOT EXISTS (
                      SELECT 1 FROM DIL.JEST j 
                      WHERE j.OBJNR = equi.OBJNR 
                      AND j.STAT IN ('I0320', 'I0013', 'I0076')
                      AND (j.INACT IS NULL OR j.INACT = '')
                  )
            """,
            'IFLOT': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       iflot.IWERK as WERK
                FROM DIL.DRAD drad
                JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR
                WHERE drad.DOKOB = 'IFLOT' AND iflot.IWERK IN ('{werke_filter}')
                  AND NOT EXISTS (
                      SELECT 1 FROM DIL.JEST j 
                      WHERE j.OBJNR = iflot.OBJNR 
                      AND j.STAT IN ('I0320', 'I0013', 'I0076')
                      AND (j.INACT IS NULL OR j.INACT = '')
                  )
            """,
            'MPLA': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) as WERK
                FROM DIL.DRAD drad
                JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
                LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
                WHERE drad.DOKOB = 'MPLA' 
                  AND COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) IN ('{werke_filter}')
            """,
            'PMPLKO': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       plko.WERKS as WERK
                FROM DIL.DRAD drad
                JOIN DIL.PLKO plko ON 
                    LEFT(drad.OBJKY, 1) = plko.PLNTY AND
                    SUBSTRING(drad.OBJKY, 2, 8) = plko.PLNNR AND
                    RIGHT(drad.OBJKY, 2) = plko.PLNAL
                WHERE drad.DOKOB = 'PMPLKO' AND plko.WERKS IN ('{werke_filter}')
                  AND (plko.LOEKZ IS NULL OR plko.LOEKZ = '')
            """,
            'PMAUFK': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       aufk.WERKS as WERK
                FROM DIL.DRAD drad
                JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR
                WHERE drad.DOKOB = 'PMAUFK' AND aufk.WERKS IN ('{werke_filter}')
                  AND NOT EXISTS (
                      SELECT 1 FROM DIL.JEST j 
                      WHERE j.OBJNR = aufk.OBJNR 
                      AND j.STAT IN ('I0045', 'I0013', 'I0076')
                      AND (j.INACT IS NULL OR j.INACT = '')
                  )
            """,
            'PMAFVC': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       afvc.WERKS as WERK
                FROM DIL.DRAD drad
                JOIN DIL.AFVC afvc ON 
                    SUBSTRING(drad.OBJKY, 3, 10) = afvc.AUFPL AND
                    SUBSTRING(drad.OBJKY, 13, 8) = afvc.APLZL
                JOIN DIL.AFKO afko ON afvc.AUFPL = afko.AUFPL
                JOIN DIL.AUFK aufk ON afko.AUFNR = aufk.AUFNR
                WHERE drad.DOKOB = 'PMAFVC' AND afvc.WERKS IN ('{werke_filter}')
                  AND NOT EXISTS (
                      SELECT 1 FROM DIL.JEST j 
                      WHERE j.OBJNR = aufk.OBJNR 
                      AND j.STAT IN ('I0045', 'I0013', 'I0076')
                      AND (j.INACT IS NULL OR j.INACT = '')
                  )
            """,
            'PMQMEL': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       qmih.IWERK as WERK
                FROM DIL.DRAD drad
                JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
                WHERE drad.DOKOB = 'PMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                  AND NOT EXISTS (
                      SELECT 1 FROM DIL.JEST j 
                      WHERE j.OBJNR = qmel.OBJNR 
                      AND j.STAT IN ('I0072', 'I0076')
                      AND (j.INACT IS NULL OR j.INACT = '')
                  )
            """,
            'SMQMEL': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       qmih.IWERK as WERK
                FROM DIL.DRAD drad
                JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
                WHERE drad.DOKOB = 'SMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                  AND NOT EXISTS (
                      SELECT 1 FROM DIL.JEST j 
                      WHERE j.OBJNR = qmel.OBJNR 
                      AND j.STAT IN ('I0072', 'I0076')
                      AND (j.INACT IS NULL OR j.INACT = '')
                  )
            """,
            'STKO_DOC': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       stko.WRKAN as WERK
                FROM DIL.DRAD drad
                JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
                WHERE drad.DOKOB = 'STKO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                  AND (stko.LOEKZ IS NULL OR stko.LOEKZ = '')
            """,
            'STPO_DOC': f"""
                SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                       stko.WRKAN as WERK
                FROM DIL.DRAD drad
                JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX)
                JOIN DIL.STKO stko ON stpo.STLNR = stko.STLNR
                WHERE drad.DOKOB = 'STPO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                  AND (stpo.LKENZ IS NULL OR stpo.LKENZ = '')
            """
        }
        
        all_results = []
        stats = {}
        
        with dil_db.engine.begin() as con:
            for dokob, query in queries.items():
                query_start = time.time()
                print(f"[DMS Load] Querying {dokob}...")
                try:
                    df = pd.read_sql(query, con)
                    count = len(df)
                    stats[dokob] = count
                    if count > 0:
                        all_results.append(df)
                    query_time = time.time() - query_start
                    print(f"[DMS Load] {dokob}: {count} records in {query_time:.2f}s")
                except Exception as e:
                    print(f"[DMS Load] ERROR in {dokob}: {str(e)}")
                    stats[dokob] = f"ERROR: {str(e)}"
        
        # Combine all results
        if all_results:
            combined_df = pd.concat(all_results, ignore_index=True)
            data_list = combined_df.to_dict(orient='records')
        else:
            data_list = []
        
        stats['total'] = len(data_list)
        total_time = time.time() - start_time
        print(f"[DMS Load] Completed: {len(data_list)} total records in {total_time:.2f}s")
        
        # Auto-save to SQLite if requested
        saved = False
        if data.get('auto_save', False) and data_list:
            try:
                import sqlite3
                os.makedirs('userdata', exist_ok=True)
                db_path = 'userdata/dms_objects.db'
                conn = sqlite3.connect(db_path)
                df_save = pd.DataFrame(data_list)
                df_save.to_sql('dms_objects', conn, if_exists='replace', index=False)
                conn.close()
                saved = True
                print(f"[DMS Load] Auto-saved {len(data_list)} records to {db_path}")
            except Exception as save_error:
                print(f"[DMS Load] Auto-save failed: {save_error}")
        
        return jsonify({
            'success': True,
            'data': data_list,
            'stats': stats,
            'count': len(data_list),
            'query_time': f"{total_time:.2f}s",
            'saved': saved
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'success': False, 
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@migrate_bp.route('/api/dms/load-stream')
def load_dms_objects_stream():
    """
    Load DMS objects with Server-Sent Events for real-time progress.
    Query parameters: werke (comma-separated), auto_save (boolean)
    """
    from flask import Response
    import time
    import json
    
    werke_param = request.args.get('werke', '')
    auto_save = request.args.get('auto_save', 'true').lower() == 'true'
    selected_werke = [w.strip() for w in werke_param.split(',') if w.strip()]
    
    def generate():
        start_time = time.time()
        
        try:
            from app_config import DilEngine
            import pandas as pd
            
            if not selected_werke:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Keine Werke ausgewählt'})}\n\n"
                return
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Verbinde mit DIL...', 'percent': 5})}\n\n"
            
            dil_db = DilEngine.load()
            if dil_db.engine is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'DIL database not connected'})}\n\n"
                return
            
            werke_filter = "', '".join(selected_werke)
            
            # Define queries per DOKOB with exclusion rules
            # - EQUI/IFLOT: Exclude if JEST status I0320, I0013, I0076 (deleted)
            # - PMAUFK: Exclude if JEST status I0045 (TECO) or I0013, I0076 (deleted)
            # - PMQMEL/SMQMEL: Exclude if JEST status I0072 (closed) or I0076 (deleted)
            # - PMAFVC: Exclude if parent order is TECO/deleted
            # - STKO_DOC: Exclude if STKO.LOEKZ = 'X'
            # - STPO_DOC: Exclude if STPO.LKENZ = 'X'
            # - PLKO: Exclude if PLKO.LOEKZ = 'X'
            queries = {
                'EQUI': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY, 
                           equz.IWERK as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231'
                    JOIN DIL.EQUI equi ON drad.OBJKY = equi.EQUNR
                    WHERE drad.DOKOB = 'EQUI' AND equz.IWERK IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = equi.OBJNR 
                          AND j.STAT IN ('I0320', 'I0013', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'IFLOT': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           iflot.IWERK as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR
                    WHERE drad.DOKOB = 'IFLOT' AND iflot.IWERK IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = iflot.OBJNR 
                          AND j.STAT IN ('I0320', 'I0013', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'MPLA': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
                    LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
                    WHERE drad.DOKOB = 'MPLA' 
                      AND COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) IN ('{werke_filter}')
                """,
                'PMPLKO': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           plko.WERKS as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.PLKO plko ON 
                        LEFT(drad.OBJKY, 1) = plko.PLNTY AND
                        SUBSTRING(drad.OBJKY, 2, 8) = plko.PLNNR AND
                        RIGHT(drad.OBJKY, 2) = plko.PLNAL
                    WHERE drad.DOKOB = 'PMPLKO' AND plko.WERKS IN ('{werke_filter}')
                      AND (plko.LOEKZ IS NULL OR plko.LOEKZ = '')
                """,
                'PMAUFK': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           aufk.WERKS as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR
                    WHERE drad.DOKOB = 'PMAUFK' AND aufk.WERKS IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = aufk.OBJNR 
                          AND j.STAT IN ('I0045', 'I0013', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'PMAFVC': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           afvc.WERKS as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.AFVC afvc ON 
                        SUBSTRING(drad.OBJKY, 3, 10) = afvc.AUFPL AND
                        SUBSTRING(drad.OBJKY, 13, 8) = afvc.APLZL
                    JOIN DIL.AFKO afko ON afvc.AUFPL = afko.AUFPL
                    JOIN DIL.AUFK aufk ON afko.AUFNR = aufk.AUFNR
                    WHERE drad.DOKOB = 'PMAFVC' AND afvc.WERKS IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = aufk.OBJNR 
                          AND j.STAT IN ('I0045', 'I0013', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'PMQMEL': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           qmih.IWERK as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
                    WHERE drad.DOKOB = 'PMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = qmel.OBJNR 
                          AND j.STAT IN ('I0072', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'SMQMEL': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           qmih.IWERK as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    JOIN DIL.QMEL qmel ON drad.OBJKY = qmel.QMNUM
                    WHERE drad.DOKOB = 'SMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                      AND NOT EXISTS (
                          SELECT 1 FROM DIL.JEST j 
                          WHERE j.OBJNR = qmel.OBJNR 
                          AND j.STAT IN ('I0072', 'I0076')
                          AND (j.INACT IS NULL OR j.INACT = '')
                      )
                """,
                'STKO_DOC': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           stko.WRKAN as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
                    WHERE drad.DOKOB = 'STKO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                      AND (stko.LOEKZ IS NULL OR stko.LOEKZ = '')
                """,
                'STPO_DOC': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           stko.WRKAN as WERK
                    FROM DIL.DRAD drad
                    JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX)
                    JOIN DIL.STKO stko ON stpo.STLNR = stko.STLNR
                    WHERE drad.DOKOB = 'STPO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                      AND (stpo.LKENZ IS NULL OR stpo.LKENZ = '')
                """
            }
            
            # Define count queries (without exclusion filter) to calculate excluded count
            count_queries = {
                'EQUI': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.EQUZ equz ON drad.OBJKY = equz.EQUNR AND equz.DATBI = '99991231'
                    WHERE drad.DOKOB = 'EQUI' AND equz.IWERK IN ('{werke_filter}')
                """,
                'IFLOT': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.IFLOT iflot ON drad.OBJKY = iflot.TPLNR
                    WHERE drad.DOKOB = 'IFLOT' AND iflot.IWERK IN ('{werke_filter}')
                """,
                'MPLA': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
                    LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
                    WHERE drad.DOKOB = 'MPLA' 
                      AND COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) IN ('{werke_filter}')
                """,
                'PMPLKO': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.PLKO plko ON 
                        LEFT(drad.OBJKY, 1) = plko.PLNTY AND
                        SUBSTRING(drad.OBJKY, 2, 8) = plko.PLNNR AND
                        RIGHT(drad.OBJKY, 2) = plko.PLNAL
                    WHERE drad.DOKOB = 'PMPLKO' AND plko.WERKS IN ('{werke_filter}')
                """,
                'PMAUFK': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.AUFK aufk ON drad.OBJKY = aufk.AUFNR
                    WHERE drad.DOKOB = 'PMAUFK' AND aufk.WERKS IN ('{werke_filter}')
                """,
                'PMAFVC': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.AFVC afvc ON 
                        SUBSTRING(drad.OBJKY, 3, 10) = afvc.AUFPL AND
                        SUBSTRING(drad.OBJKY, 13, 8) = afvc.APLZL
                    WHERE drad.DOKOB = 'PMAFVC' AND afvc.WERKS IN ('{werke_filter}')
                """,
                'PMQMEL': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    WHERE drad.DOKOB = 'PMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                """,
                'SMQMEL': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.QMIH qmih ON drad.OBJKY = qmih.QMNUM
                    WHERE drad.DOKOB = 'SMQMEL' AND qmih.IWERK IN ('{werke_filter}')
                """,
                'STKO_DOC': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
                    WHERE drad.DOKOB = 'STKO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                """,
                'STPO_DOC': f"""
                    SELECT COUNT(*) FROM DIL.DRAD drad
                    JOIN DIL.STPO stpo ON drad.OBJKY = BINTOHEX(stpo.GUIDX)
                    JOIN DIL.STKO stko ON stpo.STLNR = stko.STLNR
                    WHERE drad.DOKOB = 'STPO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                """
            }
            
            all_results = []
            stats = {}
            stats_total = {}  # Total counts without exclusion
            stats_excluded = {}  # Excluded counts
            total_queries = len(queries)
            
            with dil_db.engine.begin() as con:
                for idx, (dokob, query) in enumerate(queries.items()):
                    percent = 10 + int((idx / total_queries) * 80)
                    yield f"data: {json.dumps({'type': 'progress', 'dokob': dokob, 'message': f'Lade {dokob}...', 'percent': percent, 'step': idx + 1, 'total_steps': total_queries})}\n\n"
                    
                    query_start = time.time()
                    try:
                        # Get filtered data
                        df = pd.read_sql(query, con)
                        count = len(df)
                        stats[dokob] = count
                        if count > 0:
                            all_results.append(df)
                        
                        # Get total count (without filter) for exclusion statistics
                        total_count = count  # Default to same as filtered
                        excluded_count = 0
                        if dokob in count_queries:
                            try:
                                result = con.execute(text(count_queries[dokob]))
                                total_count = result.scalar() or 0
                                excluded_count = total_count - count
                            except Exception as count_err:
                                print(f"[DMS Load] Count query error for {dokob}: {count_err}")
                        
                        stats_total[dokob] = total_count
                        stats_excluded[dokob] = excluded_count
                        
                        query_time = time.time() - query_start
                        
                        yield f"data: {json.dumps({'type': 'step_complete', 'dokob': dokob, 'count': count, 'total': total_count, 'excluded': excluded_count, 'time': f'{query_time:.2f}s', 'percent': percent + 5})}\n\n"
                        print(f"[DMS Load] {dokob}: {count} records (excluded {excluded_count}) in {query_time:.2f}s")
                    except Exception as e:
                        print(f"[DMS Load] ERROR in {dokob}: {str(e)}")
                        stats[dokob] = 0
                        yield f"data: {json.dumps({'type': 'step_error', 'dokob': dokob, 'error': str(e)})}\n\n"
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Verarbeite Daten...', 'percent': 95})}\n\n"
            
            # Combine all results
            if all_results:
                combined_df = pd.concat(all_results, ignore_index=True)
                data_list = combined_df.to_dict(orient='records')
            else:
                data_list = []
            
            stats['total'] = len(data_list)
            total_time = time.time() - start_time
            
            # Auto-save to SQLite
            saved = False
            if auto_save and data_list:
                try:
                    import sqlite3
                    os.makedirs('userdata', exist_ok=True)
                    db_path = 'userdata/dms_objects.db'
                    conn = sqlite3.connect(db_path)
                    df_save = pd.DataFrame(data_list)
                    df_save.to_sql('dms_objects', conn, if_exists='replace', index=False)
                    conn.close()
                    saved = True
                    print(f"[DMS Load] Auto-saved {len(data_list)} records to {db_path}")
                except Exception as save_error:
                    print(f"[DMS Load] Auto-save failed: {save_error}")
            
            # Send final result with exclusion statistics
            yield f"data: {json.dumps({'type': 'complete', 'stats': stats, 'stats_total': stats_total, 'stats_excluded': stats_excluded, 'count': len(data_list), 'query_time': f'{total_time:.2f}s', 'saved': saved, 'data': data_list})}\n\n"
            
        except Exception as e:
            import traceback
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'traceback': traceback.format_exc()})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })


@migrate_bp.route('/api/dms/save', methods=['POST'])
def save_dms_objects():
    """
    Save loaded DMS objects to local SQLite database.
    Creates a new table or appends to existing.
    """
    try:
        import sqlite3
        
        data = request.get_json()
        objects = data.get('data', [])
        
        if not objects:
            return jsonify({'success': False, 'error': 'Keine Daten zum Speichern'}), 400
        
        # Create userdata folder if needed
        os.makedirs('userdata', exist_ok=True)
        
        # Save to SQLite
        db_path = 'userdata/dms_objects.db'
        conn = sqlite3.connect(db_path)
        
        # Create DataFrame and save
        import pandas as pd
        df = pd.DataFrame(objects)
        df.to_sql('dms_objects', conn, if_exists='replace', index=False)
        
        conn.close()
        
        return jsonify({
            'success': True,
            'count': len(objects),
            'db_path': db_path
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'success': False, 
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@migrate_bp.route('/api/dms/status', methods=['GET'])
def get_dms_status():
    """
    Get status of local DMS objects database.
    """
    try:
        import sqlite3
        db_path = 'userdata/dms_objects.db'
        
        if not os.path.exists(db_path):
            return jsonify({'success': True, 'count': 0, 'exists': False})
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dms_objects")
        count = cursor.fetchone()[0]
        conn.close()
        
        return jsonify({
            'success': True,
            'count': count,
            'exists': True,
            'db_path': db_path
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'count': 0,
            'error': str(e)
        })


@migrate_bp.route('/api/dms/dokob-stats', methods=['GET'])
def get_dms_dokob_stats():
    """
    Get DOKOB (object type) statistics from local DMS database.
    Returns count per DOKOB for filtering in batch creation.
    """
    try:
        import sqlite3
        db_path = 'userdata/dms_objects.db'
        
        if not os.path.exists(db_path):
            return jsonify({'success': True, 'dokobs': []})
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dokob, COUNT(*) as count 
            FROM dms_objects 
            GROUP BY dokob 
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        dokobs = [{'dokob': row[0] or 'UNKNOWN', 'count': row[1]} for row in rows]
        
        return jsonify({
            'success': True,
            'dokobs': dokobs
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@migrate_bp.route('/api/dms/create-batch-stream', methods=['GET'])
def create_dms_migration_batch_stream():
    """
    Create a migration batch from local DMS objects database using SSE for progress.
    Uses GET with query parameters for EventSource compatibility.
    
    Query params:
        wave: Wave identifier (required)
        description: Batch description
        notes: Additional notes
        dokob_filter: Comma-separated list of DOKOB values to include (optional, empty = all)
    """
    import sqlite3
    from datetime import datetime
    from app.db_schema import init_staging_tables
    
    wave = request.args.get('wave')
    description = request.args.get('description', '')
    notes = request.args.get('notes', '')
    dokob_filter = request.args.get('dokob_filter', '')  # Comma-separated list of DOKOBs
    
    if not wave:
        return jsonify({'success': False, 'error': 'Wave ist erforderlich'})
    
    db_path = 'userdata/dms_objects.db'
    if not os.path.exists(db_path):
        return jsonify({'success': False, 'error': 'Keine DMS-Objekte in lokaler Datenbank'})
    
    # Extract session data BEFORE the generator (outside request context)
    current_user = session.get('user_email', 'system')
    
    # Parse DOKOB filter
    dokob_list = [d.strip() for d in dokob_filter.split(',') if d.strip()] if dokob_filter else []
    
    def generate():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Lese lokale Datenbank...', 'percent': 5})}\n\n"
            
            # Read from SQLite with optional DOKOB filter
            conn = sqlite3.connect(db_path)
            if dokob_list:
                placeholders = ','.join(['?' for _ in dokob_list])
                query = f"SELECT * FROM dms_objects WHERE dokob IN ({placeholders})"
                dms_df = pd.read_sql(query, conn, params=dokob_list)
                filter_info = f"DOKOB-Filter: {', '.join(dokob_list)}"
            else:
                dms_df = pd.read_sql("SELECT * FROM dms_objects", conn)
                filter_info = "Alle Objekttypen"
            conn.close()
            
            if len(dms_df) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Keine DMS-Objekte gefunden (evtl. Filter zu streng)'})}\n\n"
                return
            
            total_records = len(dms_df)
            yield f"data: {json.dumps({'type': 'status', 'message': f'{total_records:,} Datensätze geladen ({filter_info})', 'percent': 10})}\n\n"
            
            # Generate batch ID
            batch_id = f"DMS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Ensure staging tables exist
            init_staging_tables(misc_engine)
            
            # Get unique Werke from the loaded data
            unique_werke = dms_df['werk'].unique().tolist() if 'werk' in dms_df.columns else []
            werke_str = ', '.join(sorted(unique_werke))
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Bereite Staging-Daten vor...', 'percent': 15})}\n\n"
            
            # Helper function to compute target document number
            # - Auto-generated IDs (25 digits, all numeric) → None (will get new number in target)
            # - Manual/external IDs (contain letters) → preserve as target number
            def compute_target_docnumber(doknr):
                if pd.isnull(doknr):
                    return None
                val = str(doknr).strip()
                # Check if this is an auto-generated ID (25 chars, all numeric after stripping leading zeros)
                if len(val) == 25:
                    try:
                        int(val.lstrip('0') or '0')
                        return None  # Auto-generated → will get new number
                    except (ValueError, TypeError):
                        pass
                # Manual/external ID → preserve it
                return val[:25]
            
            # Prepare staging DataFrame using vectorized operations (FAST!)
            # NOTE: target_* fields depend on whether source is auto-generated or manual
            # - Auto-generated IDs → target stays None (will get new number during migration)
            # - Manual/external IDs → target = source (preserve external number)
            staging_df = pd.DataFrame({
                'batch_id': batch_id,
                'created_by': current_user,
                'source_documentnumber': dms_df['doknr'].fillna(''),
                'source_documentpart': dms_df['doktl'].fillna('000'),
                'source_documenttype': dms_df['dokar'].fillna(''),
                'source_documentversion': dms_df['dokvr'].fillna('00'),
                'source_dokob': dms_df['dokob'].fillna(''),
                'source_objky': dms_df['objky'].fillna(''),
                'target_documentnumber': dms_df['doknr'].apply(compute_target_docnumber),
                'target_documentpart': dms_df['doktl'].fillna('000'),
                'target_documenttype': dms_df['dokar'].fillna(''),
                'target_documentversion': dms_df['dokvr'].fillna('00'),
                'user_approved': 0,
                'skip_migration': 0,
                'validation_status': 'pending',
                'execution_status': 'pending'
            })
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Schreibe in Staging-Datenbank...', 'percent': 20})}\n\n"
            
            # Save to staging database in chunks (SQL Server limit with method='multi' is ~1000)
            chunk_size = 900
            total_rows = len(staging_df)
            
            with misc_engine.begin() as con:
                for i in range(0, total_rows, chunk_size):
                    chunk_df = staging_df.iloc[i:i + chunk_size]
                    chunk_df.to_sql(
                        'migration_staging',
                        con,
                        schema='dbo',
                        if_exists='append',
                        index=False,
                        method='multi'
                    )
                    
                    # Calculate progress (20% to 90%)
                    progress = 20 + int(70 * min(i + chunk_size, total_rows) / total_rows)
                    rows_done = min(i + chunk_size, total_rows)
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'{rows_done:,} / {total_rows:,} Zeilen', 'percent': progress, 'rows': rows_done, 'total': total_rows})}\n\n"
                    print(f"[DMS Batch] Inserted rows {i+1}-{rows_done} of {total_rows}")
                
                yield f"data: {json.dumps({'type': 'status', 'message': 'Erstelle Batch-Eintrag...', 'percent': 95})}\n\n"
                
                # Create batch record with Werke info
                batch_record = pd.DataFrame([{
                    'batch_id': batch_id,
                    'created_by': current_user,
                    'source_file': f'DMS Objects: {werke_str}' if werke_str else 'dms_objects.db',
                    'total_records': len(staging_df),
                    'status': 'prepared',
                    'wave': wave,
                    'description': description[:40] if description else None,
                    'notes': f"Werke: {werke_str}\n{notes}" if werke_str else notes if notes else None
                }])
                
                batch_record.to_sql(
                    'migration_batch',
                    con,
                    schema='dbo',
                    if_exists='append',
                    index=False
                )
            
            print(f"[DMS Batch] Created batch {batch_id} with {len(staging_df)} records")
            
            yield f"data: {json.dumps({'type': 'complete', 'success': True, 'batch_id': batch_id, 'record_count': len(staging_df), 'wave': wave, 'percent': 100})}\n\n"
            
        except Exception as e:
            import traceback
            print(f"[DMS Batch ERROR] {e}")
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })
