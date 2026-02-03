"""
Step 2: Execute migration based on approved staging records.
Reads from staging database and performs API calls.
"""

import pandas as pd
import datetime as dt
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor
import asyncio
from sqlalchemy import text
from flask import session as http_session

# Global migration lock to prevent parallel executions
_migration_lock = threading.Lock()
_active_migrations = {}  # batch_id -> start_time
_cancel_requested = {}   # batch_id -> True/False - for graceful cancellation

# Circuit Breaker settings
CIRCUIT_BREAKER_THRESHOLD = 3  # Stop after N consecutive auth errors (reduced from 5)
CIRCUIT_BREAKER_ERRORS = (401, 403)  # HTTP status codes that trigger circuit breaker
PACKAGE_SIZE = 10  # Process in packages of N records (reduced from 100 for faster error detection)

# Token refresh import (for automatic refresh before packages)
try:
    from authentication import ensure_valid_token, get_token_remaining_seconds
    TOKEN_REFRESH_AVAILABLE = True
except ImportError:
    TOKEN_REFRESH_AVAILABLE = False

from app_config import Config, MiscEngine
from app.process import (
    prepare_session_headers, 
    get_info,
    _extract_error_fields,
    _sanitize_filename,
    _classify_error,
    get_error_description,
    MAX_API_WORKERS,
    ADD_UP_TO,
    MAX_DESC_LEN,
    read_sap_system,
    write_sap_system
)
from app.logger import get_logger

cfg = Config.load()
misc_db = MiscEngine.load()
misc_engine = misc_db.engine


# Pacing mode: 'response' = wait for API response, 'time' = time-based delays
# Time-based pacing is more reliable for APIs with rate limiting
PACING_MODE = 'time'  # 'response' or 'time'

# Minimum delay between containers (seconds) - prevents rate limiting
# Only applies in response mode; set to 0 for maximum throughput
MIN_CONTAINER_DELAY = 0.5

# Time-based pacing buckets (used when PACING_MODE = 'time')
PACING_BUCKETS = {
    'tiny':    {'max_mb': 1,    'pacing': 5},   # ≤1MB: Fast batch processing
    'small':   {'max_mb': 10,   'pacing': 10},  # 1-10MB: Normal processing
    'medium':  {'max_mb': 50,   'pacing': 20},  # 10-50MB: Larger files
    'large':   {'max_mb': float('inf'), 'pacing': 45},  # >50MB: Very large
    'unknown': {'pacing': 5}    # Unknown size: Assume small (same as tiny)
}

# Terminal logging verbosity: True = detailed, False = minimal (progress + errors only)
VERBOSE_TERMINAL_LOGGING = False

# API Warmup settings
WARMUP_ENABLED = True
WARMUP_REQUESTS = 3  # Number of warmup pings
WARMUP_DELAY = 0.5   # Delay between warmup requests (seconds)


def warmup_api(session_snapshot, first_loio_id=None):
    """
    Send warmup requests to wake up the API before starting migration.
    This helps avoid initial 401/403/500 errors due to cold API instances.
    
    Args:
        session_snapshot: Dict with bearer_token and other auth info
        first_loio_id: Optional LOIO ID to use for warmup (from first record)
    
    Returns:
        dict with warmup results
    """
    if not WARMUP_ENABLED:
        return {'skipped': True}
    
    print(f"[WARMUP] Waking up API with {WARMUP_REQUESTS} requests...")
    
    results = []
    start_time = time.time()
    
    for i in range(WARMUP_REQUESTS):
        try:
            # Prepare headers with auth
            headers = {
                'Authorization': f"Bearer {session_snapshot.get('bearer_token')}",
                'Accept': 'application/json',
            }
            
            # Add CSRF token if available
            if session_snapshot.get('x_csrf_token'):
                headers['x-csrf-token'] = session_snapshot['x_csrf_token']
            
            # Use cookies if available
            cookies = session_snapshot.get('cookies', {})
            
            # Get target API base URL from config
            sap_system = session_snapshot.get('sap_system', 'P')
            target_base_url = cfg.get('sap', {}).get(sap_system, {}).get('sdm', {}).get('url', '')
            
            if target_base_url:
                # Warmup request to target API (simple GET to root or health endpoint)
                warmup_url = f"{target_base_url}"
                response = requests.get(
                    warmup_url, 
                    headers=headers, 
                    cookies=cookies,
                    timeout=10
                )
                results.append({
                    'target': 'target_api',
                    'status': response.status_code,
                    'ok': response.status_code in [200, 401, 403]  # Even auth errors mean API is awake
                })
            
            # Optional: warmup source API if we have a LOIO
            if first_loio_id and i == 0:
                # Just try to get info - even if it fails, it wakes up the API
                try:
                    info_result = get_info(first_loio_id, session_snapshot)
                    results.append({
                        'target': 'source_api',
                        'status': 'ok' if info_result else 'error',
                        'ok': True  # Any response means API is awake
                    })
                except Exception:
                    results.append({'target': 'source_api', 'status': 'error', 'ok': True})
            
            if i < WARMUP_REQUESTS - 1:
                time.sleep(WARMUP_DELAY)
                
        except requests.exceptions.Timeout:
            results.append({'target': 'warmup', 'status': 'timeout', 'ok': False})
        except Exception as e:
            results.append({'target': 'warmup', 'status': str(e)[:50], 'ok': False})
    
    elapsed = time.time() - start_time
    success_count = sum(1 for r in results if r.get('ok'))
    
    print(f"[WARMUP] Completed in {elapsed:.1f}s - {success_count}/{len(results)} successful")
    
    return {
        'elapsed': elapsed,
        'results': results,
        'success': success_count > 0
    }


def get_historical_pacing_stats():
    """
    Analyze historical execution data to calculate pacing recommendations.
    Returns statistics per size bucket based on actual execution times.
    """
    try:
        query = """
            SELECT 
                file_size_bytes,
                DATEDIFF(MILLISECOND, execution_started_at, execution_completed_at) / 1000.0 as execution_time_sec,
                execution_status
            FROM dbo.migration_staging
            WHERE execution_status IN ('success', 'partial')
            AND execution_started_at IS NOT NULL
            AND execution_completed_at IS NOT NULL
            AND file_size_bytes IS NOT NULL
            AND file_size_bytes > 0
        """
        
        with misc_engine.begin() as con:
            result = con.execute(text(query))
            rows = result.fetchall()
        
        if not rows:
            return {
                'has_data': False,
                'message': 'Keine historischen Daten verfügbar',
                'buckets': PACING_BUCKETS
            }
        
        # Group by size bucket
        bucket_stats = {
            'tiny': {'count': 0, 'times': [], 'max_mb': 1},
            'small': {'count': 0, 'times': [], 'max_mb': 10},
            'medium': {'count': 0, 'times': [], 'max_mb': 50},
            'large': {'count': 0, 'times': [], 'max_mb': 999999}  # Use large number instead of inf for JSON compatibility
        }
        
        for row in rows:
            size_bytes, exec_time, status = row
            if size_bytes is None or exec_time is None:
                continue
            
            # Convert Decimal to float for division
            size_bytes = float(size_bytes)
            exec_time = float(exec_time)
            size_mb = size_bytes / (1024 * 1024)
            
            if size_mb <= 1:
                bucket = 'tiny'
            elif size_mb <= 10:
                bucket = 'small'
            elif size_mb <= 50:
                bucket = 'medium'
            else:
                bucket = 'large'
            
            bucket_stats[bucket]['count'] += 1
            bucket_stats[bucket]['times'].append(exec_time)
        
        # Calculate statistics for each bucket
        recommendations = {}
        for bucket_name, stats in bucket_stats.items():
            if stats['count'] > 0:
                times = stats['times']
                avg_time = sum(times) / len(times)
                max_time = max(times)
                min_time = min(times)
                # Recommended pacing = max_time + 20% buffer, rounded up
                recommended = round(max_time * 1.2, 1)
                
                recommendations[bucket_name] = {
                    'count': stats['count'],
                    'avg_time': round(avg_time, 2),
                    'min_time': round(min_time, 2),
                    'max_time': round(max_time, 2),
                    'current_pacing': PACING_BUCKETS[bucket_name]['pacing'],
                    'recommended_pacing': recommended,
                    'max_mb': stats['max_mb']
                }
            else:
                recommendations[bucket_name] = {
                    'count': 0,
                    'avg_time': None,
                    'min_time': None,
                    'max_time': None,
                    'current_pacing': PACING_BUCKETS[bucket_name]['pacing'],
                    'recommended_pacing': PACING_BUCKETS[bucket_name]['pacing'],
                    'max_mb': stats['max_mb']
                }
        
        total_records = sum(s['count'] for s in recommendations.values())
        
        return {
            'has_data': True,
            'total_records': total_records,
            'buckets': recommendations,
            'current_pacing': {k: v['pacing'] for k, v in PACING_BUCKETS.items() if k != 'unknown'}
        }
        
    except Exception as e:
        return {
            'has_data': False,
            'error': str(e),
            'buckets': PACING_BUCKETS
        }


def get_dynamic_pacing(file_size_bytes):
    """
    Calculate dynamic pacing based on file size.
    Smaller files get shorter pacing, larger files get more time.
    
    Args:
        file_size_bytes: File size in bytes (None if unknown)
        
    Returns:
        Pacing time in seconds
    """
    import math
    # Handle None, NaN, and invalid values - use tiny pacing as default for unknown small files
    try:
        if file_size_bytes is None:
            return PACING_BUCKETS['tiny']['pacing']  # Assume small file if unknown
        if math.isnan(float(file_size_bytes)):
            return PACING_BUCKETS['tiny']['pacing']
        if file_size_bytes <= 0:
            return PACING_BUCKETS['tiny']['pacing']
    except (TypeError, ValueError):
        return PACING_BUCKETS['tiny']['pacing']
    
    size_mb = file_size_bytes / (1024 * 1024)
    
    if size_mb <= 1:
        return PACING_BUCKETS['tiny']['pacing']
    elif size_mb <= 10:
        return PACING_BUCKETS['small']['pacing']
    elif size_mb <= 50:
        return PACING_BUCKETS['medium']['pacing']
    else:
        return PACING_BUCKETS['large']['pacing']


def load_approved_records(batch_id):
    """Load records from staging that are pending execution."""
    query = f"""
        SELECT 
            id,
            batch_id,
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
            authorization_group,
            filename,
            file_size_bytes,
            skip_migration
        FROM dbo.migration_staging
        WHERE batch_id = '{batch_id}'
            AND skip_migration = 0
            AND execution_status = 'pending'
        ORDER BY CASE WHEN file_size_bytes IS NULL THEN 1 ELSE 0 END, file_size_bytes ASC, id
    """
    
    with misc_engine.begin() as con:
        df = pd.read_sql(query, con)
    
    return df


def load_specific_records(batch_id, record_ids):
    """Load specific records by IDs for execution."""
    if not record_ids:
        return pd.DataFrame()
    
    ids_str = ','.join(str(id) for id in record_ids)
    query = f"""
        SELECT 
            id,
            batch_id,
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
            authorization_group,
            filename,
            file_size_bytes,
            skip_migration
        FROM dbo.migration_staging
        WHERE batch_id = '{batch_id}'
            AND id IN ({ids_str})
            AND skip_migration = 0
        ORDER BY CASE WHEN file_size_bytes IS NULL THEN 1 ELSE 0 END, file_size_bytes ASC, id
    """
    
    with misc_engine.begin() as con:
        df = pd.read_sql(query, con)
    
    return df


def update_execution_status(staging_id, status, error=None):
    """Update execution status for a staging record."""
    try:
        update_query = """
            UPDATE dbo.migration_staging
            SET execution_status = :status,
                execution_completed_at = GETUTCDATE(),
                execution_error = :error
            WHERE id = :staging_id
        """
        
        with misc_engine.begin() as con:
            con.execute(text(update_query), {
                'status': status,
                'error': str(error) if error else None,
                'staging_id': staging_id
            })
    except Exception as e:
        print(f"[UPDATE_ERROR] Failed to update staging_id={staging_id}: {e}")


def mark_execution_started(staging_id):
    """Mark execution as started by setting execution_started_at."""
    try:
        with misc_engine.begin() as con:
            con.execute(text("""
                UPDATE dbo.migration_staging
                SET execution_started_at = GETUTCDATE()
                WHERE id = :staging_id
            """), {'staging_id': staging_id})
    except Exception as e:
        print(f"[UPDATE_ERROR] Failed to mark started staging_id={staging_id}: {e}")


def update_metadata_fields(staging_id, loioid=None, description=None, filename=None, file_size=None, mime_type=None):
    """Update metadata fields for a staging record after successful read."""
    try:
        updates = []
        params = {'staging_id': staging_id}
        
        if loioid:
            updates.append("source_loioid = :loioid")
            params['loioid'] = loioid
        if description:
            updates.append("source_description = :description")
            params['description'] = description
        if filename:
            updates.append("filename = :filename")
            params['filename'] = filename
        if file_size is not None:
            updates.append("file_size_bytes = :file_size")
            params['file_size'] = file_size
        if mime_type:
            updates.append("mime_type = :mime_type")
            params['mime_type'] = mime_type
        
        if updates:
            update_query = f"""
                UPDATE dbo.migration_staging
                SET {', '.join(updates)}
                WHERE id = :staging_id
            """
            
            with misc_engine.begin() as con:
                con.execute(text(update_query), params)
    except Exception as e:
        print(f"[UPDATE_METADATA_ERROR] Failed to update metadata for staging_id={staging_id}: {e}")


def save_file_details(staging_id, batch_id, file_index, file_result, loio_id=None):
    """
    Save detailed file-level results to migration_file_details table.
    
    Args:
        staging_id: Parent staging record ID
        batch_id: Batch ID for filtering
        file_index: 0-based index of file in container
        file_result: Dict with upload result (status, error_detail, file_size, etc.)
        loio_id: LOIO ID of the file (optional)
    """
    import json
    
    try:
        # Extract error information
        error_detail = file_result.get('error_detail', {}) or {}
        error_messages = error_detail.get('messages') or error_detail.get('errordetails')
        
        # Get raw status and clean it for the status field
        raw_status = file_result.get('status', 'UNKNOWN')
        # Extract just the status code (e.g., "UPLOAD_FAIL_500: xyz" -> "UPLOAD_FAIL_500")
        if ':' in raw_status:
            clean_status = raw_status.split(':')[0].strip()
            # Store the extra info in error_detail if not already set
            extra_info = raw_status.split(':', 1)[1].strip() if len(raw_status.split(':')) > 1 else None
        else:
            clean_status = raw_status
            extra_info = None
        
        # Truncate status to 50 chars max (DB limit)
        clean_status = clean_status[:50] if clean_status else 'UNKNOWN'
        
        # Combine error details
        combined_error_detail = error_detail.get('detail') if error_detail else None
        if not combined_error_detail and extra_info:
            combined_error_detail = extra_info
        
        params = {
            'staging_id': staging_id,
            'batch_id': batch_id,
            'file_index': file_index,
            'filename': file_result.get('file'),
            'loio_id': loio_id,
            'file_size_bytes': file_result.get('file_size'),
            'file_size_mb': file_result.get('file_size_mb'),
            'mime_type': file_result.get('mime_type'),
            'upload_status': clean_status,
            'http_status_code': error_detail.get('status_code') if error_detail else (200 if file_result.get('status') == 'SUCCESS' else None),
            'upload_time_seconds': file_result.get('actual_time_seconds'),
            'error_category': file_result.get('error_category'),
            'error_code': error_detail.get('code') if error_detail else None,
            'error_detail': combined_error_detail,
            'error_messages': json.dumps(error_messages) if error_messages else None,
            'is_size_error': 1 if file_result.get('is_size_error') else 0
        }
        
        insert_query = """
            INSERT INTO dbo.migration_file_details (
                staging_id, batch_id, file_index, filename, loio_id,
                file_size_bytes, file_size_mb, mime_type,
                upload_status, http_status_code, upload_time_seconds,
                error_category, error_code, error_detail, error_messages, is_size_error
            ) VALUES (
                :staging_id, :batch_id, :file_index, :filename, :loio_id,
                :file_size_bytes, :file_size_mb, :mime_type,
                :upload_status, :http_status_code, :upload_time_seconds,
                :error_category, :error_code, :error_detail, :error_messages, :is_size_error
            )
        """
        
        with misc_engine.begin() as con:
            con.execute(text(insert_query), params)
            
    except Exception as e:
        print(f"[SAVE_FILE_DETAILS_ERROR] Failed to save file details for staging_id={staging_id}, file_index={file_index}: {e}")


def is_auto_generated_id(doc_number):
    """Check if document number is auto-generated by SAP.
    
    Auto-generated IDs are:
    - Exactly 25 characters long
    - Convert to integer after removing leading zeros
    
    Args:
        doc_number: Document number to check
        
    Returns:
        bool: True if auto-generated, False if manually assigned
    """
    if not doc_number:
        return False
    
    doc_str = str(doc_number).strip()
    
    # Must be exactly 25 characters
    if len(doc_str) != 25:
        return False
    
    # Try to convert to integer after removing leading zeros
    try:
        int(doc_str.lstrip('0') or '0')
        return True  # Successfully converted to int = auto-generated
    except (ValueError, TypeError):
        return False  # Failed to convert = manually assigned


def execute_single_document(server_session, staging_record, session_snapshot):
    """Execute migration for a single staging record."""
    staging_id = staging_record['id']
    batch_id = staging_record.get('batch_id')
    logger = get_logger(batch_id=batch_id, staging_id=staging_id)
    start_time = time.time()
    
    # Mark execution as started in database
    mark_execution_started(staging_id)
    
    logger.info(f"Starting migration for document {staging_record['source_documentnumber']}", category="EXECUTE")
    
    try:
        # Prepare session headers for read system
        prepare_session_headers(server_session, session_snapshot, read_sap_system)
        server_session.headers.pop('Slug', None)
        
        logger.debug(f"Fetching document info from {read_sap_system}", category="EXECUTE")
        
        # Get document info from source system
        documents = get_info(
            server_session,
            read_sap_system,
            staging_record['source_documentnumber'],
            staging_record['source_documentpart'],
            staging_record['source_documenttype'],
            staging_record['source_documentversion']
        )
        
        if documents[0] != 200:
            import json
            error_info = {'status_code': documents[0], 'reason': documents[1]}
            error_msg = f"READ_FAILED {documents[0]} {documents[1]}"
            error_json = json.dumps(error_info)
            logger.error(error_msg, category="READ", details=error_info)
            update_execution_status(staging_id, 'failed', error_json)
            return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg, 'error_detail': error_info, 'status_code': documents[0]}
        
        if not documents[2] or len(documents[2]) == 0:
            error_msg = "READ_EMPTY - No documents found"
            logger.warning(error_msg, category="READ")
            update_execution_status(staging_id, 'failed', error_msg)
            return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg, 'status_code': 404}
        
        logger.info(f"Found {len(documents[2])} files to migrate", category="EXECUTE")
        
        # Extract metadata from first document for updating staging table
        first_doc = documents[2][0] if documents[2] else {}
        doc_loioid = first_doc.get('LOIOID')
        doc_description = first_doc.get('Description') or first_doc.get('DocumentDescription')
        
        # Process each file in the document container
        doc_created = False
        results = []
        metadata_updated = False
        # batch_id already set at function start from staging_record
        
        for file_index, document in enumerate(documents[2]):
            # Fetch document content
            selected_keys = ['Documentnumber', 'Documentpart', 'Documenttype', 'Documentversion', 'LOIOID']
            document_args = {k: document[k] for k in selected_keys}
            formatted_args = ",".join(f"{k}='{v}'" for k, v in document_args.items())
            base_read_url = cfg.get(read_sap_system, 'api_list', 'document', 'base_url')
            request_url = f"{base_read_url}/DocumentfilesSet({formatted_args})/$value"
            
            try:
                response = server_session.get(request_url, timeout=300)  # 5 min timeout for large files
            except Exception as read_ex:
                error_msg = f'READ_TIMEOUT: {str(read_ex)}'
                logger.error(f"File read timeout/error: {error_msg}", category="READ")
                file_result = {
                    'file': document.get('LOIOID'), 
                    'status': error_msg,
                    'error_detail': {'status_code': 0, 'detail': str(read_ex)},
                    'error_category': 'TIMEOUT'
                }
                results.append(file_result)
                save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                continue
            
            if response.status_code != 200:
                error_info = _extract_error_fields(response)
                error_msg = f'READ_FAIL_{response.status_code}'
                
                # For 401/403 errors, add extra context about the authentication issue
                if response.status_code in (401, 403):
                    # Check for WWW-Authenticate header which often contains useful info
                    www_auth = response.headers.get('WWW-Authenticate', '')
                    if www_auth:
                        error_info['www_authenticate'] = www_auth[:200]
                    
                    # Check response body (often empty for 401, but sometimes has info)
                    body_preview = (response.text or '')[:500]
                    if body_preview:
                        error_info['body_preview'] = body_preview
                    
                    # Add hint about likely cause
                    error_info['hint'] = 'Token may have expired or API requires re-authentication. Try refreshing login.'
                
                logger.error(f"File read failed: {error_msg}", category="READ", details=error_info)
                file_result = {
                    'file': document.get('LOIOID'), 
                    'status': error_msg,
                    'error_detail': error_info,
                    'error_category': _classify_error(error_info)
                }
                results.append(file_result)
                save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                continue
            
            filename = _sanitize_filename(document.get('Docpath', '').split('/')[-1] or 'unnamed')
            
            # Update metadata fields in staging table (once, on first successful file read)
            if not metadata_updated:
                import mimetypes
                mime_type, _ = mimetypes.guess_type(filename)
                if not mime_type:
                    mime_type = 'application/octet-stream'
                file_size = len(response.content) if response.content else 0
                
                update_metadata_fields(
                    staging_id,
                    loioid=doc_loioid,
                    description=doc_description,
                    filename=filename,
                    file_size=file_size,
                    mime_type=mime_type
                )
                metadata_updated = True
                logger.debug(f"Updated metadata: LOIOID={doc_loioid}, filename={filename}, size={file_size}, mime={mime_type}", category="EXECUTE")
            
            # Prepare for write operations
            prepare_session_headers(server_session, session_snapshot, write_sap_system)
            
            # Create document info record (once per container)
            if not doc_created:
                doc_type = staging_record['target_documenttype']
                doc_number = staging_record['target_documentnumber']
                doc_version = staging_record['target_documentversion']
                doc_part = staging_record['target_documentpart']
                
                # Check if source document number is auto-generated
                source_doc_number = staging_record['source_documentnumber']
                is_auto_id = is_auto_generated_id(source_doc_number)
                
                if is_auto_id:
                    logger.info(f"Source document {source_doc_number} is auto-generated (len={len(source_doc_number)}). Target system will assign new ID.", category="CREATE")
                else:
                    logger.info(f"Source document {source_doc_number} is manually assigned. Using as target ID.", category="CREATE")
                
                # Prepare description
                source_description = staging_record.get('source_description') or filename
                if isinstance(source_description, str):
                    source_description = source_description.strip()
                if len(source_description) > MAX_DESC_LEN:
                    source_description = source_description[:MAX_DESC_LEN]
                
                # Create payload
                doc_base_url = cfg.get(write_sap_system, 'api_list', 'document', 'base_url')
                create_url = f"{doc_base_url}/A_DocumentInfoRecord"
                server_session.headers.update({'Content-Type': 'application/json'})
                
                dms_payload = {
                    'DocumentInfoRecordDocType': doc_type,
                    'DocumentInfoRecordDocVersion': doc_version,
                    'DocumentInfoRecordDocPart': doc_part,
                    'to_DocDesc': [
                        {'Language': 'DE', 'DocumentDescription': source_description},
                        {'Language': 'EN', 'DocumentDescription': source_description}
                    ]
                }
                
                # Only include document number if it's manually assigned
                # Auto-generated IDs should be omitted to let target system create new ID
                if not is_auto_id:
                    dms_payload['DocumentInfoRecordDocNumber'] = doc_number
                    logger.debug(f"Including document number in payload: {doc_number}", category="CREATE")
                else:
                    logger.debug("Omitting document number from payload - target system will auto-generate", category="CREATE")
                
                # Add authorization group if available
                if staging_record.get('authorization_group'):
                    dms_payload['AuthorizationGroup'] = staging_record['authorization_group']
                    logger.debug(f"Using authorization group: {staging_record['authorization_group']}", category="CREATE")
                
                logger.info(f"Creating document info record", category="CREATE")
                create_resp = server_session.post(create_url, json=dms_payload)
                
                body_txt_lower = create_resp.text.lower() if create_resp.text else ''
                
                if create_resp.status_code in (200, 201):
                    # For auto-generated IDs, extract the new document number from response
                    if is_auto_id:
                        try:
                            response_data = create_resp.json()
                            if response_data and 'd' in response_data:
                                created_doc_number = response_data['d'].get('DocumentInfoRecordDocNumber')
                                if created_doc_number:
                                    doc_number = created_doc_number
                                    # Update staging record with the new document number
                                    with misc_engine.begin() as con:
                                        con.execute(text(f"""
                                            UPDATE dbo.migration_staging
                                            SET target_documentnumber = :new_doc_number
                                            WHERE id = :staging_id
                                        """), {'new_doc_number': created_doc_number, 'staging_id': staging_id})
                                    logger.info(f"Target system assigned new document number: {created_doc_number}", category="CREATE")
                                else:
                                    logger.warning("Could not extract new document number from response", category="CREATE")
                        except Exception as e:
                            logger.warning(f"Failed to extract new document number: {e}", category="CREATE")
                    
                    logger.info(f"Document created successfully: {doc_number} (status {create_resp.status_code})", category="CREATE")
                    doc_created = True
                    
                    # Create Object Link if target mapping is available
                    target_dokob = staging_record.get('target_dokob')
                    target_objky = staging_record.get('target_objky')
                    
                    if target_dokob and target_objky:
                        try:
                            logger.info(f"Creating object link: {target_dokob}/{target_objky}", category="OBJLINK")
                            
                            object_link_url = f"{doc_base_url}/A_DocumentInfoRecordObjLink"
                            server_session.headers.update({'Content-Type': 'application/json'})
                            
                            object_link_payload = {
                                'DocumentInfoRecordDocType': doc_type,
                                'DocumentInfoRecordDocNumber': doc_number,
                                'DocumentInfoRecordDocVersion': doc_version,
                                'DocumentInfoRecordDocPart': doc_part,
                                'DocumentInfoRecordToObjLnkObjectType': target_dokob,
                                'DocumentInfoRecordToObjLnkObjectKey': target_objky
                            }
                            
                            link_resp = server_session.post(object_link_url, json=object_link_payload)
                            
                            if link_resp.status_code in (200, 201):
                                logger.info(f"Object link created successfully: {target_dokob}/{target_objky}", category="OBJLINK")
                            elif link_resp.status_code in (400, 409) and 'exist' in (link_resp.text.lower() if link_resp.text else ''):
                                logger.warning(f"Object link already exists: {target_dokob}/{target_objky}", category="OBJLINK")
                            else:
                                error_info = _extract_error_fields(link_resp)
                                logger.warning(f"Object link creation failed ({link_resp.status_code}): {error_info.get('detail', 'Unknown error')}", 
                                              category="OBJLINK", details=error_info)
                                # Don't fail the whole migration for object link errors - continue with file upload
                        except Exception as link_ex:
                            logger.warning(f"Exception creating object link: {link_ex}", category="OBJLINK")
                            # Continue with file upload even if object link fails
                    
                elif create_resp.status_code in (400, 409) and any(x in body_txt_lower for x in ['exist', 'duplicate', 'already']):
                    logger.warning(f"Document already exists, continuing: {doc_number}", category="CREATE")
                    doc_created = True  # Tolerate existing
                else:
                    error_info = _extract_error_fields(create_resp)
                    error_msg = f"CREATE_FAIL_{create_resp.status_code}"
                    if error_info.get('detail'):
                        error_msg += f": {error_info['detail']}"
                    logger.error(error_msg, category="CREATE", details=error_info)
                    import json
                    error_json = json.dumps(error_info)
                    update_execution_status(staging_id, 'failed', error_json)
                    return {'staging_id': staging_id, 'status': 'failed', 'error': error_msg, 'error_detail': error_info, 'status_code': create_resp.status_code}
            
            # Upload attachment
            if doc_created:
                import mimetypes
                mime_type, _ = mimetypes.guess_type(filename)
                if not mime_type:
                    mime_type = 'application/octet-stream'
                
                server_session.headers.update({'Content-Type': mime_type, 'Slug': filename})
                
                try:
                    attachment_base_url = cfg.get(write_sap_system, 'api_list', 'attachment', 'base_url')
                except Exception:
                    attachment_base_url = cfg.get(write_sap_system, 'api_list', 'document', 'base_url')
                
                # Use the doc_number that was either:
                # 1. Set from staging_record at the start, OR
                # 2. Updated from the CREATE response for auto-generated IDs
                # Don't re-read from staging_record as it still has the old value!
                # doc_number is already set correctly above
                doc_type = staging_record['target_documenttype']
                doc_version = staging_record['target_documentversion']
                doc_part = staging_record['target_documentpart']
                
                attachment_url = (
                    f"{attachment_base_url}/A_DocumentInfoRecordAttch"
                    f"(DocumentInfoRecordDocType='{doc_type}',"
                    f"DocumentInfoRecordDocNumber='{doc_number}',"
                    f"DocumentInfoRecordDocVersion='{doc_version}',"
                    f"DocumentInfoRecordDocPart='{doc_part}'"
                    f")/DocumentInfoRecordToAttachmentNavigation"
                )
                
                content = response.content or b' '  # Pad empty files
                file_size = len(content)
                file_size_mb = file_size / 1024 / 1024
                
                # Get MIME type for file details
                import mimetypes
                current_mime_type, _ = mimetypes.guess_type(filename)
                if not current_mime_type:
                    current_mime_type = 'application/octet-stream'
                
                logger.info(f"Uploading file: {filename} ({file_size} bytes / {file_size_mb:.2f} MB)", category="UPLOAD")
                
                # Upload mit Timeout: 60s base + 10s pro MB (für große Dateien)
                upload_timeout = max(60, 60 + int(file_size_mb * 10))
                try:
                    upload_resp = server_session.post(attachment_url, data=content, timeout=upload_timeout)
                except requests.exceptions.Timeout as timeout_ex:
                    upload_time = time.time() - start_time
                    error_msg = f'UPLOAD_TIMEOUT after {upload_timeout}s'
                    logger.error(f"Upload timeout: {filename} ({file_size_mb:.2f} MB) - {error_msg}", category="UPLOAD")
                    file_result = {
                        'file': filename,
                        'status': error_msg,
                        'error_detail': {'status_code': 0, 'detail': str(timeout_ex)},
                        'error_category': 'TIMEOUT',
                        'file_size': file_size,
                        'file_size_mb': round(file_size_mb, 2),
                        'mime_type': current_mime_type,
                        'actual_time_seconds': round(upload_time, 2)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                    continue
                
                if upload_resp.status_code in (200, 201):
                    upload_time = time.time() - start_time  # Actual processing time (no pacing)
                    logger.info(f"File uploaded successfully: {filename} (status {upload_resp.status_code})", category="UPLOAD")
                    file_result = {
                        'file': filename, 
                        'status': 'SUCCESS', 
                        'file_size': file_size,
                        'file_size_mb': round(file_size_mb, 2),
                        'mime_type': current_mime_type,
                        'actual_time_seconds': round(upload_time, 2)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
                else:
                    upload_time = time.time() - start_time
                    error_info = _extract_error_fields(upload_resp)
                    error_msg = f'UPLOAD_FAIL_{upload_resp.status_code}'
                    
                    # Detect size-related errors
                    is_size_error = False
                    size_error_indicators = ['too large', 'size', 'payload', 'entity', 'limit', 'exceeded', 'maximum']
                    error_text = str(error_info).lower()
                    if upload_resp.status_code in (413, 507) or any(ind in error_text for ind in size_error_indicators):
                        is_size_error = True
                        error_msg = f'SIZE_LIMIT_EXCEEDED_{upload_resp.status_code}'
                        logger.error(f"File too large: {filename} ({file_size_mb:.2f} MB) - {error_msg}", category="UPLOAD", details=error_info)
                    else:
                        if error_info.get('detail'):
                            error_msg += f": {error_info['detail'][:100]}"
                        logger.error(f"Upload failed: {filename} - {error_msg}", category="UPLOAD", details=error_info)
                    
                    file_result = {
                        'file': filename, 
                        'status': error_msg,
                        'error_detail': error_info,
                        'error_category': _classify_error(error_info),
                        'file_size': file_size,
                        'file_size_mb': round(file_size_mb, 2),
                        'mime_type': current_mime_type,
                        'is_size_error': is_size_error,
                        'actual_time_seconds': round(upload_time, 2)
                    }
                    results.append(file_result)
                    save_file_details(staging_id, batch_id, file_index, file_result, loio_id=document.get('LOIOID'))
        
        # Calculate timing and size statistics
        execution_time = time.time() - start_time
        total_bytes = sum(r.get('file_size', 0) for r in results)
        
        # Determine overall status
        success_count = len([r for r in results if r['status'] == 'SUCCESS'])
        
        if all(r['status'] == 'SUCCESS' for r in results):
            logger.info(f"Migration completed successfully for all {len(results)} files in {execution_time:.2f}s ({total_bytes/1024/1024:.2f} MB)", category="EXECUTE")
            update_execution_status(staging_id, 'success')
            return {
                'staging_id': staging_id, 
                'status': 'success', 
                'results': results,
                'stats': {
                    'execution_time': execution_time,
                    'total_bytes': total_bytes,
                    'file_count': len(results)
                }
            }
        elif success_count == 0 and not doc_created:
            # No container created and no files uploaded -> this is a complete failure, not partial
            import json
            error_details = [r.get('error_detail') for r in results if r.get('error_detail')]
            error_summary = f"FAILED 0/{len(results)} files - no container created"
            
            logger.error(f"Migration failed completely: 0 of {len(results)} files, no container created in {execution_time:.2f}s", category="EXECUTE")
            
            if error_details:
                error_json = json.dumps({'summary': error_summary, 'errors': error_details})
                update_execution_status(staging_id, 'failed', error_json)
            else:
                update_execution_status(staging_id, 'failed', error_summary)
            
            return {
                'staging_id': staging_id, 
                'status': 'failed', 
                'results': results,
                'stats': {
                    'execution_time': execution_time,
                    'total_bytes': total_bytes,
                    'file_count': len(results)
                }
            }
        else:
            # Container created but not all files uploaded -> partial success
            import json
            # Collect all errors from results
            error_details = [r.get('error_detail') for r in results if r.get('error_detail')]
            error_summary = f"PARTIAL_SUCCESS {success_count}/{len(results)} files"
            
            logger.warning(f"Partial success: {success_count} of {len(results)} files migrated in {execution_time:.2f}s", category="EXECUTE")
            
            # Store detailed errors as JSON if available
            if error_details:
                error_json = json.dumps({'summary': error_summary, 'errors': error_details})
                update_execution_status(staging_id, 'partial', error_json)
            else:
                update_execution_status(staging_id, 'partial', error_summary)
            
            return {
                'staging_id': staging_id, 
                'status': 'partial', 
                'results': results,
                'stats': {
                    'execution_time': execution_time,
                    'total_bytes': total_bytes,
                    'file_count': len(results)
                }
            }
        
    except Exception as e:
        error_msg = f"EXCEPTION {e}"
        logger.critical(f"Exception during migration: {str(e)}", category="EXECUTE", details={'exception': str(e)})
        update_execution_status(staging_id, 'failed', error_msg)
        return {'staging_id': staging_id, 'status': 'failed', 'error': str(e), 'status_code': 500}
    
    finally:
        # Pacing between containers
        session_pacing = session_snapshot.get('pacing_seconds')
        
        if session_pacing and session_pacing > 0:
            # Manual override - use fixed pacing (legacy mode)
            time_taken = time.time() - start_time
            if time_taken < session_pacing:
                sleep_time = session_pacing - time_taken
                time.sleep(sleep_time)
        elif PACING_MODE == 'response':
            # Response-based pacing: API response already received, just add minimal delay
            # This prevents rate limiting while maximizing throughput
            if MIN_CONTAINER_DELAY > 0:
                time.sleep(MIN_CONTAINER_DELAY)
        else:
            # Legacy time-based pacing
            file_size = staging_record.get('file_size_bytes')
            dynamic_pacing = get_dynamic_pacing(file_size)
            time_taken = time.time() - start_time
            if time_taken < dynamic_pacing:
                sleep_time = dynamic_pacing - time_taken
                time.sleep(sleep_time)


def is_migration_running(batch_id):
    """Check if a migration is currently running for this batch."""
    global _active_migrations
    
    # Check in-memory lock first (most reliable)
    with _migration_lock:
        if batch_id in _active_migrations:
            start_time = _active_migrations[batch_id]
            elapsed_minutes = (time.time() - start_time) / 60
            if VERBOSE_TERMINAL_LOGGING:
                print(f"[LOCK] Batch {batch_id} has been running for {elapsed_minutes:.1f} minutes")
            return True, f"Migration already running since {elapsed_minutes:.1f} minutes"
    
    # Also check database status as fallback (in case of crash/restart)
    with misc_engine.connect() as con:
        result = con.execute(text(f"""
            SELECT status, total_records, executed_records, 
                   DATEDIFF(MINUTE, created_at, GETDATE()) as minutes_elapsed
            FROM dbo.migration_batch 
            WHERE batch_id = '{batch_id}'
        """)).fetchone()
        
        if result and result.status == 'executing':
            # Check if there are "executing" status records 
            executing_count = con.execute(text(f"""
                SELECT COUNT(*) as cnt 
                FROM dbo.migration_staging 
                WHERE batch_id = '{batch_id}' AND execution_status = 'executing'
            """)).fetchone().cnt
            
            if executing_count > 0:
                if VERBOSE_TERMINAL_LOGGING:
                    print(f"[LOCK] Found {executing_count} records still in 'executing' status - likely orphaned")
                return False, f"Found {executing_count} orphaned 'executing' records (will be reset)"
            
    return False, None


def clear_migration_lock(batch_id):
    """Remove the migration lock for a batch."""
    global _active_migrations
    with _migration_lock:
        if batch_id in _active_migrations:
            del _active_migrations[batch_id]
            if VERBOSE_TERMINAL_LOGGING:
                print(f"[LOCK] Released lock for batch {batch_id}")


def set_migration_lock(batch_id):
    """Set the migration lock for a batch."""
    global _active_migrations
    with _migration_lock:
        _active_migrations[batch_id] = time.time()
        if VERBOSE_TERMINAL_LOGGING:
            print(f"[LOCK] Acquired lock for batch {batch_id}")


def reset_orphaned_records(batch_id):
    """Reset any records stuck in 'executing' status back to 'pending'."""
    with misc_engine.begin() as con:
        result = con.execute(text(f"""
            UPDATE dbo.migration_staging
            SET execution_status = 'pending'
            WHERE batch_id = '{batch_id}' AND execution_status = 'executing'
        """))
        if result.rowcount > 0:
            if VERBOSE_TERMINAL_LOGGING:
                print(f"[CLEANUP] Reset {result.rowcount} orphaned 'executing' records to 'pending'")
        return result.rowcount


def request_cancel(batch_id):
    """Request cancellation of a running migration."""
    global _cancel_requested
    _cancel_requested[batch_id] = True
    print(f"[CANCEL] Cancellation requested for batch {batch_id}")
    return True


def is_cancel_requested(batch_id):
    """Check if cancellation was requested for this batch."""
    global _cancel_requested
    return _cancel_requested.get(batch_id, False)


def clear_cancel_request(batch_id):
    """Clear the cancel request flag for a batch."""
    global _cancel_requested
    if batch_id in _cancel_requested:
        del _cancel_requested[batch_id]


def check_token_validity(session_snapshot):
    """
    Quick check if the bearer token is still valid by making a lightweight API call.
    Returns (is_valid, error_message)
    """
    try:
        headers = {
            'Authorization': f"Bearer {session_snapshot.get('bearer_token')}",
            'Accept': 'application/json',
        }
        if session_snapshot.get('x_csrf_token'):
            headers['x-csrf-token'] = session_snapshot['x_csrf_token']
        
        cookies = session_snapshot.get('cookies', {})
        
        # Use the write API base URL for a quick check
        target_base_url = cfg.get(write_sap_system, 'api_list', 'document', 'base_url')
        if target_base_url:
            # Simple metadata request - very lightweight
            check_url = f"{target_base_url}/$metadata"
            response = requests.get(check_url, headers=headers, cookies=cookies, timeout=10)
            
            if response.status_code in (401, 403):
                return False, f"Token invalid (HTTP {response.status_code})"
            return True, None
        
        return True, None  # Can't check, assume valid
        
    except requests.exceptions.Timeout:
        return True, None  # Timeout doesn't mean token is invalid
    except Exception as e:
        return True, None  # Other errors don't mean token is invalid


def execute_migration(batch_id, record_ids=None):
    """
    Main entry point for Step 2: Execute Migration
    
    Args:
        batch_id: Batch ID to execute
        record_ids: Optional list of specific record IDs to execute. If None, executes all pending.
    
    Returns:
        dict with execution results
    """
    try:
        # Check if migration is already running
        is_running, reason = is_migration_running(batch_id)
        if is_running:
            return {
                'success': False,
                'error': f'Migration already in progress: {reason}',
                'already_running': True
            }
        
        # Reset any orphaned records from previous crashed execution
        reset_orphaned_records(batch_id)
        
        # Set the lock
        set_migration_lock(batch_id)
        
        # Get settings from session (with defaults)
        max_workers = http_session.get('max_workers', MAX_API_WORKERS)
        pacing_seconds = http_session.get('pacing_seconds', 0)  # 0 = auto/dynamic mode
        
        # Snapshot session values
        session_snapshot = {
            'bearer_token': http_session.get('bearer_token'),
            'sap_system': http_session.get('sap_system'),
            'x_csrf_token': http_session.get('x-csrf-token'),
            'cookies': http_session.get('cookies'),
            'csrf_token_time': http_session.get('csrf_token_time', 0),
            'max_workers': max_workers,
            'pacing_seconds': pacing_seconds  # 0 = dynamic pacing based on file size
        }
        
        # Load records - either specific IDs or all pending
        if record_ids:
            records_df = load_specific_records(batch_id, record_ids)
        else:
            records_df = load_approved_records(batch_id)
        
        if len(records_df) == 0:
            return {
                'success': False,
                'error': 'No records found for execution'
            }
        
        # API Warmup - wake up APIs before starting migration
        first_loio = None
        if len(records_df) > 0 and 'source_loioid' in records_df.columns:
            first_loio = records_df.iloc[0].get('source_loioid')
        warmup_result = warmup_api(session_snapshot, first_loio_id=first_loio)
        
        # Log pacing mode - always show start message
        pacing_mode = f"fixed={pacing_seconds}s" if pacing_seconds > 0 else "dynamic (5-45s)"
        print(f"[START] Batch {batch_id}: {len(records_df)} records, {max_workers} workers, pacing={pacing_mode}")
        
        # Track batch timing
        batch_start_time = time.time()
        total_records = len(records_df)
        
        # Update batch status - reset counters for this execution run
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET status = 'executing',
                    total_records = {total_records},
                    executed_records = 0,
                    successful_records = 0,
                    failed_records = 0
                WHERE batch_id = '{batch_id}'
            """))
        
        # Progress tracking
        completed_count = 0
        success_count = 0
        failed_count = 0
        partial_count = 0
        
        def update_progress():
            """Update progress in batch table for frontend polling."""
            nonlocal completed_count, success_count, failed_count, partial_count
            with misc_engine.begin() as con:
                con.execute(text(f"""
                    UPDATE dbo.migration_batch
                    SET executed_records = {completed_count},
                        successful_records = {success_count},
                        failed_records = {failed_count + partial_count}
                    WHERE batch_id = '{batch_id}'
                """))
        
        # Execute in parallel using ThreadPoolExecutor with PACKAGE-BASED processing
        # This allows cancel/circuit-breaker to work between packages
        results = []
        
        # Circuit breaker and cancel tracking
        consecutive_auth_errors = 0
        circuit_breaker_tripped = False
        cancel_reason = None
        clear_cancel_request(batch_id)  # Clear any previous cancel request
        
        # Convert DataFrame to list of tuples for package processing
        records_list = list(records_df.iterrows())
        
        # Package size = max_workers to ensure only N concurrent requests
        # This allows circuit breaker to work effectively
        effective_package_size = max_workers  # Use worker count as package size
        total_packages = (len(records_list) + effective_package_size - 1) // effective_package_size
        
        print(f"[PACKAGES] Processing {total_records} records in {total_packages} packages of {effective_package_size} (= {max_workers} workers)")
        
        server_session = requests.Session()
        token_refresh_failed = False
        
        for package_num in range(total_packages):
            # Check for cancellation BEFORE starting each package
            if is_cancel_requested(batch_id):
                cancel_reason = "User requested cancellation"
                print(f"[CANCEL] Migration cancelled by user before package {package_num + 1}/{total_packages}")
                break
            
            # Check circuit breaker before package
            if circuit_breaker_tripped:
                break
            
            # Token health check before each package (automatic refresh if possible)
            if TOKEN_REFRESH_AVAILABLE:
                remaining = get_token_remaining_seconds()
                if remaining is not None and remaining < 600:  # Less than 10 min remaining
                    print(f"[TOKEN] Token expires in {remaining}s, attempting refresh...")
                    is_valid, error = ensure_valid_token()
                    if not is_valid:
                        circuit_breaker_tripped = True
                        token_refresh_failed = True
                        cancel_reason = f"Token expired and refresh failed: {error}"
                        print(f"[TOKEN] {cancel_reason}")
                        break
                    else:
                        # Update session_snapshot with new token
                        session_snapshot['bearer_token'] = http_session.get('bearer_token')
                        print(f"[TOKEN] Token refreshed successfully")
            
            # Get records for this package
            start_idx = package_num * effective_package_size
            end_idx = min(start_idx + effective_package_size, len(records_list))
            package_records = records_list[start_idx:end_idx]
            
            print(f"[PACKAGE {package_num + 1}/{total_packages}] Processing records {start_idx + 1}-{end_idx}")
            
            # PROBE MODE: Test first record of first package to detect auth issues early
            if package_num == 0 and len(package_records) > 0:
                print(f"[PROBE] Testing first record to verify SAP authentication...")
                try:
                    _, probe_row = package_records[0]
                    probe_result = execute_single_document(server_session, probe_row, session_snapshot)
                    probe_error = str(probe_result.get('error', '')).lower()
                    probe_status = probe_result.get('status_code', 0)
                    
                    is_probe_auth_error = (
                        probe_status in CIRCUIT_BREAKER_ERRORS or
                        '403' in probe_error or '401' in probe_error or
                        'csrf' in probe_error or 'forbidden' in probe_error
                    )
                    
                    if is_probe_auth_error:
                        circuit_breaker_tripped = True
                        cancel_reason = f"PROBE FAILED: SAP auth error - {probe_result.get('error', 'Unknown')}"
                        print(f"[PROBE] {cancel_reason}")
                        print(f"[PROBE] Stopping migration - please check SAP credentials/CSRF token")
                        results.append(probe_result)
                        completed_count += 1
                        failed_count += 1
                        break
                    else:
                        print(f"[PROBE] First record OK (status: {probe_result.get('status')}) - continuing with batch")
                        results.append(probe_result)
                        completed_count += 1
                        if probe_result.get('status') == 'success':
                            success_count += 1
                        elif probe_result.get('status') == 'failed':
                            failed_count += 1
                        # Remove first record from package since we already processed it
                        package_records = package_records[1:]
                        
                except Exception as probe_ex:
                    probe_error_str = str(probe_ex).lower()
                    is_auth_exception = (
                        '403' in probe_error_str or '401' in probe_error_str or
                        'csrf' in probe_error_str or 'forbidden' in probe_error_str
                    )
                    if is_auth_exception:
                        circuit_breaker_tripped = True
                        cancel_reason = f"PROBE EXCEPTION: {probe_ex}"
                        print(f"[PROBE] {cancel_reason}")
                        print(f"[PROBE] Stopping migration - SAP authentication failed")
                        results.append({'status': 'failed', 'error': str(probe_ex)})
                        completed_count += 1
                        failed_count += 1
                        break
                    else:
                        print(f"[PROBE] Non-auth error: {probe_ex} - continuing")
                        results.append({'status': 'failed', 'error': str(probe_ex)})
                        completed_count += 1
                        failed_count += 1
                        package_records = package_records[1:]
            
            # Skip if no more records in package
            if not package_records:
                continue
            
            # Process this package with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(execute_single_document, server_session, row, session_snapshot): idx
                    for idx, (_, row) in enumerate(package_records)
                }
                
                from concurrent.futures import as_completed
                for future in as_completed(futures):
                    # Check for cancellation during package processing
                    if is_cancel_requested(batch_id):
                        cancel_reason = "User requested cancellation"
                        print(f"[CANCEL] Migration cancelled during package {package_num + 1}")
                        executor.shutdown(wait=False)
                        break
                    
                    try:
                        result = future.result()
                        results.append(result)
                        
                        # Circuit breaker: Track consecutive auth errors
                        # Check both HTTP status codes AND error messages for auth failures
                        status_code = result.get('status_code', 0)
                        error_msg = str(result.get('error', '')).lower()
                        is_auth_error = (
                            status_code in CIRCUIT_BREAKER_ERRORS or
                            '403' in error_msg or
                            '401' in error_msg or
                            'csrf' in error_msg or
                            'forbidden' in error_msg or
                            'unauthorized' in error_msg
                        )
                        
                        if is_auth_error:
                            consecutive_auth_errors += 1
                            print(f"[AUTH_ERROR] Consecutive auth errors: {consecutive_auth_errors}/{CIRCUIT_BREAKER_THRESHOLD}")
                            if consecutive_auth_errors >= CIRCUIT_BREAKER_THRESHOLD:
                                circuit_breaker_tripped = True
                                cancel_reason = f"Circuit breaker: {consecutive_auth_errors} consecutive auth errors"
                                print(f"[CIRCUIT_BREAKER] {cancel_reason}")
                                print(f"[CIRCUIT_BREAKER] Token/CSRF likely expired - stopping to prevent wasted API calls")
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                        else:
                            # Reset counter on successful response (not auth error)
                            consecutive_auth_errors = 0
                        
                        # Update counters
                        completed_count += 1
                        if result.get('status') == 'success':
                            success_count += 1
                        elif result.get('status') == 'failed':
                            failed_count += 1
                        elif result.get('status') == 'partial':
                            partial_count += 1
                        
                        # Log progress
                        pct = (completed_count / total_records) * 100
                        elapsed = time.time() - batch_start_time
                        rate = completed_count / elapsed if elapsed > 0 else 0
                        eta_seconds = (total_records - completed_count) / rate if rate > 0 else 0
                        eta_str = f"{int(eta_seconds//60)}m {int(eta_seconds%60)}s" if eta_seconds > 0 else "-"
                        
                        # Print progress every 10 records or at 25%, 50%, 75%, 100%
                        if completed_count % 10 == 0 or pct in [25, 50, 75, 100] or completed_count == total_records:
                            auth_warning = f" (auth errors: {consecutive_auth_errors})" if consecutive_auth_errors > 0 else ""
                            print(f"[PROGRESS] {completed_count}/{total_records} ({pct:.0f}%) | ✓{success_count} ✗{failed_count} | ETA: {eta_str}{auth_warning}")
                        
                        # Update DB every 5 records or at end for live progress
                        if completed_count % 5 == 0 or completed_count == total_records:
                            update_progress()

                            
                    except Exception as e:
                        error_str = str(e).lower()
                        print(f"[EXECUTE_ERROR] {e}")
                        results.append({'status': 'failed', 'error': str(e)})
                        completed_count += 1
                        failed_count += 1
                        
                        # Circuit breaker: Also check exceptions for auth errors
                        is_auth_exception = (
                            '403' in error_str or
                            '401' in error_str or
                            'csrf' in error_str or
                            'forbidden' in error_str or
                            'unauthorized' in error_str
                        )
                        if is_auth_exception:
                            consecutive_auth_errors += 1
                            print(f"[AUTH_ERROR] Consecutive auth errors: {consecutive_auth_errors}/{CIRCUIT_BREAKER_THRESHOLD}")
                            if consecutive_auth_errors >= CIRCUIT_BREAKER_THRESHOLD:
                                circuit_breaker_tripped = True
                                cancel_reason = f"Circuit breaker: {consecutive_auth_errors} consecutive auth errors (exceptions)"
                                print(f"[CIRCUIT_BREAKER] {cancel_reason}")
                                print(f"[CIRCUIT_BREAKER] Token/CSRF likely expired - stopping")
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                        # Don't reset counter on non-auth exceptions - they could be unrelated errors
                
                # Break out of package loop if cancelled or circuit breaker
                if is_cancel_requested(batch_id) or circuit_breaker_tripped:
                    break
        
        server_session.close()
        
        # Handle circuit breaker or cancel situation
        if circuit_breaker_tripped or is_cancel_requested(batch_id):
            # Final progress update before setting stopped status
            update_progress()
            
            # Update batch status to reflect stopped state
            stop_reason = cancel_reason or "Unknown"
            remaining_records = total_records - completed_count
            
            with misc_engine.begin() as con:
                con.execute(text(f"""
                    UPDATE dbo.migration_batch
                    SET status = 'stopped',
                        executed_records = {completed_count},
                        successful_records = {success_count},
                        failed_records = {failed_count + partial_count}
                    WHERE batch_id = '{batch_id}'
                """))
            
            # Clear migration lock
            clear_migration_lock(batch_id)
            clear_cancel_request(batch_id)
            
            # Calculate timing
            batch_end_time = time.time()
            this_run_duration = batch_end_time - batch_start_time
            
            print(f"[STOPPED] Batch {batch_id} stopped after {completed_count}/{total_records} records in {this_run_duration:.1f}s")
            print(f"[STOPPED] Reason: {stop_reason}")
            print(f"[STOPPED] Remaining: {remaining_records} records still pending")
            
            return {
                'success': True,
                'stopped': True,
                'stop_reason': stop_reason,
                'circuit_breaker_tripped': circuit_breaker_tripped,
                'cancelled': is_cancel_requested(batch_id),
                'processed': completed_count,
                'total': total_records,
                'remaining': remaining_records,
                'successful': success_count,
                'failed': failed_count + partial_count,
                'duration_seconds': round(this_run_duration, 2),
                'message': f"Migration stopped: {stop_reason}. Processed {completed_count}/{total_records} records."
            }
        
        # Final progress update
        update_progress()
        
        # Calculate batch timing from THIS execution run
        batch_end_time = time.time()
        this_run_duration = batch_end_time - batch_start_time
        
        # Update batch statistics - count from this run's results
        success_count = len([r for r in results if r.get('status') == 'success'])
        failed_count = len([r for r in results if r.get('status') == 'failed'])
        partial_count = len([r for r in results if r.get('status') == 'partial'])
        
        # Calculate aggregate statistics from individual results
        total_bytes_this_run = sum(r.get('stats', {}).get('total_bytes', 0) for r in results)
        total_files_this_run = sum(r.get('stats', {}).get('file_count', 0) for r in results)
        
        # Now calculate CUMULATIVE statistics from database (all executed records)
        with misc_engine.begin() as con:
            # Get cumulative stats from all executed records in this batch
            cumulative = con.execute(text("""
                SELECT 
                    COUNT(*) as total_executed,
                    SUM(CASE WHEN execution_status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN execution_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN execution_status = 'partial' THEN 1 ELSE 0 END) as partial_count,
                    SUM(COALESCE(file_size_bytes, 0)) as total_bytes,
                    SUM(DATEDIFF(MILLISECOND, execution_started_at, execution_completed_at)) / 1000.0 as total_execution_time
                FROM dbo.migration_staging 
                WHERE batch_id = :batch_id 
                AND execution_status IN ('success', 'failed', 'partial')
                AND execution_started_at IS NOT NULL
                AND execution_completed_at IS NOT NULL
            """), {'batch_id': batch_id}).fetchone()
        
        # Use cumulative stats from database
        total_executed = cumulative[0] or 0
        cumulative_success = cumulative[1] or 0
        cumulative_failed = cumulative[2] or 0
        cumulative_partial = cumulative[3] or 0
        total_bytes = float(cumulative[4] or 0)  # Convert Decimal to float
        cumulative_execution_time = float(cumulative[5] or 0)  # Sum of all individual execution times
        
        # IMPORTANT: Use REAL elapsed time (this_run_duration), not cumulative execution time
        # With parallel workers, real time is shorter than sum of individual times
        # cumulative_execution_time is useful for avg_time_per_doc calculation
        real_duration = this_run_duration  # Actual wall-clock time for this run
        
        # Calculate statistics based on actual execution data
        total_mb = total_bytes / 1024 / 1024
        # avg_time_per_doc uses cumulative time (actual CPU time spent)
        avg_time_per_doc = cumulative_execution_time / total_executed if total_executed > 0 else 0
        # Throughput uses REAL duration (what user experiences with parallel workers)
        avg_time_per_mb = real_duration / total_mb if total_mb > 0 else 0
        throughput_mb_per_min = (total_mb / real_duration * 60) if real_duration > 0 else 0
        total_files = total_executed  # Approximation - 1 file per document on average
        
        # Update batch with CUMULATIVE statistics
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET status = 'completed',
                    executed_records = {total_executed},
                    successful_records = {cumulative_success},
                    failed_records = {cumulative_failed + cumulative_partial}
                WHERE batch_id = '{batch_id}'
            """))
        
        # Format REAL duration with hours if needed (what user experiences)
        if real_duration >= 3600:
            duration_formatted = f"{int(real_duration // 3600)}h {int((real_duration % 3600) // 60)}m {int(real_duration % 60)}s"
        else:
            duration_formatted = f"{int(real_duration // 60)}m {int(real_duration % 60)}s"
        
        # Build statistics summary (using real elapsed time for throughput)
        batch_stats = {
            'batch_duration_seconds': round(real_duration, 2),  # Real wall-clock time
            'batch_duration_formatted': duration_formatted,
            'cumulative_cpu_time_seconds': round(cumulative_execution_time, 2),  # Sum of individual times
            'total_documents': total_executed,
            'total_files': total_files,
            'total_bytes': total_bytes,
            'total_mb': round(total_mb, 2),
            'avg_time_per_document_seconds': round(avg_time_per_doc, 2),  # Based on cumulative time
            'avg_time_per_mb_seconds': round(avg_time_per_mb, 2),  # Based on real time
            'throughput_mb_per_minute': round(throughput_mb_per_min, 2),  # Based on real time
            'workers': max_workers,
            'parallel_speedup': round(cumulative_execution_time / real_duration, 2) if real_duration > 0 else 1,
            'pacing_seconds': pacing_seconds,
            'this_run': {
                'documents': len(results),
                'success': success_count,
                'failed': failed_count,
                'partial': partial_count,
                'duration_seconds': round(this_run_duration, 2)
            }
        }
        
        # Analyze file size errors
        size_errors = []
        all_file_results = []
        error_by_category = {}  # Collect errors by category
        all_error_details = []  # Collect detailed error info
        
        for r in results:
            # Document-level errors (e.g., CREATE_FAIL, READ_FAILED)
            if r.get('error_detail'):
                category = _classify_error(r.get('error_detail'))
                if category not in error_by_category:
                    error_by_category[category] = []
                error_by_category[category].append({
                    'staging_id': r.get('staging_id'),
                    'error': r.get('error'),
                    'detail': r.get('error_detail')
                })
                all_error_details.append({
                    'staging_id': r.get('staging_id'),
                    'category': category,
                    'category_desc': get_error_description(category),
                    'error': r.get('error'),
                    'status_code': r.get('error_detail', {}).get('status_code'),
                    'sap_code': r.get('error_detail', {}).get('code'),
                    'message': r.get('error_detail', {}).get('detail')
                })
            
            if r.get('results'):  # Individual document results contain file details
                for file_result in r.get('results', []):
                    all_file_results.append(file_result)
                    if file_result.get('is_size_error'):
                        size_errors.append({
                            'file': file_result.get('file'),
                            'size_mb': file_result.get('file_size_mb', 0),
                            'status': file_result.get('status')
                        })
                    # Collect file-level errors by category
                    if file_result.get('error_detail'):
                        category = file_result.get('error_category') or _classify_error(file_result.get('error_detail'))
                        if category not in error_by_category:
                            error_by_category[category] = []
                        error_by_category[category].append({
                            'file': file_result.get('file'),
                            'error': file_result.get('status'),
                            'detail': file_result.get('error_detail')
                        })
                        all_error_details.append({
                            'staging_id': r.get('staging_id'),
                            'file': file_result.get('file'),
                            'file_size_mb': file_result.get('file_size_mb'),
                            'category': category,
                            'category_desc': get_error_description(category),
                            'error': file_result.get('status'),
                            'status_code': file_result.get('error_detail', {}).get('status_code'),
                            'sap_code': file_result.get('error_detail', {}).get('code'),
                            'message': file_result.get('error_detail', {}).get('detail')
                        })
        
        # Calculate size-based statistics
        if all_file_results:
            successful_files = [f for f in all_file_results if f.get('status') == 'SUCCESS']
            failed_files = [f for f in all_file_results if f.get('status') != 'SUCCESS']
            
            # Find max successful file size
            max_success_size = max([f.get('file_size', 0) for f in successful_files], default=0)
            min_failed_size = min([f.get('file_size', 0) for f in failed_files], default=0) if failed_files else 0
            
            batch_stats['file_size_analysis'] = {
                'successful_files': len(successful_files),
                'failed_files': len(failed_files),
                'size_errors': len(size_errors),
                'max_successful_size_mb': round(max_success_size / 1024 / 1024, 2),
                'min_failed_size_mb': round(min_failed_size / 1024 / 1024, 2) if min_failed_size > 0 else None,
                'size_error_details': size_errors[:10]  # Limit to first 10
            }
            
            # Estimate size limit if we have both successful and failed
            if max_success_size > 0 and min_failed_size > 0:
                batch_stats['file_size_analysis']['estimated_limit_mb'] = round(max_success_size / 1024 / 1024, 2)
            
            # Timing analysis by file size (actual processing time, without pacing)
            timing_data = []
            for f in all_file_results:
                if f.get('file_size') and f.get('actual_time_seconds'):
                    timing_data.append({
                        'file': f.get('file'),
                        'size_mb': f.get('file_size_mb', round(f.get('file_size', 0) / 1024 / 1024, 2)),
                        'actual_time_seconds': f.get('actual_time_seconds'),
                        'status': 'SUCCESS' if f.get('status') == 'SUCCESS' else 'FAILED'
                    })
            
            if timing_data:
                # Sort by size for analysis
                timing_data.sort(key=lambda x: x['size_mb'])
                
                # Calculate average time per MB for successful files
                successful_timing = [t for t in timing_data if t['status'] == 'SUCCESS']
                if successful_timing:
                    total_success_mb = sum(t['size_mb'] for t in successful_timing)
                    total_success_time = sum(t['actual_time_seconds'] for t in successful_timing)
                    avg_seconds_per_mb = total_success_time / total_success_mb if total_success_mb > 0 else 0
                    
                    # Recommended pacing based on actual times
                    max_actual_time = max(t['actual_time_seconds'] for t in successful_timing)
                    recommended_pacing = round(max_actual_time * 1.2, 1)  # 20% buffer
                    
                    batch_stats['timing_analysis'] = {
                        'files_with_timing': len(timing_data),
                        'avg_seconds_per_mb': round(avg_seconds_per_mb, 2),
                        'max_actual_time_seconds': round(max_actual_time, 2),
                        'recommended_pacing_seconds': recommended_pacing,
                        'file_details': timing_data[:20]  # First 20 files with timing
                    }
                else:
                    batch_stats['timing_analysis'] = {
                        'files_with_timing': len(timing_data),
                        'note': 'No successful files with timing data',
                        'file_details': timing_data[:20]
                    }
        
        # Add error analysis to batch_stats
        error_summary = []
        for category, errors in error_by_category.items():
            error_summary.append({
                'category': category,
                'description': get_error_description(category),
                'count': len(errors),
                'examples': errors[:3]  # First 3 examples per category
            })
        # Sort by count descending
        error_summary.sort(key=lambda x: x['count'], reverse=True)
        
        batch_stats['error_analysis'] = {
            'total_errors': len(all_error_details),
            'categories': error_summary,
            'details': all_error_details[:50]  # Limit to first 50 detailed errors
        }
        
        # Save statistics to database
        import json
        stats_json = json.dumps(batch_stats).replace("'", "''")
        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_batch
                SET notes = '{stats_json}'
                WHERE batch_id = '{batch_id}'
            """))
        
        print(f"[DONE] Batch {batch_id}: ✓{cumulative_success} ✗{cumulative_failed} ⚠{cumulative_partial} | {batch_stats['batch_duration_formatted']} | {throughput_mb_per_min:.1f}MB/min")
        
        # Release the lock
        clear_migration_lock(batch_id)
        
        return {
            'success': True,
            'batch_id': batch_id,
            'total': len(results),
            'successful': success_count,
            'failed': failed_count,
            'partial': partial_count,
            'statistics': batch_stats
        }
        
    except Exception as e:
        print(f"[EXECUTE_ERROR] {e}")
        import traceback
        traceback.print_exc()
        
        # Release the lock on error
        clear_migration_lock(batch_id)
        
        return {
            'success': False,
            'error': str(e)
        }
