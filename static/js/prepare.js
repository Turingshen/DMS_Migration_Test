// ═══════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════
let editor = null;
let allWerke = [];
let loadedData = [];
let werkeData = {};
let countryToRegion = {};
let selectedDokobs = [];
let dokobCounts = {};
let queryEdited = false;
let programmaticChange = false;
let pendingExclusions = null;  // Uploaded exclusion data (from Excel)

const regionMap = {
    'EU': ['DE','FR','IT','ES','PT','NL','BE','AT','CH','PL','CZ','HU','RO','BG','SK','SI','HR','RS','GR','FI','SE','NO','DK','IE','GB','UK','LU','EE','LV','LT'],
    'NA': ['US','CA','MX'],
    'SA': ['BR','AR','CL','CO','PE','VE','EC'],
    'AP': ['CN','JP','KR','IN','TH','MY','SG','ID','PH','VN','TW','AU','NZ']
};

// ═══════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', function() {
    // CodeMirror init (SQL tab)
    editor = CodeMirror.fromTextArea(document.getElementById('customQuery'), {
        mode: 'text/x-sql', theme: 'monokai', lineNumbers: true,
        matchBrackets: true, autoCloseBrackets: true
    });
    editor.setSize(null, 280);

    // Refresh CodeMirror when SQL tab is shown (fix hidden tab rendering)
    $('a[data-toggle="tab"]').on('shown.bs.tab', function(e) {
        if (e.target.id === 'tab-sql') editor.refresh();
    });

    // Track manual edits in CodeMirror
    editor.on('change', function() {
        if (!programmaticChange) queryEdited = true;
    });

    // Switch default query when source radio changes
    document.querySelectorAll('input[name="querySource"]').forEach(radio => {
        radio.addEventListener('change', function() {
            if (queryEdited) return;
            programmaticChange = true;
            if (this.value === 'dil') {
                editor.setValue("SELECT TOP 100\n    drad.doknr as documentnumber,\n    drad.dokob,\n    drad.objky,\n    drad.dokar as documenttype,\n    drad.dokvr as documentversion,\n    drad.doktl as documentpart,\n    drad.longtext_id,\n    iflos.strno\nFROM dil.drad AS drad\nLEFT JOIN dil.iflos AS iflos ON drad.objky = iflos.strno\nWHERE iflos.tplnr IS NOT NULL;");
            } else {
                editor.setValue("SELECT TOP 100\n    DOKNR as documentnumber,\n    DOKAR as documenttype,\n    DOKVR as documentversion,\n    DOKTL as documentpart\nFROM dbo.migration_selection;");
            }
            programmaticChange = false;
        });
    });

    // File label
    document.getElementById('fileInput').addEventListener('change', function() {
        this.nextElementSibling.textContent = this.files[0] ? this.files[0].name : 'Datei wählen...';
    });

    // Char counter
    document.getElementById('batchDescription').addEventListener('input', function() {
        document.getElementById('descCharCount').textContent = this.value.length;
    });

    // Load Werke + DB status for DMS tab
    loadWerke();
    loadDBStatus();
    loadWaves();
});

// ═══════════════════════════════════════════════════════════════
//  MAIN: CREATE BATCH (dispatcher based on active tab)
// ═══════════════════════════════════════════════════════════════
function createBatch() {
    const activeTab = document.querySelector('#sourceTabs .nav-link.active').id;
    const wave = document.getElementById('batchWave').value;

    if (!wave) { alert('Bitte eine Wave auswählen!'); return; }

    if (activeTab === 'tab-dms')       createDMSBatch();
    else if (activeTab === 'tab-sql')  createSQLBatch();
    else if (activeTab === 'tab-file') createFileBatch();
}

// ═══════════════════════════════════════════════════════════════
//  PATH 1: DMS Objekte → Batch
// ═══════════════════════════════════════════════════════════════
function createDMSBatch() {
    const count = parseInt($('#dbCount').text().replace(/[,.]/g, '')) || 0;
    if (count === 0) {
        alert('Keine DMS-Objekte in der lokalen Datenbank. Bitte zuerst Daten laden!');
        return;
    }
    // Sync modal summary
    updateModalDokobSummary();
    updateFilteredCount();
    $('#dokobFilterModal').modal('show');
}

function createDMSBatchConfirmed() {
    if (selectedDokobs.length === 0) { alert('Bitte mindestens einen Objekttyp auswählen!'); return; }

    const wave = document.getElementById('batchWave').value;
    const description = document.getElementById('batchDescription').value.trim();
    const notes = document.getElementById('batchNotes').value.trim();

    $('#dokobFilterModal').modal('hide');
    const btn = document.getElementById('createBatchBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 0%';
    showDmsProgress(5, 'Starte Batch-Erstellung...');

    const params = new URLSearchParams({ wave, description, notes, dokob_filter: selectedDokobs.join(',') });
    const es = new EventSource(`/api/dms/create-batch-stream?${params}`);

    es.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.type === 'status' || data.type === 'progress') {
            showDmsProgress(data.percent || 50, data.message || 'Verarbeite...');
            btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${data.percent || 0}%`;
        } else if (data.type === 'complete') {
            es.close();
            hideDmsProgress();
            resetBtn();
            showBatchResult(true, data);
        } else if (data.type === 'error') {
            es.close();
            hideDmsProgress();
            resetBtn();
            showBatchResult(false, { error: data.message });
        }
    };
    es.onerror = function() {
        es.close(); hideDmsProgress(); resetBtn();
        showBatchResult(false, { error: 'Verbindungsfehler' });
    };
}

// ═══════════════════════════════════════════════════════════════
//  PATH 2: SQL Query → Batch
// ═══════════════════════════════════════════════════════════════
function createSQLBatch() {
    const query = editor.getValue().trim();
    if (!query) { alert('Bitte eine SQL-Query eingeben'); return; }

    const formData = new FormData();
    formData.append('use_file', 'false');
    formData.append('custom_query', query);
    formData.append('query_source', document.querySelector('input[name="querySource"]:checked').value);
    appendMetadata(formData);
    submitPrepare(formData);
}

// ═══════════════════════════════════════════════════════════════
//  PATH 3: Excel / CSV Upload → Batch
// ═══════════════════════════════════════════════════════════════
function createFileBatch() {
    const fileInput = document.getElementById('fileInput');
    if (!fileInput.files[0]) { alert('Bitte eine Datei auswählen'); return; }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('use_file', 'true');
    appendMetadata(formData);
    submitPrepare(formData);
}

// ═══════════════════════════════════════════════════════════════
//  SHARED: Submit to /prepare (SQL + File paths)
// ═══════════════════════════════════════════════════════════════
function appendMetadata(formData) {
    formData.append('wave', document.getElementById('batchWave').value);
    formData.append('description', document.getElementById('batchDescription').value);
    formData.append('notes', document.getElementById('batchNotes').value);
}

function submitPrepare(formData) {
    const btn = document.getElementById('createBatchBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Wird erstellt...';
    document.getElementById('resultSection').style.display = 'none';

    fetch('/prepare', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => { resetBtn(); showBatchResult(data.success, data); })
        .catch(error => { resetBtn(); showBatchResult(false, { error: String(error) }); });
}

function resetBtn() {
    const btn = document.getElementById('createBatchBtn');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-rocket"></i> Migration Batch erstellen';
}

// ═══════════════════════════════════════════════════════════════
//  RESULT DISPLAY
// ═══════════════════════════════════════════════════════════════
function showBatchResult(success, data) {
    const section = document.getElementById('resultSection');
    const alertEl = document.getElementById('resultAlert');
    const details = document.getElementById('resultDetails');
    section.style.display = 'block';
    section.scrollIntoView({ behavior: 'smooth' });

    if (success) {
        alertEl.className = 'alert alert-success';
        alertEl.innerHTML = '<i class="fas fa-check-circle"></i> <strong>Migration Batch erfolgreich erstellt!</strong>';
        let exclInfo = '';
        if (data.excluded_count > 0) {
            let exclParts = [];
            if (data.excluded_per_dokob) {
                for (const [dk, cnt] of Object.entries(data.excluded_per_dokob)) {
                    exclParts.push(`${dk}: ${cnt.toLocaleString()}`);
                }
            }
            exclInfo = `<tr><th>Ausgeschlossen:</th><td><span class="badge badge-warning">${data.excluded_count.toLocaleString()} Objekte</span> <small class="text-muted">(${exclParts.join(', ')})</small></td></tr>`;
        }
        details.innerHTML = `
            <div class="card">
                <div class="card-body">
                    <table class="table table-sm">
                        <tr><th>Batch ID:</th><td><code>${data.batch_id}</code></td></tr>
                        <tr><th>Datensätze:</th><td>${(data.record_count || 0).toLocaleString()}</td></tr>
                        ${exclInfo}
                    </table>
                    <div class="mt-3">
                        <a href="/preview?batch_id=${data.batch_id}" class="btn btn-primary btn-lg">
                            <i class="fas fa-arrow-right"></i> Weiter: Anreichern &amp; Vorschau
                        </a>
                        <a href="/" class="btn btn-secondary btn-lg ml-2">
                            <i class="fas fa-home"></i> Übersicht
                        </a>
                    </div>
                </div>
            </div>`;
    } else {
        alertEl.className = 'alert alert-danger';
        alertEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> <strong>Fehler:</strong> ${data.error || 'Unbekannter Fehler'}`;
        details.innerHTML = '<button onclick="document.getElementById(\'resultSection\').style.display=\'none\'" class="btn btn-secondary"><i class="fas fa-redo"></i> Erneut versuchen</button>';
    }
}

// ═══════════════════════════════════════════════════════════════
//  Load Waves from DB
// ═══════════════════════════════════════════════════════════════
function loadWaves() {
    fetch('/wave-plans')
        .then(r => r.json())
        .then(data => {
            if (data.success && data.waves) {
                const select = document.getElementById('batchWave');
                select.innerHTML = '<option value="">-- Wave auswählen --</option>';
                data.waves.forEach(w => {
                    select.innerHTML += `<option value="${w.wave_name}">${w.wave_name}</option>`;
                });
            }
        })
        .catch(err => console.error('Error loading waves:', err));
}

// ═══════════════════════════════════════════════════════════════
//  DMS OBJECTS: Werke Grid
// ═══════════════════════════════════════════════════════════════
function loadWerke() {
    fetch('/api/dms/werke')
        .then(r => r.json())
        .then(data => { if (data.success) { allWerke = data.werke; initWerkeGrid(data.werke); } })
        .catch(err => console.error('Error loading Werke:', err));
}

function initWerkeGrid(werke) {
    const container = $('#werkeContainer');
    container.empty();
    werkeData = {};

    werke.forEach(w => {
        const werkCode = w.code || w.werk || '';
        const country = werkCode.substring(0, 2).toUpperCase() || 'XX';
        let region = 'OTHER';
        for (const [r, countries] of Object.entries(regionMap)) {
            if (countries.includes(country)) { region = r; break; }
        }
        countryToRegion[country] = region;
        werkeData[werkCode] = { count: w.count || 0, country, region };
    });

    Object.keys(werkeData).sort((a, b) => a.localeCompare(b, 'de', { numeric: true })).forEach(werkCode => {
        const d = werkeData[werkCode];
        const countStr = d.count >= 1000 ? (d.count / 1000).toFixed(0) + 'k' : d.count;
        const $el = $(`<div class="werke-checkbox" data-werk="${werkCode}" data-region="${d.region}">
            <span class="werke-code">${werkCode}</span><span class="werke-count">${countStr}</span></div>`);
        $el.on('click', function() { $(this).toggleClass('selected'); updateSelectedCount(); });
        container.append($el);
    });
}

function updateSelectedCount() {
    $('#selectedCount').text(`${$('#werkeContainer .werke-checkbox.selected').length} ausgewählt`);
}

function filterWerke(term) {
    term = term.toLowerCase();
    $('#werkeContainer .werke-checkbox').each(function() {
        $(this).toggle(String($(this).data('werk') || '').toLowerCase().includes(term));
    });
}

function getSelectedWerke() {
    const sel = [];
    $('#werkeContainer .werke-checkbox.selected').each(function() { sel.push($(this).data('werk')); });
    return sel;
}

function selectRegion(region) {
    const $items = $(`#werkeContainer .werke-checkbox[data-region="${region}"]`);
    const allSelected = $items.filter('.selected').length === $items.length;
    $items.toggleClass('selected', !allSelected);
    updateSelectedCount();
}

function clearSelection() {
    $('#werkeContainer .werke-checkbox').removeClass('selected');
    updateSelectedCount();
}

// ═══════════════════════════════════════════════════════════════
//  DMS OBJECTS: Load Data (SSE)
// ═══════════════════════════════════════════════════════════════
function loadDMSObjects() {
    const selected = getSelectedWerke();
    if (!selected.length) { alert('Bitte mindestens ein Werk auswählen!'); return; }

    $('#resultsBody').empty();
    loadedData = [];
    $('#detailedStats').empty();
    $('#dmsStatsRow, #dmsResultsRow').hide();
    showDmsProgress(5, 'Verbinde mit DIL...');
    $('#btnLoadData').prop('disabled', true);

    const params = new URLSearchParams({ werke: selected.join(','), auto_save: 'true' });
    const es = new EventSource(`/api/dms/load-stream?${params}`);
    let curStats = {}, curExcl = {}, curNoFile = {};

    es.onmessage = function(event) {
        const data = JSON.parse(event.data);
        switch (data.type) {
            case 'status':
                showDmsProgress(data.percent, data.message); break;
            case 'progress':
                showDmsProgress(data.percent, `${data.message} (${data.step}/${data.total_steps})`); break;
            case 'step_complete':
                curStats[data.dokob] = data.count;
                curExcl[data.dokob] = data.excluded || 0;
                curNoFile[data.dokob] = data.no_file || 0;
                const nfInfo = data.no_file > 0 ? ` 🗎-${data.no_file.toLocaleString()}` : '';
                const exInfo = data.excluded > 0 ? ` (-${data.excluded.toLocaleString()})` : '';
                showDmsProgress(data.percent, `✓ ${data.dokob}: ${data.count.toLocaleString()}${exInfo}${nfInfo} (${data.time})`);
                renderDokobBadges(curStats, curExcl, curNoFile);
                break;
            case 'complete':
                es.close();
                $('#btnLoadData').prop('disabled', false);
                loadedData = data.data;
                showDmsProgress(100, 'Fertig!');
                setTimeout(() => {
                    hideDmsProgress();
                    displayResults(data.data);
                    renderDokobBadges(data.stats, data.stats_excluded || {}, data.stats_no_file || {});
                    updateDBStatusFull(data.count, data.stats_excluded || {}, data.stats_no_file || {});
                }, 500);
                break;
            case 'error':
                es.close();
                $('#btnLoadData').prop('disabled', false);
                hideDmsProgress();
                alert('Fehler: ' + data.message);
                break;
        }
    };
    es.onerror = function() {
        es.close(); $('#btnLoadData').prop('disabled', false);
        hideDmsProgress(); alert('Verbindungsfehler zum Server');
    };
}

function showDmsProgress(pct, label) {
    $('#dmsProgressRow').show();
    $('#dmsProgressBar').css('width', pct + '%');
    $('#dmsProgressText').text(pct + '%');
    $('#dmsProgressLabel').text(label);
}
function hideDmsProgress() { $('#dmsProgressRow').hide(); }

let currentAblageFilter = 'ALL';

function displayResults(data) {
    loadedData = data;
    currentAblageFilter = 'ALL';
    $('#ablageFilterGroup button').removeClass('active');
    $('#ablageFilterGroup button[data-ablage="ALL"]').addClass('active');
    if (document.getElementById('tableSearchInput')) document.getElementById('tableSearchInput').value = '';
    applyTableFilter();
    $('#dmsResultsRow').show();
}

function setAblageFilter(filter) {
    currentAblageFilter = filter;
    $('#ablageFilterGroup button').removeClass('active');
    $(`#ablageFilterGroup button[data-ablage="${filter}"]`).addClass('active');
    applyTableFilter();
}

function applyTableFilter() {
    const searchTerm = ($('#tableSearchInput').val() || '').toLowerCase().trim();
    const tbody = $('#resultsBody'); tbody.empty();
    if (!loadedData || !loadedData.length) {
        tbody.append('<tr><td colspan="8" class="text-center">Keine Daten</td></tr>');
        $('#tableInfo').html('');
        return;
    }
    let filtered = loadedData;
    if (currentAblageFilter !== 'ALL') {
        filtered = filtered.filter(r => (r.ablage || 'KPRO') === currentAblageFilter);
    }
    if (searchTerm) {
        filtered = filtered.filter(r =>
            (r.dokar||'').toLowerCase().includes(searchTerm) ||
            (r.doknr||'').toLowerCase().includes(searchTerm) ||
            (r.dokvr||'').toLowerCase().includes(searchTerm) ||
            (r.doktl||'').toLowerCase().includes(searchTerm) ||
            (r.dokob||'').toLowerCase().includes(searchTerm) ||
            (r.objky||'').toLowerCase().includes(searchTerm) ||
            (r.werk||'').toLowerCase().includes(searchTerm) ||
            (r.ablage||'').toLowerCase().includes(searchTerm)
        );
    }
    filtered.slice(0, 200).forEach(r => {
        const ablage = r.ablage || 'KPRO';
        const ablageClass = ablage === 'KPRO' ? 'badge-info' : 'badge-warning';
        const ablageIcon = ablage === 'KPRO' ? '<i class="fas fa-cloud"></i>' : '<i class="fas fa-database"></i>';
        tbody.append(`<tr><td>${r.dokar||''}</td><td><code>${r.doknr||''}</code></td><td>${r.dokvr||''}</td><td>${r.doktl||''}</td><td><span class="badge badge-info">${r.dokob||''}</span></td><td><small>${r.objky||''}</small></td><td><span class="badge badge-secondary">${r.werk||''}</span></td><td><span class="badge ${ablageClass}">${ablageIcon} ${ablage}</span></td></tr>`);
    });
    const showing = Math.min(200, filtered.length);
    const filterInfo = (searchTerm || currentAblageFilter !== 'ALL')
        ? ` (gefiltert aus ${loadedData.length.toLocaleString()})`
        : '';
    $('#tableInfo').html(`${showing.toLocaleString()} von ${filtered.length.toLocaleString()} Einträgen${filterInfo}`);
}

function renderDokobBadges(stats, excluded, noFile) {
    const container = $('#detailedStats'); container.empty();
    excluded = excluded || {}; noFile = noFile || {};
    let totalCount = 0, totalExcl = 0, totalNoFile = 0;
    for (const [k, v] of Object.entries(stats)) {
        if (k !== 'total' && typeof v === 'number') {
            totalCount += v; totalExcl += (excluded[k] || 0); totalNoFile += (noFile[k] || 0);
        }
    }
    const grandTotal = totalCount + totalExcl + totalNoFile;

    // --- Summary row ---
    let summaryHtml = '<div class="stats-summary-row">';
    summaryHtml += `<div class="stats-summary-card summary-batch">
        <i class="fas fa-rocket"></i>
        <span class="summary-count">${totalCount.toLocaleString()}</span>
        <span>Batch</span>
        <span class="summary-sub">von ${grandTotal.toLocaleString()}</span>
    </div>`;
    if (totalNoFile > 0) {
        summaryHtml += `<div class="stats-summary-card summary-nofile">
            <i class="fas fa-file-excel"></i>
            <span class="summary-count">${totalNoFile.toLocaleString()}</span>
            <span>Ohne Datei</span>
        </div>`;
    }
    if (totalExcl > 0) {
        summaryHtml += `<div class="stats-summary-card summary-status">
            <i class="fas fa-ban"></i>
            <span class="summary-count">${totalExcl.toLocaleString()}</span>
            <span>Status</span>
        </div>`;
    }
    summaryHtml += '</div>';
    container.append(summaryHtml);

    // Per-DOKOB cards — clickable for batch DOKOB filter
    const entries = Object.entries(stats)
        .filter(([k, v]) => k !== 'total' && typeof v === 'number')
        .map(([dokob, count]) => [dokob, count, excluded[dokob] || 0, noFile[dokob] || 0])
        .filter(([d, c, e, n]) => c > 0 || e > 0 || n > 0)
        .sort((a, b) => (b[1]+b[2]+b[3]) - (a[1]+a[2]+a[3]));

    // Rebuild dokobCounts and init selectedDokobs
    dokobCounts = {};
    const knownDokobs = entries.map(e => e[0]);
    if (selectedDokobs.length === 0 || !selectedDokobs.some(d => knownDokobs.includes(d))) {
        selectedDokobs = knownDokobs.slice();
    }

    if (entries.length > 0) {
        let rowHtml = '<div class="stats-dokob-row">';
        entries.forEach(([dokob, count, excl, nf]) => {
            dokobCounts[dokob] = count;
            const isSel = selectedDokobs.includes(dokob);
            const selClass = isSel ? 'dokob-selected' : 'dokob-deselected';
            const checkIcon = isSel ? '\u2611' : '\u2610';
            let nums = `<span class="dokob-num batch">${count.toLocaleString()}</span>`;
            if (nf > 0) nums += `<span class="dokob-num nofile" title="${nf.toLocaleString()} ohne Datei"><i class="fas fa-file-excel"></i> ${nf.toLocaleString()}</span>`;
            if (excl > 0) nums += `<span class="dokob-num status" title="${excl.toLocaleString()} Status-ausgeschlossen"><i class="fas fa-ban"></i> ${excl.toLocaleString()}</span>`;
            rowHtml += `<div class="dokob-card dokob-selectable ${selClass}" data-dokob="${dokob}" onclick="toggleDokobCard('${dokob}')" title="Klicken zum An-/Abw\u00e4hlen f\u00fcr Batch">
                <div class="dokob-card-name"><span class="dokob-check">${checkIcon}</span>${dokob}</div>
                <div class="dokob-card-numbers">${nums}</div>
            </div>`;
        });
        rowHtml += '</div>';
        container.append(rowHtml);
    }
    $('#dmsStatsRow').show();
}

function loadDBStatus() {
    fetch('/api/dms/status').then(r => r.json()).then(data => {
        if (data.success) {
            $('#dbCount').text(data.count.toLocaleString());
            if (data.count > 0) { $('#dbStatus').removeClass('badge-secondary').addClass('badge-success'); }
            else { $('#dbStatus').removeClass('badge-success').addClass('badge-secondary'); }
        }
    }).catch(() => $('#dbStatus').removeClass('badge-success').addClass('badge-secondary'));
}

function updateDBStatusFull(batchCount, statsExcluded, statsNoFile) {
    $('#dbCount').text(batchCount.toLocaleString());
    if (batchCount > 0) { $('#dbStatus').removeClass('badge-secondary').addClass('badge-success'); }
    else { $('#dbStatus').removeClass('badge-success').addClass('badge-warning'); }
    let totalNoFile = 0, totalExcluded = 0;
    for (const v of Object.values(statsNoFile || {})) { if (typeof v === 'number') totalNoFile += v; }
    for (const v of Object.values(statsExcluded || {})) { if (typeof v === 'number') totalExcluded += v; }
    let parts = [];
    if (totalNoFile > 0) parts.push(`<span class="badge badge-no-file"><i class="fas fa-file-excel"></i> ${totalNoFile.toLocaleString()} ohne Datei</span>`);
    if (totalExcluded > 0) parts.push(`<span class="badge badge-status-excl"><i class="fas fa-ban"></i> ${totalExcluded.toLocaleString()} Status</span>`);
    if (parts.length > 0) { $('#dbExcludedInfo').html(parts.join(' ')).show(); }
    else { $('#dbExcludedInfo').hide(); }
}

function exportData() {
    if (!loadedData.length) { alert('Keine Daten zum Exportieren!'); return; }
    const headers = ['dokar','doknr','dokvr','doktl','dokob','objky','werk','ablage'];
    let csv = headers.map(h => h.toUpperCase()).join(';') + '\n';
    loadedData.forEach(r => { csv += headers.map(h => r[h]||'').join(';') + '\n'; });
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `dms_objects_${new Date().toISOString().slice(0,10)}.csv`; a.click();
}

// ═══════════════════════════════════════════════════════════════════
//  DOKOB FILTER (for DMS batch creation)
// ═══════════════════════════════════════════════════════════════════
function toggleDokobCard(dokob) {
    const el = document.querySelector(`.dokob-selectable[data-dokob="${dokob}"]`);
    if (!el) return;
    if (selectedDokobs.includes(dokob)) {
        selectedDokobs = selectedDokobs.filter(d => d !== dokob);
        el.classList.remove('dokob-selected');
        el.classList.add('dokob-deselected');
        el.querySelector('.dokob-check').textContent = '\u2610';
    } else {
        selectedDokobs.push(dokob);
        el.classList.remove('dokob-deselected');
        el.classList.add('dokob-selected');
        el.querySelector('.dokob-check').textContent = '\u2611';
    }
    updateDokobInfo();
    updateModalDokobSummary();
}

function selectAllDokob(selectAll) {
    const cards = document.querySelectorAll('.dokob-selectable');
    selectedDokobs = [];
    cards.forEach(el => {
        const dokob = el.getAttribute('data-dokob');
        if (selectAll) {
            selectedDokobs.push(dokob);
            el.classList.remove('dokob-deselected');
            el.classList.add('dokob-selected');
            el.querySelector('.dokob-check').textContent = '\u2611';
        } else {
            el.classList.remove('dokob-selected');
            el.classList.add('dokob-deselected');
            el.querySelector('.dokob-check').textContent = '\u2610';
        }
    });
    updateDokobInfo();
    updateModalDokobSummary();
}

function updateDokobInfo() {
    const total = document.querySelectorAll('.dokob-selectable').length;
    const sel = selectedDokobs.length;
    if (sel === 0) $('#selectedDokobInfo').html('<span class="text-danger">\u26a0\ufe0f Keine Objekttypen!</span>');
    else if (sel === total) $('#selectedDokobInfo').text('Alle Objekttypen ausgewählt');
    else $('#selectedDokobInfo').text(`${sel} von ${total} Objekttypen`);
    updateFilteredCount();
}

function updateFilteredCount() {
    let c = 0;
    selectedDokobs.forEach(d => { c += (dokobCounts[d] || 0); });
    $('#dmsObjectCount').text(c.toLocaleString());
}

function updateModalDokobSummary() {
    const container = document.getElementById('modalDokobSummary');
    if (!container) return;
    if (Object.keys(dokobCounts).length === 0) {
        container.innerHTML = '<span class="text-muted">Noch keine Daten geladen — bitte zuerst Daten laden.</span>';
        return;
    }
    let html = '';
    const allDokobs = Object.keys(dokobCounts).sort((a,b) => (dokobCounts[b]||0) - (dokobCounts[a]||0));
    allDokobs.forEach(dokob => {
        const count = dokobCounts[dokob] || 0;
        const isSel = selectedDokobs.includes(dokob);
        const cls = isSel ? 'badge-success' : 'badge-secondary';
        const icon = isSel ? '\u2611' : '\u2610';
        html += `<span class="badge ${cls}" style="padding:5px 8px;font-size:12px;cursor:pointer;user-select:none;" onclick="toggleDokobCard('${dokob}')">${icon} ${dokob} (${count.toLocaleString()})</span>`;
    });
    container.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════════════
//  EXCLUSION: Excel Upload / Download
// ═══════════════════════════════════════════════════════════════════
function uploadExclusionFile(input) {
    if (!input.files || !input.files[0]) return;
    const file = input.files[0];
    document.getElementById('exclusionFileLabel').textContent = file.name;

    const formData = new FormData();
    formData.append('file', file);

    const resultDiv = document.getElementById('exclusionResult');
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div class="text-muted"><i class="fas fa-spinner fa-spin"></i> Datei wird verarbeitet...</div>';

    fetch('/api/exclusion-template/upload', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                pendingExclusions = data.exclusions;
                const totalKeys = data.total_keys || 0;
                const sheets = data.sheets_found || [];

                // Build summary
                let html = '<div class="alert alert-success mb-0"><i class="fas fa-check-circle"></i> <strong>' +
                    totalKeys.toLocaleString() + ' Ausschluss-Keys</strong> aus ' +
                    sheets.length + ' Objekttypen geladen:<br>';
                html += '<div class="d-flex flex-wrap mt-2" style="gap:6px;">';
                for (const dokob of sheets) {
                    const info = data.exclusions[dokob];
                    const cnt = info ? info.count : 0;
                    html += '<span class="badge badge-danger" style="padding:4px 8px;">' +
                        '<i class="fas fa-ban"></i> ' + dokob + ': ' + cnt.toLocaleString() + '</span>';
                }
                html += '</div></div>';
                resultDiv.innerHTML = html;

                // Show badge and clear button
                document.getElementById('exclusionBadge').textContent = totalKeys.toLocaleString() + ' Keys';
                document.getElementById('exclusionBadge').style.display = 'inline';
                document.getElementById('btnClearExclusion').style.display = 'inline-block';
            } else {
                resultDiv.innerHTML = '<div class="alert alert-danger mb-0"><i class="fas fa-exclamation-circle"></i> ' +
                    (data.error || 'Unbekannter Fehler') + '</div>';
                pendingExclusions = null;
            }
        })
        .catch(err => {
            resultDiv.innerHTML = '<div class="alert alert-danger mb-0"><i class="fas fa-exclamation-circle"></i> ' +
                String(err) + '</div>';
            pendingExclusions = null;
        });
}

function clearExclusionUpload() {
    pendingExclusions = null;
    document.getElementById('exclusionFileInput').value = '';
    document.getElementById('exclusionFileLabel').textContent = 'Ausschluss-Excel wählen...';
    document.getElementById('exclusionResult').style.display = 'none';
    document.getElementById('exclusionResult').innerHTML = '';
    document.getElementById('exclusionBadge').style.display = 'none';
    document.getElementById('btnClearExclusion').style.display = 'none';

    // Clear server-side temp file
    fetch('/api/exclusion-template/clear', { method: 'POST' }).catch(() => {});
}
