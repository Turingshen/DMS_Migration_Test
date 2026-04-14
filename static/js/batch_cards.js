/**
 * batch_cards.js — Shared batch card and Kanban rendering
 * Used by index.html and wave_overview.html
 */

/**
 * CSS class for migration phase
 */
function getPhaseClass(phase) {
    const map = {
        'prepared': 'phase-prepared',
        'upload': 'phase-upload',
        'upload_done': 'phase-upload_done',
        'linking': 'phase-linking',
        'completed': 'phase-completed',
        'link_cancelled': 'phase-error',
        'link_error': 'phase-error'
    };
    return map[phase] || 'phase-prepared';
}

/**
 * Phase progress bar states: [Prepare, Upload, Linking]
 */
function getPhaseSteps(phase, status) {
    switch (phase) {
        case 'completed': return ['done', 'done', 'done'];
        case 'linking': return ['done', 'done', 'active'];
        case 'upload_done': return ['done', 'done', 'pending'];
        case 'upload': return ['done', 'active', 'pending'];
        case 'link_cancelled':
        case 'link_error': return ['done', 'done', 'error'];
        default:
            if (status === 'executing') return ['done', 'active', 'pending'];
            if (status === 'completed' || status === 'completed_with_errors') return ['done', 'done', 'pending'];
            return ['done', 'pending', 'pending'];
    }
}

/**
 * Bootstrap badge class for batch status
 */
function getStatusBadgeClass(status) {
    const map = {
        'prepared': 'badge-secondary',
        'executing': 'badge-warning',
        'completed': 'badge-success',
        'completed_with_errors': 'badge-warning',
        'failed': 'badge-danger',
        'linking': 'badge-info',
        'link_completed': 'badge-success',
        'link_completed_partial': 'badge-warning',
        'link_completed_with_errors': 'badge-warning',
        'link_cancelled': 'badge-secondary',
        'link_error': 'badge-danger'
    };
    return map[status] || 'badge-secondary';
}

/**
 * German label for batch status (supports i18n)
 */
function getStatusLabel(status) {
    // Use i18n if available
    if (typeof t === 'function') {
        const key = 'status.' + status;
        const translated = t(key);
        if (translated !== key) return translated;
    }
    const map = {
        'prepared': 'Vorbereitet',
        'executing': 'Upload...',
        'completed': 'Hochgeladen',
        'completed_with_errors': 'Upload (Fehler)',
        'failed': 'Fehlgeschlagen',
        'linking': 'Verlinke...',
        'link_completed': 'Fertig',
        'link_completed_partial': 'Teilw. verlinkt',
        'link_completed_with_errors': 'Verlinkt (Fehler)',
        'link_cancelled': 'Abgebrochen',
        'link_error': 'Link-Fehler'
    };
    return map[status] || status;
}

/**
 * Render a single batch card
 * @param {Object} batch - Batch data object
 * @param {Object} [options] - Rendering options
 * @param {boolean} [options.showEditButton=false] - Show edit pencil button
 */
function renderBatchCard(batch, options) {
    const opts = options || {};
    const phase = batch.migration_phase || 'prepared';
    const phaseClass = getPhaseClass(phase);
    const total = batch.total_records || 0;
    const success = batch.successful_records || 0;
    const failed = batch.failed_records || 0;
    const linkLinked = (batch.link_linked || 0) + (batch.link_exists || 0);
    const linkTotal = batch.link_total || 0;
    const linkFailed = batch.link_failed || 0;
    const linkSkipped = batch.link_skipped || 0;
    const uploadPct = total > 0 ? Math.round(success / total * 100) : 0;
    const linkPct = linkTotal > 0 ? Math.round(linkLinked / linkTotal * 100) : 0;
    const phaseSteps = getPhaseSteps(phase, batch.status);

    const editBtn = opts.showEditButton
        ? `<button class="btn btn-sm btn-link p-0 mr-2 text-muted" onclick="event.stopPropagation(); editBatch('${batch.batch_id}')" title="Batch bearbeiten">
               <i class="fas fa-pen fa-xs"></i>
           </button>`
        : '';

    return `
        <div class="card batch-card ${phaseClass} mb-2" onclick="window.location.href='/preview?batch_id=${batch.batch_id}'">
            <div class="card-body p-2">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong style="font-size: 0.85rem;">${batch.description || batch.batch_id}</strong>
                        <div class="wave-stats">${total} ${typeof t === 'function' ? t('status.documents') : 'Dokumente'}</div>
                    </div>
                    <div class="d-flex align-items-center">
                        ${editBtn}
                        <span class="badge ${getStatusBadgeClass(batch.status)}" style="font-size: 0.7rem;">
                            ${getStatusLabel(batch.status)}
                        </span>
                    </div>
                </div>
                <div class="mt-2">
                    <div class="d-flex justify-content-between wave-stats">
                        <span><i class="fas fa-upload"></i> ${success}/${total}</span>
                        <span>${uploadPct}%</span>
                    </div>
                    <div class="progress" style="height: 5px;">
                        <div class="progress-bar bg-success" style="width: ${uploadPct}%"></div>
                        ${failed > 0 ? `<div class="progress-bar bg-danger" style="width: ${total > 0 ? Math.round(failed / total * 100) : 0}%"></div>` : ''}
                    </div>
                </div>
                ${linkTotal > 0 ? `
                <div class="mt-1">
                    <div class="d-flex justify-content-between wave-stats">
                        <span><i class="fas fa-link"></i> ${linkLinked}/${linkTotal}</span>
                        <span>${linkPct}%${linkFailed > 0 ? ' <span class="text-danger">(' + linkFailed + ' err)</span>' : ''}${linkSkipped > 0 ? ' <span class="text-muted">(' + linkSkipped + ' skip)</span>' : ''}</span>
                    </div>
                    <div class="progress" style="height: 4px;">
                        <div class="progress-bar bg-info" style="width: ${linkPct}%"></div>
                        ${linkFailed > 0 ? `<div class="progress-bar bg-danger" style="width: ${linkTotal > 0 ? Math.round(linkFailed / linkTotal * 100) : 0}%"></div>` : ''}
                    </div>
                </div>
                ` : ''}
                <div class="phase-progress">
                    ${phaseSteps.map(s => `<div class="phase-bar ${s}"></div>`).join('')}
                </div>
            </div>
        </div>
    `;
}
