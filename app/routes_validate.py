"""Validation dashboard routes — post-linking verification."""

from flask import render_template, request, jsonify
from sqlalchemy import text

from app.blueprint import migrate_bp, misc_engine, get_template_context


@migrate_bp.route('/batch/<batch_id>/validation')
def validation_page(batch_id):
    """Render the validation dashboard page."""
    return render_template(
        'validation.html',
        batch_id=batch_id,
        **get_template_context()
    )


@migrate_bp.route('/batch/<batch_id>/validation/data')
def validation_data(batch_id):
    """Return all validation data as JSON for the dashboard."""
    try:
        with misc_engine.connect() as con:
            # ── 1. KPIs ──────────────────────────────────────────
            kpi_row = con.execute(text("""
                SELECT
                    COUNT(*)                                              AS total,
                    SUM(CASE WHEN link_status = 'linked'      THEN 1 ELSE 0 END) AS linked,
                    SUM(CASE WHEN link_status = 'link_failed' THEN 1 ELSE 0 END) AS link_failed,
                    SUM(CASE WHEN link_status = 'link_skipped' THEN 1 ELSE 0 END) AS link_skipped,
                    SUM(CASE WHEN link_status = 'pending'     THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN link_status = 'linking'     THEN 1 ELSE 0 END) AS linking,
                    SUM(CASE WHEN execution_status = 'success'  THEN 1 ELSE 0 END) AS upload_success,
                    SUM(CASE WHEN execution_status = 'failed'   THEN 1 ELSE 0 END) AS upload_failed,
                    SUM(CASE WHEN execution_status = 'partial'  THEN 1 ELSE 0 END) AS upload_partial,
                    SUM(CASE WHEN execution_status = 'pending'  THEN 1 ELSE 0 END) AS upload_pending,
                    SUM(CASE WHEN skip_migration = 1            THEN 1 ELSE 0 END) AS skipped
                FROM dbo.migration_staging
                WHERE batch_id = :bid AND skip_migration = 0
            """), {'bid': batch_id}).fetchone()

            kpis = dict(kpi_row._mapping) if kpi_row else {}
            total = kpis.get('total', 0) or 0
            linked = kpis.get('linked', 0) or 0
            link_skipped = kpis.get('link_skipped', 0) or 0
            # Coverage excludes link_skipped (not applicable, not an error)
            applicable = total - link_skipped
            kpis['coverage_pct'] = round(linked / applicable * 100, 1) if applicable > 0 else 0

            # ── 2. Link-status breakdown ─────────────────────────
            link_stats = con.execute(text("""
                SELECT link_status, COUNT(*) AS cnt
                FROM dbo.migration_staging
                WHERE batch_id = :bid AND skip_migration = 0
                GROUP BY link_status
                ORDER BY cnt DESC
            """), {'bid': batch_id}).fetchall()
            link_breakdown = [dict(r._mapping) for r in link_stats]

            # ── 3. Execution-status breakdown ────────────────────
            exec_stats = con.execute(text("""
                SELECT execution_status, COUNT(*) AS cnt
                FROM dbo.migration_staging
                WHERE batch_id = :bid AND skip_migration = 0
                GROUP BY execution_status
                ORDER BY cnt DESC
            """), {'bid': batch_id}).fetchall()
            exec_breakdown = [dict(r._mapping) for r in exec_stats]

            # ── 4. Mapping coverage per DOKOB ────────────────────
            dokob_mapping = con.execute(text("""
                SELECT
                    ms.source_dokob,
                    COUNT(*)                                                      AS total_records,
                    SUM(CASE WHEN ms.target_dokob IS NOT NULL AND ms.target_objky IS NOT NULL
                             THEN 1 ELSE 0 END)                                  AS mapped,
                    SUM(CASE WHEN ms.target_dokob IS NULL OR ms.target_objky IS NULL
                             THEN 1 ELSE 0 END)                                  AS unmapped,
                    SUM(CASE WHEN ms.link_status = 'linked' THEN 1 ELSE 0 END)   AS linked,
                    SUM(CASE WHEN ms.link_status = 'link_failed' THEN 1 ELSE 0 END) AS link_failed
                FROM dbo.migration_staging ms
                WHERE ms.batch_id = :bid AND ms.skip_migration = 0
                GROUP BY ms.source_dokob
                ORDER BY COUNT(*) DESC
            """), {'bid': batch_id}).fetchall()
            dokob_data = [dict(r._mapping) for r in dokob_mapping]

            # ── 5. Error analysis (link_error patterns) ──────────
            error_patterns = con.execute(text("""
                SELECT TOP 50
                    link_error,
                    COUNT(*) AS cnt
                FROM dbo.migration_staging
                WHERE batch_id = :bid
                  AND link_status = 'link_failed'
                  AND link_error IS NOT NULL
                  AND skip_migration = 0
                GROUP BY link_error
                ORDER BY COUNT(*) DESC
            """), {'bid': batch_id}).fetchall()
            errors = [dict(r._mapping) for r in error_patterns]

            # ── 6. Upload error analysis ─────────────────────────
            upload_errors = con.execute(text("""
                SELECT TOP 50
                    execution_error,
                    COUNT(*) AS cnt
                FROM dbo.migration_staging
                WHERE batch_id = :bid
                  AND execution_status IN ('failed', 'partial')
                  AND execution_error IS NOT NULL
                  AND skip_migration = 0
                GROUP BY execution_error
                ORDER BY COUNT(*) DESC
            """), {'bid': batch_id}).fetchall()
            upload_err_data = [dict(r._mapping) for r in upload_errors]

            # ── 7. Source → Target comparison table ──────────────
            comparison_rows = con.execute(text("""
                SELECT
                    id,
                    source_documentnumber, source_documenttype,
                    source_documentversion, source_documentpart,
                    source_dokob, source_objky,
                    source_object_links, excluded_object_links,
                    target_documentnumber, target_documenttype,
                    target_documentversion, target_documentpart,
                    target_dokob, target_objky,
                    filename, file_size_bytes,
                    execution_status, link_status, link_error,
                    container_created, ablage,
                    source_document_status, target_document_status
                FROM dbo.migration_staging
                WHERE batch_id = :bid AND skip_migration = 0
                ORDER BY
                    CASE WHEN link_status = 'link_failed' THEN 0
                         WHEN link_status = 'pending'     THEN 1
                         WHEN link_status = 'linking'     THEN 2
                         WHEN link_status = 'link_skipped' THEN 3
                         ELSE 4 END,
                    id
            """), {'bid': batch_id}).fetchall()
            comparison = [dict(r._mapping) for r in comparison_rows]

            # ── 8. Object-link counts per record (source vs target) ──
            # Count how many source_object_links each record has, vs excluded
            link_counts = con.execute(text("""
                SELECT
                    SUM(CASE WHEN source_object_links IS NOT NULL AND LEN(source_object_links) > 2
                             THEN 1 ELSE 0 END) AS with_source_links,
                    SUM(CASE WHEN source_object_links IS NULL OR LEN(source_object_links) <= 2
                             THEN 1 ELSE 0 END) AS without_source_links,
                    SUM(CASE WHEN excluded_object_links IS NOT NULL AND LEN(excluded_object_links) > 2
                             THEN 1 ELSE 0 END) AS with_excluded_links
                FROM dbo.migration_staging
                WHERE batch_id = :bid AND skip_migration = 0
            """), {'bid': batch_id}).fetchone()
            link_count_data = dict(link_counts._mapping) if link_counts else {}

            # ── 9. Batch metadata ────────────────────────────────
            batch_row = con.execute(text("""
                SELECT batch_id, created_at, created_by, total_records,
                       status, migration_phase, description, wave
                FROM dbo.migration_batch
                WHERE batch_id = :bid
            """), {'bid': batch_id}).fetchone()
            batch_info = dict(batch_row._mapping) if batch_row else {}
            # Make datetime JSON-serializable
            if batch_info.get('created_at'):
                batch_info['created_at'] = str(batch_info['created_at'])

            # ── 10. File details (per-file upload results) ────────
            # Use ROW_NUMBER to de-duplicate: keep only the latest record per
            # staging_id + file_index (prevents inflated counts from retries).
            file_rows = con.execute(text("""
                WITH ranked AS (
                    SELECT
                        fd.id, fd.staging_id, fd.file_index,
                        fd.filename, fd.mime_type,
                        fd.file_size_bytes, fd.file_size_mb,
                        fd.upload_status, fd.http_status_code,
                        fd.error_category, fd.error_detail,
                        ms.source_documentnumber, ms.source_documenttype,
                        ms.source_documentversion, ms.source_documentpart,
                        CASE WHEN ms.container_created = 1 THEN ms.target_documentnumber ELSE NULL END AS target_documentnumber,
                        ms.target_documenttype, ms.target_documentversion, ms.target_documentpart,
                        ms.execution_status, ms.container_created,
                        ROW_NUMBER() OVER (
                            PARTITION BY fd.staging_id, fd.file_index
                            ORDER BY fd.id DESC
                        ) AS rn
                    FROM dbo.migration_file_details fd
                    JOIN dbo.migration_staging ms ON fd.staging_id = ms.id
                    WHERE fd.batch_id = :bid AND ms.skip_migration = 0
                )
                SELECT id, staging_id, file_index, filename, mime_type,
                       file_size_bytes, file_size_mb, upload_status, http_status_code,
                       error_category, error_detail,
                       source_documentnumber, source_documenttype,
                       source_documentversion, source_documentpart,
                       target_documentnumber, target_documenttype,
                       target_documentversion, target_documentpart,
                       execution_status, container_created
                FROM ranked WHERE rn = 1
                ORDER BY staging_id, file_index
            """), {'bid': batch_id}).fetchall()
            file_details = [dict(r._mapping) for r in file_rows]

            # ── 11. Object mappings (source→target per link) ─────
            obj_map_rows = con.execute(text("""
                SELECT source_dokob, source_objky, target_dokob, target_objky
                FROM dbo.migration_object_mapping
                WHERE batch_id = :bid AND active = 1
            """), {'bid': batch_id}).fetchall()
            obj_mappings = [dict(r._mapping) for r in obj_map_rows]

        return jsonify({
            'success': True,
            'kpis': kpis,
            'link_breakdown': link_breakdown,
            'exec_breakdown': exec_breakdown,
            'dokob_mapping': dokob_data,
            'link_errors': errors,
            'upload_errors': upload_err_data,
            'comparison': comparison,
            'link_counts': link_count_data,
            'batch': batch_info,
            'file_details': file_details,
            'obj_mappings': obj_mappings,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/link-errors')
def link_errors_list(batch_id):
    """Return all records with link_failed status for a batch."""
    try:
        with misc_engine.connect() as con:
            rows = con.execute(text("""
                SELECT
                    id, source_documentnumber, source_documenttype,
                    source_documentversion, source_documentpart,
                    target_documentnumber, target_documenttype,
                    target_documentversion, target_documentpart,
                    source_dokob, source_objky,
                    target_dokob, target_objky,
                    link_status, link_error,
                    execution_status, filename
                FROM dbo.migration_staging
                WHERE batch_id = :bid
                  AND link_status = 'link_failed'
                  AND skip_migration = 0
                ORDER BY id
            """), {'bid': batch_id}).fetchall()
            records = [dict(r._mapping) for r in rows]

        return jsonify({'success': True, 'records': records, 'count': len(records)})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@migrate_bp.route('/batch/<batch_id>/reset-link-errors', methods=['POST'])
def reset_link_errors(batch_id):
    """Reset link_failed records back to pending so they can be re-linked."""
    try:
        data = request.get_json() or {}
        record_ids = data.get('record_ids')  # optional: specific IDs only

        with misc_engine.begin() as con:
            if record_ids:
                ids_str = ','.join(str(int(rid)) for rid in record_ids)
                result = con.execute(text(f"""
                    UPDATE dbo.migration_staging
                    SET link_status = 'pending',
                        link_error = NULL,
                        link_completed_at = NULL
                    WHERE batch_id = :bid
                      AND id IN ({ids_str})
                      AND link_status = 'link_failed'
                """), {'bid': batch_id})
            else:
                result = con.execute(text("""
                    UPDATE dbo.migration_staging
                    SET link_status = 'pending',
                        link_error = NULL,
                        link_completed_at = NULL
                    WHERE batch_id = :bid
                      AND link_status = 'link_failed'
                """), {'bid': batch_id})
            reset_count = result.rowcount

        return jsonify({'success': True, 'reset_count': reset_count})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
