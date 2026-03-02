document.addEventListener('DOMContentLoaded', function() {
    loadWaveData();
    // Auto-refresh every 30 seconds
    setInterval(loadWaveData, 30000);
});

async function loadWaveData() {
    try {
        const response = await fetch('/batches');
        const data = await response.json();

        if (!data.success) {
            document.getElementById('kanbanBoard').innerHTML =
                '<div class="alert alert-danger">Fehler: ' + data.error + '</div>';
            return;
        }

        const batches = data.batches || [];
        renderSummary(batches);
        renderKanban(batches);
    } catch (error) {
        document.getElementById('kanbanBoard').innerHTML =
            '<div class="alert alert-danger">Verbindungsfehler: ' + error + '</div>';
    }
}

function renderSummary(batches) {
    let totalDocs = 0, totalUploaded = 0, totalLinked = 0, totalFailed = 0, totalPending = 0;

    batches.forEach(b => {
        totalDocs += (b.total_records || 0);
        totalUploaded += (b.successful_records || 0);
        totalLinked += (b.link_linked || 0) + (b.link_exists || 0);
        totalFailed += (b.failed_records || 0) + (b.link_failed || 0);
        // Pending: total minus executed
        const executed = b.executed_records || 0;
        const total = b.total_records || 0;
        totalPending += Math.max(0, total - executed);
    });

    document.getElementById('totalBatches').textContent = batches.length;
    document.getElementById('totalDocs').textContent = totalDocs.toLocaleString();
    document.getElementById('totalUploaded').textContent = totalUploaded.toLocaleString();
    document.getElementById('totalLinked').textContent = totalLinked.toLocaleString();
    document.getElementById('totalFailed').textContent = totalFailed.toLocaleString();
    document.getElementById('totalPending').textContent = totalPending.toLocaleString();
}

function renderKanban(batches) {
    // Group by wave
    const waves = {};
    batches.forEach(b => {
        const wave = b.wave || 'Nicht zugeordnet';
        if (!waves[wave]) waves[wave] = [];
        waves[wave].push(b);
    });

    // Sort wave keys (Wave 0, Wave 1, ..., then unassigned last)
    const sortedWaves = Object.keys(waves).sort((a, b) => {
        if (a === 'Nicht zugeordnet') return 1;
        if (b === 'Nicht zugeordnet') return -1;
        return a.localeCompare(b, undefined, { numeric: true });
    });

    const board = document.getElementById('kanbanBoard');

    if (sortedWaves.length === 0) {
        board.innerHTML = '<div class="text-center w-100 py-5 text-muted">Keine Batches vorhanden</div>';
        return;
    }

    board.innerHTML = sortedWaves.map(waveName => {
        const waveBatches = waves[waveName];
        const isUnassigned = waveName === 'Nicht zugeordnet';

        // Wave-level aggregation
        let wTotal = 0, wUploaded = 0, wLinked = 0, wFailed = 0;
        waveBatches.forEach(b => {
            wTotal += (b.total_records || 0);
            wUploaded += (b.successful_records || 0);
            wLinked += (b.link_linked || 0) + (b.link_exists || 0);
            wFailed += (b.failed_records || 0);
        });
        const wPct = wTotal > 0 ? Math.round(wUploaded / wTotal * 100) : 0;
        const lPct = wTotal > 0 ? Math.round(wLinked / wTotal * 100) : 0;

        return `
            <div class="wave-column flex-shrink-0">
                <div class="wave-header ${isUnassigned ? 'bg-warning text-dark' : 'bg-dark text-white'}">
                    ${waveName}
                    <span class="float-right badge badge-light">${waveBatches.length}</span>
                </div>
                <div class="card border-0 shadow-sm">
                    <div class="card-body p-2">
                        <!-- Wave Progress -->
                        <div class="mb-2">
                            <div class="d-flex justify-content-between wave-stats">
                                <span>Upload: ${wPct}%</span>
                                <span>Verlinkung: ${lPct}%</span>
                            </div>
                            <div class="progress" style="height: 8px;">
                                <div class="progress-bar bg-success" style="width: ${wPct}%"></div>
                            </div>
                            <div class="progress mt-1" style="height: 4px;">
                                <div class="progress-bar bg-info" style="width: ${lPct}%"></div>
                            </div>
                            <div class="wave-stats text-right mt-1">
                                ${wUploaded}/${wTotal} Docs | ${wLinked} verlinkt
                                ${wFailed > 0 ? `| <span class="text-danger">${wFailed} Fehler</span>` : ''}
                            </div>
                        </div>

                        <!-- Batch Cards -->
                        ${waveBatches.map(b => renderBatchCard(b)).join('')}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}
