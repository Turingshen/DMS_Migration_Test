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
        .catch(err => console.error('Batches load error:', err));
}

function populateWaveFilter(batches) {
    const select = document.getElementById('waveFilter');
    const prevVal = select.value;
    const waveNames = new Set();
    batches.forEach(b => { if (b.wave) waveNames.add(b.wave); });
    // Also add waves from wave plans
    wavePlans.forEach(w => waveNames.add(w.wave_name));

    const sorted = [...waveNames].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    select.innerHTML = '<option value="">' + t('dash.all_waves') + '</option>';
    sorted.forEach(w => { select.innerHTML += `<option value="${w}">${w}</option>`; });
    select.value = prevVal || '';
}

function applyWaveFilter() {
    selectedWave = document.getElementById('waveFilter').value;
    const filtered = selectedWave ? allBatches.filter(b => b.wave === selectedWave) : allBatches;
    const filteredPlans = selectedWave ? wavePlans.filter(w => w.wave_name === selectedWave) : wavePlans;

    renderKPIs(filtered);
    renderWaveOverview(filtered, filteredPlans);
    displayBatches(filtered);

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
    let totalDocs = 0, failed = 0;
    const waves = new Set();

    batches.forEach(b => {
        if (b.wave) waves.add(b.wave);
        totalDocs += (b.total_records || 0);
        failed += (b.failed_records || 0) + (b.link_failed || 0);
    });

    document.getElementById('kpiWaves').textContent = waves.size;
    document.getElementById('kpiBatches').textContent = batches.length;
    document.getElementById('kpiDocs').textContent = totalDocs.toLocaleString();
    document.getElementById('kpiFailed').textContent = failed.toLocaleString();
}

// ========================================================================
// Wave Overview (slim, no dates/timeline)
// ========================================================================
function renderWaveOverview(batches, plans) {
    // Group batches by wave
    const waves = {};
    batches.forEach(b => {
        const wave = b.wave || t('kanban.unassigned');
        if (!waves[wave]) waves[wave] = [];
        waves[wave].push(b);
    });

    // Include planned waves that have no batches yet
    (plans || []).forEach(p => {
        if (p.wave_name && !waves[p.wave_name]) waves[p.wave_name] = [];
    });

    const sortedWaves = Object.keys(waves).sort((a, b) => {
        if (a === t('kanban.unassigned')) return 1;
        if (b === t('kanban.unassigned')) return -1;
        return a.localeCompare(b, undefined, { numeric: true });
    });

    const board = document.getElementById('waveOverview');
    if (sortedWaves.length === 0) {
        board.innerHTML = '<div class="text-center py-4 text-muted">' + t('kanban.no_batches') + '</div>';
        return;
    }

    board.innerHTML = sortedWaves.map(waveName => {
        const wb = waves[waveName];
        const isUnassigned = waveName === t('kanban.unassigned');
        const isPlanned = (plans || []).some(p => p.wave_name === waveName);
        let wTotal = 0, wUploaded = 0, wLinked = 0, wFailed = 0, wLinkTotal = 0;
        wb.forEach(b => {
            wTotal += (b.total_records || 0);
            wUploaded += (b.successful_records || 0);
            wLinked += (b.link_linked || 0) + (b.link_exists || 0);
            wFailed += (b.failed_records || 0) + (b.link_failed || 0);
            wLinkTotal += (b.link_total || 0);
        });
        const wPct = wTotal > 0 ? Math.round(wUploaded / wTotal * 100) : 0;
        const lPct = wLinkTotal > 0 ? Math.round(wLinked / wLinkTotal * 100) : 0;

        const editBtn = (isPlanned && !isUnassigned)
            ? `<button class="btn btn-sm btn-link text-white p-0 ml-2" onclick="editWavePlan('${waveName}')" title="${t('batch_action.edit')}"><i class="fas fa-pen"></i></button>`
            : '';

        const batchCards = wb.length > 0
            ? `<div class="row">${wb.map(b => `<div class="col-md-4 col-lg-3 mb-2">${renderBatchCard(b, {showEditButton: true})}</div>`).join('')}</div>`
            : `<div class="text-center text-muted py-2 small"><i class="fas fa-inbox"></i> ${t('dash.wave_empty')}</div>`;

        return `
            <div class="card mb-2 shadow-sm">
                <div class="wave-header ${isUnassigned ? 'bg-warning text-dark' : 'bg-dark text-white'} d-flex justify-content-between align-items-center px-3 py-2">
                    <span><i class="fas fa-layer-group"></i> ${waveName} ${editBtn}</span>
                    <span class="badge badge-light">${wb.length} Batches</span>
                </div>
                <div class="card-body p-2">
                    <div class="row mb-2">
                        <div class="col-md-6">
                            <div class="d-flex justify-content-between wave-stats"><span><i class="fas fa-upload"></i> Upload</span><span>${wPct}% (${wUploaded}/${wTotal})</span></div>
                            <div class="progress" style="height: 8px;"><div class="progress-bar bg-success" style="width: ${wPct}%"></div></div>
                        </div>
                        <div class="col-md-6">
                            <div class="d-flex justify-content-between wave-stats"><span><i class="fas fa-link"></i> ${t('kanban.linked')}</span><span>${lPct}% (${wLinked}/${wLinkTotal})${wFailed > 0 ? ' | <span class="text-danger">' + wFailed + ' ' + t('kanban.errors') + '</span>' : ''}</span></div>
                            <div class="progress" style="height: 8px;"><div class="progress-bar bg-info" style="width: ${lPct}%"></div></div>
                        </div>
                    </div>
                    ${batchCards}
                </div>
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
        tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted">' + t('kanban.no_batches_table') + '</td></tr>';
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
        'upload': '<span class="badge badge-primary"><i class="fas fa-upload"></i> ' + t('phase_badge.upload') + '</span>',
        'upload_done': '<span class="badge badge-success"><i class="fas fa-check"></i> ' + t('phase_badge.upload_done') + '</span>',
        'linking': '<span class="badge badge-info"><i class="fas fa-link fa-spin"></i> ' + t('phase_badge.linking') + '</span>',
        'completed': '<span class="badge badge-success"><i class="fas fa-check-double"></i> ' + t('phase_badge.completed') + '</span>',
        'link_cancelled': '<span class="badge badge-secondary"><i class="fas fa-stop"></i> ' + t('phase_badge.cancelled') + '</span>',
        'link_error': '<span class="badge badge-danger"><i class="fas fa-exclamation"></i> ' + t('phase_badge.error') + '</span>'
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

    return `<div title="${t('kanban.linked')}: ${linked} | ${t('kanban.errors')}: ${failed} | ${t('kanban.total')}: ${total}">
        <div class="progress" style="height: 16px; min-width: 60px;">
            <div class="progress-bar ${color}" style="width: ${pct}%">${linked}/${total}</div>
        </div>
    </div>`;
}

function getActionButtons(batch) {
    let buttons = [];
    buttons.push(`<a href="/preview?batch_id=${batch.batch_id}" class="btn btn-sm btn-primary" title="${t('batch_action.preview')}"><i class="fas fa-eye"></i> ${t('batch_action.preview')}</a>`);

    if (batch.status === 'completed' || batch.status === 'completed_with_errors' || batch.executed_records > 0) {
        buttons.push(`<a href="/batch/${batch.batch_id}/validation" class="btn btn-sm btn-info" title="${t('batch_action.results')}"><i class="fas fa-check-double"></i> ${t('batch_action.results')}</a>`);
    }

    buttons.push(`<button onclick="editBatch('${batch.batch_id}')" class="btn btn-sm btn-outline-primary" title="${t('batch_action.edit')}"><i class="fas fa-edit"></i></button>`);

    if (batch.status !== 'executing') {
        buttons.push(`<button onclick="deleteBatch('${batch.batch_id}')" class="btn btn-sm btn-outline-danger" title="${t('batch_action.delete')}"><i class="fas fa-trash"></i></button>`);
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
                    <h5 class="modal-title"><i class="fas fa-edit"></i> ${t('edit_batch.title')}</h5>
                    <button type="button" class="close text-white" data-dismiss="modal"><span>&times;</span></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" id="editBatchId">
                    <div class="form-group">
                        <label for="editWave">${t('edit_batch.wave')}</label>
                        <select class="form-control" id="editWave">
                            <option value="">${t('edit_batch.choose_wave')}</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>${t('edit_batch.description')}</label>
                        <input type="text" class="form-control" id="editDescription" maxlength="40">
                        <small class="form-text text-muted"><span id="descCharCount">0</span>/40</small>
                    </div>
                    <div class="form-group">
                        <label>${t('edit_batch.notes')}</label>
                        <textarea class="form-control" id="editNotes" rows="3"></textarea>
                    </div>
                    <div class="form-group">
                        <label><strong>${t('edit_batch.task_assignment')}</strong></label>
                        <table class="table table-sm table-borderless mb-0">
                            <thead><tr><th style="width:30px"></th><th>${t('edit_batch.task')}</th><th>${t('edit_batch.start')}</th><th style="width:80px">${t('edit_batch.duration')}</th><th style="width:90px">${t('edit_batch.end')}</th></tr></thead>
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
                        <small class="text-muted">${t('edit_batch.days_hint')}</small>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-danger mr-auto" onclick="deleteBatchFromModal()"><i class="fas fa-trash"></i> ${t('delete')}</button>
                    <button class="btn btn-secondary" data-dismiss="modal">${t('cancel')}</button>
                    <button class="btn btn-primary" onclick="saveBatch()"><i class="fas fa-save"></i> ${t('save')}</button>
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
        else alert(t('error_prefix') + data.error);
    })
    .catch(err => alert(t('error_prefix') + err));
}

function deleteBatch(batchId) {
    if (!confirm(t('edit_batch.delete_confirm', {id: batchId}))) return;

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
            else { alert(t('error_prefix') + data.error); btn.disabled = false; btn.innerHTML = orig; if (row) row.style.opacity = '1'; }
        })
        .catch(err => { alert(t('error_prefix') + err); btn.disabled = false; btn.innerHTML = orig; if (row) row.style.opacity = '1'; });
}

function deleteBatchFromModal() {
    const batchId = document.getElementById('editBatchId').value;
    if (!batchId) return;
    if (!confirm(t('edit_batch.delete_confirm', {id: batchId}))) return;

    fetch('/batch/' + batchId, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
            if (data.success) { $('#editBatchModal').modal('hide'); loadAll(); }
            else { alert(t('error_prefix') + data.error); }
        })
        .catch(err => { alert(t('error_prefix') + err); });
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
        editSelect.innerHTML = `<option value="">${t('edit_batch.choose_wave')}</option>`;
        names.forEach(n => {
            editSelect.innerHTML += `<option value="${n}">${n}</option>`;
        });
        if (currentVal) editSelect.value = currentVal;
    }
}

// Helper: add days to a date string (used by batch task end-date label)
function addDays(dateStr, days) {
    const parts = dateStr.substring(0, 10).split('-');
    const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    d.setDate(d.getDate() + days);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

// --- Wave Plan Modal ---
function openWavePlanModal(waveName) {
    let modal = document.getElementById('wavePlanModal');
    if (!modal) {
        document.body.insertAdjacentHTML('beforeend', `
        <div class="modal fade" id="wavePlanModal" tabindex="-1">
            <div class="modal-dialog"><div class="modal-content">
                <div class="modal-header bg-dark text-white py-2">
                    <h5 class="modal-title"><i class="fas fa-layer-group"></i> ${t('wave_plan.title')}</h5>
                    <button type="button" class="close text-white" data-dismiss="modal"><span>&times;</span></button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label><strong>${t('wave_plan.name')}</strong></label>
                        <select class="form-control" id="wpWaveName">
                            <option value="">${t('wave_plan.choose')}</option>
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
                    <div class="form-group">
                        <label>${t('wave_plan.notes')}</label>
                        <textarea class="form-control" id="wpNotes" rows="3"></textarea>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" data-dismiss="modal">${t('cancel')}</button>
                    <button class="btn btn-primary" onclick="saveWavePlan()"><i class="fas fa-save"></i> ${t('save')}</button>
                </div>
            </div></div>
        </div>`);
        modal = document.getElementById('wavePlanModal');
    }

    // Reset or fill
    if (waveName) {
        const w = wavePlans.find(x => x.wave_name === waveName);
        if (w) {
            document.getElementById('wpWaveName').value = w.wave_name;
            document.getElementById('wpNotes').value = w.notes || '';
        }
    } else {
        document.getElementById('wpWaveName').value = '';
        document.getElementById('wpNotes').value = '';
    }
    $(modal).modal('show');
}

function editWavePlan(waveName) {
    openWavePlanModal(waveName);
}

function saveWavePlan() {
    const waveName = document.getElementById('wpWaveName').value;
    if (!waveName) { alert(t('wave_plan.choose_alert')); return; }

    fetch('/wave-plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            wave_name: waveName,
            notes: document.getElementById('wpNotes').value,
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) { $('#wavePlanModal').modal('hide'); loadWavePlans(); }
        else alert(t('error_prefix') + data.error);
    })
    .catch(err => alert(t('error_prefix') + err));
}

function deleteWavePlan(waveId, waveName) {
    if (!confirm(t('wave_plan.delete_confirm', {name: waveName}))) return;
    fetch('/wave-plans/' + waveId, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => { if (data.success) loadWavePlans(); else alert(t('error_prefix') + data.error); })
        .catch(err => alert(t('error_prefix') + err));
}
