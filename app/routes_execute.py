"""Execute migration, linking, progress and status routes."""

from flask import render_template, request, jsonify, session
import pandas as pd
import json
import os
from sqlalchemy import text

from app.blueprint import (
    migrate_bp, cfg, misc_engine, get_template_context,
    _is_authenticated, _build_session_snapshot, df_to_json_safe,
)
from app.execute import (
    execute_linking, request_cancel, is_cancel_requested, is_migration_running,
    request_link_cancel, is_linking_running,
    run_migration_background, run_linking_background,
    get_background_result,
)


@migrate_bp.route('/batch/<batch_id>/progress', methods=['GET'])
def get_batch_progress(batch_id):
    """Get execution progress for a batch (for live polling during execution)."""
    try:
        query = f"""
            SELECT 
                batch_id,
                status,
                migration_phase,
                total_records,
                executed_records,
                successful_records,
                failed_records,
                created_at,
                last_execution_started_at
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
        # Scope to current execution run to avoid stale counts from previous runs
        partial = 0
        try:
            exec_start = row.get('last_execution_started_at')
            with misc_engine.begin() as con:
                if exec_start and row['status'] == 'executing':
                    # During execution: only count partials from THIS run
                    partial_result = con.execute(text(f"""
                        SELECT COUNT(*) FROM dbo.migration_staging
                        WHERE batch_id = '{batch_id}' 
                            AND execution_status = 'partial'
                            AND execution_started_at >= :exec_start
                    """), {'exec_start': exec_start}).fetchone()
                else:
                    # Not executing: show all partials (batch overview)
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
            'migration_phase': row.get('migration_phase', 'upload'),
            'total': int(total),
            'executed': int(executed),
            'successful': int(success),
            'failed': int(failed),
            'partial': int(partial),
            'remaining': int(total - executed),
            'progress_pct': round(progress_pct, 1),
            'is_running': is_migration_running(batch_id)[0] or row['status'] == 'executing',
            'is_linking': is_linking_running(batch_id)[0] or row['status'] == 'linking',
            'background_result': get_background_result(batch_id) if not is_migration_running(batch_id)[0] and row['status'] != 'executing' else None
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
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 1 THEN 1 ELSE 0 END) as skipped_count,
                SUM(CASE WHEN execution_status = 'success' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN execution_status = 'pending' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as pending_count,
                SUM(CASE WHEN execution_status = 'failed' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as failed_count,
                SUM(CASE WHEN execution_status = 'partial' AND ISNULL(skip_migration, 0) = 0 THEN 1 ELSE 0 END) as partial_count,
                -- Ablage counts (only non-skipped)
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND ISNULL(ablage, 'KPRO') = 'KPRO' THEN 1 ELSE 0 END) as kpro_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND ablage = 'DB' THEN 1 ELSE 0 END) as db_count,
                -- Buckets count only non-skipped, non-success records for runtime estimation
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND (file_size_bytes IS NULL OR file_size_bytes = 0) THEN 1 ELSE 0 END) as unknown_size_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 0 AND file_size_bytes <= 1048576 THEN 1 ELSE 0 END) as tiny_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 1048576 AND file_size_bytes <= 10485760 THEN 1 ELSE 0 END) as small_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 10485760 AND file_size_bytes <= 52428800 THEN 1 ELSE 0 END) as medium_count,
                SUM(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 52428800 THEN 1 ELSE 0 END) as large_count,
                -- Total size only for non-skipped, non-success records
                SUM(CAST(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' AND file_size_bytes > 0 THEN file_size_bytes ELSE 0 END AS BIGINT)) as total_size_bytes,
                MAX(CASE WHEN ISNULL(skip_migration, 0) = 0 AND execution_status != 'success' THEN file_size_bytes ELSE 0 END) as max_file_size
            FROM dbo.migration_staging
            WHERE batch_id = :batch_id
        """)
        
        with misc_engine.begin() as con:
            result = con.execute(query, {'batch_id': batch_id}).fetchone()
        
        if not result or result.total_records == 0:
            return jsonify({'success': False, 'error': 'Batch not found or empty'}), 404
        
        skipped_count = result.skipped_count or 0
        total_active = (result.total_records or 0) - skipped_count
        
        # Use actual pending count from DB (records with execution_status = 'pending')
        actual_pending_count = result.pending_count or 0
        # Also calculate "to execute" count (all non-success, non-skipped)
        to_execute_count = total_active - (result.success_count or 0)
        
        return jsonify({
            'success': True,
            'stats': {
                'total': result.total_records or 0,
                'total_active': total_active,
                'skipped': skipped_count,
                'success': result.success_count or 0,
                'pending': actual_pending_count,  # Real pending from DB
                'to_execute': to_execute_count,   # All non-success, non-skipped
                'failed': result.failed_count or 0,
                'partial': result.partial_count or 0,
                'kpro': result.kpro_count or 0,
                'db': result.db_count or 0,
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
                    AND execution_status IN ('failed', 'partial')
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
        search: Full-text search across DOKNR, OBJKY, description (server-side, searches ALL records)
        ablage_filter: Filter by ablage value ('KPRO' or 'DB')
    """
    try:
        # Parse pagination params
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 5000, type=int)  # Default 5000 for large batches
        status_filter = request.args.get('status_filter', '')
        error_category_filter = request.args.get('error_category', '')
        search_term = request.args.get('search', '').strip()
        ablage_filter = request.args.get('ablage_filter', '').strip()
        
        # Build WHERE clause with ms. prefix for JOIN
        where_conditions = [f"ms.batch_id = '{batch_id}'"]
        if status_filter:
            where_conditions.append(f"ms.execution_status = '{status_filter}'")
        # If filtering by error_category, filter by failed/partial status AND the category in staging table
        if error_category_filter:
            where_conditions.append("ms.execution_status IN ('failed', 'partial')")
            where_conditions.append(f"ms.error_category = '{error_category_filter}'")
        # Server-side text search: search across DOKNR, OBJKY, description, filename, target_documentnumber
        if search_term:
            safe_search = search_term.replace("'", "''")
            where_conditions.append(f"(ms.source_documentnumber LIKE '%{safe_search}%' OR ms.source_objky LIKE '%{safe_search}%' OR ms.source_description LIKE '%{safe_search}%' OR ms.filename LIKE '%{safe_search}%' OR ms.target_documentnumber LIKE '%{safe_search}%' OR ms.source_dokob LIKE '%{safe_search}%')")
        # Ablage filter (KPRO or DB)
        if ablage_filter in ('KPRO', 'DB'):
            where_conditions.append(f"ISNULL(ms.ablage, 'KPRO') = '{ablage_filter}'")
        where_clause = " AND ".join(where_conditions)
        
        # First get total count (with all filters applied)
        count_conditions = [f"ms.batch_id = '{batch_id}'"]
        if status_filter:
            count_conditions.append(f"ms.execution_status = '{status_filter}'")
        if error_category_filter:
            count_conditions.append("ms.execution_status IN ('failed', 'partial')")
            count_conditions.append(f"ms.error_category = '{error_category_filter}'")
        if search_term:
            safe_search = search_term.replace("'", "''")
            count_conditions.append(f"(ms.source_documentnumber LIKE '%{safe_search}%' OR ms.source_objky LIKE '%{safe_search}%' OR ms.source_description LIKE '%{safe_search}%' OR ms.filename LIKE '%{safe_search}%' OR ms.target_documentnumber LIKE '%{safe_search}%' OR ms.source_dokob LIKE '%{safe_search}%')")
        if ablage_filter in ('KPRO', 'DB'):
            count_conditions.append(f"ISNULL(ms.ablage, 'KPRO') = '{ablage_filter}'")
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
                    ms.target_documentnumber_sanitized,
                    ms.target_documentpart,
                    ms.target_documenttype,
                    ms.target_documentversion,
                    ms.filename,
                    ms.file_size_bytes,
                    ms.mime_type,
                    ms.source_authorization_group,
                    ms.authorization_group,
                    ms.validation_status,
                    ms.validation_notes,
                    ms.execution_status,
                    ms.execution_error,
                    ms.user_approved,
                    ms.skip_migration,
                    ms.error_category,
                    ms.target_dokob,
                    ms.target_objky,
                    ms.link_status,
                    ms.link_error,
                    ms.container_created,
                    ms.source_document_status,
                    ms.target_document_status,
                    ms.ablage,
                    ms.source_object_links,
                    ms.source_file_count,
                    ms.target_file_count,
                    ms.source_link_count,
                    ms.excluded_link_count,
                    ms.target_link_count
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
                    ms.target_documentnumber_sanitized,
                    ms.target_documentpart,
                    ms.target_documenttype,
                    ms.target_documentversion,
                    ms.filename,
                    ms.file_size_bytes,
                    ms.mime_type,
                    ms.source_authorization_group,
                    ms.authorization_group,
                    ms.validation_status,
                    ms.validation_notes,
                    ms.execution_status,
                    ms.execution_error,
                    ms.user_approved,
                    ms.skip_migration,
                    ms.error_category,
                    ms.target_dokob,
                    ms.target_objky,
                    ms.link_status,
                    ms.link_error,
                    ms.container_created,
                    ms.source_document_status,
                    ms.target_document_status,
                    ms.ablage,
                    ms.source_object_links,
                    ms.source_file_count,
                    ms.target_file_count,
                    ms.source_link_count,
                    ms.excluded_link_count,
                    ms.target_link_count
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
    """Step 2: Execute migration for approved records (background).
    
    Starts execution in a background thread and returns immediately.
    Frontend polls /batch/<id>/progress for live status updates.
    """
    try:
        if not _is_authenticated():
            return jsonify({
                'success': False, 
                'error': 'Not logged in. Please login to SAP first.',
                'login_required': True
            }), 401
        
        data = request.get_json()
        batch_id = data.get('batch_id')
        
        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID required'}), 400
        
        # Check if already running
        is_running, reason = is_migration_running(batch_id)
        if is_running:
            return jsonify({
                'success': False,
                'error': f'Migration already in progress: {reason}',
                'already_running': True
            })
        
        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_migration_background(batch_id, snapshot)
        
        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': 'Migration gestartet. Fortschritt wird automatisch aktualisiert.'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/execute_selected', methods=['POST'])
def execute_selected():
    """Execute migration for selected records only (background)."""
    try:
        if not _is_authenticated():
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
        
        # Check if already running
        is_running, reason = is_migration_running(batch_id)
        if is_running:
            return jsonify({
                'success': False,
                'error': f'Migration already in progress: {reason}',
                'already_running': True
            })
        
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
            
            # Also immediately reset the batch counters so the frontend
            # sees correct values from the very first poll (no race condition
            # with the background thread which resets them later again).
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET status = 'executing',
                    migration_phase = 'upload',
                    total_records = {len(record_ids)},
                    executed_records = 0,
                    successful_records = 0,
                    failed_records = 0,
                    last_execution_started_at = GETUTCDATE()
                WHERE batch_id = '{batch_id}'
            """))
        
        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_migration_background(batch_id, snapshot, record_ids=record_ids)
        
        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': f'Migration für {len(record_ids)} Datensätze gestartet.'
        })
        
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


# ============================================================================
# Phase 2: Object Link Creation (Verlinkung) Routes
# ============================================================================

@migrate_bp.route('/execute_linking', methods=['POST'])
def execute_link_all():
    """Phase 2: Execute object linking for all eligible records (background)."""
    try:
        if not _is_authenticated():
            return jsonify({
                'success': False,
                'error': 'Nicht angemeldet. Bitte zuerst bei SAP anmelden.',
                'login_required': True
            }), 401

        data = request.get_json()
        batch_id = data.get('batch_id')

        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID erforderlich'}), 400

        # Check if already running
        running, msg = is_linking_running(batch_id)
        if running:
            return jsonify({'success': False, 'error': msg, 'already_running': True})

        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_linking_background(batch_id, snapshot)

        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': 'Verlinkung gestartet. Fortschritt wird automatisch aktualisiert.'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/execute_linking_selected', methods=['POST'])
def execute_link_selected():
    """Phase 2: Execute object linking for selected records only (background)."""
    try:
        if not _is_authenticated():
            return jsonify({
                'success': False,
                'error': 'Nicht angemeldet. Bitte zuerst bei SAP anmelden.',
                'login_required': True
            }), 401

        data = request.get_json()
        batch_id = data.get('batch_id')
        record_ids = data.get('record_ids', [])

        if not batch_id:
            return jsonify({'success': False, 'error': 'Batch ID erforderlich'}), 400

        if not record_ids:
            return jsonify({'success': False, 'error': 'Keine Datensätze ausgewählt'}), 400

        # Check if already running
        running, msg = is_linking_running(batch_id)
        if running:
            return jsonify({'success': False, 'error': msg, 'already_running': True})

        # Reset link_status for selected records so they can be re-linked
        record_ids_str = ','.join(str(rid) for rid in record_ids)
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_staging
                SET link_status = 'pending',
                    link_error = NULL,
                    link_completed_at = NULL
                WHERE batch_id = '{batch_id}'
                    AND id IN ({record_ids_str})
                    AND execution_status IN ('success', 'partial')
                    AND ISNULL(container_created, 0) = 1
            """))

        # Snapshot session and start background thread
        snapshot = _build_session_snapshot()
        run_linking_background(batch_id, snapshot, record_ids=record_ids)

        return jsonify({
            'success': True,
            'background': True,
            'batch_id': batch_id,
            'message': f'Verlinkung für {len(record_ids)} Datensätze gestartet.'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/cancel-linking', methods=['POST'])
def cancel_linking(batch_id):
    """Cancel a running linking operation for the given batch."""
    try:
        running, msg = is_linking_running(batch_id)
        if not running:
            return jsonify({
                'success': False,
                'error': 'Keine Verlinkung läuft für diesen Batch'
            }), 400

        request_link_cancel(batch_id)

        return jsonify({
            'success': True,
            'message': f'Abbruch angefordert für Batch {batch_id}. Verlinkung wird nach Abschluss laufender Operationen beendet.',
            'cancel_requested': True
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/link-progress', methods=['GET'])
def get_link_progress(batch_id):
    """Get linking progress for a batch (for live polling during Phase 2)."""
    try:
        with misc_engine.begin() as con:
            # Get batch phase info
            batch_row = con.execute(text(f"""
                SELECT migration_phase, status
                FROM dbo.migration_batch
                WHERE batch_id = '{batch_id}'
            """)).fetchone()

            if not batch_row:
                return jsonify({'success': False, 'error': 'Batch nicht gefunden'}), 404

            # Get link status counts
            link_stats = con.execute(text(f"""
                SELECT
                    SUM(CASE WHEN link_status = 'linked' THEN 1 ELSE 0 END) as linked,
                    SUM(CASE WHEN link_status = 'link_exists' THEN 1 ELSE 0 END) as link_exists,
                    SUM(CASE WHEN link_status = 'link_failed' THEN 1 ELSE 0 END) as link_failed,
                    SUM(CASE WHEN link_status = 'linking' THEN 1 ELSE 0 END) as linking_now,
                    SUM(CASE WHEN ISNULL(link_status, 'pending') = 'pending' AND execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1 ELSE 0 END) as link_pending,
                    SUM(CASE WHEN execution_status IN ('success', 'partial') AND ISNULL(container_created, 0) = 1 AND target_dokob IS NOT NULL AND target_dokob != '' THEN 1 ELSE 0 END) as link_total
                FROM dbo.migration_staging
                WHERE batch_id = '{batch_id}'
            """)).fetchone()

        linked = link_stats[0] or 0
        link_exists = link_stats[1] or 0
        link_failed = link_stats[2] or 0
        linking_now = link_stats[3] or 0
        link_pending = link_stats[4] or 0
        link_total = link_stats[5] or 0

        completed = linked + link_exists + link_failed
        progress_pct = (completed / link_total * 100) if link_total > 0 else 0

        is_linking = is_linking_running(batch_id)[0]
        result_data = {
            'success': True,
            'batch_id': batch_id,
            'migration_phase': batch_row.migration_phase,
            'status': batch_row.status,
            'link_total': int(link_total),
            'linked': int(linked),
            'link_exists': int(link_exists),
            'link_failed': int(link_failed),
            'linking_now': int(linking_now),
            'link_pending': int(link_pending),
            'completed': int(completed),
            'progress_pct': round(progress_pct, 1),
            'is_linking': is_linking
        }

        # Include background result when linking is done
        if not is_linking:
            bg_result = get_background_result(f"{batch_id}_linking")
            if bg_result:
                result_data['background_result'] = bg_result

        return jsonify(result_data)

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


@migrate_bp.route('/debug/metadata', methods=['GET'])
def debug_metadata():
    """Temporary debug endpoint: fetch ZHL API $metadata using session bearer token."""
    import requests as _req, os as _os
    token = session.get('bearer_token')
    if not token:
        return jsonify(error='No bearer_token in session – please login first'), 401
    base_url = cfg.get('zhl', 'api_list', 'document', 'base_url')
    api_key  = cfg.get('zhl', 'X-API-Key')
    url = f"{base_url}/$metadata"
    headers = {"Authorization": f"Bearer {token}", "x-api-key": api_key}
    resp = _req.get(url, headers=headers, timeout=30)
    # Save to file so it can be inspected
    out_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), '_metadata_response.xml')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    return resp.text, resp.status_code, {'Content-Type': resp.headers.get('Content-Type', 'text/xml')}


@migrate_bp.route('/debug/document/<docnr>', methods=['GET'])
def debug_document(docnr):
    """Temporary debug endpoint: fetch raw API response for a document."""
    import requests as _req, json as _json
    token = session.get('bearer_token')
    if not token:
        return jsonify(error='No bearer_token in session – please login first'), 401
    sap_system = request.args.get('system', 'zhl')
    dokar = request.args.get('dokar', 'ZLH')
    dokvr = request.args.get('dokvr', '00')
    doktl = request.args.get('doktl', '000')
    base_url = cfg.get(sap_system, 'api_list', 'document', 'base_url')
    api_key  = cfg.get(sap_system, 'X-API-Key')
    # Strip leading zeros for API call (same as process.py)
    clean_nr = docnr.lstrip('0') or '0'
    args = f"Documentnumber='{clean_nr}',Documentpart='{doktl}',Documenttype='{dokar}',Documentversion='{dokvr}'"
    url = f"{base_url}/DocumentSet({args})?$expand=DocumentfilesSet,ObjectlinksSet,DESCRIPTIONSSet&$format=json"
    headers = {"Authorization": f"Bearer {token}", "x-api-key": api_key, "Accept": "application/json"}
    resp = _req.get(url, headers=headers, timeout=30)
    try:
        data = resp.json()
        return _json.dumps(data, indent=2, ensure_ascii=False), resp.status_code, {'Content-Type': 'application/json'}
    except Exception:
        return resp.text, resp.status_code


@migrate_bp.route('/keep-alive', methods=['GET'])
def keep_alive():
    """Lightweight session keep-alive endpoint.
    
    Called periodically by the browser to prevent session expiry
    during long-running migrations or when returning from sleep mode.
    Also returns info about any currently executing batch so the UI
    can auto-reconnect to running migrations.
    """
    try:
        session.modified = True  # Touch session to reset expiry timer

        # Check for any currently executing batch
        executing_batch = None
        try:
            with misc_engine.begin() as con:
                row = con.execute(text("""
                    SELECT TOP 1 batch_id, total_records, executed_records,
                           successful_records, failed_records, migration_phase
                    FROM dbo.migration_batch
                    WHERE status = 'executing'
                    ORDER BY created_at DESC
                """)).fetchone()
                if row:
                    executing_batch = {
                        'batch_id': row[0],
                        'total': row[1] or 0,
                        'executed': row[2] or 0,
                        'successful': row[3] or 0,
                        'failed': row[4] or 0,
                        'phase': row[5] or 'upload'
                    }
        except Exception:
            pass

        return jsonify({
            'success': True,
            'session_active': True,
            'executing_batch': executing_batch
        })
    except Exception as e:
        return jsonify({'success': False, 'session_active': False, 'error': str(e)}), 500


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


