/**
 * validation.js — Consolidated validation dashboard
 * Tabs: Dateien, Objektlinks, Fehleranalyse
 */
(function () {
    'use strict';

    const app = document.getElementById('validationApp');
    if (!app) return;
    const BATCH_ID = app.dataset.batchId;

    // Data stores
    let allFiles = [];
    let allLinks = [];          // expanded object links
    let allComparison = [];     // raw comparison rows

    // Active filters per tab
    let filesFilter = 'all';
    let linksFilter = 'all';
    let displayLimit = 500;

    // ── Bootstrap ─────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        loadValidationData();
        initFilterPills('filesFilterPills', f => { filesFilter = f; renderFiles(); });
        initFilterPills('linksFilterPills', f => { linksFilter = f; renderLinks(); });
        initSearch('filesSearch', renderFiles);
        initSearch('linksSearch', renderLinks);
        // Display limit input
        const limitInput = el('displayLimitInput');
        if (limitInput) {
            displayLimit = parseInt(limitInput.value, 10) || 500;
            limitInput.addEventListener('change', () => {
                displayLimit = Math.max(10, parseInt(limitInput.value, 10) || 500);
                renderFiles();
                renderLinks();
            });
        }
    });

    // ── Data loading ──────────────────────────────────────────────
    window.loadValidationData = async function () {
        show('loadingSpinner'); hide('validationContent');
        try {
            const res = await fetch(`/batch/${BATCH_ID}/validation/data`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Unknown');
            renderAll(data);
            hide('loadingSpinner'); show('validationContent');
            if (window.I18n) I18n.applyAll();
        } catch (e) {
            hide('loadingSpinner'); show('validationContent');
            el('validationContent').innerHTML =
                `<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> ${e.message}</div>`;
        }
    };

    // ── Render orchestrator ───────────────────────────────────────
    function renderAll(data) {
        renderBatchInfo(data.batch);
        renderKPIs(data.kpis, data.file_details);
        renderProgress(data.kpis);

        // Build object-mapping lookup: "DOKOB|objky" -> {target_dokob, target_objky}
        const objMap = {};
        for (const m of (data.obj_mappings || [])) {
            objMap[(m.source_dokob || '').toUpperCase() + '|' + (m.source_objky || '')] =
                { dokob: m.target_dokob || '', objky: m.target_objky || '' };
        }

        // Store data
        allFiles = data.file_details || [];
        allComparison = data.comparison || [];
        allLinks = expandObjectLinks(allComparison, objMap);

        // Render tabs
        renderFiles();
        renderLinks();
        renderDokob(data.dokob_mapping);
        renderLinkErrors(data.link_errors);
        renderUploadErrors(data.upload_errors);

        // Tab badge counts
        setText('tabFilesCount', allFiles.length);
        setText('tabLinksCount', allLinks.length);
        const errCount = (data.link_errors || []).reduce((s, e) => s + (e.cnt || 0), 0)
                       + (data.upload_errors || []).reduce((s, e) => s + (e.cnt || 0), 0);
        setText('tabErrorsCount', errCount || '0');
    }

    // ── Batch info ────────────────────────────────────────────────
    function renderBatchInfo(b) {
        if (!b) return;
        const desc = b.description || '';
        const wave = b.wave ? ` (Wave ${b.wave})` : '';
        setText('valBatchDesc', desc + wave);
    }

    // ── KPI cards ─────────────────────────────────────────────────
    function renderKPIs(k, files) {
        setText('kpiTotal',    fmt(k.total));
        setText('kpiLinked',   fmt(k.linked));
        setText('kpiFailed',   fmt(k.link_failed));
        setText('kpiPending',  fmt((k.pending || 0) + (k.linking || 0)));
        setText('kpiSkipped',  fmt(k.link_skipped || 0));
        setText('kpiCoverage', k.coverage_pct + '%');
    }

    // ── Progress bars ─────────────────────────────────────────────
    function renderProgress(k) {
        const total = k.total || 1;
        const skipped = k.link_skipped || 0;
        // Upload: skipped records count as done (no files to upload)
        const uploaded = (k.upload_success || 0);
        const upPct = Math.round(uploaded / total * 100);
        el('uploadProgressBar').style.width = upPct + '%';
        setText('uploadProgressLabel', `${fmt(uploaded)} / ${fmt(total)}  (${upPct}%)`);

        // Linking: exclude skipped from denominator (not applicable)
        const applicable = total - skipped;
        const linked = k.linked || 0;
        const lnPct = applicable > 0 ? Math.round(linked / applicable * 100) : 0;
        el('linkProgressBar').style.width = lnPct + '%';
        setText('linkProgressLabel', `${fmt(linked)} / ${fmt(applicable)}  (${lnPct}%)${skipped ? '  +' + fmt(skipped) + ' ' + t('val.kpi.skipped') : ''}`);
    }

    // ═══ TAB 1: Dateien ═══════════════════════════════════════════
    function renderFiles() {
        const tbody = el('filesBody');
        const searchTerm = (el('filesSearch').value || '').toLowerCase();

        let filtered = allFiles;
        if (filesFilter !== 'all') {
            filtered = filtered.filter(f => {
                if (filesFilter === 'SUCCESS') return f.upload_status === 'SUCCESS';
                if (filesFilter === 'ERROR') return f.upload_status !== 'SUCCESS';
                return true;
            });
        }
        if (searchTerm) {
            filtered = filtered.filter(f =>
                (f.filename || '').toLowerCase().includes(searchTerm) ||
                (f.source_documentnumber || '').toLowerCase().includes(searchTerm) ||
                (f.target_documentnumber || '').toLowerCase().includes(searchTerm) ||
                (f.mime_type || '').toLowerCase().includes(searchTerm) ||
                (f.error_detail || '').toLowerCase().includes(searchTerm)
            );
        }

        const totalFiltered = filtered.length;
        const displayed = filtered.slice(0, displayLimit);

        if (!displayed.length) {
            tbody.innerHTML = `<tr><td colspan="11" class="text-center text-muted py-3">${t('val.no_data')}</td></tr>`;
        } else {
            tbody.innerHTML = displayed.map(f => {
                const statusCls = f.upload_status === 'SUCCESS' ? 'diff-match' : 'diff-changed';
                const srcTvt = [f.source_documenttype, f.source_documentversion, f.source_documentpart].filter(Boolean).join('/');
                const tgtTvt = f.container_created
                    ? [f.target_documenttype, f.target_documentversion, f.target_documentpart].filter(Boolean).join('/')
                    : '';
                // DAPPL mismatch highlighting
                const headerDappl = f.header_dappl || '';
                const fileDappl = f.file_dappl || '';
                const dapplMismatch = headerDappl && fileDappl && headerDappl !== fileDappl;
                const dapplCls = dapplMismatch ? 'class="table-info"' : '';
                const dapplIcon = dapplMismatch ? ' <i class="fas fa-exchange-alt text-info" title="DAPPL mismatch"></i>' : '';
                return `<tr>
                    <td title="${esc(f.source_documentnumber || '')}">${esc(truncate(f.source_documentnumber || '\u2014', 25))}</td>
                    <td>${esc(srcTvt || '\u2014')}</td>
                    <td title="${esc(f.target_documentnumber || '')}">${esc(truncate(f.target_documentnumber || '\u2014', 25))}</td>
                    <td>${esc(tgtTvt || '\u2014')}</td>
                    <td ${dapplCls}><strong>${esc(headerDappl || '\u2014')}</strong>${dapplIcon}</td>
                    <td ${dapplCls}><strong>${esc(fileDappl || '\u2014')}</strong></td>
                    <td title="${esc(f.filename || '')}">${esc(truncate(f.filename || '\u2014', 35))}</td>
                    <td>${esc(f.mime_type || '\u2014')}</td>
                    <td>${formatSize(f.file_size_bytes)}</td>
                    <td class="${statusCls}">${statusBadge(f.upload_status)}</td>
                    <td title="${esc(f.error_detail || '')}"><span class="err-pattern">${esc(truncate(f.error_detail || f.error_category || '', 50))}</span></td>
                </tr>`;
            }).join('');
        }
        el('filesFooter').textContent = t('val.comp.showing_limit', { shown: displayed.length, filtered: totalFiltered, total: allFiles.length });
    }

    // ═══ TAB 2: Objektlinks ═══════════════════════════════════════

    /** Expand source_object_links JSON into flat link rows */
    function expandObjectLinks(rows, objMap) {
        const expanded = [];
        for (const r of rows) {
            let links = [];
            try {
                if (r.source_object_links && r.source_object_links.length > 2) {
                    links = JSON.parse(r.source_object_links);
                }
            } catch (e) { /* ignore parse errors */ }

            // Only show target info if container was actually created
            const tgtDoc = r.container_created ? r.target_documentnumber : '';

            // Combine Typ/Ver./Teil
            const srcTvt = [r.source_documenttype, r.source_documentversion, r.source_documentpart].filter(Boolean).join('/');
            const tgtTvt = r.container_created
                ? [r.target_documenttype, r.target_documentversion, r.target_documentpart].filter(Boolean).join('/')
                : '';

            if (links.length === 0) {
                // Record has no object links — use single target_dokob/target_objky
                const tgtDokob = r.container_created ? (r.target_dokob || '') : '';
                const tgtObjky = r.container_created ? (r.target_objky || '') : '';
                expanded.push({
                    id: r.id,
                    source_documentnumber: r.source_documentnumber,
                    src_tvt: srcTvt,
                    target_documentnumber: tgtDoc,
                    tgt_tvt: tgtTvt,
                    src_dokob: r.source_dokob || '\u2014',
                    src_objky: r.source_objky || '\u2014',
                    tgt_dokob: tgtDokob,
                    tgt_objky: tgtObjky,
                    link_status: r.link_status || 'pending',
                    link_error: r.link_error || '',
                    is_no_link: true
                });
            } else {
                for (const lnk of links) {
                    // Resolve per-link target via object mapping
                    let tgtDokob = '';
                    let tgtObjky = '';
                    if (r.container_created && objMap) {
                        const key = (lnk.dokob || '').toUpperCase() + '|' + (lnk.objky || '');
                        const mapped = objMap[key];
                        if (mapped) {
                            tgtDokob = mapped.dokob;
                            tgtObjky = mapped.objky;
                        } else {
                            // Fallback: pass-through source values (same behavior as execute)
                            tgtDokob = lnk.dokob || '';
                            tgtObjky = lnk.objky || '';
                        }
                    }
                    expanded.push({
                        id: r.id,
                        source_documentnumber: r.source_documentnumber,
                        src_tvt: srcTvt,
                        target_documentnumber: tgtDoc,
                        tgt_tvt: tgtTvt,
                        src_dokob: lnk.dokob || '\u2014',
                        src_objky: lnk.objky || '\u2014',
                        tgt_dokob: tgtDokob,
                        tgt_objky: tgtObjky,
                        link_status: r.link_status || 'pending',
                        link_error: r.link_error || '',
                        is_no_link: false
                    });
                }
            }
        }
        return expanded;
    }

    function renderLinks() {
        const tbody = el('linksBody');
        const searchTerm = (el('linksSearch').value || '').toLowerCase();

        let filtered = allLinks;
        if (linksFilter !== 'all') {
            filtered = filtered.filter(r => r.link_status === linksFilter);
        }
        if (searchTerm) {
            filtered = filtered.filter(r =>
                (r.source_documentnumber || '').toLowerCase().includes(searchTerm) ||
                (r.target_documentnumber || '').toLowerCase().includes(searchTerm) ||
                (r.src_dokob || '').toLowerCase().includes(searchTerm) ||
                (r.src_objky || '').toLowerCase().includes(searchTerm) ||
                (r.tgt_dokob || '').toLowerCase().includes(searchTerm) ||
                (r.tgt_objky || '').toLowerCase().includes(searchTerm) ||
                (r.link_error || '').toLowerCase().includes(searchTerm)
            );
        }

        const totalFiltered = filtered.length;
        const displayed = filtered.slice(0, displayLimit);

        if (!displayed.length) {
            tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-3">${t('val.no_data')}</td></tr>`;
        } else {
            tbody.innerHTML = displayed.map(r => {
                // Diff coloring: compare source vs target
                const dokobCls = diffClass(r.src_dokob, r.tgt_dokob);
                const objkyCls = diffClass(r.src_objky, r.tgt_objky);
                const tvtCls = diffClass(r.src_tvt, r.tgt_tvt);

                // Status text for pending records
                let statusHtml = statusBadge(r.link_status);
                if (r.link_status === 'pending' || r.link_status === 'linking') {
                    statusHtml = `<span class="badge badge-warning">${t('val.links.not_linked')}</span>`;
                }

                return `<tr>
                    <td title="${esc(r.source_documentnumber || '')}">${esc(truncate(r.source_documentnumber || '\u2014', 25))}</td>
                    <td class="${tvtCls}">${esc(r.src_tvt || '\u2014')}</td>
                    <td title="${esc(r.target_documentnumber || '')}">${esc(truncate(r.target_documentnumber || '\u2014', 25))}</td>
                    <td class="${tvtCls}">${esc(r.tgt_tvt || '\u2014')}</td>
                    <td class="${dokobCls}">${esc(r.src_dokob)}</td>
                    <td title="${esc(r.src_objky)}">${esc(truncate(r.src_objky, 25))}</td>
                    <td class="${dokobCls}">${esc(r.tgt_dokob || '\u2014')}</td>
                    <td class="${objkyCls}" title="${esc(r.tgt_objky)}">${esc(truncate(r.tgt_objky || '\u2014', 25))}</td>
                    <td>${statusHtml}</td>
                    <td title="${esc(r.link_error || '')}"><span class="err-pattern">${esc(truncate(r.link_error, 50))}</span></td>
                </tr>`;
            }).join('');
        }
        el('linksFooter').textContent = t('val.comp.showing_limit', { shown: displayed.length, filtered: totalFiltered, total: allLinks.length });
    }

    /** Return CSS class for diff highlighting */
    function diffClass(src, tgt) {
        if (!tgt || tgt === '\u2014') return 'diff-empty';
        if (src === tgt) return 'diff-match';
        return 'diff-changed';
    }

    // ═══ TAB 3: Fehleranalyse ═════════════════════════════════════

    function renderDokob(rows) {
        const tbody = el('dokobTable').querySelector('tbody');
        if (!rows || !rows.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">${t('val.no_data')}</td></tr>`;
            return;
        }
        tbody.innerHTML = rows.map(r => {
            const total = r.total_records || 0;
            const mapped = r.mapped || 0;
            const pct = total > 0 ? Math.round(mapped / total * 100) : 0;
            const barColor = pct === 100 ? '#28a745' : pct >= 50 ? '#ffc107' : '#dc3545';
            return `<tr>
                <td><strong>${esc(r.source_dokob || '\u2014')}</strong></td>
                <td>${fmt(total)}</td>
                <td class="text-success">${fmt(mapped)}</td>
                <td class="${r.unmapped > 0 ? 'text-danger font-weight-bold' : ''}">${fmt(r.unmapped)}</td>
                <td class="text-success">${fmt(r.linked)}</td>
                <td class="${r.link_failed > 0 ? 'text-danger' : ''}">${fmt(r.link_failed)}</td>
                <td style="min-width:130px">
                    <div class="d-flex align-items-center">
                        <div class="mini-progress flex-grow-1 mr-2">
                            <div class="bar" style="width:${pct}%; background:${barColor}"></div>
                        </div>
                        <small>${pct}%</small>
                    </div>
                </td>
            </tr>`;
        }).join('');
    }

    function renderLinkErrors(errors) {
        const tbody = el('linkErrorBody');
        const countBadge = el('linkErrorCount');
        if (!errors || !errors.length) {
            tbody.innerHTML = `<tr><td colspan="2" class="text-center text-muted">${t('val.no_errors')}</td></tr>`;
            countBadge.textContent = '0';
            return;
        }
        const totalErrors = errors.reduce((s, e) => s + (e.cnt || 0), 0);
        countBadge.textContent = totalErrors;
        tbody.innerHTML = errors.map(e => `<tr>
            <td><span class="err-pattern" title="${esc(e.link_error)}">${esc(categorizeError(e.link_error))}</span></td>
            <td><span class="badge badge-danger">${e.cnt}</span></td>
        </tr>`).join('');
    }

    function renderUploadErrors(errors) {
        const tbody = el('uploadErrorBody');
        const countBadge = el('uploadErrorCount');
        if (!errors || !errors.length) {
            tbody.innerHTML = `<tr><td colspan="2" class="text-center text-muted">${t('val.no_errors')}</td></tr>`;
            countBadge.textContent = '0';
            return;
        }
        const totalErrors = errors.reduce((s, e) => s + (e.cnt || 0), 0);
        countBadge.textContent = totalErrors;
        tbody.innerHTML = errors.map(e => `<tr>
            <td><span class="err-pattern" title="${esc(e.execution_error)}">${esc(categorizeError(e.execution_error))}</span></td>
            <td><span class="badge badge-danger">${e.cnt}</span></td>
        </tr>`).join('');
    }

    // ── Filter pills (generic) ────────────────────────────────────
    function initFilterPills(containerId, callback) {
        const container = el(containerId);
        if (!container) return;
        container.addEventListener('click', function (e) {
            const btn = e.target.closest('[data-filter]');
            if (!btn) return;
            container.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            callback(btn.dataset.filter);
        });
    }

    function initSearch(inputId, callback) {
        const input = el(inputId);
        if (!input) return;
        let timer;
        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(callback, 200);
        });
    }

    // ── CSV export ────────────────────────────────────────────────
    window.exportCSV = function () {
        // Export active tab data
        const activeTab = document.querySelector('#valTabs .nav-link.active');
        const tabHref = activeTab ? activeTab.getAttribute('href') : '#tabFiles';

        let headers, rows, filename;

        if (tabHref === '#tabFiles') {
            headers = ['source_documentnumber', 'source_documenttype', 'source_documentversion', 'source_documentpart',
                       'target_documentnumber', 'target_documenttype', 'target_documentversion', 'target_documentpart',
                       'filename', 'mime_type', 'file_size_bytes', 'upload_status', 'error_category', 'error_detail'];
            rows = allFiles;
            filename = `validation_files_${BATCH_ID}.csv`;
        } else if (tabHref === '#tabLinks') {
            headers = ['source_documentnumber', 'src_tvt', 'target_documentnumber', 'tgt_tvt',
                       'src_dokob', 'src_objky', 'tgt_dokob', 'tgt_objky', 'link_status', 'link_error'];
            rows = allLinks;
            filename = `validation_links_${BATCH_ID}.csv`;
        } else {
            headers = ['id', 'source_documentnumber', 'target_documentnumber', 'source_dokob',
                       'source_objky', 'target_dokob', 'target_objky', 'execution_status',
                       'link_status', 'link_error'];
            rows = allComparison;
            filename = `validation_errors_${BATCH_ID}.csv`;
        }

        if (!rows.length) return;
        const csvRows = [headers.join(';')];
        rows.forEach(r => {
            csvRows.push(headers.map(h => {
                let v = r[h];
                if (v == null) v = '';
                v = String(v).replace(/"/g, '""');
                return `"${v}"`;
            }).join(';'));
        });
        const blob = new Blob(['\uFEFF' + csvRows.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
    };

    // ── Error categorization ──────────────────────────────────────
    function categorizeError(err) {
        if (!err) return '\u2014';
        const e = err.toUpperCase();
        if (e.includes('500'))           return 'SAP 500 \u2013 Server Error';
        if (e.includes('400'))           return 'SAP 400 \u2013 Bad Request';
        if (e.includes('VORHANDEN') || e.includes('ALREADY') || e.includes('EXIST') || e.includes('DUPLICATE'))
            return 'Duplicate / Already Exists';
        if (e.includes('TIMEOUT'))       return 'Timeout';
        if (e.includes('404'))           return 'Not Found (404)';
        if (e.includes('401') || e.includes('TOKEN')) return 'Auth / Token Error';
        if (e.includes('LOCKED'))        return 'Document Locked';
        if (e.includes('CONNECTION'))    return 'Connection Error';
        return truncate(err, 80);
    }

    // ── Status badge ──────────────────────────────────────────────
    function statusBadge(status) {
        if (!status) return '<span class="badge badge-secondary">\u2014</span>';
        const labels = {
            'linked': 'Verlinkt', 'link_failed': 'Fehler', 'link_exists': 'Vorhanden',
            'partial_linked': 'Teilweise', 'pending': 'Ausstehend', 'linking': 'L\u00e4uft',
            'link_skipped': '\u00dcbersprungen',
            'success': 'Erfolgreich', 'failed': 'Fehlgeschlagen', 'partial': 'Teilweise',
            'SUCCESS': 'Erfolgreich'
        };
        const label = labels[status] || status;
        let cls;
        if (['linked', 'link_exists', 'success', 'SUCCESS'].includes(status)) cls = 'badge-success';
        else if (['link_failed', 'failed'].includes(status) || status.includes('FAIL')) cls = 'badge-danger';
        else if (['partial', 'partial_linked'].includes(status) || status.includes('SIZE_LIMIT')) cls = 'badge-warning';
        else if (status === 'pending') cls = 'badge-warning';
        else if (status === 'linking') cls = 'badge-info';
        else cls = 'badge-secondary';
        return `<span class="badge ${cls}">${esc(label)}</span>`;
    }

    // ── Utilities ─────────────────────────────────────────────────
    function el(id)       { return document.getElementById(id); }
    function show(id)     { const e = el(id); if (e) e.style.display = ''; }
    function hide(id)     { const e = el(id); if (e) e.style.display = 'none'; }
    function setText(id, v) { const e = el(id); if (e) e.textContent = v; }
    function fmt(n)       { return (n || 0).toLocaleString('de-DE'); }
    function t(key, vars) { return window.t ? window.t(key, vars) : key; }

    function esc(s) {
        if (!s) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function truncate(s, max) {
        if (!s || s.length <= max) return s || '';
        return s.substring(0, max) + '\u2026';
    }

    function formatSize(bytes) {
        if (!bytes) return '\u2014';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1048576).toFixed(1) + ' MB';
    }

    // ═══ DAPPL/Extension Analysis ═════════════════════════════════
    window.loadDapplAnalysis = async function () {
        const loadingEl = el('dapplLoading');
        const contentEl = el('dapplContent');
        const emptyEl = el('dapplEmpty');
        const refreshBtn = el('dapplRefreshBtn');

        // Show loading state
        hide('dapplContent');
        hide('dapplEmpty');
        show('dapplLoading');
        if (refreshBtn) refreshBtn.disabled = true;

        try {
            const res = await fetch(`/batch/${BATCH_ID}/validation/dappl-analysis`);
            const data = await res.json();

            if (!data.success) throw new Error(data.error || 'Unknown error');

            renderDapplAnalysis(data.analysis, data.summary);
            hide('dapplLoading');
            show('dapplContent');
        } catch (err) {
            hide('dapplLoading');
            el('dapplContent').innerHTML = `
                <div class="alert alert-danger m-3">
                    <i class="fas fa-exclamation-triangle"></i> ${esc(err.message)}
                </div>`;
            show('dapplContent');
        } finally {
            if (refreshBtn) refreshBtn.disabled = false;
        }
    };

    function renderDapplAnalysis(analysis, summary) {
        // Update badge
        setText('dapplComboCount', summary.combinations || 0);

        // Count mismatches
        const mismatchCount = analysis.filter(r => r.mismatch).length;

        // Summary alert
        const summaryEl = el('dapplSummary');
        const problemCount = summary.total_problems || 0;
        const alertClass = (problemCount > 0 || mismatchCount > 0) ? 'alert-warning' : 'alert-success';
        summaryEl.className = `alert ${alertClass} m-3 py-2`;
        summaryEl.innerHTML = `
            <i class="fas fa-${(problemCount > 0 || mismatchCount > 0) ? 'exclamation-triangle' : 'check-circle'}"></i>
            <strong>${fmt(summary.combinations)}</strong> DAPPL/Endung-Kombinationen gefunden.
            <strong>${fmt(summary.total)}</strong> Datensätze analysiert.
            ${mismatchCount > 0 ? `<span class="text-info ml-2"><i class="fas fa-exchange-alt"></i> <strong>${fmt(mismatchCount)}</strong> DAPPL-Abweichungen (Header ≠ File).</span>` : ''}
            ${problemCount > 0 ? `<span class="text-danger ml-2"><strong>${fmt(problemCount)}</strong> Probleme erkannt.</span>` : ''}
        `;

        // Table body
        const tbody = el('dapplBody');
        if (!analysis || !analysis.length) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">${t('val.no_data')}</td></tr>`;
            return;
        }

        tbody.innerHTML = analysis.map(r => {
            const hasProblems = r.problems > 0;
            const rowClass = r.mismatch ? 'table-info' : (hasProblems ? 'table-warning' : '');
            const successPct = r.success_rate || 0;
            const barColor = successPct >= 90 ? '#28a745' : successPct >= 50 ? '#ffc107' : '#dc3545';

            // Icon for mismatch
            const mismatchIcon = r.mismatch ? '<i class="fas fa-exchange-alt text-info ml-1" title="Header DAPPL differs from File DAPPL"></i>' : '';

            return `<tr class="${rowClass}">
                <td><strong>${esc(r.header_dappl)}</strong>${mismatchIcon}</td>
                <td><strong>${esc(r.file_dappl)}</strong></td>
                <td><code>${esc(r.file_ext)}</code></td>
                <td>${fmt(r.total)}</td>
                <td class="text-success">${fmt(r.upload_success)}</td>
                <td class="${r.upload_failed > 0 ? 'text-danger font-weight-bold' : ''}">${fmt(r.upload_failed)}</td>
                <td class="text-success">${fmt(r.link_success)}</td>
                <td class="${r.link_failed > 0 ? 'text-danger font-weight-bold' : ''}">${fmt(r.link_failed)}</td>
                <td style="min-width:100px">
                    <div class="d-flex align-items-center">
                        <div class="mini-progress flex-grow-1 mr-2" style="height:4px;">
                            <div class="bar" style="width:${successPct}%; background:${barColor};"></div>
                        </div>
                        <small class="${successPct < 50 ? 'text-danger' : ''}">${successPct}%</small>
                    </div>
                </td>
            </tr>`;
        }).join('');
    }
})();
