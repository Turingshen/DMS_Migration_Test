/**
 * qm_material.js — QM Material workflow logic
 * Flow: Upload → Parse → Column Select → Save to Staging → Review (select) → Execute → Result
 */
(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────
    var currentStep = 1;
    var uploadedData = [];
    var allColumns = [];
    var selectedColumns = [];
    var parsedFilename = '';
    var parsedTotal = 0;
    var previewRows = [];
    var currentBatchId = '';
    var reviewColumns = [];
    var selectedRecords = {};  // id -> true
    var pollTimer = null;
    var currentPage = 1;
    var totalPages = 1;
    var totalRecords = 0;
    var perPage = 500;
    var _filesScanned = false;  // true after successful scan-files call

    // ── Init ───────────────────────────────────────────────────────
    $(document).ready(function () {
        initUploadZone();
        loadBatchList();
        if (typeof I18n !== 'undefined') I18n.applyAll();
    });

    // ── Workflow navigation ────────────────────────────────────────
    function setStep(step) {
        currentStep = step;
        for (var i = 1; i <= 4; i++) {
            var el = $('#qmStep' + i);
            el.removeClass('active done');
            if (i < step) el.addClass('done');
            if (i === step) el.addClass('active');
        }
        $('#qmPanelUpload').toggleClass('d-none', step !== 1);
        $('#qmPanelReview').toggleClass('d-none', step !== 2);
        $('#qmPanelExecute').toggleClass('d-none', step !== 3);
        $('#qmPanelResult').toggleClass('d-none', step !== 4);

        // When navigating to Step 4 directly, load results from DB
        if (step === 4 && currentBatchId) {
            _loadResultsFromDB();
        }
    }

    function _loadResultsFromDB() {
        $.getJSON('/api/qm-material/data/' + currentBatchId + '?page=1&per_page=' + perPage, function (resp) {
            if (resp.ok) {
                var data = resp.data || [];
                uploadedData = data;
                totalRecords = resp.total || 0;
                // Compute KPIs from data
                var doneCount = 0, errorCount = 0;
                data.forEach(function (r) {
                    if (r.status === 'done') doneCount++;
                    else if (r.status === 'error') errorCount++;
                });
                $('#qmResTotal').text(data.length);
                $('#qmResDone').text(doneCount);
                $('#qmResFailed').text(errorCount);
                updateKpis();
                _buildResultTable(data);
            }
        });
    }

    // ── Upload zone ────────────────────────────────────────────────
    function initUploadZone() {
        var zone = $('#qmUploadZone');
        var input = $('#qmFileInput');

        zone.on('dragover', function (e) { e.preventDefault(); zone.addClass('dragover'); });
        zone.on('dragleave drop', function () { zone.removeClass('dragover'); });
        zone.on('drop', function (e) {
            e.preventDefault();
            var files = e.originalEvent.dataTransfer.files;
            if (files.length > 0) handleFile(files[0]);
        });
        input.on('change', function () {
            if (this.files.length > 0) handleFile(this.files[0]);
        });
    }

    // ── Step 1: Parse file (no DB write) ───────────────────────────
    function handleFile(file) {
        var formData = new FormData();
        formData.append('file', file);

        $('#qmFileName').text(file.name);
        $('#qmFileInfo').removeClass('d-none');
        $('#qmColumnSelect').addClass('d-none');

        $.ajax({
            url: '/api/qm-material/parse',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function (resp) {
                if (resp.ok) {
                    parsedFilename = resp.filename;
                    allColumns = resp.columns || [];
                    previewRows = resp.preview || [];
                    parsedTotal = resp.total || 0;
                    selectedColumns = allColumns.slice();
                    $('#qmFileRows').text(parsedTotal + ' Zeilen erkannt');
                    buildColumnPicker();
                    buildPreviewTable();
                    $('#qmColumnSelect').removeClass('d-none');
                } else {
                    alert(resp.error || 'Parsing fehlgeschlagen');
                }
            },
            error: function (xhr) {
                var msg = 'Parsing fehlgeschlagen';
                if (xhr.responseJSON && xhr.responseJSON.error) msg += ': ' + xhr.responseJSON.error;
                alert(msg);
            }
        });
    }

    // ── Column picker ──────────────────────────────────────────────
    function buildColumnPicker() {
        var container = $('#qmColumnList');
        container.empty();

        allColumns.forEach(function (col) {
            var checked = selectedColumns.indexOf(col) >= 0 ? 'checked' : '';
            var html =
                '<div class="col-md-3 col-sm-4 col-6 mb-1">' +
                '  <div class="custom-control custom-checkbox">' +
                '    <input type="checkbox" class="custom-control-input qm-col-cb" ' +
                '           id="qmCol_' + col.replace(/[^a-zA-Z0-9]/g, '_') + '" ' +
                '           value="' + escHtml(col) + '" ' + checked + '>' +
                '    <label class="custom-control-label" ' +
                '           for="qmCol_' + col.replace(/[^a-zA-Z0-9]/g, '_') + '">' +
                '      <small>' + escHtml(col) + '</small>' +
                '    </label>' +
                '  </div>' +
                '</div>';
            container.append(html);
        });

        container.off('change', '.qm-col-cb').on('change', '.qm-col-cb', function () {
            syncSelectedColumns();
            buildPreviewTable();
        });

        syncSelectedColumns();
    }

    function syncSelectedColumns() {
        selectedColumns = [];
        $('.qm-col-cb:checked').each(function () {
            selectedColumns.push($(this).val());
        });
        $('#qmColCount').text(selectedColumns.length + ' / ' + allColumns.length);
        $('#qmPreviewInfo').text(parsedTotal + ' Zeilen, ' + selectedColumns.length + ' Spalten ausgewählt');
        $('#qmBtnSave').prop('disabled', selectedColumns.length === 0);
    }

    window.qmSelectAllCols = function (selectAll) {
        $('.qm-col-cb').prop('checked', selectAll);
        syncSelectedColumns();
        buildPreviewTable();
    };

    // ── Preview table (first N rows, selected columns) ─────────────
    function buildPreviewTable() {
        var head = $('#qmPreviewHead');
        var body = $('#qmPreviewBody');
        head.empty();
        body.empty();

        if (selectedColumns.length === 0 || previewRows.length === 0) {
            body.html('<tr><td class="text-center text-muted py-3">Keine Spalten ausgewählt</td></tr>');
            return;
        }

        var hrow = '<tr><th>#</th>';
        selectedColumns.forEach(function (c) { hrow += '<th style="font-size:0.75rem;white-space:nowrap">' + escHtml(c) + '</th>'; });
        hrow += '</tr>';
        head.html(hrow);

        var maxPreview = Math.min(previewRows.length, 10);
        for (var i = 0; i < maxPreview; i++) {
            var row = previewRows[i];
            var tr = '<tr><td>' + (i + 1) + '</td>';
            selectedColumns.forEach(function (c) {
                tr += '<td style="font-size:0.8rem">' + escHtml(row[c] || '') + '</td>';
            });
            tr += '</tr>';
            body.append(tr);
        }
        if (parsedTotal > maxPreview) {
            body.append('<tr><td colspan="' + (selectedColumns.length + 1) + '" class="text-center text-muted"><small>... und ' + (parsedTotal - maxPreview) + ' weitere Zeilen</small></td></tr>');
        }
    }

    // ── Step 1→2: Save selected columns to staging ─────────────────
    window.qmSaveToStaging = function () {
        if (selectedColumns.length === 0) return;

        $('#qmBtnSave').prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Speichern...');

        $.ajax({
            url: '/api/qm-material/save',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                filename: parsedFilename,
                columns: selectedColumns
            }),
            success: function (resp) {
                $('#qmBtnSave').prop('disabled', false).html('<i class="fas fa-database"></i> In Staging speichern');
                if (resp.ok) {
                    currentBatchId = resp.batch_id || '';
                    selectedRecords = {};
                    currentPage = 1;
                    _loadPage(1, function () { setStep(2); });
                } else {
                    alert(resp.error || 'Speichern fehlgeschlagen');
                }
            },
            error: function (xhr) {
                $('#qmBtnSave').prop('disabled', false).html('<i class="fas fa-database"></i> In Staging speichern');
                var msg = 'Speichern fehlgeschlagen';
                if (xhr.responseJSON && xhr.responseJSON.error) msg += ': ' + xhr.responseJSON.error;
                alert(msg);
            }
        });
    };

    window.qmClearFile = function () {
        uploadedData = [];
        allColumns = [];
        selectedColumns = [];
        previewRows = [];
        parsedFilename = '';
        parsedTotal = 0;
        currentBatchId = '';
        selectedRecords = {};
        $('#qmFileInfo').addClass('d-none');
        $('#qmColumnSelect').addClass('d-none');
        $('#qmFileInput').val('');
        setStep(1);
        updateKpis();
    };

    // ── Review table (Step 2) with checkboxes ──────────────────────
    function buildReviewTable(cols, data) {
        var head = $('#qmTableHead');
        var body = $('#qmTableBody');
        head.empty();
        body.empty();

        if (cols.length === 0) return;

        // Filter out columns shown separately (status, error_message)
        var hideCols = ['status', 'error_message'];
        var visibleCols = cols.filter(function (c) { return hideCols.indexOf(c) === -1; });

        // Header with select-all checkbox
        var hrow = '<th><input type="checkbox" id="qmSelectAll"></th><th>#</th>';
        visibleCols.forEach(function (c) { hrow += '<th>' + escHtml(c) + '</th>'; });
        hrow += '<th>Status</th><th>Fehler</th>';
        head.html(hrow);

        data.forEach(function (row, idx) {
            var rowId = row['id'] || (idx + 1);
            var status = row['status'] || row['Status'] || 'pending';
            var checked = selectedRecords[rowId] ? 'checked' : '';
            var rowHighlight = selectedRecords[rowId] ? ' table-warning' : '';
            var statusBadge = _statusBadge(status);
            var errMsg = row['error_message'] || '';
            var errBadge = errMsg
                ? '<span class="badge badge-danger" style="cursor:pointer;" onclick="qmShowError(this)" data-error="' + escAttr(errMsg) + '"><i class="fas fa-exclamation-circle"></i> Detail</span>'
                : '<span class="badge badge-light">–</span>';
            var tr = '<tr data-id="' + rowId + '" class="' + rowHighlight + '">' +
                '<td><input type="checkbox" class="qm-row-cb" value="' + rowId + '" ' + checked + '></td>' +
                '<td>' + (idx + 1) + '</td>';
            visibleCols.forEach(function (c) {
                tr += '<td>' + escHtml(row[c] || '') + '</td>';
            });
            tr += '<td>' + statusBadge + '</td><td>' + errBadge + '</td></tr>';
            body.append(tr);
        });

        // Select-all handler
        $('#qmSelectAll').off('change').on('change', function () {
            var checked = $(this).is(':checked');
            $('.qm-row-cb').prop('checked', checked);
            selectedRecords = {};
            if (checked) {
                $('.qm-row-cb').each(function () { selectedRecords[$(this).val()] = true; });
            }
            _updateSelCount();
        });

        // Individual row checkboxes
        body.off('change', '.qm-row-cb').on('change', '.qm-row-cb', function () {
            var id = $(this).val();
            if ($(this).is(':checked')) {
                selectedRecords[id] = true;
            } else {
                delete selectedRecords[id];
            }
            _updateSelCount();
        });

        _updateSelCount();

        // Search filter
        $('#qmSearchTable').off('input').on('input', function () {
            var q = $(this).val().toLowerCase();
            $('#qmTableBody tr').each(function () {
                $(this).toggle($(this).text().toLowerCase().indexOf(q) > -1);
            });
        });
    }

    function _statusBadge(status) {
        if (status === 'done') return '<span class="badge badge-success">done</span>';
        if (status === 'error') return '<span class="badge badge-danger">error</span>';
        return '<span class="badge badge-warning">pending</span>';
    }

    function _updateSelCount() {
        var count = Object.keys(selectedRecords).length;
        $('#qmSelCount').text(count + ' ausgewählt');
        $('#qmBtnExecSelected').prop('disabled', count === 0);
        $('#qmBtnDeleteSelected').prop('disabled', count === 0);
    }

    // ── KPI update ─────────────────────────────────────────────────
    function updateKpis() {
        if (currentBatchId) {
            // Fetch accurate counts from batches endpoint
            $.getJSON('/api/qm-material/batches', function (resp) {
                if (!resp.ok) return;
                var b = (resp.batches || []).find(function (x) { return x.batch_id === currentBatchId; });
                if (b) {
                    $('#qmKpiTotal').text(b.total);
                    $('#qmKpiMaterials').text(b.materials);
                    $('#qmKpiVendors').text(b.vendors);
                    $('#qmKpiPending').text(b.pending);
                    $('#qmKpiDone').text(b.done);
                    $('#qmKpiFailed').text(b.errors);
                }
            });
            return;
        }
        var total = uploadedData.length;
        var materials = new Set(uploadedData.map(function (r) { return r['Material'] || r['material'] || ''; })).size;
        var vendors = new Set(uploadedData.map(function (r) { return r['Vendor'] || r['vendor'] || r['Lieferant'] || ''; })).size;
        var pending = 0, done = 0, failed = 0;
        uploadedData.forEach(function (r) {
            var s = r['status'] || r['Status'] || 'pending';
            if (s === 'done') done++;
            else if (s === 'error') failed++;
            else pending++;
        });
        $('#qmKpiTotal').text(total);
        $('#qmKpiMaterials').text(materials);
        $('#qmKpiVendors').text(vendors);
        $('#qmKpiPending').text(pending);
        $('#qmKpiDone').text(done);
        $('#qmKpiFailed').text(failed);
    }

    // ── Execute migration ──────────────────────────────────────────

    window.qmExecuteAll = function () {
        if (!currentBatchId) { alert('Kein Batch geladen'); return; }
        if (!confirm('Alle ausstehenden Datensätze migrieren?')) return;
        _startExecution(null);
    };

    window.qmExecuteSelected = function () {
        var ids = Object.keys(selectedRecords).map(Number);
        if (ids.length === 0) { alert('Keine Datensätze ausgewählt'); return; }
        if (!confirm(ids.length + ' Datensätze migrieren?')) return;
        _startExecution(ids);
    };

    function _startExecution(recordIds) {
        var dirPath = ($('#qmFilePath').val() || '').trim();
        var onlyWithMapping = $('#qmOnlyWithMapping').is(':checked');

        // Warn if no dir_path provided at all
        if (!dirPath) {
            if (!confirm('⚠️ Kein Dateipfad angegeben!\n\nOhne Pfad werden nur Container und Links erstellt – keine Dateien hochgeladen.\n\nTrotzdem fortfahren?')) {
                return;
            }
        }

        // Warn if dir_path is set but files were not scanned yet
        if (dirPath && !_filesScanned) {
            if (!confirm('⚠️ Der Dateipfad "' + dirPath + '" wurde angegeben, aber die Dateien wurden noch nicht gescannt.\n\nOhne Scan werden keine Dateien hochgeladen – nur Container und Links erstellt.\n\nTrotzdem fortfahren ohne Datei-Upload?')) {
                return;
            }
        }

        setStep(3);
        $('#qmExecSpinner').show();

        var payload = { batch_id: currentBatchId };
        if (recordIds) payload.record_ids = recordIds;
        if (dirPath) payload.dir_path = dirPath;
        if (onlyWithMapping) payload.only_with_mapping = true;

        $.ajax({
            url: '/api/qm-material/execute',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            success: function (resp) {
                if (resp.ok) {
                    _startPolling();
                } else {
                    alert(resp.error || 'Migration konnte nicht gestartet werden');
                    setStep(2);
                }
            },
            error: function (xhr) {
                var msg = 'Fehler beim Starten';
                if (xhr.responseJSON && xhr.responseJSON.error) msg += ': ' + xhr.responseJSON.error;
                alert(msg);
                setStep(2);
            }
        });
    }

    function _startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(function () {
            $.getJSON('/api/qm-material/execute/progress/' + currentBatchId, function (resp) {
                if (!resp.ok) return;
                var total = resp.total || 0;
                var done = resp.done || 0;
                var failed = resp.failed || 0;
                var remaining = total - done - failed;

                $('#qmExecTotal').text(total);
                $('#qmExecDone').text(done);
                $('#qmExecFailed').text(failed);
                $('#qmExecRemaining').text(remaining);

                var pctDone = total > 0 ? (done / total * 100) : 0;
                var pctFail = total > 0 ? (failed / total * 100) : 0;
                $('#qmProgressDone').css('width', pctDone + '%').text(done);
                $('#qmProgressFailed').css('width', pctFail + '%').text(failed > 0 ? failed : '');

                if (resp.status === 'completed' || resp.status === 'error') {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    $('#qmExecSpinner').hide();
                    _showResults(resp);
                }
            });
        }, 1500);
    }

    function _showResults(execResult) {
        // Update result KPIs from execution data
        $('#qmResTotal').text(execResult.total || 0);
        $('#qmResDone').text(execResult.done || 0);
        $('#qmResFailed').text(execResult.failed || 0);

        // Clear top-level error block (errors are shown inline per row now)
        $('#qmResultErrors').empty();

        // setStep(4) will trigger _loadResultsFromDB automatically
        setStep(4);
    }

    function _buildResultTable(data) {
        var head = $('#qmResultHead');
        var body = $('#qmResultBody');
        head.empty();
        body.empty();

        var cols = ['material', 'vendor', 'cocd', 'plnt', 'source_file', 'target_dokar', 'target_doknr', 'target_dokvr', 'target_doktl', 'target_description', 'qinf_material', 'qinf_zaehl', 'file_uploaded', 'status', 'error_message'];
        var labels = ['Material', 'Vendor', 'CoCd', 'Plnt', 'Datei', 'Typ', 'DOKNR (Ziel)', 'Ver.', 'Teil', 'Beschreibung', 'QINF Material', 'QINF Zähler', 'Datei hochgeladen', 'Status', 'Fehler'];

        var hrow = '<th>#</th>';
        labels.forEach(function (l) { hrow += '<th>' + l + '</th>'; });
        head.html(hrow);

        data.forEach(function (row, idx) {
            var status = row.status || 'pending';
            var rowClass = status === 'done' ? 'table-success' : (status === 'error' ? 'table-danger' : '');
            var tr = '<tr class="' + rowClass + '"><td>' + (idx + 1) + '</td>';
            cols.forEach(function (c) {
                var val = row[c] || '';
                if (c === 'status') val = _statusBadge(val);
                else if (c === 'file_uploaded') val = (val === '1' || val === 'True' || val === true || val === 1) ? '<span class="badge badge-success">Ja</span>' : '<span class="badge badge-secondary">Nein</span>';
                else if (c === 'error_message') {
                    if (val) {
                        val = '<span class="badge badge-danger" style="cursor:pointer;" onclick="qmShowError(this)" data-error="' + escAttr(val) + '">' +
                              '<i class="fas fa-exclamation-circle"></i> Detail</span>';
                    } else {
                        val = '<span class="badge badge-light">–</span>';
                    }
                }
                else val = escHtml(val);
                tr += '<td>' + val + '</td>';
            });
            tr += '</tr>';
            body.append(tr);
        });
    }

    window.qmBackToReview = function () {
        if (currentBatchId) {
            selectedRecords = {};
            _loadPage(1, function () { setStep(2); });
        } else {
            setStep(2);
        }
    };

    // ── Helpers ────────────────────────────────────────────────────
    function escHtml(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(s));
        return d.innerHTML;
    }

    function escAttr(s) {
        return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    window.qmShowError = function (el) {
        var msg = $(el).attr('data-error') || '';
        $('#qmErrorModalBody').html(
            '<pre class="alert alert-danger mb-0" style="white-space:pre-wrap;word-break:break-all;max-height:400px;overflow-y:auto;">' +
            escHtml(msg) + '</pre>'
        );
        $('#qmErrorModal').modal('show');
    };

    window.qmDownloadExcel = function () {
        if (!currentBatchId) return;
        window.location.href = '/api/qm-material/export-excel/' + currentBatchId;
    };

    window.qmDeleteSelected = function () {
        var ids = Object.keys(selectedRecords);
        if (ids.length === 0) return;
        if (!confirm('⚠️ ' + ids.length + ' Zeilen dauerhaft löschen?\n\nNur Zeilen mit Status "pending" werden gelöscht.')) return;

        $.ajax({
            url: '/api/qm-material/delete-rows/' + encodeURIComponent(currentBatchId),
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ ids: ids }),
            success: function (resp) {
                if (resp.ok) {
                    alert('✓ ' + resp.deleted + ' Zeilen gelöscht');
                    selectedRecords = {};
                    _loadPage(currentPage);
                    updateKpis();
                } else {
                    alert('Fehler: ' + (resp.error || 'Unbekannt'));
                }
            },
            error: function (xhr) {
                var msg = 'Löschen fehlgeschlagen';
                if (xhr.responseJSON && xhr.responseJSON.error) msg = xhr.responseJSON.error;
                alert(msg);
            }
        });
    };

    window.qmSuggestDelete = function () {
        if (!currentBatchId) return;
        $.getJSON('/api/qm-material/suggest-delete/' + encodeURIComponent(currentBatchId), function (resp) {
            if (!resp.ok) { alert('Fehler beim Laden'); return; }
            if (resp.count === 0) { alert('Keine Zeilen ohne Datei/Mapping gefunden.'); return; }

            // Set all suggested IDs as selected
            selectedRecords = {};
            resp.ids.forEach(function (id) { selectedRecords[String(id)] = true; });
            _updateSelCount();

            // Update checkboxes on current page
            $('.qm-row-cb').each(function () {
                var id = $(this).val();
                $(this).prop('checked', !!selectedRecords[id]);
                // Highlight row
                var row = $(this).closest('tr');
                if (selectedRecords[id]) {
                    row.addClass('table-warning');
                } else {
                    row.removeClass('table-warning');
                }
            });

            alert(resp.count + ' Zeilen ohne Datei oder Mapping markiert.\n\nPrüfen Sie die Auswahl und klicken Sie "Ausgewählte löschen".');
        });
    };

    window.qmSetStep = setStep;
    window.qmStartMigration = window.qmExecuteAll;
    window.qmLoadBatchList = loadBatchList;

    // ── Batch list (load existing batches) ─────────────────────────
    function loadBatchList() {
        var container = $('#qmBatchList');
        container.html('<div class="text-center text-muted py-3"><i class="fas fa-spinner fa-spin"></i> Lade...</div>');
        $.getJSON('/api/qm-material/batches', function (resp) {
            container.empty();
            if (!resp.ok || !resp.batches || resp.batches.length === 0) {
                container.html('<div class="text-center text-muted py-3">Keine Batches vorhanden</div>');
                return;
            }
            var table = '<table class="table table-sm table-hover mb-0">' +
                '<thead class="thead-light"><tr>' +
                '<th>Batch</th><th>Erstellt</th><th>Von</th>' +
                '<th class="text-center">Gesamt</th>' +
                '<th class="text-center">Pending</th>' +
                '<th class="text-center">Done</th>' +
                '<th class="text-center">Fehler</th>' +
                '<th></th>' +
                '</tr></thead><tbody>';
            resp.batches.forEach(function (b) {
                var dt = b.created_at ? b.created_at.replace('T', ' ').substring(0, 16) : '';
                table += '<tr>' +
                    '<td><code>' + escHtml(b.batch_id) + '</code></td>' +
                    '<td><small>' + escHtml(dt) + '</small></td>' +
                    '<td><small>' + escHtml(b.created_by || '') + '</small></td>' +
                    '<td class="text-center">' + b.total + '</td>' +
                    '<td class="text-center"><span class="badge badge-warning">' + b.pending + '</span></td>' +
                    '<td class="text-center"><span class="badge badge-success">' + b.done + '</span></td>' +
                    '<td class="text-center"><span class="badge badge-danger">' + b.errors + '</span></td>' +
                    '<td><button class="btn btn-xs btn-outline-info mr-1" onclick="qmLoadBatch(\'' + escHtml(b.batch_id) + '\')">'
                    + '<i class="fas fa-folder-open"></i> Öffnen</button>'
                    + '<button class="btn btn-xs btn-outline-danger" onclick="qmDeleteBatch(\'' + escHtml(b.batch_id) + '\')">'
                    + '<i class="fas fa-trash"></i></button></td>' +
                    '</tr>';
            });
            table += '</tbody></table>';
            container.html(table);
        });
    }

    window.qmLoadBatch = function (batchId) {
        currentBatchId = batchId;
        selectedRecords = {};
        currentPage = 1;
        _filesScanned = false;  // Reset scan flag for newly loaded batch
        _loadPage(1, function () { setStep(2); });
    };

    window.qmDeleteBatch = function (batchId) {
        if (!confirm('⚠️ Batch "' + batchId + '" komplett löschen?\n\nAlle Zeilen (inkl. migrierter) werden unwiderruflich entfernt.')) return;
        $.ajax({
            url: '/api/qm-material/batches/' + encodeURIComponent(batchId),
            type: 'DELETE',
            success: function (resp) {
                if (resp.ok) {
                    alert('✓ ' + resp.message);
                    loadBatchList();
                } else {
                    alert('Fehler: ' + (resp.error || 'Unbekannt'));
                }
            },
            error: function (xhr) {
                var msg = 'Löschen fehlgeschlagen';
                if (xhr.responseJSON && xhr.responseJSON.error) msg = xhr.responseJSON.error;
                alert(msg);
            }
        });
    };

    // ── Pagination ────────────────────────────────────────────────
    function _loadPage(page, callback) {
        $.getJSON('/api/qm-material/data/' + currentBatchId + '?page=' + page + '&per_page=' + perPage, function (resp) {
            if (resp.ok) {
                uploadedData = resp.data || [];
                reviewColumns = resp.columns || [];
                currentPage = resp.page || 1;
                totalPages = resp.total_pages || 1;
                totalRecords = resp.total || 0;
                updateKpis();
                buildReviewTable(reviewColumns, uploadedData);
                _updatePagination();
                if (typeof callback === 'function') callback();
            } else {
                alert(resp.error || 'Daten konnten nicht geladen werden');
            }
        });
    }

    function _updatePagination() {
        var from = totalRecords === 0 ? 0 : ((currentPage - 1) * perPage + 1);
        var to = Math.min(currentPage * perPage, totalRecords);
        $('#qmPageInfo').text('Seite ' + currentPage + ' / ' + totalPages);
        $('#qmTotalInfo').text(from + '–' + to + ' von ' + totalRecords + ' Datensätzen');
        $('#qmPageFirst, #qmPagePrev').prop('disabled', currentPage <= 1);
        $('#qmPageNext, #qmPageLast').prop('disabled', currentPage >= totalPages);
    }

    window.qmGoToPage = function (target) {
        var pg = currentPage;
        if (target === 'prev') pg = Math.max(1, currentPage - 1);
        else if (target === 'next') pg = Math.min(totalPages, currentPage + 1);
        else if (target === 'last') pg = totalPages;
        else pg = parseInt(target, 10) || 1;
        if (pg !== currentPage) _loadPage(pg);
    };

    // ── File scan ─────────────────────────────────────────────────
    window.qmScanFiles = function () {
        var dirPath = $('#qmFilePath').val().trim();
        if (!dirPath) { alert('Bitte einen Pfad angeben'); return; }
        if (!currentBatchId) { alert('Kein Batch geladen'); return; }

        var resultDiv = $('#qmScanResult');
        resultDiv.removeClass('d-none').html('<i class="fas fa-spinner fa-spin"></i> Scanne...');

        $.ajax({
            url: '/api/qm-material/scan-files',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ batch_id: currentBatchId, dir_path: dirPath }),
            success: function (resp) {
                if (resp.ok) {
                    var html = '<div class="alert alert-info mb-0 py-2">' +
                        '<strong>' + resp.total_files + '</strong> Dateien gescannt | ' +
                        '<strong>' + resp.total_records + '</strong> Staging-Datensätze | ' +
                        '<span class="text-success"><strong>' + resp.matched + '</strong> zugeordnet</span> | ' +
                        '<span class="text-danger"><strong>' + resp.unmatched + '</strong> ohne Datei</span>' +
                        '</div>';
                    resultDiv.html(html);
                    _filesScanned = true;
                    // Reload current page to show source_file column
                    _loadPage(currentPage);
                } else {
                    resultDiv.html('<div class="alert alert-danger mb-0 py-2">' + escHtml(resp.error || 'Fehler') + '</div>');
                }
            },
            error: function (xhr) {
                var msg = 'Fehler beim Scannen';
                if (xhr.responseJSON && xhr.responseJSON.error) msg = xhr.responseJSON.error;
                resultDiv.html('<div class="alert alert-danger mb-0 py-2">' + escHtml(msg) + '</div>');
            }
        });
    };

    // ── Rename files (replace source material with target material) ──
    window.qmRenameFiles = function (dryRun) {
        var dirPath = $('#qmFilePath').val().trim();
        if (!dirPath) { alert('Bitte einen Pfad angeben'); return; }
        if (!currentBatchId) { alert('Kein Batch geladen'); return; }

        var resultDiv = $('#qmRenameResult');
        resultDiv.removeClass('d-none').html('<i class="fas fa-spinner fa-spin"></i> Analysiere...');

        $.ajax({
            url: '/api/qm-material/rename-files',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ batch_id: currentBatchId, dir_path: dirPath, dry_run: dryRun }),
            success: function (resp) {
                if (resp.ok) {
                    var html = '<div class="alert ' + (dryRun ? 'alert-warning' : 'alert-success') + ' mb-0 py-2">';
                    if (dryRun) {
                        html += '<strong>Vorschau:</strong> ' + resp.to_rename + ' Dateien würden umbenannt, ' + resp.skipped + ' übersprungen.';
                        if (resp.to_rename > 0) {
                            html += '<br><button class="btn btn-sm btn-warning mt-1" onclick="qmRenameFiles(false)">' +
                                '<i class="fas fa-check"></i> Jetzt umbenennen (' + resp.to_rename + ' Dateien)</button>';
                            html += '<br><small class="text-muted mt-1">Beispiele: ';
                            var examples = resp.renames.slice(0, 3);
                            examples.forEach(function (r) { html += '<br>' + escHtml(r.old) + ' → ' + escHtml(r.new); });
                            html += '</small>';
                        }
                    } else {
                        html += '<strong>' + resp.renamed + '</strong> Dateien erfolgreich umbenannt.';
                        if (resp.errors.length > 0) {
                            html += ' <span class="text-danger">' + resp.errors.length + ' Fehler.</span>';
                        }
                    }
                    html += '</div>';
                    resultDiv.html(html);
                } else {
                    resultDiv.html('<div class="alert alert-danger mb-0 py-2">' + escHtml(resp.error || 'Fehler') + '</div>');
                }
            },
            error: function (xhr) {
                var msg = 'Fehler beim Umbenennen';
                if (xhr.responseJSON && xhr.responseJSON.error) msg = xhr.responseJSON.error;
                resultDiv.html('<div class="alert alert-danger mb-0 py-2">' + escHtml(msg) + '</div>');
            }
        });
    };

    // ── QINF Mapping (download / upload) ──────────────────────────
    window.qmQinfDownload = function () {
        if (!currentBatchId) { alert('Kein Batch geladen'); return; }
        window.location.href = '/api/qm-material/qinf-mapping/download/' + encodeURIComponent(currentBatchId);
    };

    window.qmQinfUpload = function (input) {
        if (!input.files || !input.files[0]) return;
        if (!currentBatchId) { alert('Kein Batch geladen'); return; }

        var formData = new FormData();
        formData.append('file', input.files[0]);

        var resultDiv = $('#qmQinfResult');
        resultDiv.removeClass('d-none').html('<i class="fas fa-spinner fa-spin"></i> Wird hochgeladen...');

        $.ajax({
            url: '/api/qm-material/qinf-mapping/upload/' + encodeURIComponent(currentBatchId),
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function (resp) {
                if (resp.ok) {
                    resultDiv.html(
                        '<div class="alert alert-success mb-0 py-2">' +
                        '<i class="fas fa-check-circle"></i> ' + escHtml(resp.message) +
                        '</div>'
                    );
                    // Reload table to show updated QINF columns
                    _loadPage(currentPage);
                } else {
                    resultDiv.html(
                        '<div class="alert alert-danger mb-0 py-2">' + escHtml(resp.error || 'Fehler') + '</div>'
                    );
                }
            },
            error: function (xhr) {
                var msg = 'Upload fehlgeschlagen';
                if (xhr.responseJSON && xhr.responseJSON.error) msg = xhr.responseJSON.error;
                resultDiv.html('<div class="alert alert-danger mb-0 py-2">' + escHtml(msg) + '</div>');
            }
        });

        // Reset input so same file can be re-selected
        input.value = '';
    };
})();
