// ─── Custom Badges & Sorting (localStorage) ────────────────────────

const BADGE_COLORS = [
    'badge-primary', 'badge-secondary', 'badge-success', 'badge-danger',
    'badge-warning', 'badge-info', 'badge-dark', 'badge-light'
];
const BADGE_COLOR_LABELS = {
    'badge-primary': 'Blau', 'badge-secondary': 'Grau', 'badge-success': 'Grün',
    'badge-danger': 'Rot', 'badge-warning': 'Gelb', 'badge-info': 'Cyan',
    'badge-dark': 'Dunkel', 'badge-light': 'Hell'
};

function _badgeStoreKey(section) { return 'dms_badges_' + section; }
function _sortStoreKey(section) { return 'dms_sort_' + section; }

function loadBadges(section) {
    try { return JSON.parse(localStorage.getItem(_badgeStoreKey(section))) || {}; } catch(e) { return {}; }
}
function saveBadges(section, data) {
    localStorage.setItem(_badgeStoreKey(section), JSON.stringify(data));
}
function getBadgesFor(section, systemId) {
    return (loadBadges(section)[systemId] || []);
}
function setBadgesFor(section, systemId, badges) {
    const all = loadBadges(section);
    all[systemId] = badges;
    saveBadges(section, all);
}

function loadSortPref(section) {
    try { return JSON.parse(localStorage.getItem(_sortStoreKey(section))) || { field: 'name', dir: 'asc' }; } catch(e) { return { field: 'name', dir: 'asc' }; }
}
function saveSortPref(section, pref) {
    localStorage.setItem(_sortStoreKey(section), JSON.stringify(pref));
}

function renderCustomBadges(section, systemId) {
    const badges = getBadgesFor(section, systemId);
    return badges.map(b =>
        `<span class="badge ${escapeHtml(b.color)} ml-1" style="cursor:pointer;" title="${t('set.badge.click_edit')}" onclick="openBadgeEditor('${section}','${systemId}')">${escapeHtml(b.text)}</span>`
    ).join('');
}

function openBadgeEditor(section, systemId) {
    // Remove any existing editor
    const existingEditor = document.getElementById('badge-editor-overlay');
    if (existingEditor) existingEditor.remove();

    const badges = getBadgesFor(section, systemId);

    const overlay = document.createElement('div');
    overlay.id = 'badge-editor-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

    let badgeRows = '';
    badges.forEach((b, i) => {
        const colorOptions = BADGE_COLORS.map(c =>
            `<option value="${c}" ${b.color === c ? 'selected' : ''}>${BADGE_COLOR_LABELS[c]}</option>`
        ).join('');
        badgeRows += `
            <div class="form-row mb-2 badge-edit-row" data-idx="${i}">
                <div class="col-md-5">
                    <input type="text" class="form-control form-control-sm badge-edit-text" value="${escapeHtml(b.text)}" maxlength="30" placeholder="${t('set.badge.text_ph')}">
                </div>
                <div class="col-md-4">
                    <select class="form-control form-control-sm badge-edit-color">${colorOptions}</select>
                </div>
                <div class="col-md-3">
                    <button class="btn btn-sm btn-outline-danger" onclick="this.closest('.badge-edit-row').remove()"><i class="fas fa-trash"></i></button>
                    <span class="badge badge-preview ml-1"></span>
                </div>
            </div>`;
    });

    overlay.innerHTML = `
        <div class="card" style="min-width:450px;max-width:550px;">
            <div class="card-header bg-dark text-white py-2">
                <strong><i class="fas fa-tags"></i> ${t('set.badge.edit_title')} – ${systemId.toUpperCase()}</strong>
                <button class="btn btn-sm btn-outline-light float-right" onclick="document.getElementById('badge-editor-overlay').remove()"><i class="fas fa-times"></i></button>
            </div>
            <div class="card-body" id="badgeEditorBody">
                <div id="badgeEditorRows">${badgeRows}</div>
                <button class="btn btn-sm btn-outline-success mt-2" id="badgeAddBtn">
                    <i class="fas fa-plus"></i> ${t('set.badge.add')}
                </button>
            </div>
            <div class="card-footer text-right py-2">
                <button class="btn btn-primary btn-sm" id="badgeSaveBtn"><i class="fas fa-save"></i> ${t('save')}</button>
                <button class="btn btn-outline-secondary btn-sm ml-1" onclick="document.getElementById('badge-editor-overlay').remove()">${t('cancel')}</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    // Add badge button
    document.getElementById('badgeAddBtn').addEventListener('click', function() {
        const colorOptions = BADGE_COLORS.map(c =>
            `<option value="${c}">${BADGE_COLOR_LABELS[c]}</option>`
        ).join('');
        const row = document.createElement('div');
        row.className = 'form-row mb-2 badge-edit-row';
        row.innerHTML = `
            <div class="col-md-5">
                <input type="text" class="form-control form-control-sm badge-edit-text" value="" maxlength="30" placeholder="${t('set.badge.text_ph')}">
            </div>
            <div class="col-md-4">
                <select class="form-control form-control-sm badge-edit-color">${colorOptions}</select>
            </div>
            <div class="col-md-3">
                <button class="btn btn-sm btn-outline-danger" onclick="this.closest('.badge-edit-row').remove()"><i class="fas fa-trash"></i></button>
            </div>`;
        document.getElementById('badgeEditorRows').appendChild(row);
        row.querySelector('.badge-edit-text').focus();
    });

    // Save badges
    document.getElementById('badgeSaveBtn').addEventListener('click', function() {
        const rows = document.querySelectorAll('#badgeEditorRows .badge-edit-row');
        const newBadges = [];
        rows.forEach(r => {
            const txt = r.querySelector('.badge-edit-text').value.trim();
            const col = r.querySelector('.badge-edit-color').value;
            if (txt) newBadges.push({ text: txt, color: col });
        });
        setBadgesFor(section, systemId, newBadges);
        overlay.remove();
        // Refresh the section
        if (section === 'cred') loadCredentials();
        else loadSapSystems();
    });
}

function sortSystems(systems, section) {
    const pref = loadSortPref(section);
    const dir = pref.dir === 'desc' ? -1 : 1;
    return systems.slice().sort((a, b) => {
        let va, vb;
        switch (pref.field) {
            case 'type':
                va = a.system_type || ''; vb = b.system_type || '';
                break;
            case 'env':
                // Order: DEV < QUAL < PROD < empty
                const envOrder = { 'DEV': 0, 'QUAL': 1, 'PROD': 2 };
                va = envOrder[(a.environment || '').toUpperCase()] ?? 3;
                vb = envOrder[(b.environment || '').toUpperCase()] ?? 3;
                break;
            case 'status':
                // For credentials: configured first
                va = a.has_credentials ? 0 : 1; vb = b.has_credentials ? 0 : 1;
                break;
            case 'source':
                va = a.source || ''; vb = b.source || '';
                break;
            case 'auth':
                va = a.auth_type || ''; vb = b.auth_type || '';
                break;
            case 'badges':
                // Systems with custom badges first
                va = getBadgesFor(section, a.system_id).length > 0 ? 0 : 1;
                vb = getBadgesFor(section, b.system_id).length > 0 ? 0 : 1;
                break;
            default: // 'name'
                va = a.system_id || ''; vb = b.system_id || '';
        }
        if (typeof va === 'string') return va.localeCompare(vb) * dir;
        return (va - vb) * dir;
    });
}

function renderSortControls(section, containerId) {
    const pref = loadSortPref(section);
    const fields = section === 'cred'
        ? [['name', t('set.sort.name')], ['type', t('set.sort.type')], ['status', t('set.sort.status')], ['auth', 'Auth'], ['badges', t('set.sort.badges')]]
        : [['name', t('set.sort.name')], ['type', t('set.sort.type')], ['env', t('set.sort.env')], ['source', t('set.sort.source')], ['auth', 'Auth'], ['badges', t('set.sort.badges')]];

    const btns = fields.map(([f, label]) => {
        const isActive = pref.field === f;
        const arrow = isActive ? (pref.dir === 'asc' ? ' ↑' : ' ↓') : '';
        return `<button class="btn btn-xs ${isActive ? 'btn-primary' : 'btn-outline-secondary'} mr-1" onclick="toggleSort('${section}','${f}')">${label}${arrow}</button>`;
    }).join('');

    const container = document.getElementById(containerId);
    if (container) container.innerHTML = btns;
}

function toggleSort(section, field) {
    const pref = loadSortPref(section);
    if (pref.field === field) {
        pref.dir = pref.dir === 'asc' ? 'desc' : 'asc';
    } else {
        pref.field = field;
        pref.dir = 'asc';
    }
    saveSortPref(section, pref);
    if (section === 'cred') loadCredentials();
    else loadSapSystems();
}

document.addEventListener('DOMContentLoaded', function() {
    try { updateThroughput(); } catch(e) { console.error('[settings] updateThroughput failed:', e); }
    try { loadPacingStats(); } catch(e) { console.error('[settings] loadPacingStats failed:', e); }
    try { loadCredentials(); } catch(e) { console.error('[settings] loadCredentials failed:', e); }
    try { loadSapSystems(); } catch(e) { console.error('[settings] loadSapSystems failed:', e); }
    try { runHealthCheck(); } catch(e) { console.error('[settings] runHealthCheck failed:', e); }
    
    document.getElementById('maxWorkers').addEventListener('input', updateThroughput);
    document.getElementById('pacingSeconds').addEventListener('input', updateThroughput);
});

function updateThroughput() {
    const workers = parseInt(document.getElementById('maxWorkers').value) || 1;
    const pacing = parseFloat(document.getElementById('pacingSeconds').value);
    
    // Update pacing mode label
    const pacingLabel = document.getElementById('pacingModeLabel');
    if (pacing === 0) {
        pacingLabel.innerHTML = '<span class="badge badge-success">' + t('set.perf.dynamic') + '</span>';
        // For dynamic pacing, estimate average (tiny=5, small=10, medium=20, large=45) ≈ 15s average
        const avgPacing = 15;
        const throughput = (workers * (60 / avgPacing)).toFixed(1);
        document.getElementById('throughputValue').textContent = throughput + ' ' + t('set.msg.dynamic_avg');
    } else {
        pacingLabel.innerHTML = '<span class="badge badge-secondary">' + t('set.perf.fixed') + '</span>';
        const throughput = (workers * (60 / pacing)).toFixed(1);
        document.getElementById('throughputValue').textContent = throughput;
    }
}

function loadPacingStats() {
    document.getElementById('pacingStatsLoading').style.display = 'block';
    document.getElementById('pacingStatsContent').style.display = 'none';
    
    fetch('/pacing_stats')
        .then(response => response.json())
        .then(data => {
            document.getElementById('pacingStatsLoading').style.display = 'none';
            document.getElementById('pacingStatsContent').style.display = 'block';
            
            if (!data.has_data) {
                document.getElementById('pacingNoData').style.display = 'block';
                document.getElementById('pacingHasData').style.display = 'none';
                return;
            }
            
            document.getElementById('pacingNoData').style.display = 'none';
            document.getElementById('pacingHasData').style.display = 'block';
            document.getElementById('totalRecords').textContent = data.total_records;
            
            const tbody = document.getElementById('pacingTableBody');
            tbody.innerHTML = '';
            
            const bucketNames = {
                'tiny': { name: t('set.bucket.tiny'), icon: '📄', size_range: '≤ 1 MB' },
                'small': { name: t('set.bucket.small'), icon: '📁', size_range: '1 - 10 MB' },
                'medium': { name: t('set.bucket.medium'), icon: '📦', size_range: '10 - 50 MB' },
                'large': { name: t('set.bucket.large'), icon: '📚', size_range: '> 50 MB' },
                'unknown': { name: t('set.bucket.unknown'), icon: '❓', size_range: t('set.pacing_status.no_size') }
            };
            
            const bucketOrder = ['tiny', 'small', 'medium', 'large'];
            
            for (const bucket of bucketOrder) {
                const stats = data.buckets[bucket];
                if (!stats) continue;
                
                const bucketInfo = bucketNames[bucket] || { name: bucket, icon: '❓', size_range: '-' };
                const row = document.createElement('tr');
                
                // Determine status - use correct field names from Python
                const currentPacing = stats.current_pacing || 0;
                const recommendedPacing = stats.recommended_pacing || 0;
                
                let statusBadge, statusClass;
                if (stats.count === 0) {
                    statusBadge = '<span class="badge badge-secondary">' + t('set.pacing_status.none') + '</span>';
                    statusClass = '';
                } else if (recommendedPacing <= currentPacing * 0.8) {
                    statusBadge = '<span class="badge badge-success">' + t('set.pacing_status.faster') + '</span>';
                    statusClass = 'table-success';
                } else if (recommendedPacing > currentPacing) {
                    statusBadge = '<span class="badge badge-warning">' + t('set.pacing_status.increase') + '</span>';
                    statusClass = 'table-warning';
                } else {
                    statusBadge = '<span class="badge badge-info">OK</span>';
                    statusClass = '';
                }
                
                row.className = statusClass;
                row.innerHTML = `
                    <td><strong>${bucketInfo.icon} ${bucketInfo.name}</strong></td>
                    <td>${bucketInfo.size_range}</td>
                    <td>${stats.count}</td>
                    <td>${stats.count > 0 && stats.avg_time ? stats.avg_time.toFixed(1) : '-'}</td>
                    <td>${stats.count > 0 && stats.min_time ? stats.min_time.toFixed(1) : '-'}</td>
                    <td>${stats.count > 0 && stats.max_time ? stats.max_time.toFixed(1) : '-'}</td>
                    <td><strong>${currentPacing}s</strong></td>
                    <td>${stats.count > 0 ? recommendedPacing.toFixed(0) + 's' : '-'}</td>
                    <td>${statusBadge}</td>
                `;
                tbody.appendChild(row);
            }
        })
        .catch(error => {
            console.error('Error loading pacing stats:', error);
            document.getElementById('pacingStatsLoading').style.display = 'none';
            document.getElementById('pacingStatsContent').style.display = 'block';
            document.getElementById('pacingNoData').style.display = 'block';
            document.getElementById('pacingNoData').innerHTML = 
                '<i class="fas fa-exclamation-circle"></i> ' + t('set.msg.stats_error', {msg: error});
            document.getElementById('pacingHasData').style.display = 'none';
        });
}

document.getElementById('settingsForm').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const maxWorkers = parseInt(document.getElementById('maxWorkers').value);
    const pacingSeconds = parseFloat(document.getElementById('pacingSeconds').value);
    
    if (maxWorkers < 1 || maxWorkers > 50) {
        alert(t('set.msg.workers_range'));
        return;
    }
    
    if (pacingSeconds < 0 || pacingSeconds > 60) {
        alert(t('set.msg.pacing_range'));
        return;
    }
    
    fetch('/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            max_workers: maxWorkers,
            pacing_seconds: pacingSeconds
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(t('set.msg.saved'));
            document.getElementById('currentWorkers').textContent = maxWorkers;
            if (pacingSeconds === 0) {
                document.getElementById('currentPacing').innerHTML = '<span class="badge badge-success">' + t('set.perf.dynamic') + '</span> ' + t('set.msg.dynamic_info');
            } else {
                document.getElementById('currentPacing').innerHTML = '<span class="badge badge-secondary">' + t('set.perf.fixed') + '</span> ' + pacingSeconds + ' ' + t('set.msg.seconds');
            }
        } else {
            alert(t('set.msg.save_error', {msg: data.error}));
        }
    })
    .catch(error => {
        alert(t('error_prefix') + error);
    });
});

// ─── Credentials Management ─────────────────────────────────────────

function loadCredentials() {
    document.getElementById('credentialsLoading').style.display = 'block';
    document.getElementById('credentialsContent').style.display = 'none';
    
    fetch('/credentials')
        .then(response => response.json())
        .then(data => {
            document.getElementById('credentialsLoading').style.display = 'none';
            document.getElementById('credentialsContent').style.display = 'block';
            
            if (!data.success || !data.systems || data.systems.length === 0) {
                document.getElementById('credentialsNoSystems').style.display = 'block';
                document.getElementById('credentialsList').innerHTML = '';
                return;
            }
            
            document.getElementById('credentialsNoSystems').style.display = 'none';
            const container = document.getElementById('credentialsList');
            container.innerHTML = '';

            // Render sort controls
            renderSortControls('cred', 'credSortControls');

            // Sort systems
            const sortedSystems = sortSystems(data.systems, 'cred');
            
            sortedSystems.forEach(sys => {
                const card = document.createElement('div');
                card.className = 'card mb-3';
                card.id = 'cred-card-' + sys.system_id;
                
                const statusBadge = sys.has_credentials
                    ? '<span class="badge badge-success"><i class="fas fa-check"></i> ' + t('set.cred.configured') + '</span>'
                    : '<span class="badge badge-warning"><i class="fas fa-exclamation-triangle"></i> ' + t('set.cred.not_configured') + '</span>';
                
                const typeBadge = sys.is_custom
                    ? '<span class="badge badge-warning ml-1">Benutzerdefiniert</span>'
                    : sys.system_type === 'R3'
                        ? '<span class="badge badge-info ml-1">R/3 Source</span>'
                        : '<span class="badge badge-primary ml-1">S/4 Target</span>';
                
                const authBadge = sys.auth_type === 'basic'
                    ? '<span class="badge badge-dark ml-1">Basic Auth</span>'
                    : '<span class="badge badge-secondary ml-1">OAuth</span>';
                
                const userInfo = sys.has_credentials
                    ? `<span class="text-muted">${t('set.cred.user')} <strong>${sys.username}</strong></span>
                       ${sys.sap_client ? '<span class="text-muted ml-3">Mandant <strong>' + sys.sap_client + '</strong></span>' : ''}
                       ${sys.host ? '<span class="text-muted ml-3">Host <strong>' + sys.host + '</strong></span>' : ''}
                       <span class="text-muted ml-3">${t('set.cred.updated_at')} ${sys.updated_at ? new Date(sys.updated_at).toLocaleString('de-DE') : '-'}</span>
                       <span class="text-muted ml-3">${t('set.cred.updated_by')} ${sys.updated_by || '-'}</span>`
                    : '<span class="text-muted">' + t('set.cred.none') + '</span>';
                
                card.innerHTML = `
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <span>
                            <strong><i class="fas fa-server"></i> ${sys.system_id.toUpperCase()}</strong>
                            ${typeBadge}${authBadge}
                            ${renderCustomBadges('cred', sys.system_id)}
                            <button class="btn btn-xs btn-outline-secondary ml-1" onclick="openBadgeEditor('cred','${sys.system_id}')" title="${t('set.badge.edit_title')}"><i class="fas fa-tags"></i></button>
                            <small class="text-muted ml-2">${sys.description || sys.system_label}</small>
                        </span>
                        ${statusBadge}
                    </div>
                    <div class="card-body">
                        <div class="mb-2">${userInfo}</div>
                        
                        <div id="cred-form-${sys.system_id}" style="display: none;">
                            <div class="form-row mb-2">
                                <div class="col-md-6">
                                    <div class="form-group mb-1">
                                        <label><i class="fas fa-tag"></i> Beschreibung</label>
                                        <input type="text" class="form-control" id="cred-desc-${sys.system_id}" 
                                               value="${sys.description || sys.system_label}" 
                                               maxlength="200" placeholder="${sys.system_label}">
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="form-group mb-1">
                                        <label><i class="fas fa-globe"></i> Host</label>
                                        <input type="text" class="form-control" id="cred-host-${sys.system_id}" 
                                               value="${sys.host || ''}" 
                                               placeholder="z.B. zvfr3.basf.net">
                                    </div>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="col-md-3">
                                    <div class="form-group">
                                        <label><i class="fas fa-user"></i> ${t('set.cred.username')}</label>
                                        <input type="text" class="form-control" id="cred-user-${sys.system_id}" 
                                               value="${sys.has_credentials ? sys.username : ''}" 
                                               placeholder="${t('set.cred.ph_example')}" autocomplete="off">
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="form-group">
                                        <label><i class="fas fa-lock"></i> ${t('set.cred.password')}</label>
                                        <input type="password" class="form-control" id="cred-pass-${sys.system_id}" 
                                               placeholder="${sys.has_credentials ? t('set.cred.password_unchanged') : t('set.cred.password_enter')}" 
                                               autocomplete="new-password">
                                    </div>
                                </div>
                                <div class="col-md-2">
                                    <div class="form-group">
                                        <label><i class="fas fa-building"></i> Mandant</label>
                                        <input type="text" class="form-control" id="cred-client-${sys.system_id}" 
                                               value="${sys.sap_client || sys.config_client || ''}" 
                                               maxlength="3" pattern="[0-9]{3}"
                                               placeholder="100">
                                    </div>
                                </div>
                                <div class="col-md-4 d-flex align-items-end">
                                    <div class="form-group mb-0 w-100">
                                        <button class="btn btn-primary mr-1" onclick="saveCredential('${sys.system_id}')">
                                            <i class="fas fa-save"></i> ${t('save')}
                                        </button>
                                        <button class="btn btn-info mr-1" onclick="testCredential('${sys.system_id}')" 
                                                id="cred-test-btn-${sys.system_id}">
                                            <i class="fas fa-plug"></i> ${t('set.cred.test')}
                                        </button>
                                        <button class="btn btn-outline-secondary" onclick="toggleCredForm('${sys.system_id}')">
                                            ${t('cancel')}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <div id="cred-actions-${sys.system_id}">
                            <button class="btn btn-sm btn-outline-primary mr-1" onclick="toggleCredForm('${sys.system_id}')">
                                <i class="fas fa-edit"></i> ${sys.has_credentials ? t('set.cred.change') : t('set.cred.setup')}
                            </button>
                            ${sys.has_credentials ? `
                                <button class="btn btn-sm btn-outline-info mr-1" onclick="testCredential('${sys.system_id}')">
                                    <i class="fas fa-plug"></i> ${t('set.cred.test_conn')}
                                </button>
                                <button class="btn btn-sm btn-outline-danger" onclick="deleteCredential('${sys.system_id}')">
                                    <i class="fas fa-trash"></i> ${t('delete')}
                                </button>
                            ` : ''}
                        </div>
                        
                        <div id="cred-result-${sys.system_id}"></div>
                    </div>
                `;
                container.appendChild(card);
            });
        })
        .catch(error => {
            console.error('Error loading credentials:', error);
            document.getElementById('credentialsLoading').style.display = 'none';
            document.getElementById('credentialsContent').style.display = 'block';
            document.getElementById('credentialsList').innerHTML = 
                '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> ' + t('error_prefix') + error + '</div>';
        });
}

function toggleCredForm(systemId) {
    const form = document.getElementById('cred-form-' + systemId);
    const actions = document.getElementById('cred-actions-' + systemId);
    if (form.style.display === 'none') {
        form.style.display = 'block';
        actions.style.display = 'none';
    } else {
        form.style.display = 'none';
        actions.style.display = 'block';
    }
    // Clear result area
    document.getElementById('cred-result-' + systemId).innerHTML = '';
}

function saveCredential(systemId) {
    const username = document.getElementById('cred-user-' + systemId).value.trim();
    const password = document.getElementById('cred-pass-' + systemId).value;
    const clientEl = document.getElementById('cred-client-' + systemId);
    const sapClient = clientEl && !clientEl.disabled ? clientEl.value.trim() : null;
    const descEl = document.getElementById('cred-desc-' + systemId);
    const description = descEl ? descEl.value.trim() : null;
    const hostEl = document.getElementById('cred-host-' + systemId);
    const host = hostEl ? hostEl.value.trim() : null;
    
    if (!username) {
        alert(t('set.cred.required'));
        return;
    }
    if (sapClient !== null && !/^[0-9]{3}$/.test(sapClient)) {
        alert('Mandant muss 3-stellig numerisch sein (z.B. 100)');
        return;
    }
    
    const payload = { system_id: systemId, username: username, password: password };
    if (sapClient !== null) payload.sap_client = sapClient;
    if (description) payload.description = description;
    if (host) payload.host = host;
    
    fetch('/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            document.getElementById('cred-result-' + systemId).innerHTML =
                '<div class="alert alert-success mt-2"><i class="fas fa-check"></i> ' + data.message + '</div>';
            setTimeout(() => loadCredentials(), 1500);
        } else {
            document.getElementById('cred-result-' + systemId).innerHTML =
                '<div class="alert alert-danger mt-2"><i class="fas fa-times"></i> ' + data.error + '</div>';
        }
    })
    .catch(error => {
        document.getElementById('cred-result-' + systemId).innerHTML =
            '<div class="alert alert-danger mt-2"><i class="fas fa-times"></i> ' + error + '</div>';
    });
}

function testCredential(systemId) {
    const resultEl = document.getElementById('cred-result-' + systemId);
    resultEl.innerHTML = '<div class="alert alert-info mt-2"><i class="fas fa-spinner fa-spin"></i> ' + t('set.cred.testing') + '</div>';
    
    fetch('/credentials/test/' + systemId, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                resultEl.innerHTML = '<div class="alert alert-success mt-2"><i class="fas fa-check-circle"></i> ' + data.message + 
                    (data.csrf_token_received ? ' ' + t('set.cred.csrf_received') : '') +
                    (data.details ? '<br><small class="text-muted">' + data.details + '</small>' : '') + '</div>';
            } else {
                resultEl.innerHTML = '<div class="alert alert-danger mt-2"><i class="fas fa-times-circle"></i> ' + data.error +
                    (data.details ? '<br><small class="text-muted">' + data.details + '</small>' : '') +
                    (data.body ? '<br><small class="text-muted text-break">' + data.body.substring(0, 200) + '</small>' : '') + '</div>';
            }
        })
        .catch(error => {
            resultEl.innerHTML = '<div class="alert alert-danger mt-2"><i class="fas fa-times-circle"></i> ' + error + '</div>';
        });
}

function deleteCredential(systemId) {
    if (!confirm(t('set.cred.delete_confirm', {system: systemId.toUpperCase()}))) return;
    
    fetch('/credentials/' + systemId, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                loadCredentials();
            } else {
                alert(t('error_prefix') + data.error);
            }
        })
        .catch(error => alert(t('error_prefix') + error));
}

// ─── New System Credential ──────────────────────────────────────────

function toggleNewCredForm() {
    const form = document.getElementById('newCredForm');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    document.getElementById('new-cred-result').innerHTML = '';
}

function saveNewCredential() {
    const sid   = document.getElementById('new-cred-sid').value.trim().toLowerCase();
    const desc  = document.getElementById('new-cred-desc').value.trim();
    const host  = document.getElementById('new-cred-host').value.trim();
    const user  = document.getElementById('new-cred-user').value.trim();
    const pass  = document.getElementById('new-cred-pass').value;
    const client = document.getElementById('new-cred-client').value.trim();
    const resultEl = document.getElementById('new-cred-result');

    if (!sid || !/^[a-zA-Z0-9_]{2,50}$/.test(sid)) {
        resultEl.innerHTML = '<div class="alert alert-danger mt-2">System-ID ist erforderlich (Buchstaben, Ziffern, _, 2-50 Zeichen)</div>';
        return;
    }
    if (!user) {
        resultEl.innerHTML = '<div class="alert alert-danger mt-2">Benutzername ist erforderlich</div>';
        return;
    }
    if (!pass) {
        resultEl.innerHTML = '<div class="alert alert-danger mt-2">Passwort ist erforderlich</div>';
        return;
    }
    if (client && !/^[0-9]{3}$/.test(client)) {
        resultEl.innerHTML = '<div class="alert alert-danger mt-2">Mandant muss 3-stellig numerisch sein (z.B. 100)</div>';
        return;
    }

    const payload = { system_id: sid, username: user, password: pass };
    if (client) payload.sap_client = client;
    if (desc)   payload.description = desc;
    if (host)   payload.host = host;

    fetch('/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            resultEl.innerHTML = '<div class="alert alert-success mt-2"><i class="fas fa-check"></i> ' + data.message + '</div>';
            // Clear form
            document.getElementById('new-cred-sid').value = '';
            document.getElementById('new-cred-desc').value = '';
            document.getElementById('new-cred-host').value = '';
            document.getElementById('new-cred-user').value = '';
            document.getElementById('new-cred-pass').value = '';
            document.getElementById('new-cred-client').value = '';
            setTimeout(() => {
                toggleNewCredForm();
                loadCredentials();
            }, 1200);
        } else {
            resultEl.innerHTML = '<div class="alert alert-danger mt-2"><i class="fas fa-times"></i> ' + data.error + '</div>';
        }
    })
    .catch(err => {
        resultEl.innerHTML = '<div class="alert alert-danger mt-2"><i class="fas fa-times"></i> ' + err + '</div>';
    });
}

// ─── SAP System Management ──────────────────────────────────────────

let editingSystemId = null;

function loadSapSystems() {
    document.getElementById('sapSystemsLoading').style.display = 'block';
    document.getElementById('sapSystemsList').style.display = 'none';
    document.getElementById('envTabs').style.display = 'none';
    
    fetch('/sap-systems')
        .then(r => r.json())
        .then(data => {
            document.getElementById('sapSystemsLoading').style.display = 'none';
            
            if (!data.success || !data.systems || data.systems.length === 0) {
                document.getElementById('sapSystemsList').style.display = 'block';
                document.getElementById('sapSystemsList').innerHTML = 
                    '<div class="alert alert-info"><i class="fas fa-info-circle"></i> ' + t('set.sys.no_systems') + '</div>';
                document.getElementById('sysSortWrapper').style.display = 'none';
                return;
            }

            // Render sort controls
            document.getElementById('sysSortWrapper').style.display = 'block';
            renderSortControls('sys', 'sysSortControls');

            // Sort systems
            const sortedSystems = sortSystems(data.systems, 'sys');

            // Group by environment
            const envGroups = { DEV: [], QUAL: [], PROD: [], '': [] };
            sortedSystems.forEach(sys => {
                const env = (sys.environment || '').toUpperCase();
                if (envGroups[env] !== undefined) {
                    envGroups[env].push(sys);
                } else {
                    envGroups[''].push(sys);
                }
            });

            // Update tab counts
            const total = sortedSystems.length;
            document.getElementById('envCountAll').textContent = total;
            document.getElementById('envCountDev').textContent = envGroups.DEV.length;
            document.getElementById('envCountQual').textContent = envGroups.QUAL.length;
            document.getElementById('envCountProd').textContent = envGroups.PROD.length;
            document.getElementById('envCountNone').textContent = envGroups[''].length;

            // Show/hide tabs based on content
            document.getElementById('envTabs').style.display = 'flex';
            document.getElementById('env-dev-tab').parentElement.style.display = envGroups.DEV.length ? '' : 'none';
            document.getElementById('env-qual-tab').parentElement.style.display = envGroups.QUAL.length ? '' : 'none';
            document.getElementById('env-prod-tab').parentElement.style.display = envGroups.PROD.length ? '' : 'none';
            document.getElementById('env-none-tab').parentElement.style.display = envGroups[''].length ? '' : 'none';

            // Render "All" tab (ungrouped flat list)
            document.getElementById('env-all').innerHTML = _renderSystemCards(sortedSystems);

            // Render each environment tab with OAuth / Direct sub-groups
            ['DEV', 'QUAL', 'PROD', ''].forEach(env => {
                const tabId = env ? 'env-' + env.toLowerCase() : 'env-none';
                const systems = envGroups[env];
                if (systems.length === 0) {
                    document.getElementById(tabId).innerHTML = '';
                    return;
                }
                const oauth = systems.filter(s => s.auth_type !== 'basic');
                const direct = systems.filter(s => s.auth_type === 'basic');

                let html = '';
                if (oauth.length > 0) {
                    html += `<h6 class="mt-2 mb-2 text-muted"><i class="fas fa-cloud"></i> OAuth / API Gateway <span class="badge badge-secondary">${oauth.length}</span></h6>`;
                    html += _renderSystemCards(oauth);
                }
                if (direct.length > 0) {
                    html += `<h6 class="mt-3 mb-2 text-muted"><i class="fas fa-link"></i> Direct / Basic Auth <span class="badge badge-dark">${direct.length}</span></h6>`;
                    html += _renderSystemCards(direct);
                }
                document.getElementById(tabId).innerHTML = html;
            });

            // sapSystemsList is no longer needed for card display (tabs take over)
            document.getElementById('sapSystemsList').style.display = 'none';
        })
        .catch(error => {
            console.error('Error loading SAP systems:', error);
            document.getElementById('sapSystemsLoading').style.display = 'none';
            document.getElementById('sapSystemsList').style.display = 'block';
            document.getElementById('sapSystemsList').innerHTML = 
                '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> ' + error + '</div>';
        });
}

/**
 * Render an array of system objects as Bootstrap cards HTML.
 */
function _renderSystemCards(systems) {
    let html = '';
    systems.forEach(sys => {
        const typeBadge = sys.system_type === 'R3'
            ? '<span class="badge badge-info">R/3 Source</span>'
            : '<span class="badge badge-primary">S/4 Target</span>';
        
        const sourceBadge = sys.source === 'yaml' 
            ? '<span class="badge badge-secondary ml-1" title="' + t('set.sys.source_yaml') + '">YAML</span>'
            : sys.source === 'db+yaml'
            ? '<span class="badge badge-warning ml-1" title="YAML + DB Override">DB+YAML</span>'
            : '<span class="badge badge-success ml-1" title="' + t('set.sys.source_db') + '">DB</span>';
        
        const authBadge = sys.auth_type === 'basic'
            ? '<span class="badge badge-dark ml-1">Basic</span>'
            : '<span class="badge badge-secondary ml-1">OAuth</span>';
        
        const clientBadge = sys.sap_client
            ? `<span class="badge badge-light ml-1" title="SAP Mandant">Mdt ${escapeHtml(sys.sap_client)}</span>`
            : '';
        const sslBadge = sys.verify_ssl === false
            ? '<span class="badge badge-warning ml-1" title="SSL nicht verifiziert"><i class="fas fa-unlock"></i></span>'
            : '';

        const envBadge = sys.environment
            ? `<span class="badge ${sys.environment === 'PROD' ? 'badge-danger' : sys.environment === 'QUAL' ? 'badge-warning' : 'badge-info'} ml-1">${escapeHtml(sys.environment)}</span>`
            : '';

        // Build APIs table
        let apisHtml = '';
        if (sys.apis && sys.apis.length > 0) {
            apisHtml = '<table class="table table-sm table-bordered mt-2 mb-0"><thead class="thead-light"><tr>' +
                '<th>API</th><th>Label</th><th>Base URL</th><th>' + t('set.sys.source_col') + '</th><th></th></tr></thead><tbody>';
            sys.apis.forEach(api => {
                const apiSourceBadge = api.source === 'db' 
                    ? '<span class="badge badge-success">DB</span>' 
                    : '<span class="badge badge-secondary">YAML</span>';
                apisHtml += `<tr>
                    <td><code>${escapeHtml(api.api_name)}</code></td>
                    <td>${escapeHtml(api.api_label || '')}</td>
                    <td><small class="text-monospace">${escapeHtml(api.base_url)}</small></td>
                    <td>${apiSourceBadge}</td>
                    <td>
                        <button class="btn btn-xs btn-outline-danger" title="${t('set.sys.remove_api')}"
                                onclick="deleteSapApi('${escapeHtml(sys.system_id)}', '${escapeHtml(api.api_name)}')">
                            <i class="fas fa-times"></i>
                        </button>
                    </td>
                </tr>`;
            });
            apisHtml += '</tbody></table>';
        } else {
            apisHtml = '<small class="text-muted">' + t('set.sys.no_apis') + '</small>';
        }

        // Add API inline form
        const addApiFormId = 'add-api-' + sys.system_id;
        const addApiHtml = `
            <div id="${addApiFormId}" class="form-row mt-2" style="display:none;">
                <div class="col-md-2">
                    <input type="text" class="form-control form-control-sm" id="new-api-name-${sys.system_id}" placeholder="API Name">
                </div>
                <div class="col-md-2">
                    <input type="text" class="form-control form-control-sm" id="new-api-label-${sys.system_id}" placeholder="Label">
                </div>
                <div class="col-md-5">
                    <input type="text" class="form-control form-control-sm" id="new-api-url-${sys.system_id}" placeholder="Base URL">
                </div>
                <div class="col-md-3">
                    <button class="btn btn-sm btn-success mr-1" onclick="saveNewApi('${escapeHtml(sys.system_id)}')">
                        <i class="fas fa-check"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="document.getElementById('${addApiFormId}').style.display='none'">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>`;

        html += `
            <div class="card mb-3">
                <div class="card-header d-flex justify-content-between align-items-center py-2">
                    <span>
                        <span id="health-badge-${sys.system_id}" class="mr-1"></span>
                        <strong><i class="fas fa-server"></i> ${escapeHtml(sys.system_id.toUpperCase())}</strong>
                        ${typeBadge}${authBadge}${clientBadge}${sslBadge}${envBadge}${sourceBadge}
                        ${renderCustomBadges('sys', sys.system_id)}
                        <button class="btn btn-xs btn-outline-secondary ml-1" onclick="openBadgeEditor('sys','${escapeHtml(sys.system_id)}')" title="${t('set.badge.edit_title')}"><i class="fas fa-tags"></i></button>
                        <small class="text-muted ml-2">${escapeHtml(sys.system_label)}</small>
                    </span>
                    <span>
                        <small class="text-muted mr-2">${escapeHtml(sys.host || '')}</small>
                        <button class="btn btn-xs btn-outline-primary" onclick="editSystem('${escapeHtml(sys.system_id)}')" title="${t('set.sys.edit')}">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-xs btn-outline-danger ml-1" onclick="deleteSapSystem('${escapeHtml(sys.system_id)}')" title="${t('set.sys.deactivate')}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </span>
                </div>
                <div class="card-body py-2">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <small><strong>${t('set.sys.endpoints')}:</strong></small>
                        <button class="btn btn-xs btn-outline-success" onclick="document.getElementById('${addApiFormId}').style.display='flex'">
                            <i class="fas fa-plus"></i> API
                        </button>
                    </div>
                    ${apisHtml}
                    ${addApiHtml}
                    ${sys.api_key_masked ? `<small class="text-muted mt-1 d-block">API-Key: <code>${escapeHtml(sys.api_key_masked)}</code></small>` : ''}
                </div>
            </div>`;
    });
    return html;
}

function showAddSystemForm() {
    editingSystemId = null;
    document.getElementById('systemFormTitle').innerHTML = '<i class="fas fa-plus"></i> ' + t('set.sys.create');
    document.getElementById('sysId').value = '';
    document.getElementById('sysId').readOnly = false;
    document.getElementById('sysLabel').value = '';
    document.getElementById('sysType').value = 'R3';
    document.getElementById('sysHost').value = '';
    document.getElementById('sysAuth').value = 'oauth';
    document.getElementById('sysClient').value = '';
    document.getElementById('sysApiKey').value = '';
    document.getElementById('sysEnv').value = '';
    document.getElementById('sysVerifySsl').checked = true;
    document.getElementById('systemApisEditor').innerHTML = '';
    document.getElementById('systemFormCard').style.display = 'block';
    document.getElementById('systemFormCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.getElementById('sysId').focus();
}

function editSystem(systemId) {
    // Load system data and populate form
    fetch('/sap-systems')
        .then(r => r.json())
        .then(data => {
            const sys = data.systems.find(s => s.system_id === systemId);
            if (!sys) return;
            
            editingSystemId = systemId;
            document.getElementById('systemFormTitle').innerHTML = '<i class="fas fa-edit"></i> ' + t('set.sys.edit_system', {system: systemId.toUpperCase()});
            document.getElementById('sysId').value = sys.system_id;
            document.getElementById('sysId').readOnly = true;
            document.getElementById('sysLabel').value = sys.system_label;
            document.getElementById('sysType').value = sys.system_type;
            document.getElementById('sysHost').value = sys.host || '';
            document.getElementById('sysAuth').value = sys.auth_type || 'oauth';
            document.getElementById('sysClient').value = sys.sap_client || '';
            document.getElementById('sysApiKey').value = sys.api_key || '';
            document.getElementById('sysEnv').value = sys.environment || '';
            document.getElementById('sysVerifySsl').checked = sys.verify_ssl !== false;
            
            // Populate APIs
            const apisDiv = document.getElementById('systemApisEditor');
            apisDiv.innerHTML = '';
            (sys.apis || []).forEach(api => {
                addApiRow(api.api_name, api.api_label, api.base_url);
            });
            
            document.getElementById('systemFormCard').style.display = 'block';
            document.getElementById('systemFormCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
}

function hideSystemForm() {
    document.getElementById('systemFormCard').style.display = 'none';
    editingSystemId = null;
}

function addApiRow(name, label, url) {
    const container = document.getElementById('systemApisEditor');
    const idx = container.children.length;
    const row = document.createElement('div');
    row.className = 'form-row mb-1 api-row';
    row.innerHTML = `
        <div class="col-md-2">
            <input type="text" class="form-control form-control-sm api-name" value="${name || ''}" placeholder="${t('set.sys.api_name_ph')}">
        </div>
        <div class="col-md-2">
            <input type="text" class="form-control form-control-sm api-label" value="${label || ''}" placeholder="Label">
        </div>
        <div class="col-md-7">
            <input type="text" class="form-control form-control-sm api-url" value="${url || ''}" placeholder="Base URL">
        </div>
        <div class="col-md-1">
            <button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest('.api-row').remove()">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    container.appendChild(row);
}

function saveSapSystem(event) {
    event.preventDefault();
    
    const systemId = document.getElementById('sysId').value.trim().toLowerCase();
    const systemLabel = document.getElementById('sysLabel').value.trim();
    const systemType = document.getElementById('sysType').value;
    const host = document.getElementById('sysHost').value.trim();
    const authType = document.getElementById('sysAuth').value;
    const sapClient = document.getElementById('sysClient').value.trim();
    const apiKey = document.getElementById('sysApiKey').value.trim();
    const verifySsl = document.getElementById('sysVerifySsl').checked;
    const environment = document.getElementById('sysEnv').value;
    
    if (!systemId || !systemLabel) {
        alert(t('set.sys.id_label_required'));
        return;
    }
    
    // Collect APIs from form
    const apis = [];
    document.querySelectorAll('#systemApisEditor .api-row').forEach(row => {
        const name = row.querySelector('.api-name').value.trim();
        const label = row.querySelector('.api-label').value.trim();
        const url = row.querySelector('.api-url').value.trim();
        if (name && url) {
            apis.push({ api_name: name, api_label: label || name, base_url: url });
        }
    });
    
    fetch('/sap-systems', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            system_id: systemId, system_label: systemLabel, system_type: systemType,
            host: host, auth_type: authType, sap_client: sapClient, api_key: apiKey,
            verify_ssl: verifySsl, environment: environment, apis: apis
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            hideSystemForm();
            loadSapSystems();
            loadCredentials();  // Refresh credentials list too (new system might appear)
        } else {
            alert(t('error_prefix') + data.error);
        }
    })
    .catch(error => alert(t('error_prefix') + error));
}

function deleteSapSystem(systemId) {
    if (!confirm(t('set.sys.delete_confirm', {system: systemId.toUpperCase()}))) return;
    
    fetch('/sap-systems/' + systemId, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                loadSapSystems();
            } else {
                alert(t('error_prefix') + data.error);
            }
        })
        .catch(error => alert(t('error_prefix') + error));
}

function saveNewApi(systemId) {
    const name = document.getElementById('new-api-name-' + systemId).value.trim();
    const label = document.getElementById('new-api-label-' + systemId).value.trim();
    const url = document.getElementById('new-api-url-' + systemId).value.trim();
    
    if (!name || !url) {
        alert(t('set.sys.api_required'));
        return;
    }
    
    fetch('/sap-systems/' + systemId + '/apis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_name: name, api_label: label || name, base_url: url })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            loadSapSystems();
        } else {
            alert(t('error_prefix') + data.error);
        }
    })
    .catch(error => alert(t('error_prefix') + error));
}

function deleteSapApi(systemId, apiName) {
    if (!confirm(t('set.sys.api_delete_confirm', {api: apiName, system: systemId.toUpperCase()}))) return;
    
    fetch('/sap-systems/' + systemId + '/apis/' + apiName, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                loadSapSystems();
            } else {
                alert(t('error_prefix') + data.error);
            }
        })
        .catch(error => alert(t('error_prefix') + error));
}


// ─── Health Check (Ampel) ───────────────────────────────────────────

let _healthCache = null;

function runHealthCheck() {
    const btn = document.getElementById('healthCheckBtn');
    const icon = document.getElementById('healthCheckIcon');
    const body = document.getElementById('healthStatusBody');
    const details = document.getElementById('healthDetails');
    const summaryEl = document.getElementById('healthSummaryBadges');
    const tsEl = document.getElementById('healthTimestamp');
    const header = document.getElementById('healthCardHeader');

    // Spinning icon
    if (icon) icon.className = 'fas fa-sync-alt fa-spin';
    if (btn) btn.disabled = true;
    summaryEl.innerHTML = '<span class="badge badge-secondary"><i class="fas fa-spinner fa-spin"></i> ' + t('set.health.checking') + '</span>';

    fetch('/api/health-check', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (icon) icon.className = 'fas fa-sync-alt';
            if (btn) btn.disabled = false;

            if (!data.success) {
                summaryEl.innerHTML = '<span class="badge badge-danger">Error</span>';
                return;
            }

            _healthCache = data.results;
            const s = data.summary;

            // Summary badges in header
            let sumHtml = '';
            if (s.ok > 0) sumHtml += `<span class="badge badge-success mr-1"><i class="fas fa-check-circle"></i> ${s.ok}</span>`;
            if (s.error > 0) sumHtml += `<span class="badge badge-danger mr-1"><i class="fas fa-times-circle"></i> ${s.error}</span>`;
            const warnCount = s.total - s.ok - s.error;
            if (warnCount > 0) sumHtml += `<span class="badge badge-warning mr-1"><i class="fas fa-exclamation-triangle"></i> ${warnCount}</span>`;
            sumHtml += `<small class="text-muted">${data.total_ms}ms</small>`;
            summaryEl.innerHTML = sumHtml;

            // Header color
            if (s.error === 0 && warnCount === 0) {
                header.style.background = '#d4edda'; // green
            } else if (s.error > 0) {
                header.style.background = '#f8d7da'; // red
            } else {
                header.style.background = '#fff3cd'; // yellow
            }

            // Timestamp
            tsEl.textContent = new Date().toLocaleTimeString();

            // Detailed results table
            let tbl = '<table class="table table-sm table-bordered mb-0"><thead class="thead-light"><tr>' +
                '<th>' + t('set.health.system') + '</th><th>CSRF</th><th>APIs</th><th>Status</th><th>ms</th></tr></thead><tbody>';
            const sortedIds = Object.keys(data.results).sort();
            sortedIds.forEach(sid => {
                const r = data.results[sid];
                const statusIcon = r.status === 'ok' ? '<span class="text-success"><i class="fas fa-check-circle"></i></span>'
                    : r.status === 'error' ? '<span class="text-danger"><i class="fas fa-times-circle"></i></span>'
                    : r.status === 'warn' ? '<span class="text-warning"><i class="fas fa-exclamation-triangle"></i></span>'
                    : '<span class="text-muted"><i class="fas fa-minus-circle"></i></span>';
                const csrfIcon = r.csrf === true ? '<span class="text-success"><i class="fas fa-check"></i></span>'
                    : r.csrf === false ? '<span class="text-danger"><i class="fas fa-times"></i></span>'
                    : '<span class="text-muted">\u2013</span>';

                let apiIcons = '';
                if (r.apis && Object.keys(r.apis).length > 0) {
                    Object.entries(r.apis).forEach(([name, info]) => {
                        const color = info.reachable ? 'text-success' : 'text-danger';
                        const ic = info.reachable ? 'fa-check' : 'fa-times';
                        apiIcons += `<span class="${color}" title="${escapeHtml(name)}: HTTP ${info.status_code || 'err'}"><i class="fas ${ic}"></i> <small>${escapeHtml(name)}</small></span> `;
                    });
                } else {
                    apiIcons = '<span class="text-muted">\u2013</span>';
                }

                const msgHint = r.message ? ` title="${escapeHtml(r.message)}"` : '';
                tbl += `<tr><td><strong>${escapeHtml(sid.toUpperCase())}</strong></td><td>${csrfIcon}</td><td>${apiIcons}</td><td${msgHint}>${statusIcon}</td><td>${r.ms}</td></tr>`;
            });
            tbl += '</tbody></table>';
            details.innerHTML = tbl;
            body.style.display = 'block';

            // Apply ampel badges to system cards
            _applyHealthBadges(data.results);
        })
        .catch(err => {
            console.error('[health-check]', err);
            if (icon) icon.className = 'fas fa-sync-alt';
            if (btn) btn.disabled = false;
            summaryEl.innerHTML = '<span class="badge badge-danger">Fehler</span>';
        });
}

function _applyHealthBadges(results) {
    if (!results) return;
    Object.entries(results).forEach(([sid, r]) => {
        const el = document.getElementById('health-badge-' + sid);
        if (!el) return;
        if (r.status === 'ok') {
            el.innerHTML = '<span class="badge badge-success" title="' + t('set.health.ok') + '"><i class="fas fa-check-circle"></i></span>';
        } else if (r.status === 'error') {
            el.innerHTML = '<span class="badge badge-danger" title="' + escapeHtml(r.message || t('set.health.error')) + '"><i class="fas fa-times-circle"></i></span>';
        } else if (r.status === 'warn') {
            el.innerHTML = '<span class="badge badge-warning" title="' + escapeHtml(r.message || t('set.health.warn')) + '"><i class="fas fa-exclamation-triangle"></i></span>';
        } else {
            el.innerHTML = '<span class="badge badge-secondary" title="' + escapeHtml(r.message || t('set.health.skip')) + '"><i class="fas fa-minus-circle"></i></span>';
        }
    });
}
