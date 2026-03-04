let allRecords = [];
let selectedRecords = new Set();
let currentAblageFilter = '';
const batchId = window.BATCH_ID;

// Progress polling for execution (declared early to avoid TDZ issues)
let progressInterval = null;
let pollingTimeoutId = null; // Track the delayed start timeout
let executionStartTime = null;
let completionAlertShown = false; // Prevent duplicate completion alerts

// Error Category Details - lazy initialized because t() may not be available yet
let ERROR_CATEGORY_DETAILS = null;

function getErrorCategoryDetails() {
    if (!ERROR_CATEGORY_DETAILS) {
        ERROR_CATEGORY_DETAILS = {
            'API_KEY_INVALID': { desc: t('err.API_KEY'), class: 'badge-danger' },
            'TOKEN_EXPIRED': { desc: t('err.TOKEN_EXPIRED'), class: 'badge-danger' },
            'TOKEN_INVALID': { desc: t('err.INVALID_TOKEN'), class: 'badge-danger' },
            'CSRF_FAILED': { desc: t('err.CSRF_ERROR'), class: 'badge-danger' },
            'SOURCE_NOT_FOUND': { desc: t('err.NOT_FOUND'), class: 'badge-warning' },
            'SOURCE_EMPTY': { desc: t('err.NO_FILES'), class: 'badge-secondary' },
            'SOURCE_READ_ERROR': { desc: t('err.READ_ERROR'), class: 'badge-warning' },
            'TARGET_CREATE_FAILED': { desc: t('err.CONTAINER_CREATE_FAIL'), class: 'badge-info' },
            'TARGET_EXISTS': { desc: t('err.ALREADY_EXISTS'), class: 'badge-info' },
            'TARGET_LOCKED': { desc: t('err.LOCKED'), class: 'badge-info' },
            'UPLOAD_SIZE_EXCEEDED': { desc: t('err.PAYLOAD_TOO_LARGE'), class: 'badge-warning' },
            'UPLOAD_TIMEOUT': { desc: t('err.TIMEOUT'), class: 'badge-secondary' },
            'GATEWAY_TIMEOUT': { desc: t('err.GATEWAY_TIMEOUT'), class: 'badge-secondary' },
            'RATE_LIMITED': { desc: t('err.RATE_LIMIT'), class: 'badge-secondary' },
            'SERVER_ERROR': { desc: t('err.SERVER_ERROR'), class: 'badge-dark' },
            'BAD_REQUEST': { desc: t('err.BAD_REQUEST'), class: 'badge-warning' },
            'UNKNOWN': { desc: t('err.UNKNOWN'), class: 'badge-secondary' },
            'READ_EMPTY': { desc: t('err.NO_SOURCE_FILES'), class: 'badge-secondary' },
            'TIMEOUT_RETRY': { desc: t('err.TIMEOUT_RETRY'), class: 'badge-warning' },
            'API_NOT_IMPLEMENTED': { desc: t('err.NOT_IMPLEMENTED'), class: 'badge-dark' },
            'CODE_BUG_FIXED': { desc: t('err.BUG_FIXED'), class: 'badge-success' },
            'CONNECTION_ERROR': { desc: t('err.CONNECTION_ERROR'), class: 'badge-warning' },
            'TIMEOUT': { desc: t('err.TIMEOUT'), class: 'badge-warning' },
            'AUTH_ERROR': { desc: t('err.AUTH_ERROR'), class: 'badge-danger' },
            'AUTH_FORBIDDEN': { desc: t('err.FORBIDDEN'), class: 'badge-danger' },
            'CODE_BUG': { desc: t('err.CODE_BUG'), class: 'badge-dark' },
            'UPLOAD_ERROR': { desc: t('err.UPLOAD_FAIL'), class: 'badge-warning' },
            'SIZE_EXCEEDED': { desc: t('err.FILE_TOO_LARGE'), class: 'badge-warning' }
        };
    }
    return ERROR_CATEGORY_DETAILS;
}

// Column visibility state
let visibleColumns = {
    'id': true,
    'source_doc': true,
    'target_doc': true,
    'type_info': true,
    'target_type': true,
    'dokob': true,
    'target_dokob': true,
    'objky': true,
    'target_objky': true,
    'doc_status': true,
    'description': true,
    'filename': true,
    'file_size': true,
    'file_count': true,
    'link_count': true,
    'ablage': true,
    'source_auth_group': true,
    'target_auth_group': true,
    'execution': true,
    'link_status': true,
    'error_category': true,
    'source_loioid': false,
    'mime_type': false,
    'batch_id': false,
    'created_at': false,
    'created_by': false,
    'exec_started': false,
    'exec_completed': false,
    'exec_error': false
};

// Load column preferences from localStorage
function loadColumnPreferences() {
    const saved = localStorage.getItem('migrate_columns_' + batchId);
    if (saved) {
        visibleColumns = JSON.parse(saved);
    }
    // Update checkboxes to match current state (when they exist)
    Object.keys(visibleColumns).forEach(col => {
        const checkbox = document.getElementById('col_' + col);
        if (checkbox) {
            checkbox.checked = visibleColumns[col];
        }
    });
}

// Apply column visibility to table
function applyColumnVisibility() {
    Object.keys(visibleColumns).forEach(col => {
        const visible = visibleColumns[col];
        
        // Update table header
        const headers = document.querySelectorAll(`th[data-column="${col}"]`);
        headers.forEach(th => {
            th.style.display = visible ? '' : 'none';
        });
        
        // Update table cells
        const columnIndex = getColumnIndex(col);
        if (columnIndex >= 0) {
            const rows = document.querySelectorAll('#recordsTable tbody tr');
            rows.forEach(row => {
                const cell = row.cells[columnIndex];
                if (cell) {
                    cell.style.display = visible ? '' : 'none';
                }
            });
        }
    });
}

// Save column preferences to localStorage
function saveColumnPreferences() {
    localStorage.setItem('migrate_columns_' + batchId, JSON.stringify(visibleColumns));
}

// Toggle column visibility
function toggleColumn(columnName, visible) {
    visibleColumns[columnName] = visible;
    saveColumnPreferences();
    
    // Update table header
    const headers = document.querySelectorAll(`th[data-column="${columnName}"]`);
    headers.forEach(th => {
        th.style.display = visible ? '' : 'none';
    });
    
    // Update table cells
    const columnIndex = getColumnIndex(columnName);
    const rows = document.querySelectorAll('#recordsTable tbody tr');
    rows.forEach(row => {
        const cell = row.cells[columnIndex];
        if (cell) {
            cell.style.display = visible ? '' : 'none';
        }
    });
}

// Get column index by name
function getColumnIndex(columnName) {
    const headers = document.querySelectorAll('#recordsTable thead th');
    for (let i = 0; i < headers.length; i++) {
        if (headers[i].dataset.column === columnName) {
            return i;
        }
    }
    return -1;
}

// Reset columns to default
const defaultVisibleColumns = {
    'id': true, 'source_doc': true, 'target_doc': true,
    'type_info': true, 'target_type': true,
    'dokob': true, 'target_dokob': true,
    'objky': true, 'target_objky': true,
    'doc_status': true, 'description': true,
    'filename': true, 'file_size': true, 'file_count': true, 'link_count': true, 'ablage': true,
    'source_auth_group': true, 'target_auth_group': true, 'execution': true,
    'link_status': true, 'error_category': true,
    'source_loioid': false, 'mime_type': false, 'batch_id': false,
    'created_at': false, 'created_by': false,
    'exec_started': false, 'exec_completed': false, 'exec_error': false
};
function resetColumns() {
    Object.keys(defaultVisibleColumns).forEach(col => {
        const visible = defaultVisibleColumns[col];
        visibleColumns[col] = visible;
        const checkbox = document.getElementById('col_' + col);
        if (checkbox) {
            checkbox.checked = visible;
        }
        toggleColumn(col, visible);
    });
    localStorage.removeItem('migrate_columns_' + batchId);
}

document.addEventListener('DOMContentLoaded', function() {
    // Load column preferences from localStorage
    loadColumnPreferences();
    
    // Apply initial column visibility to table headers immediately
    applyColumnVisibility();
    
    // Load pacing settings
    loadPacingSettings();
    
    // Then load records
    loadRecords();
    
    // Auto-reconnect: check if a migration is currently executing for this batch
    checkAndReconnectExecution();
    
    // Column toggle event listeners
    document.querySelectorAll('.column-toggle').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            toggleColumn(this.value, this.checked);
        });
    });
    
    // Search functionality - debounced server-side search across ALL staging records
    let searchDebounceTimer = null;
    document.getElementById('searchInput').addEventListener('input', function() {
        clearTimeout(searchDebounceTimer);
        const searchTerm = this.value.trim();
        if (searchTerm.length >= 3 || searchTerm.length === 0) {
            searchDebounceTimer = setTimeout(() => {
                loadRecordsWithAllFilters();
            }, 400);
        }
    });
    // Also trigger on Enter key immediately
    document.getElementById('searchInput').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            clearTimeout(searchDebounceTimer);
            loadRecordsWithAllFilters();
        }
    });
    
    // Status filter functionality - reload from server with all active filters
    document.getElementById('statusFilter').addEventListener('change', function() {
        const status = this.value;
        if (status === 'hide_completed') {
            // Client-side filter for hide_completed (applied on top of current results)
            applyFilters();
        } else {
            loadRecordsWithAllFilters();
        }
    });
    
    // Error category filter functionality - reload from server with all active filters
    document.getElementById('errorCategoryFilter').addEventListener('change', function() {
        loadRecordsWithAllFilters();
    });
    
    // Load available error categories for filter dropdown
    loadErrorCategories();
    
    // Select all checkbox
    document.getElementById('selectAllCheckbox').addEventListener('change', function() {
        const checkboxes = document.querySelectorAll('.record-checkbox');
        checkboxes.forEach(cb => {
            cb.checked = this.checked;
            if (this.checked) {
                selectedRecords.add(parseInt(cb.dataset.id));
            } else {
                selectedRecords.delete(parseInt(cb.dataset.id));
            }
        });
        updateSelectionInfo();
    });
});

// Current pacing setting from server
let currentPacingSeconds = 0;
let currentMaxWorkers = 2;

// Load error categories for filter dropdown
function loadErrorCategories() {
    fetch(`/batch/${batchId}/error-categories`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.categories) {
                const select = document.getElementById('errorCategoryFilter');
                const categoryDetails = getErrorCategoryDetails();
                data.categories.forEach(cat => {
                    const info = categoryDetails[cat.category] || { desc: cat.category };
                    const option = document.createElement('option');
                    option.value = cat.category;
                    option.textContent = `${info.desc} (${cat.count})`;
                    select.appendChild(option);
                });
            }
        })
        .catch(error => {
            console.error('Error loading error categories:', error);
        });
}

function loadPacingSettings() {
    fetch('/settings/json')
        .then(response => response.json())
        .then(data => {
            currentPacingSeconds = data.pacing_seconds || 0;
            currentMaxWorkers = data.max_workers || 2;
            updatePacingDisplay();
        })
        .catch(error => {
            console.error('Error loading pacing settings:', error);
            updatePacingDisplay();
        });
}

function updatePacingDisplay() {
    const pacingEl = document.getElementById('statPacing');
    if (!pacingEl) return;
    
    if (currentPacingSeconds === 0) {
        pacingEl.innerHTML = `<span class="badge badge-success" title="${t('prev.pacing.response_tip')}">Response</span>`;
    } else {
        pacingEl.innerHTML = `<span class="badge badge-secondary" title="${t('prev.pacing.fixed_tip')}">${t('prev.pacing.fixed_label', {n: currentPacingSeconds})}</span>`;
    }
}

/**
 * Unified function to load records with ALL active filters (search, status, ablage, error category).
 * Always sends filters server-side so the entire staging table is searched.
 */
function loadRecordsWithAllFilters() {
    const searchTerm = document.getElementById('searchInput').value.trim();
    const statusFilter = document.getElementById('statusFilter').value;
    const errorCategoryFilter = document.getElementById('errorCategoryFilter').value;
    
    // Skip hide_completed as server param (it's client-side only)
    const serverStatusFilter = (statusFilter && statusFilter !== 'hide_completed') ? statusFilter : '';
    
    // Determine per_page: if ANY filter is active, load up to 500. Otherwise default 100 preview.
    const hasFilter = searchTerm || serverStatusFilter || errorCategoryFilter || currentAblageFilter;
    const perPage = hasFilter ? 500 : 100;
    
    let recordsUrl = `/batch/${batchId}/records?per_page=${perPage}&page=1`;
    if (serverStatusFilter) {
        recordsUrl += `&status_filter=${encodeURIComponent(serverStatusFilter)}`;
    }
    if (errorCategoryFilter) {
        recordsUrl += `&error_category=${encodeURIComponent(errorCategoryFilter)}`;
    }
    if (searchTerm) {
        recordsUrl += `&search=${encodeURIComponent(searchTerm)}`;
    }
    if (currentAblageFilter) {
        recordsUrl += `&ablage_filter=${encodeURIComponent(currentAblageFilter)}`;
    }
    
    // Show loading indicator
    const tbody = document.getElementById('recordsBody');
    tbody.innerHTML = `<tr><td colspan="20" class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> ${t('prev.searching')}</td></tr>`;
    
    // Load statistics from server (aggregated - fast!) and records
    Promise.all([
        fetch(`/batch/${batchId}/preview-stats`).then(r => r.json()),
        fetch(recordsUrl).then(r => r.json())
    ])
    .then(([statsData, recordsData]) => {
        if (!statsData.success) {
            showError('Failed to load statistics: ' + statsData.error);
            return;
        }
        if (!recordsData.success) {
            showError('Failed to load records: ' + recordsData.error);
            return;
        }
        
        // Store records
        allRecords = recordsData.records;
        
        // Apply client-side hide_completed filter if active
        if (statusFilter === 'hide_completed') {
            applyFilters();
        } else {
            displayRecords(allRecords);
        }
        
        // Update filter info
        const filterInfo = document.getElementById('filterInfo');
        const totalInBatch = recordsData.pagination?.total || allRecords.length;
        const parts = [];
        if (searchTerm) parts.push(`"${searchTerm}"`);
        if (serverStatusFilter) parts.push(serverStatusFilter);
        if (currentAblageFilter) parts.push(currentAblageFilter);
        if (errorCategoryFilter) parts.push(errorCategoryFilter);
        
        if (parts.length > 0) {
            filterInfo.textContent = t('prev.filter_hits', {n: totalInBatch, filters: parts.join(', ')});
        } else {
            filterInfo.textContent = t('prev.records_of_total', {n: allRecords.length, total: totalInBatch});
        }
        
        // Update statistics from server-aggregated data
        updateBatchStatisticsFromServer(statsData.stats, recordsData.pagination?.total || 0);
    })
    .catch(error => {
        showError('Error loading records: ' + error);
    });
}

// Legacy wrapper for simple cases
function loadRecordsWithFilters(statusFilter = '', errorCategoryFilter = '') {
    if (statusFilter) document.getElementById('statusFilter').value = statusFilter;
    if (errorCategoryFilter) document.getElementById('errorCategoryFilter').value = errorCategoryFilter;
    loadRecordsWithAllFilters();
}

function loadRecords(errorCategoryFilter = '') {
    // Build query params
    let recordsUrl = `/batch/${batchId}/records?per_page=100&page=1`;
    if (errorCategoryFilter) {
        // When filtering by error category, load up to 500 matching records
        recordsUrl = `/batch/${batchId}/records?per_page=500&page=1&error_category=${encodeURIComponent(errorCategoryFilter)}`;
    }
    
    // Load statistics from server (aggregated - fast!) and records
    Promise.all([
        fetch(`/batch/${batchId}/preview-stats`).then(r => r.json()),
        fetch(recordsUrl).then(r => r.json())
    ])
    .then(([statsData, recordsData]) => {
        if (!statsData.success) {
            showError('Failed to load statistics: ' + statsData.error);
            return;
        }
        if (!recordsData.success) {
            showError('Failed to load records: ' + recordsData.error);
            return;
        }
        
        // Store records
        allRecords = recordsData.records;
        
        // Display records
        displayRecords(allRecords);
        
        // Update filter info
        const filterInfo = document.getElementById('filterInfo');
        if (errorCategoryFilter) {
            filterInfo.textContent = t('prev.filter_active', {filter: errorCategoryFilter, n: allRecords.length, total: recordsData.pagination?.total || allRecords.length});
        } else {
            filterInfo.textContent = t('prev.records_of_total', {n: allRecords.length, total: recordsData.pagination?.total || allRecords.length});
        }
        
        // Update statistics from server-aggregated data
        updateBatchStatisticsFromServer(statsData.stats, recordsData.pagination?.total || 0);
    })
    .catch(error => {
        showError('Error loading records: ' + error);
    });
}

// New function: Update stats from server-aggregated data (FAST - no client-side loop)
function updateBatchStatisticsFromServer(stats, totalRecords) {
    const buckets = stats.buckets;
    const pendingCount = stats.pending || 0;  // Real pending from DB
    const toExecuteCount = stats.to_execute || pendingCount;  // All non-success, non-skipped
    const successCount = stats.success || 0;
    const failedCount = stats.failed || 0;
    const partialCount = stats.partial || 0;
    const totalCount = stats.total || 0;
    const totalActive = stats.total_active || totalCount;
    const skippedCount = stats.skipped || 0;
    const kproCount = stats.kpro || 0;
    const dbCount = stats.db || 0;
    
    // Update excluded (skipped records) / KPRO / DB badges
    if (skippedCount > 0) {
        document.getElementById('statExcluded').textContent = skippedCount.toLocaleString();
    } else {
        document.getElementById('statExcluded').textContent = '-';
    }
    document.getElementById('statKpro').textContent = kproCount.toLocaleString();
    document.getElementById('statDb').textContent = dbCount.toLocaleString();
    
    // Update status filter dropdown with counts from DB (entire table, not just preview)
    const pendingOpt = document.getElementById('statusPending');
    const successOpt = document.getElementById('statusSuccess');
    const failedOpt = document.getElementById('statusFailed');
    const partialOpt = document.getElementById('statusPartial');
    
    if (pendingOpt) pendingOpt.textContent = `${t('prev.filter.pending')} (${pendingCount.toLocaleString()})`;
    if (successOpt) successOpt.textContent = `${t('prev.filter.success')} (${successCount.toLocaleString()})`;
    if (failedOpt) failedOpt.textContent = `${t('prev.filter.failed')} (${failedCount.toLocaleString()})`;
    if (partialOpt) partialOpt.textContent = `${t('prev.filter.partial')} (${partialCount.toLocaleString()})`;
    
    // Calculate runtime based on REALISTIC estimates:
    // - API initialization (test ping, auth, etc.): ~60 seconds fixed overhead
    // - Transfer rate: ~1 sec/MB
    // - Container creation: ~5 seconds per container (includes API latency)
    // - Safety buffer: 30% (accounts for network variability)
    const apiInitOverhead = 60;
    const transferRate = 1.0;
    const containerOverhead = 5.0;
    const safetyBuffer = 1.3;
    
    const totalSizeMB = (stats.total_size_bytes || 0) / (1024 * 1024);
    const transferTime = totalSizeMB * transferRate;
    const processingTime = toExecuteCount * containerOverhead;
    const totalSerialRuntime = (transferTime + processingTime) * safetyBuffer;
    
    const maxWorkers = currentMaxWorkers;
    const parallelRuntime = totalSerialRuntime / maxWorkers;
    const totalRuntime = toExecuteCount > 0 ? apiInitOverhead + parallelRuntime : 0;
    
    // Update statistics display (use toExecuteCount for "remaining work", totalActive excludes skipped)
    document.getElementById('statRecords').innerHTML = toExecuteCount > 0 
        ? `${toExecuteCount.toLocaleString()} <small class="text-muted">(${successCount} ✓)</small>`
            + (skippedCount > 0 ? `<br><small class="text-muted" style="font-size:10px;">${t('prev.stats.of_total', {n: totalCount.toLocaleString()})}</small>` : '')
        : `<span class="text-success">${t('prev.stats.all_done', {n: totalActive.toLocaleString()})}</span>`
            + (skippedCount > 0 ? `<br><small class="text-muted" style="font-size:10px;">${t('prev.stats.of_total', {n: totalCount.toLocaleString()})}</small>` : '');
    document.getElementById('statTotalSize').textContent = formatFileSize(stats.total_size_bytes);
    document.getElementById('statTiny').textContent = buckets.tiny || 0;
    document.getElementById('statSmall').textContent = buckets.small || 0;
    document.getElementById('statMedium').textContent = buckets.medium || 0;
    document.getElementById('statLarge').textContent = (buckets.large || 0) > 0 ? (buckets.large + ' ⚠️') : '0';
    document.getElementById('statUnknown').textContent = buckets.unknown || 0;
    document.getElementById('statRuntime').textContent = toExecuteCount > 0 ? formatDuration(totalRuntime) : '-';
    
    // Update selection info to show preview info
    const selectionInfo = document.getElementById('selectionInfo');
    if (totalRecords > 100) {
        selectionInfo.innerHTML = t('prev.stats.preview_info', {n: totalRecords.toLocaleString()});
    } else {
        selectionInfo.textContent = t('prev.stats.n_records', {n: totalRecords});
    }
    
    // Build runtime breakdown
    const breakdown = [];
    if (buckets.tiny > 0) breakdown.push(`⚡${buckets.tiny}`);
    if (buckets.small > 0) breakdown.push(`🟢${buckets.small}`);
    if (buckets.medium > 0) breakdown.push(`🟡${buckets.medium}`);
    if (buckets.large > 0) breakdown.push(`🔴${buckets.large}`);
    if (buckets.unknown > 0) breakdown.push(`❓${buckets.unknown}`);
    
    const detailText = toExecuteCount > 0 
        ? `~1min Init + (${formatFileSize(stats.total_size_bytes)} + ${toExecuteCount}×5s) ÷ ${maxWorkers}`
        : t('runtime.no_pending');
    document.getElementById('statRuntimeDetail').textContent = detailText;
    
    // Store for modal details
    window.runtimeStats = {
        buckets: buckets,
        totalSize: stats.total_size_bytes,
        totalRuntime: totalRuntime,
        totalSerialRuntime: totalSerialRuntime,
        parallelRuntime: parallelRuntime,
        apiInitOverhead: apiInitOverhead,
        maxWorkers: maxWorkers,
        transferRate: transferRate,
        containerOverhead: containerOverhead,
        safetyBuffer: safetyBuffer,
        containerCount: toExecuteCount
    };
}

function updateBatchStatistics(records) {
    // Count all records except successful ones (pending, failed, partial need to run)
    const pendingRecords = records.filter(r => r.execution_status !== 'success');
    const successCount = records.filter(r => r.execution_status === 'success').length;
    
    // Size buckets for statistics display
    const buckets = {
        tiny:    { max: 1,   count: 0, size: 0, label: '⚡ ≤1MB' },
        small:   { max: 10,  count: 0, size: 0, label: '🟢 1-10MB' },
        medium:  { max: 99,  count: 0, size: 0, label: '🟡 10-99MB' },
        large:   { max: Infinity, count: 0, size: 0, label: '🔴 >99MB' },
        unknown: { count: 0 }
    };
    
    let totalSize = 0;
    
    pendingRecords.forEach(record => {
        const bytes = record.file_size_bytes;
        if (bytes !== null && bytes !== undefined && !isNaN(bytes) && bytes > 0) {
            const sizeMB = bytes / (1024 * 1024);
            totalSize += Number(bytes);
            
            if (sizeMB <= 1) {
                buckets.tiny.count++;
                buckets.tiny.size += bytes;
            } else if (sizeMB <= 10) {
                buckets.small.count++;
                buckets.small.size += bytes;
            } else if (sizeMB <= 99) {
                buckets.medium.count++;
                buckets.medium.size += bytes;
            } else {
                buckets.large.count++;
                buckets.large.size += bytes;
            }
        } else {
            buckets.unknown.count++;
        }
    });
    
    // Calculate runtime based on response-based pacing
    // REALISTIC ESTIMATES based on actual observations:
    // - API initialization (test ping, auth, etc.): ~60 seconds fixed overhead
    // - Transfer rate: ~1 sec/MB (download + upload combined)
    // - Container creation: ~3-4 seconds per container (API call, processing, response)
    // - Safety buffer: 20% for network variability
    
    const apiInitOverhead = 60;    // Fixed startup cost in seconds
    const transferRate = 1.0;      // seconds per MB
    const containerOverhead = 5.0; // API overhead per container (includes latency)
    const safetyBuffer = 1.3;      // 30% buffer for network variability
    
    // Total runtime = init + (transfer time + overhead per container) * safety
    const totalSizeMB = totalSize / (1024 * 1024);
    const containerCount = pendingRecords.length;
    const transferTime = totalSizeMB * transferRate;
    const processingTime = containerCount * containerOverhead;
    const totalSerialRuntime = (transferTime + processingTime) * safetyBuffer;
    
    // Divide by number of workers for parallel execution
    const maxWorkers = currentMaxWorkers;
    const parallelRuntime = totalSerialRuntime / maxWorkers;
    
    // Add fixed init overhead (not parallelizable)
    const totalRuntime = pendingRecords.length > 0 ? apiInitOverhead + parallelRuntime : 0;
    
    // Update statistics display - show pending count and success count
    document.getElementById('statRecords').innerHTML = pendingRecords.length > 0 
        ? `${pendingRecords.length} <small class="text-muted">(${successCount} ✓)</small>`
        : `<span class="text-success">${t('prev.stats.all_done', {n: records.length})}</span>`;
    document.getElementById('statTotalSize').textContent = formatFileSize(totalSize);
    document.getElementById('statTiny').textContent = buckets.tiny.count;
    document.getElementById('statSmall').textContent = buckets.small.count;
    document.getElementById('statMedium').textContent = buckets.medium.count;
    document.getElementById('statLarge').textContent = buckets.large.count > 0 ? buckets.large.count + ' ⚠️' : '0';
    document.getElementById('statUnknown').textContent = buckets.unknown.count;
    document.getElementById('statRuntime').textContent = pendingRecords.length > 0 ? formatDuration(totalRuntime) : '-';
    
    // Build runtime breakdown
    const breakdown = [];
    if (buckets.tiny.count > 0) breakdown.push(`⚡${buckets.tiny.count}`);
    if (buckets.small.count > 0) breakdown.push(`🟢${buckets.small.count}`);
    if (buckets.medium.count > 0) breakdown.push(`🟡${buckets.medium.count}`);
    if (buckets.large.count > 0) breakdown.push(`🔴${buckets.large.count}`);
    if (buckets.unknown.count > 0) breakdown.push(`❓${buckets.unknown.count}`);
    
    const detailText = pendingRecords.length > 0 
        ? `~1min Init + (${formatFileSize(totalSize)} + ${containerCount}×5s) ÷ ${maxWorkers}`
        : t('runtime.no_pending');
    document.getElementById('statRuntimeDetail').textContent = detailText;
    
    // Store for modal details
    window.runtimeStats = {
        buckets: buckets,
        totalSize: totalSize,
        totalRuntime: totalRuntime,
        totalSerialRuntime: totalSerialRuntime,
        parallelRuntime: parallelRuntime,
        apiInitOverhead: apiInitOverhead,
        maxWorkers: maxWorkers,
        transferRate: transferRate,
        containerOverhead: containerOverhead,
        safetyBuffer: safetyBuffer,
        containerCount: containerCount
    };
}

function showRuntimeDetails() {
    if (!window.runtimeStats) return;
    
    const stats = window.runtimeStats;
    const b = stats.buckets;
    
    const details = `
═══ Runtime Calculation (Realistic Estimate) ═══

📦 PACKAGE BREAKDOWN:
┌─────────────┬───────┬──────────┐
│ Package     │ Count │ Size     │
├─────────────┼───────┼──────────┤
│ ⚡ ≤1MB     │ ${b.tiny.count.toString().padStart(5)} │ ${formatFileSize(b.tiny.size || 0).padStart(8)} │
│ 🟢 1-10MB   │ ${b.small.count.toString().padStart(5)} │ ${formatFileSize(b.small.size || 0).padStart(8)} │
│ 🟡 10-99MB  │ ${b.medium.count.toString().padStart(5)} │ ${formatFileSize(b.medium.size || 0).padStart(8)} │
│ 🔴 >99MB    │ ${b.large.count.toString().padStart(5)} │ ${formatFileSize(b.large.size || 0).padStart(8)} │
│ ❓ Unknown  │ ${b.unknown.count.toString().padStart(5)} │      -   │
└─────────────┴───────┴──────────┘

📊 CALCULATION:
1️⃣ API-Initialisierung (Ping, Auth): ~${stats.apiInitOverhead}s (fix)

2️⃣ Transfer Time:
   ${formatFileSize(stats.totalSize)} × ${stats.transferRate}s/MB = ${formatDuration(stats.totalSize / (1024*1024) * stats.transferRate)}

3️⃣ Container-Verarbeitung:
   ${stats.containerCount} Container × ${stats.containerOverhead}s = ${formatDuration(stats.containerCount * stats.containerOverhead)}

4️⃣ Sicherheitspuffer: +${Math.round((stats.safetyBuffer - 1) * 100)}%

🚀 PARALLEL EXECUTION:
• Workers: ${stats.maxWorkers}
• Serielle Zeit: ${formatDuration(stats.totalSerialRuntime)}
• Parallel: ${formatDuration(stats.parallelRuntime)}
• + Init: ${formatDuration(stats.apiInitOverhead)}

⏱️ GESCHÄTZTE LAUFZEIT: ${formatDuration(stats.totalRuntime)}

💡 HINWEIS:
• Grobe Schätzung basierend auf Erfahrungswerten
• Tatsächliche Zeit variiert je nach Netzwerk/Last
    `.trim();
    
    alert(details);
}

function formatDuration(seconds) {
    if (seconds < 60) return Math.round(seconds) + ' sec';
    if (seconds < 3600) return Math.round(seconds / 60) + ' min';
    const hours = Math.floor(seconds / 3600);
    const mins = Math.round((seconds % 3600) / 60);
    return hours + 'h ' + mins + 'm';
}

function displayRecords(records) {
    const tbody = document.getElementById('recordsBody');
    
    if (records.length === 0) {
        tbody.innerHTML = `<tr><td colspan="20" class="text-center">${t('mig.no_records')}</td></tr>`;
        return;
    }
    
    tbody.innerHTML = records.map(record => {
        const executionBadge = getExecutionBadge(record.execution_status);
        const typeInfo = `${record.source_documenttype}/${record.source_documentversion}/${record.source_documentpart}`;
        const fileSize = (record.file_size_bytes !== null && record.file_size_bytes !== undefined)
            ? formatFileSizeWithColor(Number(record.file_size_bytes))
            : '-';
        const createdAt = record.created_at ? formatDateTime(record.created_at) : '-';
        const execStarted = record.execution_started_at ? formatDateTime(record.execution_started_at) : '-';
        const execCompleted = record.execution_completed_at ? formatDateTime(record.execution_completed_at) : '-';
        
        // Detect rule-modified values (target differs from source)
        const isTypeModified = record.target_documenttype && record.source_documenttype && 
                              record.target_documenttype !== record.source_documenttype;
        const isDokobModified = record.target_dokob && record.source_dokob && 
                               record.target_dokob !== record.source_dokob;
        const isObjkyModified = record.target_objky && record.source_objky && 
                               record.target_objky !== record.source_objky;
        const isDocStatusModified = record.target_document_status && record.source_document_status && 
                                   record.target_document_status !== record.source_document_status;
        const isAuthGroupModified = record.authorization_group && record.source_authorization_group !== undefined &&
                                   record.authorization_group !== record.source_authorization_group;
        
        return `
            <tr class="${record.skip_migration ? 'table-secondary' : ''}">
                <td>
                    <input type="checkbox" class="record-checkbox" 
                           data-id="${record.id}" 
                           onchange="toggleSelection(${record.id})"
                           ${record.skip_migration ? 'disabled' : ''}>
                </td>
                <td data-column="id">${record.id}</td>
                <td data-column="source_doc"><code>${record.source_documentnumber}</code></td>
                <td data-column="target_doc" class="target-col"><code>${record.target_documentnumber || '-'}</code></td>
                <td data-column="type_info"><small>${typeInfo}</small></td>
                <td data-column="target_type" class="target-col${isTypeModified ? ' rule-modified' : ''}"><small>${record.target_documenttype || '-'}</small></td>
                <td data-column="dokob"><small>${formatDokob(record)}</small></td>
                <td data-column="target_dokob" class="target-col${isDokobModified ? ' rule-modified' : ''}"><small>${record.target_dokob || '-'}</small></td>
                <td data-column="objky"><small>${formatObjky(record)}</small></td>
                <td data-column="target_objky" class="target-col${isObjkyModified ? ' rule-modified' : ''}"><small>${truncate(record.target_objky, 25) || '-'}</small></td>
                <td data-column="doc_status"${isDocStatusModified ? ' class="rule-modified"' : ''}><small>${record.source_document_status ? record.source_document_status : '-'}${record.target_document_status ? ' → ' + record.target_document_status : ''}</small></td>
                <td data-column="description"><small>${truncate(record.source_description, 30)}</small></td>
                <td data-column="filename"><small>${truncate(record.filename, 25) || '-'}</small></td>
                <td data-column="file_size"><small>${fileSize}</small></td>
                <td data-column="file_count"><small>${formatFileCount(record)}</small></td>
                <td data-column="link_count"><small>${formatLinkCount(record)}</small></td>
                <td data-column="ablage">${record.ablage === 'DB' ? '<span class="badge badge-warning"><i class="fas fa-database"></i> DB</span>' : '<span class="badge badge-info"><i class="fas fa-cloud"></i> KPRO</span>'}</td>
                <td data-column="source_auth_group"><small>${record.source_authorization_group || '-'}</small></td>
                <td data-column="target_auth_group"${isAuthGroupModified ? ' class="rule-modified"' : ''}><small>${record.authorization_group || '-'}</small></td>
                <td data-column="execution">${executionBadge}</td>
                <td data-column="link_status">${getLinkStatusBadge(record.link_status, record.execution_status, record.target_dokob)}</td>
                <td data-column="error_category">${getErrorCategoryBadge(record.error_category)}</td>
                <td data-column="source_loioid"><small>${truncate(record.source_loioid, 20) || '-'}</small></td>
                <td data-column="mime_type"><small>${record.mime_type || '-'}</small></td>
                <td data-column="batch_id"><small>${record.batch_id || '-'}</small></td>
                <td data-column="created_at"><small>${createdAt}</small></td>
                <td data-column="created_by"><small>${record.created_by || '-'}</small></td>
                <td data-column="exec_started"><small>${execStarted}</small></td>
                <td data-column="exec_completed"><small>${execCompleted}</small></td>
                <td data-column="exec_error"><small>${truncate(record.execution_error, 30) || '-'}</small></td>
                <td>
                    <button class="btn btn-sm btn-outline-info" 
                            onclick="viewRecordDetail(${record.id})"
                            title="${t('detail.show')}">
                        <i class="fas fa-info-circle"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
    
    // Apply column visibility after rendering
    applyColumnVisibility();
}

function getExecutionBadge(status) {
    const map = {
        'success': `<span class="badge badge-success">${t('exec.success')}</span>`,
        'failed': `<span class="badge badge-danger">${t('exec.failed')}</span>`,
        'partial': `<span class="badge badge-warning">${t('exec.partial')}</span>`,
        'pending': `<span class="badge badge-secondary">${t('exec.pending')}</span>`,
        'skipped_orphan': `<span class="badge badge-dark" title="${t('exec.orphan_tip')}">${t('exec.orphan')}</span>`
    };
    return map[status] || '<span class="badge badge-secondary">' + status + '</span>';
}

function getLinkStatusBadge(linkStatus, execStatus, targetDokob) {
    // If not uploaded yet or no mapping, show dash
    if (!execStatus || execStatus === 'pending' || execStatus === 'failed') {
        return '<span class="text-muted">—</span>';
    }
    if (!targetDokob) {
        return `<span class="badge badge-light" title="${t('link.skipped_tip')}">—</span>`;
    }
    const map = {
        'pending': `<span class="badge badge-secondary" title="${t('link.open_tip')}"><i class="fas fa-clock"></i> ${t('link.open')}</span>`,
        'linking': `<span class="badge badge-info" title="${t('link.linking_tip')}"><i class="fas fa-spinner fa-spin"></i> ${t('link.linking')}</span>`,
        'linked': `<span class="badge badge-success" title="${t('link.linked_tip')}"><i class="fas fa-check"></i> ${t('link.linked')}</span>`,
        'link_exists': `<span class="badge badge-success" title="${t('link.exists_tip')}"><i class="fas fa-check-double"></i> ${t('link.exists')}</span>`,
        'link_failed': `<span class="badge badge-danger" title="${t('link.error_tip')}"><i class="fas fa-times"></i> ${t('link.error')}</span>`,
        'skipped': `<span class="badge badge-light" title="${t('link.skipped_tip')}">${t('link.skipped')}</span>`
    };
    return map[linkStatus] || '<span class="badge badge-secondary">' + (linkStatus || 'pending') + '</span>';
}

function getErrorCategoryBadge(category) {
    if (!category) return '-';
    const categoryDetails = getErrorCategoryDetails();
    const info = categoryDetails[category] || { desc: category, class: 'badge-secondary' };
    return `<span class="badge ${info.class}" title="${category}">${info.desc}</span>`;
}

function formatFileSizeWithColor(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes)) return '-';
    const sizeText = formatFileSize(bytes);
    const sizeMB = bytes / (1024 * 1024);
    
    if (sizeMB > 99) {
        // Red: high risk of failure (>99MB)
        return `<span class="text-danger font-weight-bold" title="${t('filesize.high_risk')}">${sizeText} ⚠️</span>`;
    } else if (sizeMB > 10) {
        // Orange: moderate risk (10-99MB)
        return `<span class="text-warning" title="${t('filesize.medium')}">${sizeText}</span>`;
    } else {
        // Green: safe size (≤10MB)
        return `<span class="text-success" title="${t('filesize.safe')}">${sizeText}</span>`;
    }
}

function formatFileCount(record) {
    const src = record.source_file_count;
    const tgt = record.target_file_count;
    if (src === null && tgt === null) return '-';
    const srcStr = (src !== null && src !== undefined) ? src : '-';
    const tgtStr = (tgt !== null && tgt !== undefined) ? tgt : '-';
    if (src !== null && tgt !== null && src === tgt) {
        return `<span class="text-success" title="${t('prev.tip.file_count', {src: src, tgt: tgt})}">${srcStr} / ${tgtStr} ✓</span>`;
    } else if (src !== null && tgt !== null && src !== tgt) {
        return `<span class="text-danger font-weight-bold" title="${t('prev.tip.file_count_mismatch', {src: src, tgt: tgt})}">${srcStr} / ${tgtStr} ✗</span>`;
    }
    return `${srcStr} / ${tgtStr}`;
}

function formatLinkCount(record) {
    const src = record.source_link_count;
    const excl = record.excluded_link_count;
    const tgt = record.target_link_count;
    if (src === null || src === undefined) return '-';
    const exclStr = (excl !== null && excl !== undefined) ? excl : 0;
    const tgtStr = (tgt !== null && tgt !== undefined) ? tgt : src;
    // No exclusions: all green
    if (exclStr === 0) {
        return `<span class="text-success" title="Source: ${src}, Excluded: 0, Target: ${tgtStr}">${src} / 0 / ${tgtStr} ✓</span>`;
    }
    // All links excluded: red — record will be skipped during execute
    if (tgtStr === 0) {
        return `<span class="text-danger font-weight-bold" title="${t('prev.tip.all_links_excluded', {n: src})}">${src} / ${exclStr} / 0 ⊘</span>`;
    }
    // Partial exclusion: orange
    return `<span class="text-warning font-weight-bold" title="${t('prev.tip.partial_excluded', {src: src, excl: exclStr, tgt: tgtStr})}">${src} / ${exclStr} / ${tgtStr} ⚠</span>`;
}

function toggleSelection(id) {
    if (selectedRecords.has(id)) {
        selectedRecords.delete(id);
    } else {
        selectedRecords.add(id);
    }
    updateSelectionInfo();
}

function selectAll() {
    const checkboxes = document.querySelectorAll('.record-checkbox:not([disabled])');
    const allSelected = Array.from(checkboxes).every(cb => cb.checked);
    
    checkboxes.forEach(cb => {
        cb.checked = !allSelected;
        const id = parseInt(cb.dataset.id);
        if (!allSelected) {
            selectedRecords.add(id);
        } else {
            selectedRecords.delete(id);
        }
    });
    
    updateSelectionInfo();
}

function updateSelectionInfo() {
    document.getElementById('selectionInfo').textContent = t('prev.records_selected', {n: selectedRecords.size});
    document.getElementById('executeSelectedBtn').disabled = selectedRecords.size === 0;
}

/**
 * Auto-reconnect: on page load, check if this batch is currently executing.
 * If so, resume the progress bar and polling so the user can pick up
 * where they left off (e.g. after sleep mode or browser refresh).
 */
function checkAndReconnectExecution() {
    fetch(`/batch/${batchId}/progress`)
        .then(r => r.json())
        .then(data => {
            if (data.success && data.is_running) {
                console.log('[reconnect] Batch is executing, resuming progress display');
                // Disable execute button + show cancel button
                const btn = document.getElementById('executeBtn');
                const cancelBtn = document.getElementById('cancelBtn');
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t('mig.executing');
                }
                if (cancelBtn) cancelBtn.style.display = 'inline-block';
                // Start progress polling
                startProgressPolling();
                // We don't have the original start time, estimate from progress
                if (data.executed > 0) {
                    executionStartTime = Date.now() - 2000; // rough estimate
                }
            }
        })
        .catch(() => { /* ignore */ });
}

function showProgressBar() {
    // Create progress bar if not exists
    let progressDiv = document.getElementById('executionProgress');
    if (!progressDiv) {
        progressDiv = document.createElement('div');
        progressDiv.id = 'executionProgress';
        progressDiv.className = 'alert alert-info mt-2';
        progressDiv.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-2">
                <strong><i class="fas fa-sync fa-spin"></i> ${t('mig.running')}</strong>
                <span id="progressStats">0 / 0</span>
            </div>
            <div class="progress" style="height: 25px;">
                <div id="progressBar" class="progress-bar progress-bar-striped progress-bar-animated" 
                     role="progressbar" style="width: 0%">0%</div>
            </div>
            <div class="d-flex justify-content-between mt-2">
                <small id="progressDetails">${t('mig.starting')}</small>
                <small id="progressETA">${t('mig.eta_calc')}</small>
            </div>
            <div class="text-end mt-1">
                <small id="progressPulse" class="text-muted"><i class="fas fa-circle text-success" style="font-size:6px;vertical-align:middle"></i> ${t('mig.polling')}</small>
            </div>
        `;
        document.getElementById('batchStats').parentNode.appendChild(progressDiv);
    }
    progressDiv.style.display = 'block';
    executionStartTime = Date.now();
}

function hideProgressBar() {
    const progressDiv = document.getElementById('executionProgress');
    if (progressDiv) {
        progressDiv.style.display = 'none';
    }
}

function updateProgressDisplay(data) {
    const bar = document.getElementById('progressBar');
    const stats = document.getElementById('progressStats');
    const details = document.getElementById('progressDetails');
    const eta = document.getElementById('progressETA');
    
    if (!bar) return;
    
    // Update pulse indicator with timestamp
    const pulse = document.getElementById('progressPulse');
    if (pulse) {
        const now = new Date().toLocaleTimeString('de-DE');
        pulse.innerHTML = `<i class="fas fa-circle text-success" style="font-size:6px;vertical-align:middle;animation:pulse 1s infinite"></i> ${t('mig.last_updated', {time: now})}`;
    }
    
    const pct = data.progress_pct || 0;
    bar.style.width = pct + '%';
    bar.textContent = pct.toFixed(1) + '%';
    
    // Update color based on progress
    bar.className = 'progress-bar progress-bar-striped progress-bar-animated';
    if (data.failed > 0) bar.classList.add('bg-warning');
    else bar.classList.add('bg-success');
    
    stats.textContent = `${data.executed} / ${data.total}`;
    
    // Build details with optional partial count
    let detailsHtml = `<span class="text-success">✓ ${data.successful}</span>`;
    if (data.partial && data.partial > 0) {
        detailsHtml += ` | <span class="text-warning">⚠ ${data.partial}</span>`;
    }
    detailsHtml += ` | <span class="text-danger">✗ ${data.failed}</span> | ${t('mig.remaining', {n: data.remaining})}`;
    details.innerHTML = detailsHtml;
    
    // Calculate ETA
    if (data.executed > 0 && executionStartTime) {
        const elapsed = (Date.now() - executionStartTime) / 1000;
        const rate = data.executed / elapsed;
        const etaSeconds = data.remaining / rate;
        
        if (etaSeconds > 3600) {
            eta.textContent = `ETA: ${Math.floor(etaSeconds/3600)}h ${Math.round((etaSeconds%3600)/60)}m`;
        } else if (etaSeconds > 60) {
            eta.textContent = `ETA: ${Math.round(etaSeconds/60)}m ${Math.round(etaSeconds%60)}s`;
        } else {
            eta.textContent = `ETA: ${Math.round(etaSeconds)}s`;
        }
    }
}

function pollProgress() {
    fetch(`/batch/${batchId}/progress`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Update display for any status that has progress data
                if (data.total > 0) {
                    updateProgressDisplay(data);
                }
                
                // Show waiting message if not yet executing
                if (data.status === 'executing' || data.is_running) {
                    // Still running — keep polling
                } else if (data.status === 'completed' || data.status === 'completed_with_errors' || 
                           data.status === 'stopped' || data.status === 'failed') {
                    // Migration finished — clean up UI
                    stopProgressPolling();
                    
                    const btn = document.getElementById('executeBtn');
                    const cancelBtn = document.getElementById('cancelBtn');
                    const retryBtn = document.getElementById('retryBtn');
                    
                    // Show final summary (only once)
                    if (!completionAlertShown) {
                        completionAlertShown = true;
                        if (data.status === 'stopped' && data.background_result && data.background_result.stopped) {
                            const r = data.background_result;
                            let message = t('mig.stopped') + `\n\n`;
                            message += `${t('mig.reason')} ${r.stop_reason}\n`;
                            message += `${t('mig.processed')} ${r.processed}/${r.total}\n`;
                            message += `${t('mig.successful')} ${r.successful}\n${t('mig.failed')} ${r.failed}\n`;
                            message += `${t('mig.remaining2')} ${r.remaining}`;
                            if (r.circuit_breaker_tripped) {
                                message += '\n\n⚠️ ' + t('mig.token_expired');
                            }
                            alert(message);
                        } else if (data.status === 'completed' || data.status === 'completed_with_errors') {
                            alert(t('mig.completed') + `\n\n${t('mig.total_label')} ${data.total}\n${t('mig.successful')} ${data.successful}\n${t('mig.failed')} ${data.failed}`);
                        }
                    }
                    
                    // Reset UI
                    hideProgressBar();
                    if (cancelBtn) cancelBtn.style.display = 'none';
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-play"></i> ' + t('prev.btn.execute_all');
                    }
                    // Also reset execute-selected button
                    const selBtn = document.getElementById('executeSelectedBtn');
                    if (selBtn) {
                        selBtn.disabled = selectedRecords.size === 0;
                        selBtn.innerHTML = '<i class="fas fa-play-circle"></i> ' + t('prev.btn.execute_selected');
                    }
                    // Also reset retry button
                    if (retryBtn) {
                        retryBtn.disabled = false;
                        retryBtn.innerHTML = '<i class="fas fa-redo"></i> ' + t('prev.btn.retry_failed');
                    }
                    loadRecords();
                } else {
                    // Other status (e.g. 'pending', 'linking') — show status text
                    const details = document.getElementById('progressDetails');
                    if (details) {
                        details.textContent = `Status: ${data.status}`;
                    }
                }
            }
        })
        .catch(err => console.error('Progress poll error:', err));
}

function startProgressPolling() {
    // Prevent duplicate polling
    if (progressInterval || pollingTimeoutId) {
        console.log('[polling] Already running, skipping duplicate start');
        return;
    }
    showProgressBar();
    completionAlertShown = false; // Reset flag when starting new polling
    // Delay polling to give server time to reset counters and start execution
    pollingTimeoutId = setTimeout(() => {
        pollingTimeoutId = null;
        progressInterval = setInterval(pollProgress, 1000); // Poll every 1 second
        pollProgress(); // Initial poll after delay
    }, 2000); // Wait 2 seconds before first poll
}

function stopProgressPolling() {
    // Clear the delayed start timeout
    if (pollingTimeoutId) {
        clearTimeout(pollingTimeoutId);
        pollingTimeoutId = null;
    }
    // Clear the interval
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
}

function executeAll() {
    if (!confirm(t('mig.confirm_all'))) {
        return;
    }
    
    const btn = document.getElementById('executeBtn');
    const cancelBtn = document.getElementById('cancelBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t('mig.executing');
    
    // Show cancel button during execution
    cancelBtn.style.display = 'inline-block';
    
    fetch('/execute', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ batch_id: batchId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.background) {
            // Background execution started - switch to polling mode
            console.log('[execute] Background migration started, polling for progress');
            startProgressPolling();
            // Frontend will be cleaned up by pollProgress() when batch finishes
        } else if (data.login_required) {
            alert('⚠️ ' + t('mig.not_logged_in'));
            window.location.href = '/';
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play"></i> ' + t('prev.btn.execute_all');
            cancelBtn.style.display = 'none';
        } else if (data.already_running) {
            alert('⚠️ ' + t('mig.already_running') + '\n\n' + data.error + '\n\n' + t('mig.wait_for_completion'));
            // Still start polling to show progress of the running migration
            startProgressPolling();
        } else {
            alert(t('mig.failed_msg', {msg: data.error}));
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play"></i> ' + t('prev.btn.execute_all');
            cancelBtn.style.display = 'none';
        }
    })
    .catch(error => {
        cancelBtn.style.display = 'none';
        alert(t('mig.error_msg', {msg: error}));
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play"></i> ' + t('prev.btn.execute_all');
    });
}

function cancelMigration() {
    if (!confirm(t('mig.cancel_confirm'))) {
        return;
    }
    
    const cancelBtn = document.getElementById('cancelBtn');
    cancelBtn.disabled = true;
    cancelBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t('mig.cancelling');
    
    fetch(`/batch/${batchId}/cancel`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update button to show cancellation is in progress
            cancelBtn.innerHTML = '<i class="fas fa-hourglass-half"></i> ' + t('mig.cancel_requested');
            // The actual stop will be handled when executeAll returns
        } else {
            alert(t('mig.cancel_failed', {msg: data.error}));
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = '<i class="fas fa-stop"></i> ' + t('prev.btn.cancel_migration');
        }
    })
    .catch(error => {
        alert(t('mig.cancel_error', {msg: error}));
        cancelBtn.disabled = false;
        cancelBtn.innerHTML = '<i class="fas fa-stop"></i> ' + t('prev.btn.cancel_migration');
    });
}

function executeSelected() {
    if (selectedRecords.size === 0) {
        alert(t('mig.select_records'));
        return;
    }
    
    if (!confirm(t('mig.confirm_selected', {n: selectedRecords.size}))) {
        return;
    }
    
    const btn = document.getElementById('executeSelectedBtn');
    btn.disabled = true;
    const totalSelected = selectedRecords.size;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${t('mig.executing_n', {n: totalSelected})}`;
    
    const cancelBtn = document.getElementById('cancelBtn');
    cancelBtn.style.display = 'inline-block';
    
    fetch('/execute_selected', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
            batch_id: batchId,
            record_ids: Array.from(selectedRecords)
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.background) {
            // Background execution started — switch to polling mode
            console.log('[execute_selected] Background migration started, polling for progress');
            startProgressPolling();
            selectedRecords.clear();
        } else if (data.login_required) {
            alert('⚠️ ' + t('mig.not_logged_in'));
            window.location.href = '/';
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play-circle"></i> ' + t('prev.btn.execute_selected');
            cancelBtn.style.display = 'none';
        } else if (data.already_running) {
            alert('⚠️ ' + t('mig.already_running') + '\n\n' + data.error);
            startProgressPolling();
        } else {
            alert(t('mig.failed_msg', {msg: data.error}));
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play-circle"></i> ' + t('prev.btn.execute_selected');
            cancelBtn.style.display = 'none';
        }
    })
    .catch(error => {
        cancelBtn.style.display = 'none';
        alert(t('mig.error_msg', {msg: error}));
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play-circle"></i> ' + t('prev.btn.execute_selected');
    });
}

function viewRecordDetail(recordId) {
    $('#detailModal').modal('show');
    $('#detailContent').html(`<div class="text-center"><div class="spinner-border" role="status"></div><p class="text-muted mt-2">${t('detail.loading')}</p></div>`);
    
    // Fetch record details from results API
    fetch(`/batch/${batchId}/results`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const record = data.results.find(r => r.id === recordId);
                if (record) {
                    displayRecordDetail(record);
                } else {
                    $('#detailContent').html(`<div class="alert alert-warning">${t('detail.record_not_found')}</div>`);
                }
            } else {
                $('#detailContent').html(`<div class="alert alert-danger">${t('detail.load_error', {msg: data.error})}</div>`);
            }
        })
        .catch(error => {
            $('#detailContent').html(`<div class="alert alert-danger">${t('detail.load_error', {msg: error})}</div>`);
        });
}

function displayRecordDetail(record) {
    let html = '<div class="row">';
    
    // Document Information
    html += `<div class="col-md-6"><h6 class="text-primary">${t('detail.doc_info')}</h6>`;
    html += `<table class="table table-sm table-bordered">`;
    html += `<tr><th>ID</th><td>${record.id}</td></tr>`;
    html += `<tr><th>${t('detail.source_doc')}</th><td><code>${record.source_documentnumber}</code></td></tr>`;
    html += `<tr><th>${t('detail.target_doc')}</th><td><code>${record.target_documentnumber || '-'}</code></td></tr>`;
    html += `<tr><th>${t('detail.doc_type')}</th><td>${record.source_documenttype}</td></tr>`;
    html += `<tr><th>${t('detail.description')}</th><td>${record.source_description || '-'}</td></tr>`;
    html += `<tr><th>${t('detail.source_auth_group')}</th><td>${record.source_authorization_group || '-'}</td></tr>`;
    html += `<tr><th>${t('detail.target_auth_group')}</th><td>${record.authorization_group || '-'}</td></tr>`;
    html += `</table></div>`;
    
    // Execution Information
    html += `<div class="col-md-6"><h6 class="text-primary">${t('detail.exec_info')}</h6>`;
    html += `<table class="table table-sm table-bordered">`;
    html += `<tr><th>Status</th><td>${getExecutionBadge(record.execution_status)}</td></tr>`;
    html += `<tr><th>${t('detail.started')}</th><td>${record.execution_started_at ? new Date(record.execution_started_at).toLocaleString() : '-'}</td></tr>`;
    html += `<tr><th>${t('detail.completed')}</th><td>${record.execution_completed_at ? new Date(record.execution_completed_at).toLocaleString() : '-'}</td></tr>`;
    html += `<tr><th>${t('detail.file')}</th><td>${record.filename || '-'}</td></tr>`;
    html += `<tr><th>${t('detail.files')}</th><td>${formatFileCount(record)}</td></tr>`;
    html += `<tr><th>${t('detail.objlinks')}</th><td>${formatLinkCount(record)}</td></tr>`;
    html += `<tr><th>${t('detail.mime_type')}</th><td>${record.mime_type || '-'}</td></tr>`;
    html += `</table></div>`;
    
    html += '</div>';
    
    // Execution Error
    if (record.execution_error) {
        html += `<div class="row mt-3"><div class="col-12"><h6 class="text-danger">${t('detail.exec_error')}</h6>`;
        let errorContent = '';
        if (typeof record.execution_error === 'object') {
            errorContent = JSON.stringify(record.execution_error, null, 2);
        } else {
            errorContent = record.execution_error;
        }
        html += `<pre class="alert alert-danger" style="white-space: pre-wrap; max-height: 300px; overflow-y: auto;">${escapeHtml(errorContent)}</pre></div></div>`;
    }
    
    $('#detailContent').html(html);
}

function excludeLargeFiles(checked) {
    // Find records with file_size_bytes > 99MB
    const largeRecords = allRecords.filter(r => {
        const bytes = r.file_size_bytes;
        return bytes !== null && bytes !== undefined && (bytes / (1024 * 1024)) > 99;
    });
    
    if (largeRecords.length === 0) {
        alert(t('mig.no_99mb'));
        document.getElementById('excludeLargeCheckbox').checked = false;
        return;
    }
    
    const totalMB = largeRecords.reduce((sum, r) => sum + (r.file_size_bytes / (1024 * 1024)), 0);
    
    if (checked) {
        if (!confirm(t('mig.exclude_99mb', {n: largeRecords.length}) + `\n\nGesamtgr\u00f6\u00dfe: ${totalMB.toFixed(1)} MB\n\n` + t('mig.excluded_ok'))) {
            document.getElementById('excludeLargeCheckbox').checked = false;
            return;
        }
    } else {
        if (!confirm(t('mig.include_99mb', {n: largeRecords.length}))) {
            document.getElementById('excludeLargeCheckbox').checked = true;
            return;
        }
    }
    
    const label = document.getElementById('excludeLargeLabel');
    const checkbox = document.getElementById('excludeLargeCheckbox');
    checkbox.disabled = true;
    
    const recordIds = largeRecords.map(r => r.id);
    
    fetch('/skip_records', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
            batch_id: batchId,
            record_ids: recordIds,
            skip: checked,
            reason: checked ? 'File size exceeds 99MB limit' : ''
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(checked ? `${data.updated} ${t('mig.excluded_ok')}` : `${data.updated} ${t('mig.included_ok')}`);
            loadRecords();
        } else {
            alert(t('error_prefix') + data.error);
            checkbox.checked = !checked; // revert
        }
        checkbox.disabled = false;
    })
    .catch(error => {
        alert(t('mig.exclude_error', {msg: error}));
        checkbox.checked = !checked; // revert
        checkbox.disabled = false;
    });
}

function resetFailed() {
    if (!confirm(t('mig.reset_confirm'))) {
        return;
    }
    
    const btn = document.getElementById('resetBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t('mig.resetting');
    
    fetch('/reset_failed', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ batch_id: batchId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(t('mig.reset_done') + `\n\n${data.reset_count} ${t('prev.btn.reset_failed')}`);
            loadRecords();
        } else {
            alert(t('mig.reset_failed', {msg: data.error}));
        }
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-undo"></i> ' + t('prev.btn.reset_failed');
    })
    .catch(error => {
        alert(t('mig.reset_error', {msg: error}));
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-undo"></i> ' + t('prev.btn.reset_failed');
    });
}

function refreshData() {
    if (!confirm(t('mig.refresh_confirm'))) {
        return;
    }
    
    const btn = document.getElementById('refreshDataBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t('loading');
    
    // Use SSE for progress updates
    const eventSource = new EventSource(`/batch/${batchId}/refresh-data-stream`);
    
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        
        if (data.type === 'status') {
            btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${data.message}`;
        } else if (data.type === 'progress') {
            const pct = data.percent || 0;
            btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${pct}% ${data.message}`;
        } else if (data.type === 'complete') {
            eventSource.close();
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Data';
            
            let message = `Refresh Complete!\n\n`;
            message += `✓ ${t('mig.metadata_updated')} ${data.metadata_updated || 0}\n`;
            message += `✓ ${t('mig.filenames_found')} ${data.filenames_found || 0}\n`;
            message += `✓ ${t('mig.rules_applied')} ${data.rules_applied || 0}\n`;
            
            if (data.links_excluded !== undefined) {
                message += `✓ ${t('mig.objlinks_checked')} ${data.links_excluded || 0} exkludiert\n`;
                if (data.records_zero_links > 0) {
                    message += `⚠ ${data.records_zero_links} ${t('mig.orphan_warning')}\n`;
                }
            }
            
            if (data.total_size_mb) {
                message += `\n📊 ${t('mig.total_size')} ${data.total_size_mb} MB\n`;
                message += `📊 ${t('mig.largest_file')} ${data.max_file_mb} MB\n`;
            }
            
            alert(message);
            loadRecords();  // Reload to show updated data
        } else if (data.type === 'error') {
            eventSource.close();
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Data';
            alert(t('mig.refresh_failed', {msg: data.message}));
        }
    };
    
    eventSource.onerror = function(error) {
        eventSource.close();
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Data';
        alert(t('mig.refresh_conn_error'));
    };
}

function retryFailed() {
    if (!confirm(t('mig.retry_confirm'))) {
        return;
    }
    
    const btn = document.getElementById('retryBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t('mig.resetting');
    
    // Step 1: Reset failed records to pending
    fetch('/reset_failed', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ batch_id: batchId })
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            throw new Error(data.error || 'Failed to reset records');
        }
        
        const resetCount = data.reset_count;
        if (resetCount === 0) {
            alert(t('mig.retry_none'));
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-redo"></i> ' + t('prev.btn.retry_failed');
            return;
        }
        
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t('mig.retrying_n', {n: resetCount});
        
        // Step 2: Show progress bar and start polling
        showProgressBar();
        document.getElementById('progressStats').textContent = t('mig.retry_starting', {n: resetCount});
        document.getElementById('progressBar').style.width = '0%';
        document.getElementById('progressBar').textContent = '0%';
        document.getElementById('progressDetails').textContent = t('mig.retry_init');
        document.getElementById('progressETA').textContent = t('mig.eta_calc');
        startProgressPolling();
        
        // Step 3: Execute the pending (reset) records
        return fetch('/execute', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ batch_id: batchId })
        });
    })
    .then(response => {
        if (response) return response.json();
    })
    .then(data => {
        if (!data) return; // No reset happened
        
        // Background execution started - let polling handle completion
        if (data.background) {
            console.log('[retry] Background migration started, polling for progress');
            // Polling is already running, just let it handle everything
            return;
        }
        
        // Non-background response (error cases)
        stopProgressPolling();
        hideProgressBar();
        
        if (data.success) {
            alert(t('mig.retry_done') + `\n\n${t('mig.total_label')} ${data.total}\n${t('mig.successful')} ${data.successful}\n${t('mig.failed')} ${data.failed}`);
            loadRecords();
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-redo"></i> ' + t('prev.btn.retry_failed');
        } else if (data.login_required) {
            alert('⚠️ ' + t('mig.not_logged_in'));
            window.location.href = '/';
        } else if (data.already_running) {
            alert('⚠️ ' + t('mig.already_running') + '\n\n' + data.error);
            // Polling is already running from the initial start, continue showing progress
        } else {
            alert(t('mig.retry_failed', {msg: data.error}));
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-redo"></i> ' + t('prev.btn.retry_failed');
        }
    })
    .catch(error => {
        stopProgressPolling();
        hideProgressBar();
        alert(t('mig.retry_error', {msg: error}));
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-redo"></i> ' + t('prev.btn.retry_failed');
    });
}

function setAblageFilter(filter) {
    currentAblageFilter = filter;
    // Update button active states
    document.querySelectorAll('#ablageFilterGroup .btn').forEach(btn => btn.classList.remove('active'));
    event.target.closest('.btn').classList.add('active');
    // Reload from server with ablage filter applied to ALL staging records
    loadRecordsWithAllFilters();
}

function applyFilters() {
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const statusFilter = document.getElementById('statusFilter').value;
    const errorCategoryFilter = document.getElementById('errorCategoryFilter').value;
    
    const filtered = allRecords.filter(record => {
        // Text search filter
        const matchesSearch = !searchTerm || (
            record.source_documentnumber.toLowerCase().includes(searchTerm) ||
            (record.target_documentnumber && record.target_documentnumber.toLowerCase().includes(searchTerm)) ||
            (record.source_description && record.source_description.toLowerCase().includes(searchTerm)) ||
            (record.source_dokob && record.source_dokob.toLowerCase().includes(searchTerm)) ||
            (record.source_objky && record.source_objky.toLowerCase().includes(searchTerm)) ||
            (record.filename && record.filename.toLowerCase().includes(searchTerm))
        );
        
        // Ablage filter (KPRO/DB)
        const matchesAblage = !currentAblageFilter || (record.ablage || 'KPRO') === currentAblageFilter;
        
        // Status filter
        let matchesStatus = true;
        if (statusFilter === 'hide_completed') {
            // Hide success and partial - show only pending and failed
            matchesStatus = record.execution_status === 'pending' || record.execution_status === 'failed';
        } else if (statusFilter) {
            matchesStatus = record.execution_status === statusFilter;
        }
        
        // Error category filter
        let matchesErrorCategory = true;
        if (errorCategoryFilter) {
            matchesErrorCategory = record.error_category === errorCategoryFilter;
        }
        
        return matchesSearch && matchesAblage && matchesStatus && matchesErrorCategory;
    });
    
    displayRecords(filtered);
    
    // Update statistics to reflect filtered records
    updateBatchStatistics(filtered);
    
    // Update filter info on the left side
    const filterInfo = document.getElementById('filterInfo');
    if (filtered.length < allRecords.length) {
        filterInfo.textContent = t('prev.showing_filtered', {n: filtered.length, total: allRecords.length});
    } else {
        filterInfo.textContent = t('prev.n_records', {n: allRecords.length});
    }
}

function filterRecords(searchTerm) {
    // Legacy function - call applyFilters instead
    applyFilters();
}

function parseObjectLinks(record) {
    // Parse source_object_links JSON, fall back to single dokob/objky
    if (record.source_object_links) {
        try {
            const links = JSON.parse(record.source_object_links);
            if (Array.isArray(links) && links.length > 0) return links;
        } catch(e) {}
    }
    // Fallback: single entry from primary columns
    if (record.source_dokob || record.source_objky) {
        return [{ dokob: record.source_dokob || '', objky: record.source_objky || '' }];
    }
    return [];
}

function formatDokob(record) {
    const links = parseObjectLinks(record);
    if (links.length === 0) return '-';
    if (links.length === 1) return links[0].dokob || '-';
    // Multiple: show first + badge with count
    const unique_types = [...new Set(links.map(l => l.dokob))];
    return unique_types.join(', ') + ` <span class="badge badge-secondary" title="${links.length} Object-Links">${links.length}x</span>`;
}

function formatObjky(record) {
    const links = parseObjectLinks(record);
    if (links.length === 0) return '-';
    if (links.length === 1) return truncate(links[0].objky, 25);
    // Multiple: show first + badge
    return truncate(links[0].objky, 20) + ` <span class="badge badge-secondary" title="${links.map(l => l.objky).join('\n')}">+${links.length - 1}</span>`;
}

function showError(message) {
    console.error(message);
    const tbody = document.getElementById('recordsBody');
    tbody.innerHTML = `<tr><td colspan="19" class="text-danger">${message}</td></tr>`;
}
