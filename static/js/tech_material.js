/**
 * tech_material.js — TECH Material workflow logic
 * Handles: file upload, data review, migration execution, results
 */
(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────
    let currentStep = 1;
    let uploadedData = [];
    let columns = [];

    // ── Init ───────────────────────────────────────────────────────
    $(document).ready(function () {
        initUploadZone();
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

    function handleFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('workflow', 'tech_material');

        $('#techFileName').text(file.name);
        $('#techFileInfo').removeClass('d-none');

        $.ajax({
            url: '/api/material/upload',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function (resp) {
                if (resp.ok) {
                    uploadedData = resp.data || [];
                    columns = resp.columns || [];
                    $('#techFileRows').text(uploadedData.length + ' Zeilen');
                    updateKpis();
                    buildTable();
                    setStep(2);
                } else {
                    alert(resp.error || 'Upload fehlgeschlagen');
                }
            },
            error: function () {
                alert('Upload fehlgeschlagen');
            }
        });
    }

    window.techClearFile = function () {
        uploadedData = [];
        columns = [];
        $('#techFileInfo').addClass('d-none');
        $('#techFileInput').val('');
        setStep(1);
        updateKpis();
    };

    // ── Table ──────────────────────────────────────────────────────
    function buildTable() {
        const head = $('#techTableHead');
        const body = $('#techTableBody');
        head.empty();
        body.empty();

        if (columns.length === 0) return;

        // Header
        let hrow = '<th>#</th>';
        columns.forEach(function (c) { hrow += '<th>' + escHtml(c) + '</th>'; });
        head.html(hrow);

        // Rows
        uploadedData.forEach(function (row, idx) {
            let tr = '<tr><td>' + (idx + 1) + '</td>';
            columns.forEach(function (c) {
                tr += '<td>' + escHtml(row[c] || '') + '</td>';
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

    // ── KPI update ─────────────────────────────────────────────────
    function updateKpis() {
        const total = uploadedData.length;
        const materials = new Set(uploadedData.map(function (r) { return r['Material'] || r['material'] || ''; })).size;
        const plants = new Set(uploadedData.map(function (r) { return r['Plnt'] || r['Plant'] || r['Werk'] || ''; })).size;
        $('#techKpiTotal').text(total);
        $('#techKpiMaterials').text(materials);
        $('#techKpiPlants').text(plants);
        $('#techKpiPending').text(total);
        $('#techKpiDone').text(0);
        $('#techKpiFailed').text(0);
    }

    // ── Execute migration ──────────────────────────────────────────
    window.techStartMigration = function () {
        setStep(3);
        $('#techProgressBar').removeClass('d-none');
        // Placeholder – will be connected to backend API
        let pct = 0;
        const iv = setInterval(function () {
            pct += 5;
            if (pct > 100) pct = 100;
            $('#techProgress').css('width', pct + '%').text(pct + '%');
            if (pct >= 100) {
                clearInterval(iv);
                setTimeout(function () { setStep(4); }, 500);
            }
        }, 200);
    };

    // ── Helpers ────────────────────────────────────────────────────
    function escHtml(s) {
        const d = document.createElement('div');
        d.appendChild(document.createTextNode(s));
        return d.innerHTML;
    }

    // Expose step navigation
    window.techSetStep = setStep;
})();
