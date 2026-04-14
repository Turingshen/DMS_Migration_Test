    const BATCH_ID = window.BATCH_ID;
    let allMappings = [];
    let selectedFile = null;

    // Initialize
    document.addEventListener('DOMContentLoaded', function() {
        loadBatchInfo();
        loadStats();
        setupTabs();
        setupDragDrop();
        checkAndReconnectLinking();
        // Load all datasets
        Promise.all([
            fetch(`/batch/${BATCH_ID}/object-mapping/list`).then(r => r.json()).then(data => {
                allMappings = data.mappings || [];
                renderMappings(allMappings);
                document.getElementById('mappingCount').textContent = t('map.mappings.count', {n: allMappings.length});
            }),
            fetch(`/batch/${BATCH_ID}/object-mapping/unmapped`).then(r => r.json()).then(data => {
                allUnmapped = data.unmapped || [];
                buildDokobBadges(allUnmapped);
                activeDokobFilter = null;
                renderUnmapped(allUnmapped);
            })
        ]).catch(err => console.error('Init load error:', err));
    });

    function checkAndReconnectLinking() {
        fetch(`/batch/${BATCH_ID}/link-progress`)
            .then(r => r.json())
            .then(data => {
                if (data.success && data.is_linking) {
                    // Linking is still running — reconnect UI
                    const btn = document.getElementById('linkAllBtn');
                    const cancelBtn = document.getElementById('cancelLinkBtn');
                    if (btn) { btn.disabled = true; btn.textContent = t('map.linking_status'); }
                    if (cancelBtn) cancelBtn.style.display = 'inline-flex';
                    startLinkProgressPolling();
                }
            })
            .catch(() => {});
    }

    // Load batch info
    function loadBatchInfo() {
        fetch(`/api/batch/${BATCH_ID}`)
            .then(r => r.json())
            .then(data => {
                if (data.success && data.batch) {
                    document.getElementById('batchWave').textContent = data.batch.wave || '-';
                    document.getElementById('batchDescription').textContent = data.batch.description || t('map.no_description');
                    document.getElementById('batchRecordCount').textContent = data.batch.total_records || '0';
                }
            })
            .catch(err => console.error('Error loading batch info:', err));
    }

    // Setup tabs
    function setupTabs() {
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', function() {
                const tabId = this.dataset.tab;
                
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                this.classList.add('active');
                document.getElementById('tab-' + tabId).classList.add('active');
                
                if (tabId === 'unmapped') {
                    loadUnmapped();
                }
                if (tabId === 'link-errors') {
                    loadLinkErrors();
                }

            });
        });
    }

    // Load mappings
    function loadMappings() {
        fetch(`/batch/${BATCH_ID}/object-mapping/list`)
            .then(r => r.json())
            .then(data => {
                allMappings = data.mappings || [];
                renderMappings(allMappings);
                document.getElementById('mappingCount').textContent = t('map.mappings.count', {n: allMappings.length});
            })
            .catch(err => {
                console.error('Error loading mappings:', err);
                document.getElementById('mappingsBody').innerHTML = 
                    '<tr><td colspan="7" class="empty-state">' + t('map.load_error') + '</td></tr>';
            });
    }

    // Render mappings table
    function renderMappings(mappings) {
        const tbody = document.getElementById('mappingsBody');
        
        if (mappings.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7">
                        <div class="empty-state">
                            <div class="empty-state-icon">📋</div>
                            <div>${t('map.empty')}</div>
                            <div style="margin-top: 10px; color: #999;">${t('map.empty_hint')}</div>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = mappings.map(m => `
            <tr>
                <td><code>${escapeHtml(m.source_dokob)}</code></td>
                <td><code>${escapeHtml(m.source_objky)}</code></td>
                <td style="color: #4CAF50; font-weight: bold;">→</td>
                <td><code>${escapeHtml(m.target_dokob)}</code></td>
                <td><code>${escapeHtml(m.target_objky)}</code></td>
                <td>${formatDateTime(m.created_at)}</td>
                <td>
                    <button class="action-btn edit" onclick="editMapping(${m.id}, '${escapeJs(m.source_dokob)}', '${escapeJs(m.source_objky)}', '${escapeJs(m.target_dokob)}', '${escapeJs(m.target_objky)}')">${t('batch_action.edit')}</button>
                    <button class="action-btn delete" onclick="deleteMapping(${m.id})">${t('batch_action.delete')}</button>
                </td>
            </tr>
        `).join('');
    }

    // Filter mappings
    function filterMappings() {
        const search = document.getElementById('searchMappings').value.toLowerCase();
        const filtered = allMappings.filter(m => 
            m.source_dokob.toLowerCase().includes(search) ||
            m.source_objky.toLowerCase().includes(search) ||
            m.target_dokob.toLowerCase().includes(search) ||
            m.target_objky.toLowerCase().includes(search)
        );
        renderMappings(filtered);
    }

    // Load stats
    function loadStats() {
        fetch(`/batch/${BATCH_ID}/object-mapping/stats`)
            .then(r => r.json())
            .then(data => {
                document.getElementById('statTotalMappings').textContent = data.total_mappings || 0;
                document.getElementById('statUniqueSources').textContent = data.unique_sources || 0;
                document.getElementById('statUniqueTargets').textContent = data.unique_targets || 0;
                document.getElementById('statUnmapped').textContent = data.unmapped_count || 0;
            })
            .catch(err => console.error('Error loading stats:', err));
    }

    // Load unmapped objects
    let allUnmapped = [];
    let activeDokobFilter = null;

    function loadUnmapped() {
        const tbody = document.getElementById('unmappedBody');
        tbody.innerHTML = '<tr><td colspan="4" class="loading"><div class="spinner"></div> ' + t('loading') + '</td></tr>';

        fetch(`/batch/${BATCH_ID}/object-mapping/unmapped`)
            .then(r => r.json())
            .then(data => {
                allUnmapped = data.unmapped || [];
                buildDokobBadges(allUnmapped);
                activeDokobFilter = null;
                renderUnmapped(allUnmapped);
            })
            .catch(err => {
                console.error('Error loading unmapped:', err);
                tbody.innerHTML = '<tr><td colspan="4" class="empty-state">' + t('map.unmapped_load_error') + '</td></tr>';
            });
    }

    function buildDokobBadges(unmapped) {
        const bar = document.getElementById('dokobFilterBar');
        // Count per DOKOB
        const counts = {};
        unmapped.forEach(u => { counts[u.dokob] = (counts[u.dokob] || 0) + 1; });
        const keys = Object.keys(counts).sort();
        if (keys.length <= 1) { bar.style.display = 'none'; return; }
        bar.style.display = 'flex';
        bar.innerHTML = '<span style="font-weight:600;font-size:13px;margin-right:4px;">DOKOB:</span>';
        // "Alle" badge
        const allBadge = document.createElement('span');
        allBadge.className = 'dokob-badge active';
        allBadge.textContent = t('map.all_count', {n: unmapped.length});
        allBadge.onclick = () => filterByDokob(null);
        bar.appendChild(allBadge);
        // Per-DOKOB badges
        keys.forEach(k => {
            const b = document.createElement('span');
            b.className = 'dokob-badge';
            b.dataset.dokob = k;
            b.textContent = `${k} (${counts[k]})`;
            b.onclick = () => filterByDokob(k);
            bar.appendChild(b);
        });
    }

    function filterByDokob(dokob) {
        activeDokobFilter = dokob;
        // Update badge active state
        document.querySelectorAll('.dokob-badge').forEach(b => {
            if (dokob === null) {
                b.classList.toggle('active', !b.dataset.dokob);
            } else {
                b.classList.toggle('active', b.dataset.dokob === dokob);
            }
        });
        const filtered = dokob ? allUnmapped.filter(u => u.dokob === dokob) : allUnmapped;
        renderUnmapped(filtered);
    }

    function renderUnmapped(unmapped) {
        const tbody = document.getElementById('unmappedBody');
        if (unmapped.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4">
                        <div class="empty-state">
                            <div class="empty-state-icon">✅</div>
                            <div>${t('map.all_mapped')}</div>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        tbody.innerHTML = unmapped.map(u => `
            <tr>
                <td><code>${escapeHtml(u.dokob)}</code></td>
                <td><code>${escapeHtml(u.objky)}</code></td>
                <td><span class="badge badge-warning">${u.count}</span></td>
                <td>
                    <button class="action-btn edit" onclick="quickAddMapping('${escapeJs(u.dokob)}', '${escapeJs(u.objky)}')">
                        ${t('map.add_mapping')}
                    </button>
                </td>
            </tr>
        `).join('');
    }

    function refreshUnmapped() {
        loadUnmapped();
        loadStats();
    }

    // Edit mapping - addMapping/quickAddMapping removed (use Template + Upload instead)
    // Placeholder kept so existing unmapped-table "Aktion" column still works gracefully
    function quickAddMapping(dokob, objky) {
        alert(t('map.add_via_upload'));
    }


    // Edit mapping
    function editMapping(id, sourceDokob, sourceObjky, targetDokob, targetObjky) {
        document.getElementById('editId').value = id;
        document.getElementById('editSourceDokob').value = sourceDokob;
        document.getElementById('editSourceObjky').value = sourceObjky;
        document.getElementById('editTargetDokob').value = targetDokob;
        document.getElementById('editTargetObjky').value = targetObjky;
        document.getElementById('editModal').classList.add('active');
    }

    function closeEditModal() {
        document.getElementById('editModal').classList.remove('active');
    }

    function saveEdit() {
        const id = document.getElementById('editId').value;
        const data = {
            source_dokob: document.getElementById('editSourceDokob').value,
            source_objky: document.getElementById('editSourceObjky').value,
            target_dokob: document.getElementById('editTargetDokob').value,
            target_objky: document.getElementById('editTargetObjky').value
        };

        fetch(`/batch/${BATCH_ID}/object-mapping/${id}/update`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                closeEditModal();
                loadMappings();
                loadStats();
            } else {
                alert(t('error_prefix') + (result.error || t('map.error_unknown')));
            }
        })
        .catch(err => alert(t('map.update_error', {msg: err})));
    }

    // Delete mapping
    function deleteMapping(id) {
        if (!confirm(t('map.delete_confirm'))) return;

        fetch(`/batch/${BATCH_ID}/object-mapping/${id}/delete`, {
            method: 'DELETE'
        })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                loadMappings();
                loadStats();
            } else {
                alert(t('error_prefix') + (result.error || t('map.error_unknown')));
            }
        })
        .catch(err => alert(t('map.delete_error', {msg: err})));
    }

    // Upload functionality
    function showUploadModal() {
        document.getElementById('uploadModal').classList.add('active');
        selectedFile = null;
        document.getElementById('uploadStatus').innerHTML = '';
        document.getElementById('uploadBtn').disabled = true;
    }

    function closeUploadModal() {
        document.getElementById('uploadModal').classList.remove('active');
        document.getElementById('fileInput').value = '';
    }

    function setupDragDrop() {
        const area = document.getElementById('uploadArea');
        
        area.addEventListener('dragover', (e) => {
            e.preventDefault();
            area.classList.add('dragover');
        });
        
        area.addEventListener('dragleave', () => {
            area.classList.remove('dragover');
        });
        
        area.addEventListener('drop', (e) => {
            e.preventDefault();
            area.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) {
                selectedFile = file;
                document.getElementById('uploadStatus').innerHTML = 
                    `<div class="alert alert-success">${t('map.file_selected', {name: file.name})}</div>`;
                document.getElementById('uploadBtn').disabled = false;
            }
        });
    }

    function handleFileSelect(event) {
        const file = event.target.files[0];
        if (file) {
            selectedFile = file;
            document.getElementById('uploadStatus').innerHTML = 
                `<div class="alert alert-success">${t('map.file_selected', {name: file.name})}</div>`;
            document.getElementById('uploadBtn').disabled = false;
        }
    }

    function uploadFile() {
        if (!selectedFile) return;

        const formData = new FormData();
        formData.append('file', selectedFile);

        document.getElementById('uploadBtn').disabled = true;
        document.getElementById('uploadStatus').innerHTML = 
            '<div class="loading"><div class="spinner"></div> ' + t('map.uploading') + '</div>';

        fetch(`/batch/${BATCH_ID}/object-mapping/upload`, {
            method: 'POST',
            body: formData
        })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                document.getElementById('uploadStatus').innerHTML = 
                    `<div class="alert alert-success">${t('map.upload_success', {n: result.count})}</div>`;
                setTimeout(() => {
                    closeUploadModal();
                    loadMappings();
                    loadStats();
                }, 1500);
            } else {
                document.getElementById('uploadStatus').innerHTML = 
                    `<div class="alert alert-warning">${t('map.upload_error_msg', {msg: result.error})}</div>`;
                document.getElementById('uploadBtn').disabled = false;
            }
        })
        .catch(err => {
            document.getElementById('uploadStatus').innerHTML = 
                `<div class="alert alert-warning">${t('map.upload_failed', {msg: err})}</div>`;
            document.getElementById('uploadBtn').disabled = false;
        });
    }

    // Download functions
    function downloadTemplate() {
        window.location.href = '/object-mapping/download-template';
    }

    function downloadMappings() {
        window.location.href = `/batch/${BATCH_ID}/object-mapping/download`;
    }

    // Apply mappings to staging
    function applyMappings() {
        if (!confirm(t('map.apply_confirm'))) return;

        fetch(`/batch/${BATCH_ID}/object-mapping/apply`, {
            method: 'POST'
        })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                if (result.updated === 0) {
                    alert(t('map.apply_no_records'));
                } else {
                    alert(t('map.apply_success', {n: result.updated}));
                }
                loadStats();
            } else {
                alert(t('error_prefix') + (result.error || t('map.error_unknown')));
            }
        })
        .catch(err => alert(t('map.apply_error', {msg: err})));
    }

    function escapeJs(text) {
        if (!text) return '';
        return text.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
    }

    // ========================================================================
    // Linking Functions
    // ========================================================================

    let linkProgressInterval = null;

    function showLinkProgress() {
        document.getElementById('linkProgressContainer').style.display = 'block';
    }
    function hideLinkProgress() {
        document.getElementById('linkProgressContainer').style.display = 'none';
    }

    function startLinkProgressPolling() {
        if (linkProgressInterval) clearInterval(linkProgressInterval);
        const btn = document.getElementById('linkAllBtn');
        const selBtn = document.getElementById('linkSelectedBtn');
        const cancelBtn = document.getElementById('cancelLinkBtn');

        linkProgressInterval = setInterval(() => {
            fetch(`/batch/${BATCH_ID}/link-progress`)
                .then(response => response.json())
                .then(data => {
                    if (!data.success || !linkProgressInterval) return;

                    const pct = Math.min(data.progress_pct || 0, 100);
                    showLinkProgress();
                    const bar = document.getElementById('linkProgressBar');
                    bar.style.width = pct.toFixed(1) + '%';
                    bar.textContent = pct.toFixed(1) + '%';
                    // Use real total (max of link_total and completed to avoid >100%)
                    const realTotal = Math.max(data.link_total || 0, data.completed || 0);
                    document.getElementById('linkProgressStats').textContent =
                        t('map.link_progress', {completed: data.completed, total: realTotal, linked: data.linked, exists: data.link_exists, failed: data.link_failed});
                    document.getElementById('linkProgressPhase').textContent =
                        t('map.link_phase', {phase: data.migration_phase || '—'});

                    // Background linking finished?
                    if (!data.is_linking && data.background_result) {
                        stopLinkProgressPolling();
                        hideLinkProgress();
                        if (cancelBtn) cancelBtn.style.display = 'none';

                        const r = data.background_result;
                        if (r.success) {
                            let msg = t('map.link_complete_msg', {total: r.total_records, linked: r.linked, existed: r.already_existed, failed: r.failed, duration: r.duration_formatted});
                            if (r.cancel_reason) msg += t('map.link_complete_note', {reason: r.cancel_reason});
                            alert(msg);
                        } else if (r.error) {
                            alert(t('map.link_failed_msg', {msg: r.error}));
                        }
                        // Reset UI
                        if (btn) { btn.disabled = false; btn.textContent = t('map.link_all'); }
                        if (selBtn) { selBtn.disabled = false; }
                        loadStats();
                    }
                })
                .catch(() => {});
        }, 2000);
    }

    function stopLinkProgressPolling() {
        if (linkProgressInterval) {
            clearInterval(linkProgressInterval);
            linkProgressInterval = null;
        }
    }

    function linkAll() {
        if (!confirm(t('map.link_confirm'))) {
            return;
        }

        const btn = document.getElementById('linkAllBtn');
        const cancelBtn = document.getElementById('cancelLinkBtn');
        btn.disabled = true;
        btn.textContent = t('map.linking_status');
        cancelBtn.style.display = 'inline-flex';

        fetch('/execute_linking', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ batch_id: BATCH_ID })
        })
        .then(response => response.json())
        .then(data => {
            if (data.background) {
                // Background linking started successfully — poll for completion
                startLinkProgressPolling();
            } else if (data.login_required) {
                alert(t('map.link_not_logged_in'));
                window.location.href = '/';
            } else {
                alert(t('map.link_start_error', {msg: data.error || t('map.error_unknown')}));
                btn.disabled = false;
                btn.textContent = t('map.link_all');
                cancelBtn.style.display = 'none';
            }
        })
        .catch(error => {
            alert(t('map.link_conn_error', {msg: error}));
            btn.disabled = false;
            btn.textContent = t('map.link_all');
            cancelBtn.style.display = 'none';
        });
    }

    function linkSelected() {
        // For now, link-selected not applicable on mapping page (no record selection here)
        alert(t('map.link_use_all'));
    }

    function cancelLinking() {
        if (!confirm(t('map.cancel_confirm'))) {
            return;
        }

        const cancelBtn = document.getElementById('cancelLinkBtn');
        cancelBtn.disabled = true;
        cancelBtn.textContent = t('map.cancel_requested');

        fetch(`/batch/${BATCH_ID}/cancel-linking`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                cancelBtn.textContent = t('map.cancel_requested');
            } else {
                alert(t('map.cancel_failed_msg', {msg: data.error}));
                cancelBtn.disabled = false;
                cancelBtn.textContent = t('map.cancel_linking');
            }
        })
        .catch(error => {
            alert(t('map.cancel_error', {msg: error}));
            cancelBtn.disabled = false;
            cancelBtn.textContent = t('map.cancel_linking');
        });
    }

    // ========================================================================
    // Link Errors Functions
    // ========================================================================

    let allLinkErrors = [];
    let currentErrorDetailRecord = null;

    // ── Error category classification ──────────────────────────────
    function classifyLinkError(errText) {
        if (!errText) return { key: 'unknown', color: '#6c757d', icon: '❓' };
        const e = errText.toLowerCase();
        if (e.includes('500'))        return { key: 'sap_500',    color: '#dc3545', icon: '🔴' };
        if (e.includes('400'))        return { key: 'sap_400',    color: '#e67e22', icon: '🟠' };
        if (e.includes('401') || e.includes('403') || e.includes('auth'))
                                       return { key: 'auth',       color: '#9b59b6', icon: '🔒' };
        if (e.includes('timeout') || e.includes('timed out') || e.includes('read timed'))
                                       return { key: 'timeout',    color: '#f39c12', icon: '⏱️' };
        if (e.includes('duplicate') || e.includes('already') || e.includes('exist') || e.includes('vorhanden') || e.includes('bereits'))
                                       return { key: 'duplicate',  color: '#3498db', icon: '🔁' };
        if (e.includes('connection') || e.includes('connect') || e.includes('refused'))
                                       return { key: 'connection', color: '#e74c3c', icon: '🔌' };
        if (e.includes('mapping') || e.includes('not found'))
                                       return { key: 'no_mapping', color: '#95a5a6', icon: '🗺️' };
        return { key: 'other', color: '#6c757d', icon: '⚠️' };
    }

    function getCategoryLabel(key) {
        const labels = {
            sap_500:    'SAP 500 Server Error',
            sap_400:    'SAP 400 Bad Request',
            auth:       t('map.link_errors.cat_auth'),
            timeout:    'Timeout',
            duplicate:  t('map.link_errors.cat_duplicate'),
            connection: t('map.link_errors.cat_connection'),
            no_mapping: t('map.link_errors.cat_no_mapping'),
            other:      t('map.link_errors.cat_other'),
            unknown:    t('map.link_errors.cat_unknown')
        };
        return labels[key] || key;
    }

    function loadLinkErrors() {
        const tbody = document.getElementById('linkErrorsBody');
        tbody.innerHTML = '<tr><td colspan="9" class="loading"><div class="spinner"></div> ' + t('loading') + '</td></tr>';

        fetch(`/batch/${BATCH_ID}/link-errors`)
            .then(r => r.json())
            .then(data => {
                if (!data.success) throw new Error(data.error);
                allLinkErrors = data.records || [];
                renderLinkErrors(allLinkErrors);
                updateLinkErrorBadge(allLinkErrors.length);
                renderErrorCategorySummary(allLinkErrors);
            })
            .catch(err => {
                console.error('Error loading link errors:', err);
                tbody.innerHTML = '<tr><td colspan="9" class="empty-state">' + t('map.link_errors.load_error') + '</td></tr>';
            });
    }

    function renderErrorCategorySummary(records) {
        const container = document.getElementById('linkErrorCategorySummary');
        const catDiv = document.getElementById('linkErrorCategories');
        if (!records || records.length === 0) {
            container.style.display = 'none';
            return;
        }
        // Count by category
        const counts = {};
        records.forEach(r => {
            const cat = classifyLinkError(r.link_error);
            counts[cat.key] = (counts[cat.key] || 0) + 1;
        });

        catDiv.innerHTML = Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .map(([key, count]) => {
                const cat = classifyLinkError(key === 'sap_500' ? '500' : key === 'sap_400' ? '400' : key);
                // Re-derive proper color for each category
                const catInfo = { sap_500:{color:'#dc3545',icon:'🔴'}, sap_400:{color:'#e67e22',icon:'🟠'},
                    auth:{color:'#9b59b6',icon:'🔒'}, timeout:{color:'#f39c12',icon:'⏱️'},
                    duplicate:{color:'#3498db',icon:'🔁'}, connection:{color:'#e74c3c',icon:'🔌'},
                    no_mapping:{color:'#95a5a6',icon:'🗺️'}, other:{color:'#6c757d',icon:'⚠️'},
                    unknown:{color:'#6c757d',icon:'❓'} };
                const info = catInfo[key] || catInfo.other;
                return `<span onclick="filterByCategory('${key}')" style="cursor:pointer; display:inline-flex; align-items:center; gap:4px; padding:4px 10px; border-radius:12px; background:${info.color}18; border:1px solid ${info.color}40; font-size:12px; color:${info.color};">
                    ${info.icon} ${getCategoryLabel(key)} <strong>${count}</strong>
                </span>`;
            }).join('');

        container.style.display = 'block';
    }

    function filterByCategory(catKey) {
        if (!catKey) {
            renderLinkErrors(allLinkErrors);
            return;
        }
        const filtered = allLinkErrors.filter(r => classifyLinkError(r.link_error).key === catKey);
        renderLinkErrors(filtered);
        document.getElementById('searchLinkErrors').value = '';
    }

    function renderLinkErrors(records) {
        const tbody = document.getElementById('linkErrorsBody');
        const footer = document.getElementById('linkErrorsFooter');

        if (!records || records.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <div>${t('map.link_errors.none')}</div>
            </div></td></tr>`;
            footer.textContent = '';
            return;
        }

        tbody.innerHTML = records.map(r => {
            const srcDoc = r.source_documentnumber || '—';
            const tgtDoc = r.target_documentnumber || '—';
            const errText = r.link_error || '—';
            const cat = classifyLinkError(errText);
            const shortErr = errText.length > 60 ? errText.substring(0, 60) + '…' : errText;
            const tgtMapping = (r.target_dokob || '—') + ' / ' + (r.target_objky ? (r.target_objky.length > 20 ? r.target_objky.substring(0, 20) + '…' : r.target_objky) : '—');
            return `<tr style="cursor:pointer;" ondblclick="showErrorDetail(${r.id})">
                <td onclick="event.stopPropagation();"><input type="checkbox" class="link-error-cb" value="${r.id}"></td>
                <td>${r.id}</td>
                <td><code title="${escapeHtml(srcDoc)}">${escapeHtml(srcDoc)}</code></td>
                <td><code title="${escapeHtml(tgtDoc)}">${escapeHtml(tgtDoc)}</code></td>
                <td><code>${escapeHtml(r.source_dokob || '—')}</code></td>
                <td title="${escapeHtml((r.target_dokob||'') + ' / ' + (r.target_objky||''))}">${escapeHtml(tgtMapping)}</td>
                <td><span style="display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:10px;background:${cat.color}18;color:${cat.color};font-size:11px;white-space:nowrap;">${cat.icon} ${escapeHtml(getCategoryLabel(cat.key))}</span></td>
                <td title="${escapeHtml(errText)}" style="font-family:monospace;font-size:12px;color:#dc3545;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(shortErr)}</td>
                <td><button onclick="event.stopPropagation(); showErrorDetail(${r.id})" style="border:none;background:none;cursor:pointer;font-size:16px;" title="${t('map.link_errors.show_detail')}">🔍</button></td>
            </tr>`;
        }).join('');

        footer.textContent = t('map.link_errors.showing', {n: records.length});
        updateResetSelectedBtn();
    }

    function filterLinkErrors() {
        const search = (document.getElementById('searchLinkErrors').value || '').toLowerCase();
        if (!search) {
            renderLinkErrors(allLinkErrors);
            return;
        }
        const filtered = allLinkErrors.filter(r => {
            const cat = classifyLinkError(r.link_error);
            return (r.source_documentnumber || '').toLowerCase().includes(search) ||
                (r.target_documentnumber || '').toLowerCase().includes(search) ||
                (r.source_dokob || '').toLowerCase().includes(search) ||
                (r.link_error || '').toLowerCase().includes(search) ||
                getCategoryLabel(cat.key).toLowerCase().includes(search) ||
                String(r.id).includes(search);
        });
        renderLinkErrors(filtered);
    }

    // ── Error Detail Modal ─────────────────────────────────────────
    function showErrorDetail(recordId) {
        const r = allLinkErrors.find(x => x.id === recordId);
        if (!r) return;
        currentErrorDetailRecord = r;

        const errText = r.link_error || '—';
        const cat = classifyLinkError(errText);

        // Parse enriched error format: LINK_FAIL_{status}: [{code}] detail (ID:{corrId})
        const statusMatch = errText.match(/LINK_FAIL_(\d+)/);
        const httpStatus = statusMatch ? statusMatch[1] : '—';
        const codeMatch = errText.match(/\[([^\]]+)\]/);
        const sapCode = codeMatch ? codeMatch[1] : '';
        const corrIdMatch = errText.match(/\(ID:([^)]+)\)/);
        const corrId = corrIdMatch ? corrIdMatch[1] : '';
        // Extract the detail portion (between code bracket and corrId, or after status)
        let errorDetail = errText;
        if (statusMatch) {
            errorDetail = errText.replace(/LINK_FAIL_\d+:\s*/, '');
        }
        if (codeMatch) {
            errorDetail = errorDetail.replace(/\[[^\]]+\]\s*/, '');
        }
        if (corrIdMatch) {
            errorDetail = errorDetail.replace(/\s*\(ID:[^)]+\)\s*$/, '');
        }
        errorDetail = errorDetail.trim() || '—';

        const body = document.getElementById('errorDetailBody');
        body.innerHTML = `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:15px; margin-bottom:15px;">
                <div style="background:#f8f9fa; padding:12px; border-radius:6px;">
                    <div style="font-weight:bold; margin-bottom:8px; color:#495057;"><i class="fas fa-file-alt"></i> ${t('map.link_errors.detail_source')}</div>
                    <table style="width:100%; font-size:12px;">
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_docnr')}:</td><td><code>${escapeHtml(r.source_documentnumber || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_type')}:</td><td><code>${escapeHtml(r.source_documenttype || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_version')}:</td><td><code>${escapeHtml(r.source_documentversion || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_part')}:</td><td><code>${escapeHtml(r.source_documentpart || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">DOKOB:</td><td><code>${escapeHtml(r.source_dokob || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">OBJKY:</td><td><code style="word-break:break-all;">${escapeHtml(r.source_objky || '—')}</code></td></tr>
                    </table>
                </div>
                <div style="background:#f8f9fa; padding:12px; border-radius:6px;">
                    <div style="font-weight:bold; margin-bottom:8px; color:#495057;"><i class="fas fa-file-import"></i> ${t('map.link_errors.detail_target')}</div>
                    <table style="width:100%; font-size:12px;">
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_docnr')}:</td><td><code>${escapeHtml(r.target_documentnumber || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_type')}:</td><td><code>${escapeHtml(r.target_documenttype || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_version')}:</td><td><code>${escapeHtml(r.target_documentversion || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">${t('map.link_errors.detail_part')}:</td><td><code>${escapeHtml(r.target_documentpart || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">DOKOB:</td><td><code>${escapeHtml(r.target_dokob || '—')}</code></td></tr>
                        <tr><td style="color:#666; padding:2px 8px 2px 0; white-space:nowrap;">OBJKY:</td><td><code style="word-break:break-all;">${escapeHtml(r.target_objky || '—')}</code></td></tr>
                    </table>
                </div>
            </div>

            <div style="background:#fff5f5; border:1px solid #f5c6cb; padding:12px; border-radius:6px; margin-bottom:12px;">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap;">
                    <span style="display:inline-flex;align-items:center;gap:3px;padding:3px 10px;border-radius:10px;background:${cat.color}18;color:${cat.color};font-size:12px; font-weight:bold;">${cat.icon} ${escapeHtml(getCategoryLabel(cat.key))}</span>
                    ${httpStatus !== '—' ? `<span style="background:#dc3545; color:#fff; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold;">HTTP ${httpStatus}</span>` : ''}
                    ${sapCode ? `<span style="background:#6f42c1; color:#fff; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold;">SAP ${escapeHtml(sapCode)}</span>` : ''}
                </div>
                <div style="font-weight:bold; margin-bottom:4px; font-size:12px; color:#721c24;">${t('map.link_errors.detail_error_msg')}:</div>
                <pre style="background:#fff; border:1px solid #ddd; padding:10px; border-radius:4px; font-size:12px; white-space:pre-wrap; word-break:break-all; max-height:200px; overflow-y:auto; margin:0; color:#333;">${escapeHtml(errorDetail)}</pre>
                ${corrId ? `<div style="margin-top:6px; font-size:11px; color:#888;"><i class="fas fa-fingerprint"></i> Correlation-ID: <code>${escapeHtml(corrId)}</code></div>` : ''}
            </div>

            <div style="display:flex; gap:15px; font-size:12px; color:#666;">
                <span><strong>ID:</strong> ${r.id}</span>
                <span><strong>Exec-Status:</strong> <code>${escapeHtml(r.execution_status || '—')}</code></span>
                <span><strong>Datei:</strong> <code>${escapeHtml(r.filename || '—')}</code></span>
            </div>
        `;

        document.getElementById('errorDetailModal').style.display = 'flex';
    }

    function closeErrorDetailModal() {
        document.getElementById('errorDetailModal').style.display = 'none';
        currentErrorDetailRecord = null;
    }

    function resetSingleFromModal() {
        if (!currentErrorDetailRecord) return;
        const id = currentErrorDetailRecord.id;

        fetch(`/batch/${BATCH_ID}/reset-link-errors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ record_ids: [id] })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                closeErrorDetailModal();
                loadLinkErrors();
                loadStats();
            } else {
                alert(t('error_prefix') + (data.error || ''));
            }
        })
        .catch(err => alert(t('map.link_errors.reset_error', {msg: err})));
    }

    function toggleSelectAllLinkErrors(el) {
        const checked = el.checked;
        document.querySelectorAll('.link-error-cb').forEach(cb => cb.checked = checked);
        const head = document.getElementById('selectAllLinkErrorsHead');
        const body = document.getElementById('selectAllLinkErrors');
        if (head) head.checked = checked;
        if (body) body.checked = checked;
        updateResetSelectedBtn();
    }

    function getSelectedLinkErrorIds() {
        return Array.from(document.querySelectorAll('.link-error-cb:checked')).map(cb => parseInt(cb.value));
    }

    function updateResetSelectedBtn() {
        const btn = document.getElementById('resetSelectedBtn');
        const relinkBtn = document.getElementById('resetSelectedRelinkBtn');
        const ids = getSelectedLinkErrorIds();
        btn.disabled = ids.length === 0;
        relinkBtn.disabled = ids.length === 0;
        if (ids.length > 0) {
            btn.textContent = '🔄 ' + t('map.link_errors.reset_n', {n: ids.length});
            relinkBtn.textContent = '🔗 ' + t('map.link_errors.reset_n_relink', {n: ids.length});
        }
    }

    // Delegate checkbox changes
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('link-error-cb')) {
            updateResetSelectedBtn();
        }
    });

    // ── Reset only (no relink) ─────────────────────────────────────
    function resetAllLinkErrors() {
        if (!allLinkErrors.length) return;
        if (!confirm(t('map.link_errors.reset_all_confirm', {n: allLinkErrors.length}))) return;

        fetch(`/batch/${BATCH_ID}/reset-link-errors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert(t('map.link_errors.reset_done', {n: data.reset_count}));
                loadLinkErrors();
                loadStats();
            } else {
                alert(t('error_prefix') + (data.error || ''));
            }
        })
        .catch(err => alert(t('map.link_errors.reset_error', {msg: err})));
    }

    function resetSelectedLinkErrors() {
        const ids = getSelectedLinkErrorIds();
        if (!ids.length) return;
        if (!confirm(t('map.link_errors.reset_selected_confirm', {n: ids.length}))) return;

        fetch(`/batch/${BATCH_ID}/reset-link-errors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ record_ids: ids })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert(t('map.link_errors.reset_done', {n: data.reset_count}));
                loadLinkErrors();
                loadStats();
            } else {
                alert(t('error_prefix') + (data.error || ''));
            }
        })
        .catch(err => alert(t('map.link_errors.reset_error', {msg: err})));
    }

    // ── Reset + immediately re-link ────────────────────────────────
    function resetAndRelinkAll() {
        if (!allLinkErrors.length) return;
        if (!confirm(t('map.link_errors.reset_relink_confirm', {n: allLinkErrors.length}))) return;

        // Step 1: Reset all failed
        fetch(`/batch/${BATCH_ID}/reset-link-errors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        })
        .then(r => r.json())
        .then(data => {
            if (!data.success) throw new Error(data.error);
            // Step 2: Trigger linking
            return triggerLinkingFromErrorTab();
        })
        .catch(err => alert(t('map.link_errors.reset_error', {msg: err})));
    }

    function resetSelectedAndRelink() {
        const ids = getSelectedLinkErrorIds();
        if (!ids.length) return;
        if (!confirm(t('map.link_errors.reset_relink_sel_confirm', {n: ids.length}))) return;

        fetch(`/batch/${BATCH_ID}/reset-link-errors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ record_ids: ids })
        })
        .then(r => r.json())
        .then(data => {
            if (!data.success) throw new Error(data.error);
            return triggerLinkingFromErrorTab();
        })
        .catch(err => alert(t('map.link_errors.reset_error', {msg: err})));
    }

    function triggerLinkingFromErrorTab() {
        // Trigger the same linking as "Alle verlinken" button
        const linkBtn = document.getElementById('linkAllBtn');
        const cancelBtn = document.getElementById('cancelLinkBtn');
        if (linkBtn) { linkBtn.disabled = true; linkBtn.textContent = t('map.linking_status'); }
        if (cancelBtn) cancelBtn.style.display = 'inline-flex';

        return fetch('/execute_linking', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ batch_id: BATCH_ID })
        })
        .then(r => r.json())
        .then(data => {
            if (data.background) {
                startLinkProgressPolling();
                loadLinkErrors();
            } else if (data.login_required) {
                alert(t('map.link_not_logged_in'));
                window.location.href = '/';
            } else {
                alert(t('map.link_start_error', {msg: data.error || t('map.error_unknown')}));
                if (linkBtn) { linkBtn.disabled = false; linkBtn.textContent = t('map.link_all'); }
                if (cancelBtn) cancelBtn.style.display = 'none';
            }
        })
        .catch(err => {
            alert(t('map.link_conn_error', {msg: err}));
            if (linkBtn) { linkBtn.disabled = false; linkBtn.textContent = t('map.link_all'); }
            if (cancelBtn) cancelBtn.style.display = 'none';
        });
    }

    function updateLinkErrorBadge(count) {
        const badge = document.getElementById('linkErrorBadge');
        if (badge) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline' : 'none';
        }
    }

    // Load link error count on init (for badge)
    fetch(`/batch/${BATCH_ID}/link-errors`)
        .then(r => r.json())
        .then(data => {
            if (data.success) updateLinkErrorBadge(data.count || 0);
        })
        .catch(() => {});
