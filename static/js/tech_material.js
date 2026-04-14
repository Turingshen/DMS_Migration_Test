/**
 * tech_material.js — TECH Material workflow logic
 * Handles: file upload → preview → DIL enrichment → staging review
 */
(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────
    let currentStep = 1;
    let uploadedFilename = '';
    let previewData = [];
    let stagedData = [];
    let stagedColumns = [];
    let currentBatchId = '';

    // ── Init ───────────────────────────────────────────────────────
    $(document).ready(function () {
        initUploadZone();
        loadBatches();
        if (typeof I18n !== 'undefined') I18n.applyAll();
    });

    // ── Workflow navigation ────────────────────────────────────────
    function setStep(step) {
        currentStep = step;
        for (let i = 1; i <= 4; i++) {
            const el = $('#techStep' + i);
            el.removeClass('active done');
            if (i < step) el.addClass('done');
            if (i === step) el.addClass('active');
        }
        $('#techPanelUpload').toggleClass('d-none', step !== 1);
        $('#techPanelReview').toggleClass('d-none', step !== 2);
        $('#techPanelExecute').toggleClass('d-none', step !== 3);
        $('#techPanelResult').toggleClass('d-none', step !== 4);
    }

    // ── Upload zone ────────────────────────────────────────────────
    function initUploadZone() {
        const zone = $('#techUploadZone');
        const input = $('#techFileInput');

        zone.on('dragover', function (e) { e.preventDefault(); zone.addClass('dragover'); });
        zone.on('dragleave drop', function () { zone.removeClass('dragover'); });
        zone.on('drop', function (e) {
            e.preventDefault();
            const files = e.originalEvent.dataTransfer.files;
            if (files.length > 0) handleFile(files[0]);
        });
        input.on('change', function () {
            if (this.files.length > 0) handleFile(this.files[0]);
        });
    }

    // Step 1: Upload & parse → show preview
    function handleFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        $('#techFileName').text(file.name);
        $('#techFileInfo').removeClass('d-none');

        $.ajax({
            url: '/api/tech-material/upload',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function (resp) {
                if (resp.ok) {
                    uploadedFilename = resp.filename;
                    previewData = resp.preview || [];
                    $('#techFileRows').text(resp.total + ' Zeilen');
                    buildPreviewTable(resp.columns, previewData);
                    updateUploadKpis(resp.total, previewData);
                    // Show save button
                    $('#techSaveBtn').removeClass('d-none');
                } else {
                    alert(resp.error || 'Upload fehlgeschlagen');
                }
            },
            error: function (xhr) {
                const msg = xhr.responseJSON ? xhr.responseJSON.error : 'Upload fehlgeschlagen';
                alert(msg);
            }
        });
    }

    // Step 2: Save to staging + DIL enrichment
    window.techSaveAndEnrich = function () {
        if (!uploadedFilename) { alert('Bitte erst eine Datei hochladen'); return; }

        $('#techSaveBtn').prop('disabled', true).html(
            '<span class="spinner-border spinner-border-sm me-1"></span>DIL-Abfrage läuft…'
        );

        $.ajax({
            url: '/api/tech-material/save',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ filename: uploadedFilename }),
            success: function (resp) {
                $('#techSaveBtn').prop('disabled', false).html(
                    '<i class="bi bi-check-circle me-1"></i>Speichern & Anreichern'
                );
                if (resp.ok) {
                    currentBatchId = resp.batch_id;
                    stagedData = resp.data || [];
                    stagedColumns = resp.columns || [];

                    // Show enrichment messages
                    if (resp.enrich_errors && resp.enrich_errors.length > 0) {
                        let msg = 'Hinweise:\n' + resp.enrich_errors.join('\n');
                        alert(msg);
                    }

                    buildStagedTable(stagedColumns, stagedData);
                    updateStagedKpis(stagedData, resp.total);
                    setStep(2);
                    loadBatches();
                } else {
                    alert(resp.error || 'Speichern fehlgeschlagen');
                }
            },
            error: function (xhr) {
                $('#techSaveBtn').prop('disabled', false).html(
                    '<i class="bi bi-check-circle me-1"></i>Speichern & Anreichern'
                );
                const msg = xhr.responseJSON ? xhr.responseJSON.error : 'Speichern fehlgeschlagen';
                alert(msg);
            }
        });
    };

    window.techClearFile = function () {
        uploadedFilename = '';
        previewData = [];
        stagedData = [];
        stagedColumns = [];
        currentBatchId = '';
        $('#techFileInfo').addClass('d-none');
        $('#techFileInput').val('');
        $('#techSaveBtn').addClass('d-none');
        $('#techTableHead').empty();
        $('#techTableBody').empty();
        setStep(1);
        updateUploadKpis(0, []);
    };

    // ── Preview table (after upload, before save) ──────────────────
    function buildPreviewTable(cols, data) {
        const head = $('#techTableHead');
        const body = $('#techTableBody');
        head.empty();
        body.empty();

        if (!cols || cols.length === 0) return;

        let hrow = '<th>#</th>';
        cols.forEach(function (c) { hrow += '<th>' + escHtml(c) + '</th>'; });
        head.html(hrow);

        data.forEach(function (row, idx) {
            let tr = '<tr><td>' + (idx + 1) + '</td>';
            cols.forEach(function (c) {
                tr += '<td>' + escHtml(row[c] || '') + '</td>';
            });
            tr += '</tr>';
            body.append(tr);
        });
    }

    // ── Staged table (after DIL enrichment) ────────────────────────
    function buildStagedTable(cols, data) {
        const head = $('#techTableHead');
        const body = $('#techTableBody');
        head.empty();
        body.empty();

        if (!cols || cols.length === 0) return;

        let hrow = '<th>#</th>';
        cols.forEach(function (c) { hrow += '<th>' + escHtml(c) + '</th>'; });
        head.html(hrow);

        data.forEach(function (row, idx) {
            let tr = '<tr><td>' + (idx + 1) + '</td>';
            cols.forEach(function (c) {
                let val = row[c] || '';
                // Shorten long JSON for display
                if (c === 'Objektlinks' && val.length > 60) {
                    val = val.substring(0, 57) + '…';
                }
                // Color-code status
                if (c === 'Status') {
                    const cls = val === 'done' ? 'text-success' : val === 'error' ? 'text-danger' : 'text-muted';
                    tr += '<td class="' + cls + '">' + escHtml(val) + '</td>';
                } else if (c === 'Datei?') {
                    const cls = val === 'Ja' ? 'text-success' : 'text-warning';
                    tr += '<td class="' + cls + '">' + escHtml(val) + '</td>';
                } else {
                    tr += '<td>' + escHtml(val) + '</td>';
                }
            });
            tr += '</tr>';
            body.append(tr);
        });

        // Search filter
        $('#techSearchTable').off('input').on('input', function () {
            const q = $(this).val().toLowerCase();
            $('#techTableBody tr').each(function () {
                $(this).toggle($(this).text().toLowerCase().indexOf(q) > -1);
            });
        });
    }

    // ── KPIs ───────────────────────────────────────────────────────
    function updateUploadKpis(total, data) {
        const docs = new Set(data.map(function (r) { return r['DOKNR'] || ''; })).size;
        const types = new Set(data.map(function (r) { return r['DOKAR'] || ''; })).size;
        $('#techKpiTotal').text(total);
        $('#techKpiDocuments').text(docs);
        $('#techKpiTypes').text(types);
        $('#techKpiWithFile').text('-');
        $('#techKpiDone').text(0);
        $('#techKpiFailed').text(0);
    }

    function updateStagedKpis(data, total) {
        const withFile = data.filter(function (r) { return r['Datei?'] === 'Ja'; }).length;
        const done = data.filter(function (r) { return r['Status'] === 'done'; }).length;
        const errors = data.filter(function (r) { return r['Status'] === 'error'; }).length;
        const docs = new Set(data.map(function (r) { return r['DOKNR'] || ''; })).size;
        const types = new Set(data.map(function (r) { return r['DOKAR'] || ''; })).size;
        $('#techKpiTotal').text(total);
        $('#techKpiDocuments').text(docs);
        $('#techKpiTypes').text(types);
        $('#techKpiWithFile').text(withFile);
        $('#techKpiDone').text(done);
        $('#techKpiFailed').text(errors);
    }

    // ── Batch history ──────────────────────────────────────────────
    function loadBatches() {
        $.getJSON('/api/tech-material/batches', function (resp) {
            if (!resp.ok) return;
            const list = $('#techBatchList');
            list.empty();
            if (resp.batches.length === 0) {
                list.html('<li class="list-group-item text-muted">Keine Batches vorhanden</li>');
                return;
            }
            resp.batches.forEach(function (b) {
                const dt = b.created_at ? new Date(b.created_at).toLocaleString('de-DE') : '';
                list.append(
                    '<li class="list-group-item d-flex justify-content-between align-items-center">' +
                    '<div style="cursor:pointer;flex:1" onclick="techLoadBatch(\'' + escHtml(b.batch_id) + '\')">' +
                    '<strong>' + escHtml(b.batch_id) + '</strong><br>' +
                    '<small class="text-muted">' + dt + ' — ' + escHtml(b.created_by || '') + '</small></div>' +
                    '<div class="text-end d-flex align-items-center gap-2">' +
                    '<span class="badge bg-secondary">' + b.total + ' Zeilen</span> ' +
                    '<span class="badge bg-info">' + b.documents + ' Docs</span> ' +
                    '<span class="badge bg-success">' + b.with_file + ' m. Datei</span>' +
                    '<button class="btn btn-outline-danger btn-sm ms-2" title="Batch löschen" ' +
                    'onclick="event.stopPropagation(); techDeleteBatch(\'' + escHtml(b.batch_id) + '\')">✕</button>' +
                    '</div></li>'
                );
            });
        });
    }

    window.techLoadBatch = function (batchId) {
        $.getJSON('/api/tech-material/data/' + encodeURIComponent(batchId), function (resp) {
            if (!resp.ok) { alert('Fehler beim Laden'); return; }
            currentBatchId = batchId;
            stagedData = resp.data || [];
            stagedColumns = resp.columns || [];
            buildStagedTable(stagedColumns, stagedData);
            updateStagedKpis(stagedData, resp.total);
            setStep(2);
        });
    };

    window.techDeleteBatch = function (batchId) {
        if (!confirm('Batch "' + batchId + '" und alle zugehörigen Daten löschen?')) return;
        $.ajax({
            url: '/api/tech-material/batch/' + encodeURIComponent(batchId),
            method: 'DELETE',
            success: function (resp) {
                if (resp.ok) {
                    if (currentBatchId === batchId) { currentBatchId = null; setStep(1); }
                    loadBatches();
                } else {
                    alert('Fehler: ' + (resp.error || 'Unbekannt'));
                }
            },
            error: function () { alert('Fehler beim Löschen'); }
        });
    };

    // ── Execute: Start download ──────────────────────────────────
    let _techPollTimer = null;

    window.techStartDownload = function () {
        const dlPath = ($('#techDownloadPath').val() || '').trim();
        if (!dlPath) {
            alert('Bitte einen Speicherpfad angeben.');
            return;
        }
        if (!currentBatchId) {
            alert('Kein Batch ausgewählt.');
            return;
        }

        $('#techBtnExecute').prop('disabled', true);
        $('#techDownloadPath').prop('readonly', true);
        $('#techExecProgress').removeClass('d-none');
        $('#techCurrentDoc').text('Starte Download…');

        $.ajax({
            url: '/api/tech-material/execute',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ batch_id: currentBatchId, download_path: dlPath }),
            success: function (resp) {
                if (!resp.ok) {
                    alert(resp.error || 'Fehler');
                    _resetExecuteUI();
                    return;
                }
                _techPollTimer = setInterval(function () {
                    _pollTechProgress(currentBatchId);
                }, 2000);
            },
            error: function (xhr) {
                const msg = (xhr.responseJSON || {}).error || 'Server-Fehler';
                alert(msg);
                _resetExecuteUI();
            }
        });
    };

    function _pollTechProgress(batchId) {
        $.getJSON('/api/tech-material/execute/progress/' + encodeURIComponent(batchId), function (resp) {
            if (!resp.ok) return;
            const total = resp.total || 0;
            const done = resp.done || 0;
            const failed = resp.failed || 0;
            const skipped = resp.skipped || 0;
            const pct = total > 0 ? Math.round(((done + failed) / total) * 100) : 0;

            $('#techProgress').css('width', pct + '%').text(pct + '%');
            $('#techStatDone').text(done);
            $('#techStatFailed').text(failed);
            $('#techStatSkipped').text(skipped);
            $('#techStatTotal').text(total);
            if (resp.current_doc) {
                $('#techCurrentDoc').text('Aktuell: ' + resp.current_doc);
            }

            if (resp.status === 'done' || resp.status === 'error') {
                clearInterval(_techPollTimer);
                _techPollTimer = null;
                _showTechResults(resp);
            }
        });
    }

    function _showTechResults(resp) {
        // Fill result panel
        $('#techResDone').text(resp.done || 0);
        $('#techResFailed').text(resp.failed || 0);
        $('#techResSkipped').text(resp.skipped || 0);
        $('#techResTotal').text(resp.total || 0);

        if (resp.download_path) {
            $('#techResPath').val(resp.download_path);
            $('#techResPathBox').show();
        }
        if (resp.excel_path) {
            $('#techResExcel').val(resp.excel_path);
            $('#techResExcelBox').show();
        }

        var errList = resp.errors || [];
        if (errList.length > 0) {
            var $ul = $('#techResErrorList').empty();
            errList.forEach(function (e) {
                $ul.append('<li class="list-group-item list-group-item-danger small">' + escHtml(e) + '</li>');
            });
            $('#techResErrors').removeClass('d-none');
        } else {
            $('#techResErrors').addClass('d-none');
        }

        setStep(4);
        _resetExecuteUI();
    }

    function _resetExecuteUI() {
        $('#techBtnExecute').prop('disabled', false);
        $('#techDownloadPath').prop('readonly', false);
    }

    // ── Helpers ────────────────────────────────────────────────────
    function escHtml(s) {
        const d = document.createElement('div');
        d.appendChild(document.createTextNode(s));
        return d.innerHTML;
    }

    // Expose step navigation
    window.techSetStep = setStep;
})();
