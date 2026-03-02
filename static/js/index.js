document.addEventListener('DOMContentLoaded', function() {
    loadAll();
    loadWavePlans();
    setInterval(loadAll, 30000);
});

let allBatches = [];
let selectedWave = '';

function loadAll() {
    fetch('/batches')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                allBatches = data.batches || [];
                populateWaveFilter(allBatches);
                applyWaveFilter();
            }
        })
        .catch(err => console.error('Fehler:', err));
}

function populateWaveFilter(batches) {
    const select = document.getElementById('waveFilter');
    const prevVal = select.value;
    const waveNames = new Set();
    batches.forEach(b => { if (b.wave) waveNames.add(b.wave); });
    // Also add waves from wave plans
    wavePlans.forEach(w => waveNames.add(w.wave_name));

    const sorted = [...waveNames].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    select.innerHTML = '<option value="">Alle Wellen</option>';
    sorted.forEach(w => { select.innerHTML += `<option value="${w}">${w}</option>`; });
    select.value = prevVal || '';
}

function applyWaveFilter() {
    selectedWave = document.getElementById('waveFilter').value;
    const filtered = selectedWave ? allBatches.filter(b => b.wave === selectedWave) : allBatches;
    const filteredPlans = selectedWave ? wavePlans.filter(w => w.wave_name === selectedWave) : wavePlans;

    renderKPIs(filtered);
    renderKanban(filtered);
    displayBatches(filtered);
    renderGantt(filteredPlans, filtered);
    renderTaskList(filteredPlans);

    const info = document.getElementById('waveFilterInfo');
    if (selectedWave) {
        info.textContent = `${filtered.length} Batches in ${selectedWave}`;
    } else {
        info.textContent = '';
    }
}

// ========================================================================
// KPI Cards
// ========================================================================
function renderKPIs(batches) {
    let totalDocs = 0, uploaded = 0, linked = 0, failed = 0;
    const waves = new Set();

    batches.forEach(b => {
        if (b.wave) waves.add(b.wave);
        totalDocs += (b.total_records || 0);
        uploaded += (b.successful_records || 0);
        linked += (b.link_linked || 0) + (b.link_exists || 0);
        failed += (b.failed_records || 0) + (b.link_failed || 0);
    });

    document.getElementById('kpiWaves').textContent = waves.size;
    document.getElementById('kpiBatches').textContent = batches.length;
    document.getElementById('kpiDocs').textContent = totalDocs.toLocaleString();
    document.getElementById('kpiUploaded').textContent = uploaded.toLocaleString();
    document.getElementById('kpiLinked').textContent = linked.toLocaleString();
    document.getElementById('kpiFailed').textContent = failed.toLocaleString();
}

// ========================================================================
// Kanban Board
// ========================================================================
function renderKanban(batches) {
    const waves = {};
    batches.forEach(b => {
        const wave = b.wave || 'Nicht zugeordnet';
        if (!waves[wave]) waves[wave] = [];
        waves[wave].push(b);
    });

    const sortedWaves = Object.keys(waves).sort((a, b) => {
        if (a === 'Nicht zugeordnet') return 1;
        if (b === 'Nicht zugeordnet') return -1;
        return a.localeCompare(b, undefined, { numeric: true });
    });

    const board = document.getElementById('kanbanBoard');
    if (sortedWaves.length === 0) {
        board.innerHTML = '<div class="text-center w-100 py-5 text-muted">Keine Batches vorhanden. <a href="/prepare">Ersten Batch erstellen</a></div>';
        return;
    }

    board.innerHTML = sortedWaves.map(waveName => {
        const wb = waves[waveName];
        const isUnassigned = waveName === 'Nicht zugeordnet';
        let wTotal = 0, wUploaded = 0, wLinked = 0, wFailed = 0;
        wb.forEach(b => {
            wTotal += (b.total_records || 0);
            wUploaded += (b.successful_records || 0);
            wLinked += (b.link_linked || 0) + (b.link_exists || 0);
            wFailed += (b.failed_records || 0);
        });
        const wPct = wTotal > 0 ? Math.round(wUploaded / wTotal * 100) : 0;
        const lPct = wTotal > 0 ? Math.round(wLinked / wTotal * 100) : 0;

        return `
            <div class="wave-column">
                <div class="wave-header ${isUnassigned ? 'bg-warning text-dark' : 'bg-dark text-white'}">
                    ${waveName}
                    <span class="float-right badge badge-light">${wb.length} Batches</span>
                </div>
                <div class="mb-2">
                    <div class="d-flex justify-content-between wave-stats">
                        <span><i class="fas fa-upload"></i> Upload: ${wPct}%</span>
                        <span><i class="fas fa-link"></i> Verlinkung: ${lPct}%</span>
                    </div>
                    <div class="progress" style="height: 8px;">
                        <div class="progress-bar bg-success" style="width: ${wPct}%"></div>
                    </div>
                    <div class="progress mt-1" style="height: 4px;">
                        <div class="progress-bar bg-info" style="width: ${lPct}%"></div>
                    </div>
                    <div class="wave-stats text-right mt-1">
                        ${wUploaded}/${wTotal} Docs | ${wLinked} verlinkt
                        ${wFailed > 0 ? '| <span class="text-danger">' + wFailed + ' Fehler</span>' : ''}
                    </div>
                </div>
                ${wb.map(b => renderBatchCard(b, {showEditButton: true})).join('')}
            </div>
        `;
    }).join('');
}

// ========================================================================
// Batch Table
// ========================================================================
function toggleBatchTable() {
    const body = document.getElementById('batchTableBody');
    const icon = document.getElementById('batchTableToggle');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        icon.className = 'fas fa-chevron-up';
    } else {
        body.style.display = 'none';
        icon.className = 'fas fa-chevron-down';
    }
}

function displayBatches(batches) {
    const tbody = document.getElementById('batchesBody');
    if (batches.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted">Keine Batches vorhanden</td></tr>';
        return;
    }

    tbody.innerHTML = batches.map(batch => {
        const phaseBadge = getPhaseBadge(batch.migration_phase, batch.status);
        const linkInfo = getLinkInfo(batch);
        const actions = getActionButtons(batch);

        return `
            <tr data-batch='${JSON.stringify(batch).replace(/'/g, "&#39;")}'>
                <td><code>${batch.batch_id}</code></td>
                <td><span class="badge badge-secondary">${batch.wave || '-'}</span></td>
                <td>${batch.description ? escapeHtml(batch.description) : '<span class="text-muted">-</span>'}</td>
                <td>${formatDateTime(batch.created_at)}</td>
                <td>${batch.created_by || '-'}</td>
                <td>${batch.total_records || 0}</td>
                <td class="text-success">${batch.successful_records || 0}</td>
                <td class="text-danger">${batch.failed_records || 0}</td>
                <td>${phaseBadge}</td>
                <td>${linkInfo}</td>
                <td>${actions}</td>
            </tr>
        `;
    }).join('');
}

function getPhaseBadge(phase, status) {
    if (!phase) {
        if (status === 'prepared') return '<span class="badge badge-light">—</span>';
        return '<span class="badge badge-secondary">Upload</span>';
    }
    const phases = {
        'upload': '<span class="badge badge-primary"><i class="fas fa-upload"></i> Upload</span>',
        'upload_done': '<span class="badge badge-success"><i class="fas fa-check"></i> Upload ✓</span>',
        'linking': '<span class="badge badge-info"><i class="fas fa-link fa-spin"></i> Verlinkung</span>',
        'completed': '<span class="badge badge-success"><i class="fas fa-check-double"></i> Fertig</span>',
        'link_cancelled': '<span class="badge badge-secondary"><i class="fas fa-stop"></i> Abgebrochen</span>',
        'link_error': '<span class="badge badge-danger"><i class="fas fa-exclamation"></i> Fehler</span>'
    };
    return phases[phase] || '<span class="badge badge-secondary">' + phase + '</span>';
}

function getLinkInfo(batch) {
    const total = batch.link_total || 0;
    if (total === 0) return '<span class="text-muted">—</span>';
    const linked = (batch.link_linked || 0) + (batch.link_exists || 0);
    const failed = batch.link_failed || 0;
    const pct = Math.round(linked / total * 100);
    let color = 'bg-secondary';
    if (linked === total) color = 'bg-success';
    else if (linked > 0) color = 'bg-info';
    else if (failed > 0) color = 'bg-danger';

    return `<div title="Verlinkt: ${linked} | Fehler: ${failed} | Gesamt: ${total}">
        <div class="progress" style="height: 16px; min-width: 60px;">
            <div class="progress-bar ${color}" style="width: ${pct}%">${linked}/${total}</div>
        </div>
    </div>`;
}

function getActionButtons(batch) {
    let buttons = [];
    buttons.push(`<a href="/preview?batch_id=${batch.batch_id}" class="btn btn-sm btn-primary" title="Vorschau & Vorbereitung"><i class="fas fa-eye"></i> Vorschau</a>`);

    if (batch.status === 'completed' || batch.status === 'completed_with_errors' || batch.executed_records > 0) {
        buttons.push(`<a href="/details?batch_id=${batch.batch_id}" class="btn btn-sm btn-info" title="Auswertung"><i class="fas fa-chart-bar"></i> Auswertung</a>`);
    }

    buttons.push(`<button onclick="editBatch('${batch.batch_id}')" class="btn btn-sm btn-outline-primary" title="Bearbeiten"><i class="fas fa-edit"></i></button>`);

    if (batch.status !== 'executing') {
        buttons.push(`<button onclick="deleteBatch('${batch.batch_id}')" class="btn btn-sm btn-outline-danger" title="Löschen"><i class="fas fa-trash"></i></button>`);
    }
    return buttons.join(' ');
}

// ========================================================================
// Batch Edit / Delete
// ========================================================================
function editBatch(batchId) {
    const row = document.querySelector(`tr[data-batch*="${batchId}"]`);
    let batch = {};
    try { batch = JSON.parse(row.getAttribute('data-batch')); } catch(e) {}

    let modal = document.getElementById('editBatchModal');
    if (!modal) {
        const html = `
        <div class="modal fade" id="editBatchModal" tabindex="-1">
            <div class="modal-dialog"><div class="modal-content">
                <div class="modal-header bg-primary text-white py-2">
                    <h5 class="modal-title"><i class="fas fa-edit"></i> Batch bearbeiten</h5>
                    <button type="button" class="close text-white" data-dismiss="modal"><span>&times;</span></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="editBatchId">
                    <div class="form-group">
                        <label for="editWave">Wave</label>
                        <select class="form-control" id="editWave">
                            <option value="">-- Wave w&auml;hlen --</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Beschreibung (max. 40 Zeichen)</label>
                        <input type="text" class="form-control" id="editDescription" maxlength="40">
                        <small class="form-text text-muted"><span id="descCharCount">0</span>/40</small>
                    </div>
                    <div class="form-group">
                        <label>Notizen</label>
                        <textarea class="form-control" id="editNotes" rows="3"></textarea>
                    </div>
                    <div class="form-group">
                        <label><strong>Aufgaben-Zuordnung</strong></label>
                        <table class="table table-sm table-borderless mb-0">
                            <thead><tr><th style="width:30px"></th><th>Aufgabe</th><th>Start</th><th style="width:80px">Dauer</th><th style="width:90px">Ende</th></tr></thead>
                            <tbody>
                                <tr>
                                    <td><input type="checkbox" id="editTaskQualLoad" onchange="toggleBatchTaskRow('QualLoad')"></td>
                                    <td><span class="task-env qual">Q</span> Load</td>
                                    <td><input type="date" class="form-control form-control-sm bt-start" id="editTaskQualLoadStart" data-task="QualLoad" disabled></td>
                                    <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm bt-dur" id="editTaskQualLoadDur" data-task="QualLoad" disabled><div class="input-group-append"><span class="input-group-text" style="font-size:0.7rem">T</span></div></div></td>
                                    <td><span class="text-muted bt-end-label" id="editTaskQualLoadEnd" style="font-size:0.8rem">&ndash;</span></td>
                                </tr>
                                <tr>
                                    <td><input type="checkbox" id="editTaskQualLink" onchange="toggleBatchTaskRow('QualLink')"></td>
                                    <td><span class="task-env qual">Q</span> Link</td>
                                    <td><input type="date" class="form-control form-control-sm bt-start" id="editTaskQualLinkStart" data-task="QualLink" disabled></td>
                                    <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm bt-dur" id="editTaskQualLinkDur" data-task="QualLink" disabled><div class="input-group-append"><span class="input-group-text" style="font-size:0.7rem">T</span></div></div></td>
                                    <td><span class="text-muted bt-end-label" id="editTaskQualLinkEnd" style="font-size:0.8rem">&ndash;</span></td>
                                </tr>
                                <tr>
                                    <td><input type="checkbox" id="editTaskProdLoad" onchange="toggleBatchTaskRow('ProdLoad')"></td>
                                    <td><span class="task-env prod">P</span> Load</td>
                                    <td><input type="date" class="form-control form-control-sm bt-start" id="editTaskProdLoadStart" data-task="ProdLoad" disabled></td>
                                    <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm bt-dur" id="editTaskProdLoadDur" data-task="ProdLoad" disabled><div class="input-group-append"><span class="input-group-text" style="font-size:0.7rem">T</span></div></div></td>
                                    <td><span class="text-muted bt-end-label" id="editTaskProdLoadEnd" style="font-size:0.8rem">&ndash;</span></td>
                                </tr>
                                <tr>
                                    <td><input type="checkbox" id="editTaskProdLink" onchange="toggleBatchTaskRow('ProdLink')"></td>
                                    <td><span class="task-env prod">P</span> Link</td>
                                    <td><input type="date" class="form-control form-control-sm bt-start" id="editTaskProdLinkStart" data-task="ProdLink" disabled></td>
                                    <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm bt-dur" id="editTaskProdLinkDur" data-task="ProdLink" disabled><div class="input-group-append"><span class="input-group-text" style="font-size:0.7rem">T</span></div></div></td>
                                    <td><span class="text-muted bt-end-label" id="editTaskProdLinkEnd" style="font-size:0.8rem">&ndash;</span></td>
                                </tr>
                            </tbody>
                        </table>
                        <small class="text-muted">T = Kalendertage. Checkbox aktiviert die Aufgabe.</small>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-danger mr-auto" onclick="deleteBatchFromModal()"><i class="fas fa-trash"></i> L&ouml;schen</button>
                    <button class="btn btn-secondary" data-dismiss="modal">Abbrechen</button>
                    <button class="btn btn-primary" onclick="saveBatch()"><i class="fas fa-save"></i> Speichern</button>
                </div>
            </div></div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', html);
        modal = document.getElementById('editBatchModal');
        document.getElementById('editDescription').addEventListener('input', function() {
            document.getElementById('descCharCount').textContent = this.value.length;
        });
        // Attach live-update listeners for start + duration → end label
        modal.querySelectorAll('.bt-start, .bt-dur').forEach(el => {
            el.addEventListener('input', () => btUpdateEndLabel(el.dataset.task));
        });
        // Populate wave dropdown
        populateWaveDropdowns(wavePlans);
    }

    document.getElementById('editBatchId').value = batchId;
    document.getElementById('editWave').value = batch.wave || '';
    document.getElementById('editDescription').value = batch.description || '';
    document.getElementById('editNotes').value = batch.notes || '';
    document.getElementById('descCharCount').textContent = (batch.description || '').length;

    // Populate per-task fields
    const taskKeys = ['QualLoad','QualLink','ProdLoad','ProdLink'];
    const dbKeys   = ['task_qual_load','task_qual_link','task_prod_load','task_prod_link'];
    taskKeys.forEach((tk, i) => {
        const checked = !!batch[dbKeys[i]];
        document.getElementById('editTask' + tk).checked = checked;
        document.getElementById('editTask' + tk + 'Start').value = batch[dbKeys[i] + '_start'] || '';
        document.getElementById('editTask' + tk + 'Dur').value = batch[dbKeys[i] + '_dur'] || '';
        toggleBatchTaskRow(tk);
        btUpdateEndLabel(tk);
    });

    $(modal).modal('show');
}

// Toggle start/duration inputs based on checkbox
function toggleBatchTaskRow(task) {
    const checked = document.getElementById('editTask' + task).checked;
    document.getElementById('editTask' + task + 'Start').disabled = !checked;
    document.getElementById('editTask' + task + 'Dur').disabled = !checked;
    if (!checked) {
        document.getElementById('editTask' + task + 'Start').value = '';
        document.getElementById('editTask' + task + 'Dur').value = '';
        document.getElementById('editTask' + task + 'End').textContent = '–';
    }
}

// Compute end date label from start + duration
function btUpdateEndLabel(task) {
    const startVal = document.getElementById('editTask' + task + 'Start').value;
    const durVal   = parseInt(document.getElementById('editTask' + task + 'Dur').value);
    const label    = document.getElementById('editTask' + task + 'End');
    if (startVal && durVal > 0) {
        const endStr = addDays(startVal, durVal - 1);
        const parts = endStr.split('-');
        label.textContent = parts[2] + '.' + parts[1] + '.' + parts[0];
    } else {
        label.textContent = '–';
    }
}

function saveBatch() {
    const batchId = document.getElementById('editBatchId').value;
    fetch(`/batch/${batchId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            wave: document.getElementById('editWave').value,
            description: document.getElementById('editDescription').value,
            notes: document.getElementById('editNotes').value,
            estimated_duration_h: null,
            task_qual_load: document.getElementById('editTaskQualLoad').checked,
            task_qual_link: document.getElementById('editTaskQualLink').checked,
            task_prod_load: document.getElementById('editTaskProdLoad').checked,
            task_prod_link: document.getElementById('editTaskProdLink').checked,
            task_qual_load_start: document.getElementById('editTaskQualLoadStart').value || null,
            task_qual_load_dur: document.getElementById('editTaskQualLoadDur').value || null,
            task_qual_link_start: document.getElementById('editTaskQualLinkStart').value || null,
            task_qual_link_dur: document.getElementById('editTaskQualLinkDur').value || null,
            task_prod_load_start: document.getElementById('editTaskProdLoadStart').value || null,
            task_prod_load_dur: document.getElementById('editTaskProdLoadDur').value || null,
            task_prod_link_start: document.getElementById('editTaskProdLinkStart').value || null,
            task_prod_link_dur: document.getElementById('editTaskProdLinkDur').value || null
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) { $('#editBatchModal').modal('hide'); loadAll(); }
        else alert('Fehler: ' + data.error);
    })
    .catch(err => alert('Fehler: ' + err));
}

function deleteBatch(batchId) {
    if (!confirm('Batch ' + batchId + ' wirklich l\u00f6schen?\n\nAlle Staging-Datens\u00e4tze, Dateidetails, Logs und Mappings werden unwiderruflich gel\u00f6scht.')) return;

    const btn = event.target.closest('button');
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    const row = btn.closest('tr');
    if (row) row.style.opacity = '0.5';

    fetch('/batch/' + batchId, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
            if (data.success) { loadAll(); }
            else { alert('Fehler: ' + data.error); btn.disabled = false; btn.innerHTML = orig; if (row) row.style.opacity = '1'; }
        })
        .catch(err => { alert('Fehler: ' + err); btn.disabled = false; btn.innerHTML = orig; if (row) row.style.opacity = '1'; });
}

function deleteBatchFromModal() {
    const batchId = document.getElementById('editBatchId').value;
    if (!batchId) return;
    if (!confirm('Batch ' + batchId + ' wirklich l\u00f6schen?\n\nAlle Staging-Datens\u00e4tze, Dateidetails, Logs und Mappings werden unwiderruflich gel\u00f6scht.')) return;

    fetch('/batch/' + batchId, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
            if (data.success) { $('#editBatchModal').modal('hide'); loadAll(); }
            else { alert('Fehler: ' + data.error); }
        })
        .catch(err => { alert('Fehler: ' + err); });
}

// ========================================================================
// Wave Plan - Gantt Timeline + Task List
// ========================================================================
let wavePlans = [];

function loadWavePlans() {
    fetch('/wave-plans')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                wavePlans = data.waves || [];
                populateWaveDropdowns(wavePlans);
                populateWaveFilter(allBatches);
                applyWaveFilter();
            }
        })
        .catch(err => console.error('Wave plans error:', err));
}

function populateWaveDropdowns(waves) {
    const dbNames = waves.map(w => w.wave_name);
    // Always include Wave 0-7, merge with DB waves
    const defaultWaves = Array.from({length: 8}, (_, i) => `Wave ${i}`);
    const names = [...new Set([...defaultWaves, ...dbNames])].sort((a, b) => {
        const na = parseInt(a.replace(/\D/g, '')), nb = parseInt(b.replace(/\D/g, ''));
        return (isNaN(na) ? 999 : na) - (isNaN(nb) ? 999 : nb);
    });

    // Edit batch modal dropdown
    const editSelect = document.getElementById('editWave');
    if (editSelect) {
        const currentVal = editSelect.value;
        editSelect.innerHTML = '<option value="">-- Wave wählen --</option>';
        names.forEach(n => {
            editSelect.innerHTML += `<option value="${n}">${n}</option>`;
        });
        if (currentVal) editSelect.value = currentVal;
    }
}

// Helper: parse date string to local midnight (avoids UTC vs local timezone issues)
function parseLocalDate(str) {
    if (!str) return null;
    const parts = str.substring(0, 10).split('-');
    return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
}

// --- Gantt Chart ---
function renderGantt(waves, batches) {
    const container = document.getElementById('ganttContainer');
    if (waves.length === 0) {
        container.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-calendar-alt fa-2x mb-2"></i><br>Noch keine Wellenplanung vorhanden.<br><button class="btn btn-sm btn-outline-primary mt-2" onclick="openWavePlanModal()"><i class="fas fa-plus"></i> Erste Welle planen</button></div>';
        return;
    }

    // Find date range across all waves
    const allDates = [];
    waves.forEach(w => {
        ['qual_load_start','qual_load_end','qual_link_start','qual_link_end',
         'prod_load_start','prod_load_end','prod_link_start','prod_link_end'].forEach(f => {
            if (w[f]) allDates.push(parseLocalDate(w[f]));
        });
    });
    if (allDates.length === 0) {
        container.innerHTML = '<div class="text-center text-muted py-3">Keine Zeiträume definiert.</div>';
        return;
    }

    let minDate = new Date(Math.min(...allDates));
    let maxDate = new Date(Math.max(...allDates));
    // Add padding: start of minDate's month, end of maxDate's month + 1
    minDate = new Date(minDate.getFullYear(), minDate.getMonth(), 1);
    maxDate = new Date(maxDate.getFullYear(), maxDate.getMonth() + 2, 0);
    const totalDays = Math.ceil((maxDate - minDate) / 86400000);
    const today = new Date();
    today.setHours(0,0,0,0);

    // Build month headers
    const months = [];
    let d = new Date(minDate);
    while (d <= maxDate) {
        const monthStart = new Date(d);
        const monthEnd = new Date(d.getFullYear(), d.getMonth() + 1, 0);
        const daysInView = Math.min(Math.ceil((monthEnd - minDate) / 86400000) + 1, totalDays) - Math.max(0, Math.ceil((monthStart - minDate) / 86400000));
        months.push({
            label: monthStart.toLocaleDateString('de-DE', { month: 'short', year: '2-digit' }),
            days: Math.max(daysInView, 1)
        });
        d = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    }

    const waveTasks = [
        { key: 'qual_load', label: 'Qual Load', env: 'qual' },
        { key: 'qual_link', label: 'Qual Link', env: 'qual' },
        { key: 'prod_load', label: 'Prod Load', env: 'prod' },
        { key: 'prod_link', label: 'Prod Link', env: 'prod' },
    ];

    let html = '<table class="gantt-table"><thead><tr><th style="min-width:160px;">Aufgabe</th>';
    months.forEach(m => { html += `<th colspan="${m.days}" class="gantt-month-header">${m.label}</th>`; });
    html += '</tr></thead><tbody>';

    // Helper: render a bar row
    function renderBarRow(label, startStr, endStr, status, cssClass) {
        let row = `<tr class="task-row"><td>${label}</td>`;
        if (startStr && endStr) {
            const barStart = parseLocalDate(startStr);
            const barEnd = parseLocalDate(endStr);
            const offsetDays = Math.max(0, Math.round((barStart - minDate) / 86400000));
            const barDays = Math.max(1, Math.round((barEnd - barStart) / 86400000) + 1);
            const titleText = `${formatDateShort(startStr)} - ${formatDateShort(endStr)} (${status})`;
            for (let i = 0; i < totalDays; i++) {
                const cellDate = new Date(minDate.getTime() + i * 86400000);
                const isToday = cellDate.getTime() === today.getTime();
                const inBar = i >= offsetDays && i < offsetDays + barDays;
                row += `<td class="gantt-day-cell ${isToday ? 'gantt-today' : ''}">`;
                if (inBar) {
                    const isFirst = (i === offsetDays);
                    const isLast  = (i === offsetDays + barDays - 1);
                    const segCls  = `gantt-seg ${cssClass}${isFirst ? ' gantt-seg-first' : ''}${isLast ? ' gantt-seg-last' : ''}`;
                    row += `<div class="${segCls}" title="${titleText}"></div>`;
                }
                row += '</td>';
            }
        } else {
            row += `<td colspan="${totalDays}" class="text-muted" style="font-size:0.75rem">Nicht geplant</td>`;
        }
        row += '</tr>';
        return row;
    }

    waves.forEach(w => {
        // Wave header row
        html += `<tr class="gantt-row-wave"><td colspan="${totalDays + 1}"><strong>${w.wave_name}</strong>`;
        html += ` <button class="btn btn-sm btn-link p-0 ml-2" onclick="editWavePlan('${w.wave_name}')" title="Bearbeiten"><i class="fas fa-pen fa-xs"></i></button>`;
        html += ` <button class="btn btn-sm btn-link text-danger p-0 ml-1" onclick="deleteWavePlan(${w.id}, '${w.wave_name}')" title="Löschen"><i class="fas fa-trash fa-xs"></i></button>`;
        html += `</td></tr>`;

        const waveBatches = (batches || []).filter(b => b.wave === w.wave_name);

        // Render each wave task row, then its assigned batches directly underneath
        waveTasks.forEach(t => {
            const startStr = w[t.key + '_start'];
            const endStr = w[t.key + '_end'];
            const status = w[t.key + '_status'] || 'vorbereitung';
            // Calculate duration in days for the wave task
            let durationInfo = '';
            if (startStr && endStr) {
                const dDays = Math.round((parseLocalDate(endStr) - parseLocalDate(startStr)) / 86400000) + 1;
                durationInfo = ` <span class="text-muted" style="font-size:0.7rem;">(${dDays} Tage)</span>`;
            }
            const label = `<span class="task-env ${t.env}">${t.env.toUpperCase()}</span> ${t.label.split(' ')[1]}${durationInfo}`;
            html += renderBarRow(label, startStr, endStr, getStatusText(status), 'wave-' + t.env + ' status-' + status);

            // Batches assigned to this task
            const taskKey = 'task_' + t.key; // e.g. task_qual_load
            const assigned = waveBatches.filter(b => b[taskKey]);
            assigned.forEach(b => {
                const batchLabel = b.description || b.batch_id;
                // Per-task start and duration from batch
                const bStart = b[taskKey + '_start'];
                const bDur   = b[taskKey + '_dur'];
                const phase = b.migration_phase || 'upload';
                const bStatus = b.status || 'prepared';
                let batchCss = 'batch-prepared';
                if (bStatus === 'completed') batchCss = 'batch-completed';
                else if (bStatus === 'executing') batchCss = 'batch-executing';
                else if (phase === 'linking') batchCss = 'batch-linking';
                const durText = bDur > 0 ? `${bDur} Tage` : '';
                const statusText = `${b.total_records || 0} Dok.${durText ? ' | ' + durText : ''}`;
                const rowLabel = `<span style="padding-left:24px;font-size:0.78rem;"><i class="fas fa-box fa-xs text-muted"></i> ${batchLabel}</span>`
                    + ` <span class="text-muted" style="font-size:0.7rem;">(${statusText})</span>`
                    + ` <button class="btn btn-sm btn-link p-0 ml-1 text-muted" onclick="event.stopPropagation(); editBatch('${b.batch_id}')" title="Bearbeiten"><i class="fas fa-pen fa-xs"></i></button>`;
                if (bStart && bDur > 0) {
                    const barEnd = addDays(bStart, bDur - 1);
                    html += renderBarRow(rowLabel, bStart, barEnd, statusText, batchCss);
                } else if (startStr && endStr) {
                    // Fallback: use wave task range
                    html += renderBarRow(rowLabel, startStr, endStr, statusText, batchCss);
                } else {
                    html += `<tr class="gantt-row-batch"><td>${rowLabel}</td>`;
                    html += `<td colspan="${totalDays}" class="text-muted" style="font-size:0.75rem">Zeitraum nicht definiert</td></tr>`;
                }
            });
        });

        // Batches without any task assignment
        const unassigned = waveBatches.filter(b => !b.task_qual_load && !b.task_qual_link && !b.task_prod_load && !b.task_prod_link);
        unassigned.forEach(b => {
            const batchLabel = b.description || b.batch_id;
            const statusText = `${b.total_records || 0} Dok.`;
            const rowLabel = `<span style="padding-left:24px;font-size:0.78rem;"><i class="fas fa-box fa-xs text-muted"></i> ${batchLabel}</span>`
                + ` <span class="text-muted" style="font-size:0.7rem;">(${statusText})</span>`
                + ` <button class="btn btn-sm btn-link p-0 ml-1 text-muted" onclick="event.stopPropagation(); editBatch('${b.batch_id}')" title="Bearbeiten"><i class="fas fa-pen fa-xs"></i></button>`;
            html += `<tr class="gantt-row-batch"><td>${rowLabel}</td>`;
            html += `<td colspan="${totalDays}" class="text-muted" style="font-size:0.75rem">Keine Aufgabe zugeordnet</td></tr>`;
        });
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}

function addDays(dateStr, days) {
    const parts = dateStr.substring(0, 10).split('-');
    const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    d.setDate(d.getDate() + days);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

// --- Task List ---
function renderTaskList(waves) {
    const tbody = document.getElementById('taskListBody');
    if (waves.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">Keine Wellenplanung vorhanden</td></tr>';
        return;
    }

    const tasks = [
        { key: 'qual_load', label: 'Load', env: 'Qual', icon: 'fa-upload' },
        { key: 'qual_link', label: 'Verlinkung', env: 'Qual', icon: 'fa-link' },
        { key: 'prod_load', label: 'Load', env: 'Prod', icon: 'fa-upload' },
        { key: 'prod_link', label: 'Verlinkung', env: 'Prod', icon: 'fa-link' },
    ];

    let html = '';
    waves.forEach(w => {
        tasks.forEach(t => {
            const status = w[t.key + '_status'] || 'vorbereitung';
            const startStr = w[t.key + '_start'];
            const endStr = w[t.key + '_end'];
            const envClass = t.env === 'Qual' ? 'qual' : 'prod';
            const dateRange = (startStr && endStr)
                ? `${formatDateShort(startStr)} → ${formatDateShort(endStr)}`
                : '<span class="text-muted">-</span>';

            html += `
                <tr class="task-row">
                    <td>
                        <strong>${w.wave_name}</strong><br>
                        <span class="task-env ${envClass}">${t.env}</span>
                        <i class="fas ${t.icon} fa-xs"></i> ${t.label}
                    </td>
                    <td class="date-range">${dateRange}</td>
                    <td>
                        <div class="d-flex align-items-center">
                            <span class="badge ${getStatusClass(status)} status-badge mr-1" 
                                onclick="cycleTaskStatus(${w.id}, '${t.key}_status', '${getPrevStatus(status)}')" 
                                title="Klick: ← ${getStatusText(getPrevStatus(status))}">
                                <i class="fas fa-chevron-left fa-xs"></i></span>
                            <span class="badge ${getStatusClass(status)} px-2">${getStatusText(status)}</span>
                            <span class="badge ${getStatusClass(status)} status-badge ml-1" 
                                onclick="cycleTaskStatus(${w.id}, '${t.key}_status', '${getNextStatus(status)}')" 
                                title="Klick: → ${getStatusText(getNextStatus(status))}">
                                <i class="fas fa-chevron-right fa-xs"></i></span>
                            <button class="btn btn-sm btn-link p-0 ml-2 text-muted" onclick="editWavePlan('${w.wave_name}')" title="Welle bearbeiten">
                                <i class="fas fa-pen fa-xs"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        });
    });
    tbody.innerHTML = html;
}

function getStatusClass(status) {
    return { 'vorbereitung': 'badge-secondary', 'arbeit': 'badge-primary', 'fertig': 'badge-success' }[status] || 'badge-secondary';
}

function getNextStatus(status) {
    return { 'vorbereitung': 'arbeit', 'arbeit': 'fertig', 'fertig': 'fertig' }[status] || 'vorbereitung';
}

function getPrevStatus(status) {
    return { 'vorbereitung': 'vorbereitung', 'arbeit': 'vorbereitung', 'fertig': 'arbeit' }[status] || 'vorbereitung';
}

function getStatusText(status) {
    return { 'vorbereitung': 'In Vorbereitung', 'arbeit': 'In Arbeit', 'fertig': 'Fertig' }[status] || status;
}

function cycleTaskStatus(waveId, taskField, newStatus) {
    fetch('/wave-plans/task-status', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wave_id: waveId, task_field: taskField, status: newStatus })
    })
    .then(r => r.json())
    .then(data => { if (data.success) loadWavePlans(); else alert('Fehler: ' + data.error); })
    .catch(err => alert('Fehler: ' + err));
}

function formatDateShort(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.substring(0, 10).split('-');
    return `${parts[2]}.${parts[1]}`;
}

// --- Wave Plan Modal ---
function openWavePlanModal(waveName) {
    let modal = document.getElementById('wavePlanModal');
    if (!modal) {
        document.body.insertAdjacentHTML('beforeend', `
        <div class="modal fade" id="wavePlanModal" tabindex="-1">
            <div class="modal-dialog modal-lg"><div class="modal-content">
                <div class="modal-header bg-dark text-white py-2">
                    <h5 class="modal-title"><i class="fas fa-calendar-alt"></i> Welle planen</h5>
                    <button type="button" class="close text-white" data-dismiss="modal"><span>&times;</span></button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label><strong>Wellenname</strong></label>
                        <select class="form-control" id="wpWaveName">
                            <option value="">-- Welle w&auml;hlen --</option>
                            <option value="Wave 0">Wave 0</option>
                            <option value="Wave 1">Wave 1</option>
                            <option value="Wave 2">Wave 2</option>
                            <option value="Wave 3">Wave 3</option>
                            <option value="Wave 4">Wave 4</option>
                            <option value="Wave 5">Wave 5</option>
                            <option value="Wave 6">Wave 6</option>
                            <option value="Wave 7">Wave 7</option>
                        </select>
                    </div>
                    <table class="table table-sm mb-0">
                        <thead><tr><th>Aufgabe</th><th>Start</th><th style="width:90px">Dauer</th><th style="width:110px">Ende</th><th>Status</th></tr></thead>
                        <tbody>
                            <tr>
                                <td><span class="task-env qual">QUAL</span> Load</td>
                                <td><input type="date" class="form-control form-control-sm wp-start" id="wpQualLoadStart" data-task="QualLoad"></td>
                                <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm wp-dur" id="wpQualLoadDur" data-task="QualLoad"><div class="input-group-append"><span class="input-group-text" style="font-size:0.75rem">T</span></div></div></td>
                                <td><span class="text-muted wp-end-label" id="wpQualLoadEndLabel" style="font-size:0.8rem">–</span></td>
                                <td><select class="form-control form-control-sm" id="wpQualLoadStatus">
                                    <option value="vorbereitung">Vorbereitung</option>
                                    <option value="arbeit">In Arbeit</option>
                                    <option value="fertig">Fertig</option>
                                </select></td>
                            </tr>
                            <tr>
                                <td><span class="task-env qual">QUAL</span> Verlinkung</td>
                                <td><input type="date" class="form-control form-control-sm wp-start" id="wpQualLinkStart" data-task="QualLink"></td>
                                <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm wp-dur" id="wpQualLinkDur" data-task="QualLink"><div class="input-group-append"><span class="input-group-text" style="font-size:0.75rem">T</span></div></div></td>
                                <td><span class="text-muted wp-end-label" id="wpQualLinkEndLabel" style="font-size:0.8rem">–</span></td>
                                <td><select class="form-control form-control-sm" id="wpQualLinkStatus">
                                    <option value="vorbereitung">Vorbereitung</option>
                                    <option value="arbeit">In Arbeit</option>
                                    <option value="fertig">Fertig</option>
                                </select></td>
                            </tr>
                            <tr>
                                <td><span class="task-env prod">PROD</span> Load</td>
                                <td><input type="date" class="form-control form-control-sm wp-start" id="wpProdLoadStart" data-task="ProdLoad"></td>
                                <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm wp-dur" id="wpProdLoadDur" data-task="ProdLoad"><div class="input-group-append"><span class="input-group-text" style="font-size:0.75rem">T</span></div></div></td>
                                <td><span class="text-muted wp-end-label" id="wpProdLoadEndLabel" style="font-size:0.8rem">–</span></td>
                                <td><select class="form-control form-control-sm" id="wpProdLoadStatus">
                                    <option value="vorbereitung">Vorbereitung</option>
                                    <option value="arbeit">In Arbeit</option>
                                    <option value="fertig">Fertig</option>
                                </select></td>
                            </tr>
                            <tr>
                                <td><span class="task-env prod">PROD</span> Verlinkung</td>
                                <td><input type="date" class="form-control form-control-sm wp-start" id="wpProdLinkStart" data-task="ProdLink"></td>
                                <td><div class="input-group input-group-sm"><input type="number" min="1" class="form-control form-control-sm wp-dur" id="wpProdLinkDur" data-task="ProdLink"><div class="input-group-append"><span class="input-group-text" style="font-size:0.75rem">T</span></div></div></td>
                                <td><span class="text-muted wp-end-label" id="wpProdLinkEndLabel" style="font-size:0.8rem">–</span></td>
                                <td><select class="form-control form-control-sm" id="wpProdLinkStatus">
                                    <option value="vorbereitung">Vorbereitung</option>
                                    <option value="arbeit">In Arbeit</option>
                                    <option value="fertig">Fertig</option>
                                </select></td>
                            </tr>
                        </tbody>
                    </table>
                    <small class="text-muted">T = Kalendertage. Ende = Start + Dauer − 1.</small>
                    <div class="form-group">
                        <label>Notizen</label>
                        <textarea class="form-control" id="wpNotes" rows="2"></textarea>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" data-dismiss="modal">Abbrechen</button>
                    <button class="btn btn-primary" onclick="saveWavePlan()"><i class="fas fa-save"></i> Speichern</button>
                </div>
            </div></div>
        </div>`);
        modal = document.getElementById('wavePlanModal');
        // Attach live-update listeners for start + duration → end label
        modal.querySelectorAll('.wp-start, .wp-dur').forEach(el => {
            el.addEventListener('input', () => {
                const task = el.dataset.task;
                wpUpdateEndLabel(task);
            });
        });
    }

    // Helper: compute and display end date from start + duration
    function wpUpdateEndLabel(task) {
        const startVal = document.getElementById('wp' + task + 'Start').value;
        const durVal   = parseInt(document.getElementById('wp' + task + 'Dur').value);
        const label    = document.getElementById('wp' + task + 'EndLabel');
        if (startVal && durVal > 0) {
            const endStr = addDays(startVal, durVal - 1);
            const parts = endStr.split('-');
            label.textContent = parts[2] + '.' + parts[1] + '.' + parts[0];
        } else {
            label.textContent = '–';
        }
    }

    // Helper: calculate duration days from start/end strings
    function wpCalcDur(startStr, endStr) {
        if (!startStr || !endStr) return '';
        return Math.round((parseLocalDate(endStr) - parseLocalDate(startStr)) / 86400000) + 1;
    }

    // Reset or fill
    if (waveName) {
        const w = wavePlans.find(x => x.wave_name === waveName);
        if (w) {
            document.getElementById('wpWaveName').value = w.wave_name;
            document.getElementById('wpQualLoadStart').value = w.qual_load_start || '';
            document.getElementById('wpQualLoadDur').value = wpCalcDur(w.qual_load_start, w.qual_load_end);
            document.getElementById('wpQualLoadStatus').value = w.qual_load_status;
            document.getElementById('wpQualLinkStart').value = w.qual_link_start || '';
            document.getElementById('wpQualLinkDur').value = wpCalcDur(w.qual_link_start, w.qual_link_end);
            document.getElementById('wpQualLinkStatus').value = w.qual_link_status;
            document.getElementById('wpProdLoadStart').value = w.prod_load_start || '';
            document.getElementById('wpProdLoadDur').value = wpCalcDur(w.prod_load_start, w.prod_load_end);
            document.getElementById('wpProdLoadStatus').value = w.prod_load_status;
            document.getElementById('wpProdLinkStart').value = w.prod_link_start || '';
            document.getElementById('wpProdLinkDur').value = wpCalcDur(w.prod_link_start, w.prod_link_end);
            document.getElementById('wpProdLinkStatus').value = w.prod_link_status;
            document.getElementById('wpNotes').value = w.notes || '';
            // Update end labels
            ['QualLoad','QualLink','ProdLoad','ProdLink'].forEach(t => wpUpdateEndLabel(t));
        }
    } else {
        document.getElementById('wpWaveName').value = '';
        ['wpQualLoadStart','wpQualLinkStart','wpProdLoadStart','wpProdLinkStart','wpNotes'].forEach(id => {
            document.getElementById(id).value = '';
        });
        ['wpQualLoadDur','wpQualLinkDur','wpProdLoadDur','wpProdLinkDur'].forEach(id => {
            document.getElementById(id).value = '';
        });
        ['wpQualLoadStatus','wpQualLinkStatus','wpProdLoadStatus','wpProdLinkStatus'].forEach(id => {
            document.getElementById(id).value = 'vorbereitung';
        });
        ['QualLoad','QualLink','ProdLoad','ProdLink'].forEach(t => wpUpdateEndLabel(t));
    }
    $(modal).modal('show');
}

function editWavePlan(waveName) {
    openWavePlanModal(waveName);
}

function saveWavePlan() {
    const waveName = document.getElementById('wpWaveName').value;
    if (!waveName) { alert('Bitte Welle auswählen'); return; }

    // Helper: compute end date from start + duration (days)
    function wpEndDate(taskPrefix) {
        const s = document.getElementById('wp' + taskPrefix + 'Start').value;
        const d = parseInt(document.getElementById('wp' + taskPrefix + 'Dur').value);
        if (s && d > 0) return addDays(s, d - 1);
        return null;
    }

    fetch('/wave-plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            wave_name: waveName,
            qual_load_start: document.getElementById('wpQualLoadStart').value || null,
            qual_load_end: wpEndDate('QualLoad'),
            qual_load_status: document.getElementById('wpQualLoadStatus').value,
            qual_link_start: document.getElementById('wpQualLinkStart').value || null,
            qual_link_end: wpEndDate('QualLink'),
            qual_link_status: document.getElementById('wpQualLinkStatus').value,
            prod_load_start: document.getElementById('wpProdLoadStart').value || null,
            prod_load_end: wpEndDate('ProdLoad'),
            prod_load_status: document.getElementById('wpProdLoadStatus').value,
            prod_link_start: document.getElementById('wpProdLinkStart').value || null,
            prod_link_end: wpEndDate('ProdLink'),
            prod_link_status: document.getElementById('wpProdLinkStatus').value,
            notes: document.getElementById('wpNotes').value,
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) { $('#wavePlanModal').modal('hide'); loadWavePlans(); }
        else alert('Fehler: ' + data.error);
    })
    .catch(err => alert('Fehler: ' + err));
}

function deleteWavePlan(waveId, waveName) {
    if (!confirm('Wellenplanung "' + waveName + '" löschen?')) return;
    fetch('/wave-plans/' + waveId, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => { if (data.success) loadWavePlans(); else alert('Fehler: ' + data.error); })
        .catch(err => alert('Fehler: ' + err));
}
