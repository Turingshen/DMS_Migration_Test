/**
 * validation.js — Validation dashboard logic
 * Fetches data from /batch/<bid>/validation/data and renders KPIs,
 * DOKOB mapping coverage, error analysis, and source→target comparison.
 */
(function () {
    'use strict';

    const app = document.getElementById('validationApp');
    if (!app) return;
    const BATCH_ID = app.dataset.batchId;
    let allRows = [];    // comparison data
    let activeFilter = 'all';

    // ── Bootstrap ─────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        loadValidationData();
        initFilterPills();
        initSearch();
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
            I18n.applyAll();
        } catch (e) {
            hide('loadingSpinner'); show('validationContent');
            document.getElementById('validationContent').innerHTML =
                `<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> ${e.message}</div>`;
        }
    };

    // ── Render orchestrator ───────────────────────────────────────
    function renderAll(data) {
        renderBatchInfo(data.batch);
        renderKPIs(data.kpis);
        renderProgress(data.kpis);
        renderDokob(data.dokob_mapping);
        renderLinkErrors(data.link_errors);
        renderUploadErrors(data.upload_errors);
        allRows = data.comparison || [];
        renderComparison();
    }

    // ── Batch info ────────────────────────────────────────────────
    function renderBatchInfo(b) {
        if (!b) return;
        const desc = b.description || '';
        const wave = b.wave ? ` (Wave ${b.wave})` : '';
        setText('valBatchDesc', desc + wave);
    }

    // ── KPI cards ─────────────────────────────────────────────────
    function renderKPIs(k) {
        setText('kpiTotal',    fmt(k.total));
        setText('kpiLinked',   fmt(k.linked));
        setText('kpiFailed',   fmt(k.link_failed));
        setText('kpiPending',  fmt((k.pending || 0) + (k.linking || 0)));
        setText('kpiSkipped',  fmt(k.link_skipped));
        setText('kpiCoverage', k.coverage_pct + '%');
    }

    // ── Progress bars ─────────────────────────────────────────────
    function renderProgress(k) {
        const total = k.total || 1;
        // Upload progress
        const uploaded = k.upload_success || 0;
        const upPct = Math.round(uploaded / total * 100);
        el('uploadProgressBar').style.width = upPct + '%';
        setText('uploadProgressLabel', `${fmt(uploaded)} / ${fmt(total)}  (${upPct}%)`);

        // Link progress
        const linked = k.linked || 0;
        const lnPct = Math.round(linked / total * 100);
        el('linkProgressBar').style.width = lnPct + '%';
        setText('linkProgressLabel', `${fmt(linked)} / ${fmt(total)}  (${lnPct}%)`);
    }

    // ── DOKOB mapping table ───────────────────────────────────────
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
                <td><strong>${esc(r.source_dokob || '—')}</strong></td>
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

    // ── Link error table ──────────────────────────────────────────
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
        tbody.innerHTML = errors.map(e => {
            const pattern = categorizeError(e.link_error || '');
            return `<tr>
                <td><span class="err-pattern" title="${esc(e.link_error)}">${esc(pattern)}</span></td>
                <td><span class="badge badge-danger">${e.cnt}</span></td>
            </tr>`;
        }).join('');
    }

    // ── Upload error table ────────────────────────────────────────
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
        tbody.innerHTML = errors.map(e => {
            const pattern = categorizeError(e.execution_error || '');
            return `<tr>
                <td><span class="err-pattern" title="${esc(e.execution_error)}">${esc(pattern)}</span></td>
                <td><span class="badge badge-danger">${e.cnt}</span></td>
            </tr>`;
        }).join('');
    }

    // ── Source→Target comparison ───────────────────────────────────
    function renderComparison() {
        const tbody = el('compBody');
        const searchTerm = (el('compSearch').value || '').toLowerCase();

        let filtered = allRows;
        if (activeFilter !== 'all') {
            filtered = filtered.filter(r => r.link_status === activeFilter);
        }
        if (searchTerm) {
            filtered = filtered.filter(r =>
                (r.source_documentnumber || '').toLowerCase().includes(searchTerm) ||
                (r.target_documentnumber || '').toLowerCase().includes(searchTerm) ||
                (r.source_dokob || '').toLowerCase().includes(searchTerm) ||
                (r.target_dokob || '').toLowerCase().includes(searchTerm) ||
                (r.source_objky || '').toLowerCase().includes(searchTerm) ||
                (r.link_error || '').toLowerCase().includes(searchTerm) ||
                String(r.id).includes(searchTerm)
            );
        }

        if (!filtered.length) {
            tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-3">${t('val.no_data')}</td></tr>`;
        } else {
            tbody.innerHTML = filtered.map(r => {
                const srcDoc = r.source_documentnumber || '—';
                const tgtDoc = r.target_documentnumber || '—';
                const errTruncated = r.link_error ? truncate(r.link_error, 60) : '';
                return `<tr>
                    <td>${r.id}</td>
                    <td title="${esc(srcDoc)}"><span class="text-truncate">${esc(srcDoc)}</span></td>
                    <td title="${esc(tgtDoc)}"><span class="text-truncate">${esc(tgtDoc)}</span></td>
                    <td>${esc(r.source_dokob || '—')}</td>
                    <td title="${esc(r.source_objky || '')}">${esc(truncate(r.source_objky || '—', 20))}</td>
                    <td>${esc(r.target_dokob || '—')}</td>
                    <td title="${esc(r.target_objky || '')}">${esc(truncate(r.target_objky || '—', 20))}</td>
                    <td>${statusBadge(r.execution_status)}</td>
                    <td>${statusBadge(r.link_status)}</td>
                    <td title="${esc(r.link_error || '')}"><span class="err-pattern text-truncate">${esc(errTruncated)}</span></td>
                </tr>`;
            }).join('');
        }

        // Footer
        el('compFooter').textContent = t('val.comp.showing', {
            shown: filtered.length,
            total: allRows.length
        });
    }

    // ── Filter pills ──────────────────────────────────────────────
    function initFilterPills() {
        const pills = document.getElementById('compFilterPills');
        if (!pills) return;
        pills.addEventListener('click', function (e) {
            const btn = e.target.closest('[data-filter]');
            if (!btn) return;
            pills.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeFilter = btn.dataset.filter;
            renderComparison();
        });
    }

    function initSearch() {
        const input = el('compSearch');
        if (!input) return;
        let timer;
        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(renderComparison, 200);
        });
    }

    // ── CSV export ────────────────────────────────────────────────
    window.exportCSV = function () {
        if (!allRows.length) return;
        const headers = [
            'id', 'source_documentnumber', 'source_documenttype',
            'source_documentversion', 'source_documentpart',
            'source_dokob', 'source_objky',
            'target_documentnumber', 'target_documenttype',
            'target_documentversion', 'target_documentpart',
            'target_dokob', 'target_objky',
            'execution_status', 'link_status', 'link_error',
            'filename', 'file_size_bytes', 'ablage'
        ];
        const csvRows = [headers.join(';')];
        allRows.forEach(r => {
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
        a.download = `validation_${BATCH_ID}.csv`;
        a.click();
    };

    // ── Error categorization ──────────────────────────────────────
    function categorizeError(err) {
        if (!err) return '—';
        const e = err.toUpperCase();
        if (e.includes('500'))           return 'SAP 500 – Server Error';
        if (e.includes('400'))           return 'SAP 400 – Bad Request';
        if (e.includes('VORHANDEN') || e.includes('ALREADY') || e.includes('EXIST') || e.includes('DUPLICATE'))
            return 'Duplicate / Already Exists';
        if (e.includes('TIMEOUT'))       return 'Timeout';
        if (e.includes('404'))           return 'Not Found (404)';
        if (e.includes('401') || e.includes('TOKEN')) return 'Auth / Token Error';
        if (e.includes('LOCKED'))        return 'Document Locked';
        if (e.includes('CONNECTION'))    return 'Connection Error';
        // Truncate long raw error
        return truncate(err, 80);
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
        return s.substring(0, max) + '…';
    }

    function statusBadge(status) {
        if (!status) return '—';
        const cls = {
            linked: 'badge-linked', link_failed: 'badge-link_failed',
            pending: 'badge-pending', linking: 'badge-linking',
            link_skipped: 'badge-link_skipped',
            success: 'badge-success', failed: 'badge-failed',
            partial: 'badge-partial'
        }[status] || 'badge-secondary';
        return `<span class="badge ${cls}">${esc(status)}</span>`;
    }

})();
