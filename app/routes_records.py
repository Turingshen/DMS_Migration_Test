"""Record operations, rules, logs, and details routes."""

from flask import render_template, request, jsonify, session, Response
import pandas as pd
import json
from sqlalchemy import text

from app.blueprint import (
    migrate_bp, misc_engine, get_template_context, df_to_json_safe,
)


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
    """Reset all failed and partial records across all batches."""
    try:
        with misc_engine.begin() as con:
            result = con.execute(text("""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE execution_status IN ('failed', 'partial')
                    AND skip_migration = 0
            """))
            reset_count = result.rowcount
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} failed/partial records reset to pending'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/reset_failed', methods=['POST'])
def reset_failed():
    """Reset all failed AND partial records to pending status (without re-executing).
    
    For partial records: container_created and target_documentnumber are preserved.
    The execution loop will detect container_created=1 and skip already-uploaded files
    via get_successfully_uploaded_files() ? SUCCESS_SKIPPED.
    """
    try:
        data = request.get_json()
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        # Reset all failed AND partial records to pending
        # Note: container_created and target_documentnumber are NOT cleared,
        # so partial records will only retry the missing files.
        with misc_engine.begin() as con:
            result = con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET execution_status = 'pending',
                    execution_error = NULL,
                    execution_started_at = NULL,
                    execution_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND execution_status IN ('failed', 'partial')
                    AND skip_migration = 0
            """))
            reset_count = result.rowcount
        
        return jsonify({
            'success': True,
            'reset_count': reset_count,
            'message': f'{reset_count} failed/partial records reset to pending'
        })
        
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


