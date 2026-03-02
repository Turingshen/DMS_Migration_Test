let currentBatchId = null;
let currentPage = 1;
let perPage = 50;
let filterTimeout = null;
let allDocuments = [];
let fileDetailsCache = {};

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    loadBatches();
    loadErrorOverview();
    
    // Check for batch_id in URL
    const urlParams = new URLSearchParams(window.location.search);
    const batchId = urlParams.get('batch_id');
    if (batchId) {
        setTimeout(() => {
            document.getElementById('batchSelect').value = batchId;
            selectBatch(batchId);
        }, 500);
    }
    
    // Check for error_category in URL
    const errCat = urlParams.get('error_category');
    if (errCat) {
        // Auto-open error panel
        const panel = document.getElementById('errorPanelBody');
        if (panel) panel.style.display = 'block';
        const icon = document.getElementById('errorPanelToggle');
        if (icon) icon.className = 'fas fa-chevron-up';
    }
});

// ========================================================================
// Error Overview (cross-batch aggregation)
// ========================================================================
const ERROR_DETAILS = {
    'API_KEY_INVALID': { desc: 'API-Key ungültig', action: 'API im APIM freischalten' },
    'TOKEN_EXPIRED': { desc: 'OAuth Token abgelaufen', action: 'Neu einloggen' },
    'TOKEN_INVALID': { desc: 'OAuth Token ungültig', action: 'Neu einloggen' },
    'CSRF_FAILED': { desc: 'CSRF Token Fehler', action: 'Session erneuern' },
    'SOURCE_NOT_FOUND': { desc: 'Dokument nicht gefunden', action: 'Quelldaten prüfen' },
    'SOURCE_EMPTY': { desc: 'Container ohne Dateien', action: 'Erwartet - leer' },
    'SOURCE_READ_ERROR': { desc: 'Lesefehler im Quellsystem', action: 'R/3 API prüfen' },
    'TARGET_CREATE_FAILED': { desc: 'Anlage fehlgeschlagen', action: 'SAP Log prüfen' },
    'TARGET_EXISTS': { desc: 'Dokument existiert bereits', action: 'Zieldaten prüfen' },
    'TARGET_LOCKED': { desc: 'Dokument gesperrt', action: 'Sperre aufheben' },
    'UPLOAD_SIZE_EXCEEDED': { desc: 'Datei zu groß', action: 'Datei aufteilen' },
    'UPLOAD_TIMEOUT': { desc: 'Upload Timeout', action: 'Später erneut versuchen' },
    'GATEWAY_TIMEOUT': { desc: 'API Gateway Timeout (504)', action: 'Später erneut versuchen' },
    'RATE_LIMITED': { desc: 'API Rate Limit erreicht', action: 'Warten und erneut versuchen' },
    'SERVER_ERROR': { desc: 'SAP Serverfehler (5xx)', action: 'SAP Support kontaktieren' },
    'BAD_REQUEST': { desc: 'Ungültige Anfrage (400)', action: 'Daten validieren' },
    'UNKNOWN': { desc: 'Unbekannter Fehler', action: 'Log prüfen' }
};

function getErrorDetails(category) {
    return ERROR_DETAILS[category] || { desc: category, action: 'Details prüfen' };
}

async function loadErrorOverview() {
    try {
        const response = await fetch('/error_overview');
        const data = await response.json();
        
        const row = document.getElementById('errorOverviewRow');
        const tbody = document.getElementById('errorTableBody');
        
        if (data.success && data.errors && data.errors.length > 0) {
            row.style.display = 'block';
            
            tbody.innerHTML = data.errors.map(err => {
                const details = getErrorDetails(err.category);
                const categoryClass = getCategoryClass(err.category);
                return `
                    <tr>
                        <td><span class="badge ${categoryClass}">${err.category}</span></td>
                        <td>${details.desc}</td>
                        <td class="text-center"><strong>${err.count}</strong></td>
                        <td><small class="text-info">${details.action}</small></td>
                        <td>
                            <button class="btn btn-sm btn-warning" onclick="retryByCategory('${err.category}')" title="Erneut versuchen">
                                <i class="fas fa-redo"></i>
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');
            
            document.getElementById('retryAllBtn').innerHTML = 
                '<i class="fas fa-redo"></i> Alle ' + data.total_errors + ' Fehler erneut versuchen';
        } else {
            row.style.display = 'none';
        }
    } catch (error) {
        console.error('Error loading error overview:', error);
    }
}

function getCategoryClass(category) {
    if (category.includes('TOKEN') || category.includes('API_KEY') || category.includes('CSRF')) return 'badge-danger';
    if (category.includes('SOURCE')) return 'badge-warning';
    if (category.includes('TARGET')) return 'badge-info';
    if (category.includes('TIMEOUT') || category.includes('RATE')) return 'badge-secondary';
    if (category.includes('SERVER')) return 'badge-dark';
    return 'badge-danger';
}

async function retryByCategory(category) {
    if (!confirm('Alle "' + category + '" Fehler erneut versuchen?')) return;
    try {
        const response = await fetch('/retry_by_category', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category: category })
        });
        const data = await response.json();
        if (data.success) {
            alert(data.reset_count + ' Datensätze zurückgesetzt.\nStarte Migration im Hintergrund...');
            loadErrorOverview();
        } else { alert('Fehler: ' + data.error); }
    } catch (error) { alert('Fehler: ' + error); }
}

async function retryAllErrors() {
    if (!confirm('Alle fehlgeschlagenen Migrationen erneut versuchen?')) return;
    try {
        const response = await fetch('/retry_all_errors', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        if (data.success) {
            alert(data.reset_count + ' Datensätze zurückgesetzt.\nStarte Migration...');
            loadErrorOverview();
        } else { alert('Fehler: ' + data.error); }
    } catch (error) { alert('Fehler: ' + error); }
}

function toggleErrorPanel() {
    const body = document.getElementById('errorPanelBody');
    const icon = document.getElementById('errorPanelToggle');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        icon.className = 'fas fa-chevron-up';
    } else {
        body.style.display = 'none';
        icon.className = 'fas fa-chevron-down';
    }
}

async function loadBatches() {
    try {
        const response = await fetch('/batches');
        const data = await response.json();
        
        if (data.success) {
            const select = document.getElementById('batchSelect');
            select.innerHTML = '<option value="">Batch auswählen...</option>';
            
            data.batches.forEach(batch => {
                const option = document.createElement('option');
                option.value = batch.batch_id;
                const desc = batch.description ? ` - ${batch.description}` : '';
                option.textContent = `${batch.batch_id}${desc} (${batch.total_records} records)`;
                select.appendChild(option);
            });
            
            select.onchange = function() {
                if (this.value) {
                    selectBatch(this.value);
                }
            };
        }
    } catch (error) {
        console.error('Error loading batches:', error);
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
}

async function selectBatch(batchId) {
    currentBatchId = batchId;
    currentPage = 1;
    fileDetailsCache = {};
    
    document.getElementById('noBatchState').style.display = 'none';
    document.getElementById('loadingOverlay').classList.remove('hidden');
    
    // Update URL
    const url = new URL(window.location);
    url.searchParams.set('batch_id', batchId);
    window.history.replaceState({}, '', url);
    
    await Promise.all([
        loadSummary(batchId),
        loadDocuments(batchId)
    ]);
    
    document.getElementById('loadingOverlay').classList.add('hidden');
}

async function loadSummary(batchId) {
    try {
        // Load batch info + file details summary
        const [batchRes, fileRes] = await Promise.all([
            fetch(`/batch/${batchId}/progress`),
            fetch(`/batch/${batchId}/file-details/summary`)
        ]);
        
        const batchData = await batchRes.json();
        const fileData = await fileRes.json();
        
        if (batchData.success) {
            document.getElementById('summaryBatchId').textContent = `Batch: ${batchId}`;
            document.getElementById('statDocuments').textContent = batchData.total || '-';
            document.getElementById('statSuccess').textContent = batchData.success || 0;
            document.getElementById('statPartial').textContent = batchData.partial || 0;
            document.getElementById('statFailed').textContent = batchData.failed || 0;
        }
        
        if (fileData.success) {
            const summary = fileData.summary;
            document.getElementById('statFiles').textContent = summary.total_files || '-';
            document.getElementById('statSize').textContent = formatFileSize(summary.total_bytes);
            document.getElementById('statAvgTime').textContent = summary.avg_upload_time ? summary.avg_upload_time.toFixed(2) + 's' : '-';
            
            // Populate error category filter
            populateErrorCategories(fileData.error_categories);
        }
        
        // Set export links
        document.getElementById('exportFileLink').href = `/file-details/export/${batchId}`;
        document.getElementById('exportJsonLink').href = `/batch/${batchId}/results`;
        document.getElementById('exportDocLink').href = `/batch/${batchId}/export-documents`;
        
        document.getElementById('summaryCard').style.display = 'block';
        document.getElementById('filterPanel').style.display = 'block';
        
    } catch (error) {
        console.error('Error loading summary:', error);
    }
}

function populateErrorCategories(categories) {
    const select = document.getElementById('filterErrorCategory');
    select.innerHTML = '<option value="">Alle Kategorien</option>';
    
    if (categories) {
        categories.forEach(item => {
            const option = document.createElement('option');
            option.value = item.error_category;
            option.textContent = `${item.error_category} (${item.count})`;
            select.appendChild(option);
        });
    }
}

async function loadDocuments(batchId, page = 1) {
    if (!batchId) return;
    
    currentPage = page;
    
    try {
        // Load document-level data from staging
        const response = await fetch(`/batch/${batchId}/logs`);
        const data = await response.json();
        
        if (data.success) {
            allDocuments = data.logs;
            applyFiltersAndRender();
        }
    } catch (error) {
        console.error('Error loading documents:', error);
    }
}

function applyFiltersAndRender() {
    const statusFilter = document.getElementById('filterStatus').value;
    const errorCategoryFilter = document.getElementById('filterErrorCategory').value;
    const docNumberFilter = document.getElementById('filterDocNumber').value.toLowerCase();
    const filenameFilter = document.getElementById('filterFilename').value.toLowerCase();
    
    let filtered = allDocuments.filter(doc => {
        // Status filter
        if (statusFilter && doc.execution_status !== statusFilter) {
            return false;
        }
        
        // Document number filter
        if (docNumberFilter && !doc.source_documentnumber?.toLowerCase().includes(docNumberFilter)) {
            return false;
        }
        
        return true;
    });
    
    // Pagination
    const total = filtered.length;
    const start = (currentPage - 1) * perPage;
    const end = Math.min(start + perPage, total);
    const paged = filtered.slice(start, end);
    
    if (paged.length === 0) {
        document.getElementById('resultsContainer').style.display = 'none';
        document.getElementById('paginationContainer').style.display = 'none';
        document.getElementById('emptyState').style.display = 'block';
    } else {
        renderDocuments(paged);
        renderPagination(total, start, end);
        
        document.getElementById('resultsContainer').style.display = 'block';
        document.getElementById('paginationContainer').style.display = 'flex';
        document.getElementById('emptyState').style.display = 'none';
    }
}

function renderDocuments(documents) {
    const container = document.getElementById('resultsContainer');
    let html = '';
    
    documents.forEach(doc => {
        const status = doc.execution_status || 'pending';
        const statusClass = status;
        const statusLabel = status.charAt(0).toUpperCase() + status.slice(1);
        
        const targetDoc = doc.target_documentnumber || '-';
        const authGroup = doc.authorization_group ? `<span class="doc-auth">${doc.authorization_group}</span>` : '';
        
        html += `
            <div class="doc-card" data-doc-id="${doc.id}" data-status="${status}">
                <div class="doc-header status-${statusClass}" onclick="toggleDocFiles(${doc.id})">
                    <span class="doc-toggle" id="toggle-${doc.id}"><i class="fas fa-chevron-right"></i></span>
                    <div class="doc-info">
                        <span class="doc-type">${doc.source_documenttype || '-'}</span>
                        <span class="doc-number">${doc.source_documentnumber || doc.id}</span>
                        <span class="doc-mapping">→ ${targetDoc}</span>
                        ${authGroup}
                    </div>
                    <div class="doc-stats">
                        <span class="status-badge ${statusClass}">${statusLabel}</span>
                    </div>
                </div>
                <div class="doc-files" id="files-${doc.id}">
                    <div class="text-center py-3">
                        <div class="spinner-border spinner-border-sm text-primary"></div>
                        <span class="ml-2">Lade Dateien...</span>
                    </div>
                </div>
                ${doc.validation_notes ? `<div class="validation-notes"><strong>Notizen:</strong> ${escapeHtml(doc.validation_notes)}</div>` : ''}
            </div>
        `;
    });
    
    container.innerHTML = html;
}

async function toggleDocFiles(docId) {
    const filesDiv = document.getElementById(`files-${docId}`);
    const toggle = document.getElementById(`toggle-${docId}`);
    
    if (filesDiv.classList.contains('show')) {
        filesDiv.classList.remove('show');
        toggle.classList.remove('expanded');
    } else {
        toggle.classList.add('expanded');
        filesDiv.classList.add('show');
        
        // Load file details if not cached
        if (!fileDetailsCache[docId]) {
            await loadFileDetails(docId);
        } else {
            renderFileDetails(docId, fileDetailsCache[docId]);
        }
    }
}

async function loadFileDetails(stagingId) {
    try {
        const response = await fetch(`/batch/${currentBatchId}/file-details?staging_id=${stagingId}&per_page=100`);
        const data = await response.json();
        
        if (data.success) {
            fileDetailsCache[stagingId] = data.file_details;
            renderFileDetails(stagingId, data.file_details);
        }
    } catch (error) {
        console.error('Error loading file details:', error);
        document.getElementById(`files-${stagingId}`).innerHTML = 
            `<div class="text-danger p-3">Fehler beim Laden der Dateidetails: ${error}</div>`;
    }
}

function renderFileDetails(stagingId, files) {
    const filesDiv = document.getElementById(`files-${stagingId}`);
    
    if (!files || files.length === 0) {
        filesDiv.innerHTML = '<div class="text-muted p-3">Keine Dateidetails verfügbar</div>';
        return;
    }
    
    let html = `
        <table class="table file-table">
            <thead>
                <tr>
                    <th>#</th>
                    <th>Dateiname</th>
                    <th>Größe</th>
                    <th>Status</th>
                    <th>Kategorie</th>
                    <th>HTTP</th>
                    <th>Zeit</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    files.forEach(file => {
        const statusClass = getFileStatusClass(file.upload_status);
        const errorCatClass = file.error_category || '';
        
        html += `
            <tr>
                <td>${file.file_index + 1}</td>
                <td class="filename-cell" title="${escapeHtml(file.filename || '-')}">${escapeHtml(file.filename || '-')}</td>
                <td>${formatFileSize(file.file_size_bytes)}</td>
                <td><span class="file-status ${statusClass}">${file.upload_status || '-'}</span></td>
                <td>${file.error_category ? `<span class="error-category ${errorCatClass}">${file.error_category}</span>` : '-'}</td>
                <td>${file.http_status_code || '-'}</td>
                <td>${file.upload_time_seconds ? file.upload_time_seconds.toFixed(2) + 's' : '-'}</td>
            </tr>
        `;
        
        // Add error detail row if present
        if (file.error_detail) {
            html += `
                <tr class="error-detail-row">
                    <td colspan="7">
                        <strong>Fehlerdetails:</strong>
                        <pre>${escapeHtml(file.error_detail)}</pre>
                    </td>
                </tr>
            `;
        }
    });
    
    html += '</tbody></table>';
    filesDiv.innerHTML = html;
}

function getFileStatusClass(status) {
    if (!status) return '';
    if (status === 'SUCCESS') return 'SUCCESS';
    if (status.includes('SIZE') || status.includes('LARGE')) return 'SIZE';
    return 'ERROR';
}

function renderPagination(total, start, end) {
    document.getElementById('showingFrom').textContent = start + 1;
    document.getElementById('showingTo').textContent = end;
    document.getElementById('totalRecords').textContent = total;
    
    const totalPages = Math.ceil(total / perPage);
    const nav = document.getElementById('paginationNav');
    let html = '';
    
    // Previous
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="goToPage(${currentPage - 1}); return false;">«</a>
    </li>`;
    
    // Page numbers
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${i}); return false;">${i}</a>
        </li>`;
    }
    
    // Next
    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="goToPage(${currentPage + 1}); return false;">»</a>
    </li>`;
    
    nav.innerHTML = html;
}

function goToPage(page) {
    currentPage = page;
    applyFiltersAndRender();
    window.scrollTo(0, 0);
}

function quickFilter(type) {
    document.querySelectorAll('.quick-filter-btn').forEach(btn => btn.classList.remove('active'));
    event.target.closest('button').classList.add('active');
    
    const statusSelect = document.getElementById('filterStatus');
    const errorCatSelect = document.getElementById('filterErrorCategory');
    
    statusSelect.value = '';
    errorCatSelect.value = '';
    
    switch(type) {
        case 'success':
            statusSelect.value = 'success';
            break;
        case 'partial':
            statusSelect.value = 'partial';
            break;
        case 'failed':
            statusSelect.value = 'failed';
            break;
        case 'pending':
            statusSelect.value = 'pending';
            break;
        case 'size-error':
            errorCatSelect.value = 'PAYLOAD_TOO_LARGE';
            break;
    }
    
    currentPage = 1;
    applyFiltersAndRender();
}

function applyFilters() {
    currentPage = 1;
    applyFiltersAndRender();
}

function debounceFilter() {
    if (filterTimeout) clearTimeout(filterTimeout);
    filterTimeout = setTimeout(applyFilters, 300);
}

function expandAll() {
    document.querySelectorAll('.doc-card').forEach(card => {
        const docId = card.dataset.docId;
        const filesDiv = document.getElementById(`files-${docId}`);
        const toggle = document.getElementById(`toggle-${docId}`);
        
        if (!filesDiv.classList.contains('show')) {
            toggle.classList.add('expanded');
            filesDiv.classList.add('show');
            
            if (!fileDetailsCache[docId]) {
                loadFileDetails(docId);
            }
        }
    });
}

function collapseAll() {
    document.querySelectorAll('.doc-files').forEach(div => {
        div.classList.remove('show');
    });
    document.querySelectorAll('.doc-toggle').forEach(toggle => {
        toggle.classList.remove('expanded');
    });
}
