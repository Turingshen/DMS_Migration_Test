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

                    const pct = data.progress_pct || 0;
                    showLinkProgress();
                    const bar = document.getElementById('linkProgressBar');
                    bar.style.width = pct + '%';
                    bar.textContent = pct + '%';
                    document.getElementById('linkProgressStats').textContent =
                        t('map.link_progress', {completed: data.completed, total: data.link_total, linked: data.linked, exists: data.link_exists, failed: data.link_failed});
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
