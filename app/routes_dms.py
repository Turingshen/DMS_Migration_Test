"""DMS object loading, batch creation, and wave plan routes."""

from flask import request, jsonify, session, Response
import pandas as pd
import json
import os
from sqlalchemy import text

from app.blueprint import migrate_bp, misc_engine


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
            # Exclusion rules (status-based, applied in SQL):
            # - EQUI/IFLOT: Exclude if JEST status I0320, I0013, I0076 (deleted)
            # - PMAUFK: Exclude if JEST status I0045 (TECO) or I0013, I0076 (deleted)
            # - PMQMEL/SMQMEL: Exclude if JEST status I0072 (closed) or I0076 (deleted)
            # - PMAFVC: Exclude if parent order is TECO/deleted
            # - STKO_DOC: Exclude if STKO.LOEKZ = 'X'
            # - STPO_DOC: Exclude if STPO.LKENZ = 'X'
            # - PLKO: Exclude if PLKO.LOEKZ = 'X'
            # Post-filter (applied in Python):
            # - ALL: Exclude if no entry in DMS_DOC_FILES (no file in Content Repository)
            # Scalar subquery: checks DMS_DOC_FILES for file existence
            _has_file_sql = """CASE WHEN EXISTS (
                        SELECT 1 FROM DIL.DMS_DOC_FILES df 
                        WHERE df.DOKNR = drad.DOKNR AND df.DOKAR = drad.DOKAR 
                        AND df.DOKVR = drad.DOKVR AND df.DOKTL = drad.DOKTL 
                        AND df.MANDT = '100'
                    ) THEN 1 ELSE 0 END as HAS_FILE"""
            
            queries = {
                'EQUI': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY, 
                           equz.IWERK as WERK,
                           {_has_file_sql}
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
                           iflot.IWERK as WERK,
                           {_has_file_sql}
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
                           COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.MPLA mpla ON drad.OBJKY = mpla.WARPL
                    LEFT JOIN DIL.MPOS mpos ON mpla.WARPL = mpos.WARPL
                    WHERE drad.DOKOB = 'MPLA' 
                      AND COALESCE(mpos.IWERK, LEFT(mpla.PLAN_SORT, 4)) IN ('{werke_filter}')
                """,
                'PMPLKO': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           plko.WERKS as WERK,
                           {_has_file_sql}
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
                           aufk.WERKS as WERK,
                           {_has_file_sql}
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
                           afvc.WERKS as WERK,
                           {_has_file_sql}
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
                           qmih.IWERK as WERK,
                           {_has_file_sql}
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
                           qmih.IWERK as WERK,
                           {_has_file_sql}
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
                           stko.WRKAN as WERK,
                           {_has_file_sql}
                    FROM DIL.DRAD drad
                    JOIN DIL.STKO stko ON drad.OBJKY = BINTOHEX(stko.GUIDX)
                    WHERE drad.DOKOB = 'STKO_DOC' AND stko.WRKAN IN ('{werke_filter}')
                      AND (stko.LOEKZ IS NULL OR stko.LOEKZ = '')
                """,
                'STPO_DOC': f"""
                    SELECT drad.DOKAR, drad.DOKNR, drad.DOKVR, drad.DOKTL, drad.DOKOB, drad.OBJKY,
                           stko.WRKAN as WERK,
                           {_has_file_sql}
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
            stats_excluded = {}  # Excluded counts (status-based)
            stats_no_file = {}  # Records with DB storage (DRAO, no DMS_DOC_FILES/KPRO entry)
            total_queries = len(queries)
            
            with dil_db.engine.begin() as con:
                for idx, (dokob, query) in enumerate(queries.items()):
                    percent = 10 + int((idx / total_queries) * 80)
                    yield f"data: {json.dumps({'type': 'progress', 'dokob': dokob, 'message': f'Lade {dokob}...', 'percent': percent, 'step': idx + 1, 'total_steps': total_queries})}\n\n"
                    
                    query_start = time.time()
                    try:
                        # Get data (includes FILEP column from LEFT JOIN DRAW)
                        df = pd.read_sql(query, con)
                        df.columns = [c.lower() for c in df.columns]
                        
                        # Map HAS_FILE to ABLAGE column: KPRO (Content Repository) or DB (DRAO)
                        total_after_status = len(df)
                        if 'has_file' in df.columns:
                            df['ablage'] = df['has_file'].map({1: 'KPRO', 0: 'DB'}).fillna('DB')
                            db_count = int((df['has_file'] == 0).sum())
                            df = df.drop(columns=['has_file'])
                        else:
                            df['ablage'] = 'KPRO'
                            db_count = 0
                        
                        count = len(df)
                        stats[dokob] = count
                        stats_no_file[dokob] = db_count  # now tracks DB-stored count (not excluded)
                        if count > 0:
                            all_results.append(df)
                        
                        # Get total count (without any filter) for exclusion statistics
                        total_count = total_after_status  # Default
                        excluded_count = 0
                        if dokob in count_queries:
                            try:
                                result = con.execute(text(count_queries[dokob]))
                                total_count = result.scalar() or 0
                                excluded_count = total_count - total_after_status  # Status-excluded only
                            except Exception as count_err:
                                print(f"[DMS Load] Count query error for {dokob}: {count_err}")
                        
                        stats_total[dokob] = total_count
                        stats_excluded[dokob] = excluded_count
                        
                        query_time = time.time() - query_start
                        
                        yield f"data: {json.dumps({'type': 'step_complete', 'dokob': dokob, 'count': count, 'total': total_count, 'excluded': excluded_count, 'no_file': db_count, 'time': f'{query_time:.2f}s', 'percent': percent + 5})}\n\n"
                        print(f"[DMS Load] {dokob}: {count} records (status-excluded {excluded_count}, db-stored {db_count}) in {query_time:.2f}s")
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
            if auto_save:
                try:
                    import sqlite3
                    os.makedirs('userdata', exist_ok=True)
                    db_path = 'userdata/dms_objects.db'
                    conn = sqlite3.connect(db_path)
                    if data_list:
                        df_save = pd.DataFrame(data_list)
                        df_save.to_sql('dms_objects', conn, if_exists='replace', index=False)
                    else:
                        # Clear old data when new load returns 0 results
                        cursor = conn.cursor()
                        cursor.execute("DROP TABLE IF EXISTS dms_objects")
                        conn.commit()
                    conn.close()
                    saved = True
                    print(f"[DMS Load] Auto-saved {len(data_list)} records to {db_path}")
                except Exception as save_error:
                    print(f"[DMS Load] Auto-save failed: {save_error}")
            
            # Send final result with exclusion statistics
            yield f"data: {json.dumps({'type': 'complete', 'stats': stats, 'stats_total': stats_total, 'stats_excluded': stats_excluded, 'stats_no_file': stats_no_file, 'count': len(data_list), 'query_time': f'{total_time:.2f}s', 'saved': saved, 'data': data_list})}\n\n"
            
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
    
    Exclusion keys are read from userdata/pending_exclusion_keys.json (uploaded via
    /api/exclusion-template/upload) and applied before staging insertion.
    """
    import sqlite3
    from datetime import datetime
    from app.db_schema import EXCLUSION_EXCEL_SHEETS
    
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
    
    # Load pending exclusion keys (if uploaded via Excel)
    exclusion_keys = {}  # {dokob_upper: set of objky strings}
    excl_descriptions = {}  # {dokob: {objky: label}}
    temp_excl_path = os.path.join('userdata', 'pending_exclusion_keys.json')
    if os.path.exists(temp_excl_path):
        try:
            with open(temp_excl_path, 'r', encoding='utf-8') as f:
                excl_data = json.load(f)
            for dokob, info in excl_data.items():
                dk = dokob.strip().upper()
                exclusion_keys[dk] = set(str(k).strip() for k in info.get('keys', []))
                excl_descriptions[dk] = info.get('descriptions', {})
        except Exception as e:
            print(f"[DMS Batch] Warning: Could not load exclusion keys: {e}")
    
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
            
            # -- Apply exclusion keys (filter out matching DOKOB+OBJKY) --
            excluded_count = 0
            excluded_per_dokob = {}
            if exclusion_keys:
                before_count = len(dms_df)
                
                # Build mask: keep rows where (dokob, objky) is NOT in exclusion keys
                def is_excluded(row):
                    dk = str(row.get('dokob', '')).strip().upper()
                    ok = str(row.get('objky', '')).strip()
                    return dk in exclusion_keys and ok in exclusion_keys[dk]
                
                excl_mask = dms_df.apply(is_excluded, axis=1)
                
                # Count excluded per DOKOB
                if excl_mask.any():
                    excluded_rows = dms_df[excl_mask]
                    for dk in excluded_rows['dokob'].unique():
                        dk_upper = str(dk).strip().upper()
                        cnt = int((excluded_rows['dokob'] == dk).sum())
                        excluded_per_dokob[dk_upper] = cnt
                
                dms_df = dms_df[~excl_mask].reset_index(drop=True)
                excluded_count = before_count - len(dms_df)
                
                if excluded_count > 0:
                    excl_detail = ', '.join(f'{k}: {v}' for k, v in excluded_per_dokob.items())
                    yield f"data: {json.dumps({'type': 'status', 'message': f'{excluded_count:,} Objekte durch Ausschluss-Liste entfernt ({excl_detail})', 'percent': 12})}\n\n"
                    print(f"[DMS Batch] Exclusion applied: {excluded_count} records removed ({excl_detail})")
            
            if len(dms_df) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Keine Objekte nach Anwendung der Ausschluss-Liste übrig'})}\n\n"
                return
            
            # Generate batch ID
            batch_id = f"DMS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Get unique Werke from the loaded data
            unique_werke = dms_df['werk'].unique().tolist() if 'werk' in dms_df.columns else []
            werke_str = ', '.join(sorted(unique_werke))
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Bereite Staging-Daten vor...', 'percent': 15})}\n\n"
            
            # Helper function to compute target document number
            # - Auto-generated IDs (25 digits, all numeric) ? None (will get new number in target)
            # - Manual/external IDs (contain letters) ? preserve as target number
            def compute_target_docnumber(doknr):
                if pd.isnull(doknr):
                    return None
                val = str(doknr).strip()
                # Check if this is an auto-generated ID (25 chars, all numeric after stripping leading zeros)
                if len(val) == 25:
                    try:
                        int(val.lstrip('0') or '0')
                        return None  # Auto-generated ? will get new number
                    except (ValueError, TypeError):
                        pass
                # Manual/external ID ? preserve it
                return val[:25]
            
            # Prepare staging DataFrame using vectorized operations (FAST!)
            # NOTE: target_* fields depend on whether source is auto-generated or manual
            # - Auto-generated IDs ? target stays None (will get new number during migration)
            # - Manual/external IDs ? target = source (preserve external number)
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
                'ablage': dms_df['ablage'].fillna('KPRO') if 'ablage' in dms_df.columns else 'KPRO',
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
                
                # Persist exclusion keys to DB (for later reference / re-download)
                if exclusion_keys:
                    for dk, keys_set in exclusion_keys.items():
                        descs = excl_descriptions.get(dk, {})
                        for objky_val in keys_set:
                            try:
                                con.execute(text("""
                                    INSERT INTO dbo.migration_exclusion_keys
                                        (batch_id, dokob, objky, label, excluded_by)
                                    VALUES (:batch_id, :dokob, :objky, :label, :user)
                                """), {
                                    'batch_id': batch_id,
                                    'dokob': dk,
                                    'objky': objky_val,
                                    'label': descs.get(objky_val),
                                    'user': current_user
                                })
                            except Exception:
                                pass  # Skip duplicate keys silently
            
            # Clean up temp exclusion file
            if os.path.exists(temp_excl_path):
                try:
                    os.remove(temp_excl_path)
                except Exception:
                    pass
            
            print(f"[DMS Batch] Created batch {batch_id} with {len(staging_df)} records"
                  f" (excluded: {excluded_count})")
            
            yield f"data: {json.dumps({'type': 'complete', 'success': True, 'batch_id': batch_id, 'record_count': len(staging_df), 'excluded_count': excluded_count, 'excluded_per_dokob': excluded_per_dokob, 'wave': wave, 'percent': 100})}\n\n"
            
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


# ========================================================================
# Wave Plan CRUD
# ========================================================================

@migrate_bp.route('/wave-plans', methods=['GET'])
def get_wave_plans():
    """Get all wave plans."""
    try:
        with misc_engine.connect() as con:
            # Check if table exists first
            check = text("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='migration_wave_plan'
            """)
            if con.execute(check).fetchone()[0] == 0:
                return jsonify({'success': True, 'waves': []})

            result = con.execute(text("""
                SELECT id, wave_name,
                       qual_load_start, qual_load_end, qual_load_status,
                       qual_link_start, qual_link_end, qual_link_status,
                       prod_load_start, prod_load_end, prod_load_status,
                       prod_link_start, prod_link_end, prod_link_status,
                       notes, created_at, updated_at
                FROM dbo.migration_wave_plan
                ORDER BY wave_name
            """)).fetchall()

            waves = []
            for row in result:
                waves.append({
                    'id': row[0],
                    'wave_name': row[1],
                    'qual_load_start': str(row[2]) if row[2] else None,
                    'qual_load_end': str(row[3]) if row[3] else None,
                    'qual_load_status': row[4] or 'vorbereitung',
                    'qual_link_start': str(row[5]) if row[5] else None,
                    'qual_link_end': str(row[6]) if row[6] else None,
                    'qual_link_status': row[7] or 'vorbereitung',
                    'prod_load_start': str(row[8]) if row[8] else None,
                    'prod_load_end': str(row[9]) if row[9] else None,
                    'prod_load_status': row[10] or 'vorbereitung',
                    'prod_link_start': str(row[11]) if row[11] else None,
                    'prod_link_end': str(row[12]) if row[12] else None,
                    'prod_link_status': row[13] or 'vorbereitung',
                    'notes': row[14],
                    'created_at': str(row[15]) if row[15] else None,
                    'updated_at': str(row[16]) if row[16] else None,
                })
            return jsonify({'success': True, 'waves': waves})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@migrate_bp.route('/wave-plans', methods=['POST'])
def create_wave_plan():
    """Create or update a wave plan."""
    try:
        data = request.json
        wave_name = data.get('wave_name', '').strip()
        if not wave_name:
            return jsonify({'success': False, 'error': 'wave_name ist erforderlich'})

        with misc_engine.begin() as con:
            # Check if exists
            existing = con.execute(text(
                "SELECT id FROM dbo.migration_wave_plan WHERE wave_name = :wn"
            ), {'wn': wave_name}).fetchone()

            if existing:
                # Update
                con.execute(text("""
                    UPDATE dbo.migration_wave_plan SET
                        qual_load_start = :qls, qual_load_end = :qle, qual_load_status = :qlst,
                        qual_link_start = :qks, qual_link_end = :qke, qual_link_status = :qkst,
                        prod_load_start = :pls, prod_load_end = :ple, prod_load_status = :plst,
                        prod_link_start = :pks, prod_link_end = :pke, prod_link_status = :pkst,
                        notes = :notes, updated_at = GETUTCDATE()
                    WHERE wave_name = :wn
                """), {
                    'wn': wave_name,
                    'qls': data.get('qual_load_start') or None,
                    'qle': data.get('qual_load_end') or None,
                    'qlst': data.get('qual_load_status', 'vorbereitung'),
                    'qks': data.get('qual_link_start') or None,
                    'qke': data.get('qual_link_end') or None,
                    'qkst': data.get('qual_link_status', 'vorbereitung'),
                    'pls': data.get('prod_load_start') or None,
                    'ple': data.get('prod_load_end') or None,
                    'plst': data.get('prod_load_status', 'vorbereitung'),
                    'pks': data.get('prod_link_start') or None,
                    'pke': data.get('prod_link_end') or None,
                    'pkst': data.get('prod_link_status', 'vorbereitung'),
                    'notes': data.get('notes', ''),
                })
                return jsonify({'success': True, 'message': f'{wave_name} aktualisiert'})
            else:
                # Insert
                con.execute(text("""
                    INSERT INTO dbo.migration_wave_plan
                        (wave_name, qual_load_start, qual_load_end, qual_load_status,
                         qual_link_start, qual_link_end, qual_link_status,
                         prod_load_start, prod_load_end, prod_load_status,
                         prod_link_start, prod_link_end, prod_link_status, notes)
                    VALUES
                        (:wn, :qls, :qle, :qlst, :qks, :qke, :qkst,
                         :pls, :ple, :plst, :pks, :pke, :pkst, :notes)
                """), {
                    'wn': wave_name,
                    'qls': data.get('qual_load_start') or None,
                    'qle': data.get('qual_load_end') or None,
                    'qlst': data.get('qual_load_status', 'vorbereitung'),
                    'qks': data.get('qual_link_start') or None,
                    'qke': data.get('qual_link_end') or None,
                    'qkst': data.get('qual_link_status', 'vorbereitung'),
                    'pls': data.get('prod_load_start') or None,
                    'ple': data.get('prod_load_end') or None,
                    'plst': data.get('prod_load_status', 'vorbereitung'),
                    'pks': data.get('prod_link_start') or None,
                    'pke': data.get('prod_link_end') or None,
                    'pkst': data.get('prod_link_status', 'vorbereitung'),
                    'notes': data.get('notes', ''),
                })
                return jsonify({'success': True, 'message': f'{wave_name} erstellt'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@migrate_bp.route('/wave-plans/<int:wave_id>', methods=['DELETE'])
def delete_wave_plan(wave_id):
    """Delete a wave plan."""
    try:
        with misc_engine.begin() as con:
            con.execute(text("DELETE FROM dbo.migration_wave_plan WHERE id = :id"), {'id': wave_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@migrate_bp.route('/wave-plans/task-status', methods=['PUT'])
def update_wave_task_status():
    """Update a single task status for a wave plan."""
    try:
        data = request.json
        wave_id = data.get('wave_id')
        task_field = data.get('task_field')  # e.g. 'qual_load_status'
        new_status = data.get('status')

        allowed_fields = ['qual_load_status', 'qual_link_status', 'prod_load_status', 'prod_link_status']
        allowed_statuses = ['vorbereitung', 'arbeit', 'fertig']

        if task_field not in allowed_fields:
            return jsonify({'success': False, 'error': f'Ungültiges Feld: {task_field}'})
        if new_status not in allowed_statuses:
            return jsonify({'success': False, 'error': f'Ungültiger Status: {new_status}'})

        with misc_engine.begin() as con:
            con.execute(text(f"""
                UPDATE dbo.migration_wave_plan
                SET {task_field} = :status, updated_at = GETUTCDATE()
                WHERE id = :id
            """), {'status': new_status, 'id': wave_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
