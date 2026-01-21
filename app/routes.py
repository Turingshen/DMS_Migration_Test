"""
Flask routes for document migration workflow.
Implements two-step migration: prepare -> validate -> execute
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
import pandas as pd
import os
import json
from werkzeug.utils import secure_filename
from sqlalchemy import text

from app.prepare import prepare_migration
from app.execute import execute_migration
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
    
    # Make test request
    base_url = cfg.get(read_sap_system, "api_list", "document", "base_url")
    test_params = {
        "Documentnumber": "0000000000000010002159971",
        "Documentpart": "000",
        "Documenttype": "IY1",
        "Documentversion": "00"
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
            result = prepare_migration(filepath)
        else:
            # Prepare migration from database query
            custom_query = request.form.get('custom_query', '').strip()
            query_source = request.form.get('query_source', 'dil')  # 'dil' or 'datastore'
            result = prepare_migration(custom_query=custom_query if custom_query else None, query_source=query_source)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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
            'remaining': int(total - executed),
            'progress_pct': round(progress_pct, 1),
            'is_running': row['status'] == 'executing'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/records', methods=['GET'])
def get_batch_records(batch_id):
    """Get all staging records for a batch."""
    try:
        query = f"""
            SELECT 
                id,
                source_documentnumber,
                source_documentpart,
                source_documenttype,
                source_documentversion,
                source_loioid,
                source_description,
                target_documentnumber,
                target_documentpart,
                target_documenttype,
                target_documentversion,
                filename,
                file_size_bytes,
                mime_type,
                authorization_group,
                validation_status,
                validation_notes,
                execution_status,
                execution_error,
                user_approved,
                skip_migration
            FROM dbo.migration_staging
            WHERE batch_id = '{batch_id}'
            ORDER BY id
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        # Replace NaN/NaT with None for JSON serialization (robust manual conversion)
        records = []
        for _, row in df.iterrows():
            rec = {}
            for col in df.columns:
                val = row[col]
                rec[col] = None if pd.isna(val) else val
            records.append(rec)
        return jsonify({'success': True, 'records': records})
        
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
            ORDER BY id
        """
        
        with misc_engine.begin() as con:
            df = pd.read_sql(query, con)
        
        # Replace NaN/NaT with None for JSON serialization (robust manual conversion)
        results = []
        for _, row in df.iterrows():
            rec = {}
            for col in df.columns:
                val = row[col]
                rec[col] = None if pd.isna(val) else val
            results.append(rec)
        
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
            SET target_value = :target_value,
                condition_column = :condition_column,
                condition_value = :condition_value,
                condition_operator = :condition_operator,
                execution_order = :execution_order,
                notes = :notes
            WHERE id = :id
        """)
        
        with misc_engine.begin() as con:
            con.execute(update_query, {
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
        
        # Convert DataFrame to dict with explicit None conversion for NaT/NaN
        logs = []
        for _, row in df.iterrows():
            log = {}
            for col in df.columns:
                val = row[col]
                if pd.isna(val):
                    log[col] = None
                else:
                    log[col] = val
            logs.append(log)
        
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


@migrate_bp.route('/logs')
def logs_page():
    """Log viewer page."""
    batch_id = request.args.get('batch_id')
    return render_template('logs.html', batch_id=batch_id, **get_template_context())
