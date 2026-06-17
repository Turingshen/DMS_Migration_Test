/**
 * i18n.js — Internationalization for DMS Migration App
 * Supports German (de) and English (en).
 * 
 * Usage:
 *   t('key')                    — Get translated string
 *   t('key', {n: 5})            — With interpolation: "{{n}} items" → "5 items"
 *   I18n.setLang('en')          — Switch language
 *   I18n.getLang()              — Get current language
 *   I18n.applyAll()             — Re-translate all data-i18n elements
 * 
 * HTML:
 *   <span data-i18n="dashboard">Dashboard</span>
 *   <input data-i18n-placeholder="search_placeholder" placeholder="Suchen...">
 *   <button data-i18n-title="back_tooltip" title="Zurück">...</button>
 */
(function() {
    'use strict';

    const TRANSLATIONS = {

        // ══════════════════════════════════════════════════════════════
        // GLOBAL / NAVBAR / BASE
        // ══════════════════════════════════════════════════════════════
        'app_name':                     { de: 'Dokument-Migration', en: 'Document Migration' },
        'app_footer':                   { de: 'Dokument-Migration v2.0 - SAP PM Service Tools', en: 'Document Migration v2.0 - SAP PM Service Tools' },
        'nav.dashboard':                { de: 'Dashboard', en: 'Dashboard' },
        'nav.waves':                    { de: 'Wellenverwaltung', en: 'Wave Management' },
        'nav.rules':                    { de: 'Regeln', en: 'Rules' },
        'nav.settings':                 { de: 'Einstellungen', en: 'Settings' },
        'nav.qm_material':             { de: 'QM Material', en: 'QM Material' },
        'nav.tech_material':            { de: 'TECH Material', en: 'TECH Material' },
        'nav.source':                   { de: 'QUELLE', en: 'SOURCE' },
        'nav.target':                   { de: 'ZIEL', en: 'TARGET' },
        'nav.source_choose':            { de: 'Quellsystem wählen (R/3)', en: 'Choose Source System (R/3)' },
        'nav.target_choose':            { de: 'Zielsystem wählen (S/4)', en: 'Choose Target System (S/4)' },
        'nav.source_tooltip':           { de: 'Quellsystem (R/3)', en: 'Source System (R/3)' },
        'nav.target_tooltip':           { de: 'Zielsystem (S/4HANA)', en: 'Target System (S/4HANA)' },
        'nav.dil_tooltip':              { de: 'DIL Datenanreicherung', en: 'DIL Data Enrichment' },
        'nav.login':                    { de: 'Anmelden / Session erneuern', en: 'Login / Renew Session' },
        'nav.back_tooltip':             { de: 'Zurück zur Hauptseite', en: 'Back to Main Page' },
        'loading':                      { de: 'Lade...', en: 'Loading...' },
        'error_prefix':                 { de: 'Fehler: ', en: 'Error: ' },
        'cancel':                       { de: 'Abbrechen', en: 'Cancel' },
        'save':                         { de: 'Speichern', en: 'Save' },
        'close':                        { de: 'Schließen', en: 'Close' },
        'delete':                       { de: 'Löschen', en: 'Delete' },
        'update':                       { de: 'Aktualisieren', en: 'Update' },
        'reset':                        { de: 'Zurücksetzen', en: 'Reset' },
        'refresh':                      { de: 'Aktualisieren', en: 'Refresh' },
        'search':                       { de: 'Suchen...', en: 'Search...' },
        'yes':                          { de: 'Ja', en: 'Yes' },
        'no':                           { de: 'Nein', en: 'No' },
        'all':                          { de: 'Alle', en: 'All' },
        'none':                         { de: 'Keine', en: 'None' },

        // Keep-alive banner
        'keepalive.running':            { de: 'Migration läuft', en: 'Migration running' },
        'keepalive.updated':            { de: 'Aktualisiert: {{time}}', en: 'Updated: {{time}}' },
        'keepalive.goto_batch':         { de: 'Zum Batch', en: 'Go to Batch' },

        // ══════════════════════════════════════════════════════════════
        // WORKFLOW STEPS
        // ══════════════════════════════════════════════════════════════
        'wf.step1':                     { de: 'Batch erstellen', en: 'Create Batch' },
        'wf.step2':                     { de: 'Vorschau und Vorbereitung', en: 'Preview & Preparation' },
        'wf.step2b':                    { de: 'Anreichern & Vorschau', en: 'Enrich & Preview' },
        'wf.step3':                     { de: 'Objekt Link', en: 'Object Link' },
        'wf.step3b':                    { de: 'Objekt-Zuordnung', en: 'Object Mapping' },
        'wf.step4':                     { de: 'Validierung', en: 'Validation' },
        'wf.step4b':                    { de: 'Ausführen', en: 'Execute' },
        'wf.step1_title':              { de: 'Neuen Batch erstellen', en: 'Create new batch' },
        'wf.step2_title':              { de: 'Vorschau und Vorbereitung', en: 'Preview and preparation' },
        'wf.step3_title':              { de: 'Objekt Link & Verlinkung', en: 'Object link & linking' },
        'wf.step4_title':              { de: 'Validierung & Prüfung', en: 'Validation & verification' },

        // ══════════════════════════════════════════════════════════════
        // QM MATERIAL
        // ══════════════════════════════════════════════════════════════
        'qm.title':                     { de: 'QM Material', en: 'QM Material' },
        'qm.subtitle':                  { de: 'Migration von Qualitätsmanagement-Materialdokumenten (Q-Zertifikate, Spezifikationen, Prüfberichte)', en: 'Migration of quality management material documents (Q certificates, specifications, test reports)' },
        'qm.wf.step1':                  { de: 'Daten hochladen', en: 'Upload Data' },
        'qm.wf.step2':                  { de: 'Prüfen & Zuordnen', en: 'Review & Map' },
        'qm.wf.step3':                  { de: 'Migration ausführen', en: 'Execute Migration' },
        'qm.wf.step4':                  { de: 'Ergebnis & Bericht', en: 'Result & Report' },
        'qm.kpi.total':                 { de: 'Gesamt', en: 'Total' },
        'qm.kpi.materials':             { de: 'Materialien', en: 'Materials' },
        'qm.kpi.vendors':               { de: 'Lieferanten', en: 'Vendors' },
        'qm.kpi.pending':               { de: 'Ausstehend', en: 'Pending' },
        'qm.kpi.done':                  { de: 'Erledigt', en: 'Done' },
        'qm.kpi.failed':                { de: 'Fehler', en: 'Errors' },
        'qm.upload.title':              { de: 'Daten hochladen', en: 'Upload Data' },
        'qm.upload.drag':               { de: 'XLS / XLSX / CSV Datei hierher ziehen', en: 'Drag XLS / XLSX / CSV file here' },
        'qm.upload.or_click':           { de: 'oder klicken zum Auswählen', en: 'or click to browse' },
        'qm.review.title':              { de: 'Datenprüfung', en: 'Data Review' },
        'qm.review.no_data':            { de: 'Keine Daten geladen', en: 'No data loaded' },
        'qm.exec.title':                { de: 'Migration ausführen', en: 'Execute Migration' },
        'qm.exec.info':                 { de: 'Starten Sie die QM-Material-Migration für die geprüften Datensätze.', en: 'Start the QM material migration for the reviewed records.' },
        'qm.exec.start':                { de: 'Migration starten', en: 'Start Migration' },
        'qm.result.title':              { de: 'Ergebnis & Bericht', en: 'Result & Report' },
        'qm.result.empty':              { de: 'Noch kein Migrationsergebnis vorhanden.', en: 'No migration result available yet.' },

        // ══════════════════════════════════════════════════════════════
        // TECH MATERIAL
        // ══════════════════════════════════════════════════════════════
        'tech.title':                    { de: 'TECH Material', en: 'TECH Material' },
        'tech.subtitle':                 { de: 'Migration von technischen Materialdokumenten (Technische Datenblätter, Sicherheitsdatenblätter, Zeichnungen)', en: 'Migration of technical material documents (technical data sheets, safety data sheets, drawings)' },
        'tech.wf.step1':                 { de: 'Daten hochladen', en: 'Upload Data' },
        'tech.wf.step2':                 { de: 'Prüfen & Zuordnen', en: 'Review & Map' },
        'tech.wf.step3':                 { de: 'Migration ausführen', en: 'Execute Migration' },
        'tech.wf.step4':                 { de: 'Ergebnis & Bericht', en: 'Result & Report' },
        'tech.kpi.total':                { de: 'Gesamt', en: 'Total' },
        'tech.kpi.materials':            { de: 'Materialien', en: 'Materials' },
        'tech.kpi.plants':               { de: 'Werke', en: 'Plants' },
        'tech.kpi.pending':              { de: 'Ausstehend', en: 'Pending' },
        'tech.kpi.done':                 { de: 'Erledigt', en: 'Done' },
        'tech.kpi.failed':               { de: 'Fehler', en: 'Errors' },
        'tech.upload.title':             { de: 'Daten hochladen', en: 'Upload Data' },
        'tech.upload.drag':              { de: 'XLS / XLSX / CSV Datei hierher ziehen', en: 'Drag XLS / XLSX / CSV file here' },
        'tech.upload.or_click':          { de: 'oder klicken zum Auswählen', en: 'or click to browse' },
        'tech.review.title':             { de: 'Datenprüfung', en: 'Data Review' },
        'tech.review.no_data':           { de: 'Keine Daten geladen', en: 'No data loaded' },
        'tech.exec.title':               { de: 'Migration ausführen', en: 'Execute Migration' },
        'tech.exec.info':                { de: 'Starten Sie die TECH-Material-Migration für die geprüften Datensätze.', en: 'Start the TECH material migration for the reviewed records.' },
        'tech.exec.start':               { de: 'Migration starten', en: 'Start Migration' },
        'tech.result.title':             { de: 'Ergebnis & Bericht', en: 'Result & Report' },
        'tech.result.empty':             { de: 'Noch kein Migrationsergebnis vorhanden.', en: 'No migration result available yet.' },

        // ══════════════════════════════════════════════════════════════
        // DASHBOARD (index.html)
        // ══════════════════════════════════════════════════════════════
        'dash.title':                   { de: 'Dashboard', en: 'Dashboard' },
        'dash.kpi.waves':               { de: 'Wellen', en: 'Waves' },
        'dash.kpi.batches':             { de: 'Batches', en: 'Batches' },
        'dash.kpi.docs':                { de: 'Dokumente', en: 'Documents' },
        'dash.kpi.uploaded':            { de: 'Hochgeladen', en: 'Uploaded' },
        'dash.kpi.linked':              { de: 'Verlinkt', en: 'Linked' },
        'dash.kpi.failed':              { de: 'Fehler', en: 'Errors' },

        // KPI tooltips
        'dash.kpi.waves_tip':           { de: 'Anzahl verschiedener Migrationswellen. Jede Welle gruppiert mehrere Batches und hat einen eigenen Zeitplan.', en: 'Number of migration waves. Each wave groups multiple batches with its own schedule.' },
        'dash.kpi.batches_tip':         { de: 'Gesamtanzahl aller erstellten Migrationsbatches über alle Wellen hinweg.', en: 'Total number of all created migration batches across all waves.' },
        'dash.kpi.docs_tip':            { de: 'Gesamtzahl aller DMS-Dokumente (Infosätze) in allen Batches zusammen.', en: 'Total number of all DMS documents (info records) across all batches.' },
        'dash.kpi.uploaded_tip':        { de: 'Erfolgreich ins Zielsystem hochgeladene Dokumente (Container + Dateien).', en: 'Documents successfully uploaded to target system (container + files).' },
        'dash.kpi.linked_tip':          { de: 'Dokumente, die erfolgreich mit Geschäftsobjekten im Zielsystem verknüpft wurden.', en: 'Documents successfully linked to business objects in target system.' },
        'dash.kpi.failed_tip':          { de: 'Fehlgeschlagene Uploads oder Verlinkungen. Können zurückgesetzt und erneut versucht werden.', en: 'Failed uploads or linkings. Can be reset and retried.' },

        // Wave filter
        'dash.wave_filter':             { de: 'Welle:', en: 'Wave:' },
        'dash.all_waves':               { de: 'Alle Wellen', en: 'All Waves' },

        // Cards
        'dash.card.batches':            { de: 'Batches', en: 'Batches' },
        'dash.card.tasks':              { de: 'Aufgaben', en: 'Tasks' },
        'dash.card.waves':              { de: 'Wellen', en: 'Waves' },
        'dash.card.wave_schedule':      { de: 'Wellen-Zeitplan', en: 'Wave Schedule' },
        'dash.card.plan_wave':          { de: 'Welle planen', en: 'Plan Wave' },
        'dash.card.all_batches':        { de: 'Alle Batches', en: 'All Batches' },
        'dash.wave_empty':              { de: 'Noch keine Batches in dieser Welle', en: 'No batches in this wave yet' },

        // Task table
        'dash.task.wave_task':          { de: 'Welle / Aufgabe', en: 'Wave / Task' },
        'dash.task.period':             { de: 'Zeitraum', en: 'Period' },
        'dash.task.status':             { de: 'Status', en: 'Status' },

        // Batch table
        'dash.batch.id':                { de: 'Batch-ID', en: 'Batch ID' },
        'dash.batch.wave':              { de: 'Welle', en: 'Wave' },
        'dash.batch.description':       { de: 'Beschreibung', en: 'Description' },
        'dash.batch.created':           { de: 'Erstellt', en: 'Created' },
        'dash.batch.created_by':        { de: 'Erstellt von', en: 'Created by' },
        'dash.batch.total':             { de: 'Gesamt', en: 'Total' },
        'dash.batch.uploaded':          { de: 'Hochgeladen', en: 'Uploaded' },
        'dash.batch.failed':            { de: 'Fehler', en: 'Errors' },
        'dash.batch.phase':             { de: 'Phase', en: 'Phase' },
        'dash.batch.linking':           { de: 'Verlinkung', en: 'Linking' },
        'dash.batch.actions':           { de: 'Aktionen', en: 'Actions' },
        'dash.loading_schedule':        { de: 'Lade Zeitplan...', en: 'Loading schedule...' },

        // ══════════════════════════════════════════════════════════════
        // BATCH CARDS / STATUS
        // ══════════════════════════════════════════════════════════════
        'status.prepared':              { de: 'Vorbereitet', en: 'Prepared' },
        'status.executing':             { de: 'Upload...', en: 'Uploading...' },
        'status.completed':             { de: 'Hochgeladen', en: 'Uploaded' },
        'status.completed_with_errors': { de: 'Upload (Fehler)', en: 'Upload (Errors)' },
        'status.failed':                { de: 'Fehlgeschlagen', en: 'Failed' },
        'status.linking':               { de: 'Verlinke...', en: 'Linking...' },
        'status.link_completed':        { de: 'Fertig', en: 'Complete' },
        'status.link_completed_partial': { de: 'Teilw. verlinkt', en: 'Partially Linked' },
        'status.link_completed_with_errors': { de: 'Verlinkt (Fehler)', en: 'Linked (Errors)' },
        'status.link_cancelled':        { de: 'Abgebrochen', en: 'Cancelled' },
        'status.link_error':            { de: 'Link-Fehler', en: 'Link Error' },
        'status.documents':             { de: 'Dokumente', en: 'Documents' },
        'status.edit_batch':            { de: 'Batch bearbeiten', en: 'Edit Batch' },

        // Phase labels
        'phase.prepared':               { de: 'Vorbereitung', en: 'Preparation' },
        'phase.upload':                 { de: 'Upload', en: 'Upload' },
        'phase.upload_done':            { de: 'Upload fertig', en: 'Upload Done' },
        'phase.linking':                { de: 'Verlinkung', en: 'Linking' },
        'phase.completed':              { de: 'Abgeschlossen', en: 'Completed' },
        'phase.error':                  { de: 'Fehler', en: 'Error' },

        // ══════════════════════════════════════════════════════════════
        // INDEX.JS (Kanban, Gantt, Modals)
        // ══════════════════════════════════════════════════════════════
        'kanban.unassigned':            { de: 'Nicht zugeordnet', en: 'Unassigned' },
        'kanban.no_batches':            { de: 'Keine Batches vorhanden. Ersten Batch erstellen', en: 'No batches available. Create first batch' },
        'kanban.docs':                  { de: 'Docs', en: 'Docs' },
        'kanban.linked':                { de: 'verlinkt', en: 'linked' },
        'kanban.errors':                { de: 'Fehler', en: 'Errors' },
        'kanban.total':                 { de: 'Gesamt', en: 'Total' },
        'kanban.no_batches_table':      { de: 'Keine Batches vorhanden', en: 'No batches available' },

        // Phase badges
        'phase_badge.upload':           { de: 'Upload', en: 'Upload' },
        'phase_badge.upload_done':      { de: 'Upload ✓', en: 'Upload ✓' },
        'phase_badge.linking':          { de: 'Verlinkung', en: 'Linking' },
        'phase_badge.completed':        { de: 'Fertig', en: 'Complete' },
        'phase_badge.cancelled':        { de: 'Abgebrochen', en: 'Cancelled' },
        'phase_badge.error':            { de: 'Fehler', en: 'Error' },

        // Table action tooltips
        'batch_action.preview':         { de: 'Vorschau', en: 'Preview' },
        'batch_action.results':         { de: 'Validierung', en: 'Validation' },
        'batch_action.edit':            { de: 'Bearbeiten', en: 'Edit' },
        'batch_action.delete':          { de: 'Löschen', en: 'Delete' },

        // Edit batch modal
        'edit_batch.title':             { de: 'Batch bearbeiten', en: 'Edit Batch' },
        'edit_batch.wave':              { de: 'Wave', en: 'Wave' },
        'edit_batch.choose_wave':       { de: '-- Wave wählen --', en: '-- Choose Wave --' },
        'edit_batch.description':       { de: 'Beschreibung (max. 40 Zeichen)', en: 'Description (max 40 chars)' },
        'edit_batch.notes':             { de: 'Notizen', en: 'Notes' },
        'edit_batch.task_assignment':    { de: 'Aufgaben-Zuordnung', en: 'Task Assignment' },
        'edit_batch.task':              { de: 'Aufgabe', en: 'Task' },
        'edit_batch.start':             { de: 'Start', en: 'Start' },
        'edit_batch.duration':          { de: 'Dauer', en: 'Duration' },
        'edit_batch.end':               { de: 'Ende', en: 'End' },
        'edit_batch.days_hint':         { de: 'T = Kalendertage. Checkbox aktiviert die Aufgabe.', en: 'T = Calendar days. Checkbox enables the task.' },
        'edit_batch.delete_confirm':    { de: 'Batch {{id}} wirklich löschen?\n\nAlle Staging-Datensätze, Dateidetails, Logs und Mappings werden unwiderruflich gelöscht.', en: 'Really delete batch {{id}}?\n\nAll staging records, file details, logs and mappings will be permanently deleted.' },

        // Gantt / Wave planning
        'gantt.no_plan':                { de: 'Noch keine Wellenplanung vorhanden.', en: 'No wave plan available yet.' },
        'gantt.plan_first':             { de: 'Erste Welle planen', en: 'Plan First Wave' },
        'gantt.not_planned':            { de: 'Nicht geplant', en: 'Not Planned' },
        'gantt.no_periods':             { de: 'Keine Zeiträume definiert.', en: 'No time periods defined.' },
        'gantt.task':                   { de: 'Aufgabe', en: 'Task' },
        'gantt.days':                   { de: 'Tage', en: 'Days' },
        'gantt.period_undef':           { de: 'Zeitraum nicht definiert', en: 'Period not defined' },
        'gantt.no_task':                { de: 'Keine Aufgabe zugeordnet', en: 'No task assigned' },

        // Task list
        'tasklist.no_plans':            { de: 'Keine Wellenplanung vorhanden', en: 'No wave plans available' },
        'tasklist.linking':             { de: 'Verlinkung', en: 'Linking' },
        'tasklist.status_prep':         { de: 'In Vorbereitung', en: 'In Preparation' },
        'tasklist.status_work':         { de: 'In Arbeit', en: 'In Progress' },
        'tasklist.status_done':         { de: 'Fertig', en: 'Done' },
        'tasklist.edit_wave':           { de: 'Welle bearbeiten', en: 'Edit Wave' },

        // Wave plan modal
        'wave_plan.title':              { de: 'Welle planen', en: 'Plan Wave' },
        'wave_plan.name':               { de: 'Wellenname', en: 'Wave Name' },
        'wave_plan.choose':             { de: '-- Welle wählen --', en: '-- Choose Wave --' },
        'wave_plan.task':               { de: 'Aufgabe', en: 'Task' },
        'wave_plan.start':              { de: 'Start', en: 'Start' },
        'wave_plan.duration':           { de: 'Dauer', en: 'Duration' },
        'wave_plan.end':                { de: 'Ende', en: 'End' },
        'wave_plan.status':             { de: 'Status', en: 'Status' },
        'wave_plan.status_prep':        { de: 'Vorbereitung', en: 'Preparation' },
        'wave_plan.status_work':        { de: 'In Arbeit', en: 'In Progress' },
        'wave_plan.status_done':        { de: 'Fertig', en: 'Done' },
        'wave_plan.days_hint':          { de: 'T = Kalendertage. Ende = Start + Dauer − 1.', en: 'T = Calendar days. End = Start + Duration − 1.' },
        'wave_plan.notes':              { de: 'Notizen', en: 'Notes' },
        'wave_plan.choose_alert':       { de: 'Bitte Welle auswählen', en: 'Please select a wave' },
        'wave_plan.delete_confirm':     { de: 'Wellenplanung "{{name}}" löschen?', en: 'Delete wave plan "{{name}}"?' },

        // ══════════════════════════════════════════════════════════════
        // PREPARE (prepare.html)
        // ══════════════════════════════════════════════════════════════
        'prep.title':                   { de: 'Neuer Migration-Batch', en: 'New Migration Batch' },
        'prep.subtitle':                { de: 'Wähle eine Datenquelle und erstelle einen neuen Migration-Batch', en: 'Choose a data source and create a new migration batch' },
        'prep.tab.dms':                 { de: 'DMS Objekte', en: 'DMS Objects' },
        'prep.tab.excel':               { de: 'DMS-Key Liste', en: 'DMS Key List' },
        'prep.plants.title':            { de: 'Werke auswählen', en: 'Select Plants' },
        'prep.plants.selected':         { de: '{{n}} ausgewählt', en: '{{n}} selected' },
        'prep.plants.approx':           { de: 'ca. Anzahl je Werk ungefiltert', en: 'approx. count per plant unfiltered' },
        'prep.plants.search':           { de: 'Suchen...', en: 'Search...' },
        'prep.plants.reset':            { de: 'Auswahl zurücksetzen', en: 'Reset Selection' },
        'prep.plants.loading':          { de: 'Lade Werke...', en: 'Loading plants...' },
        'prep.plants.local_db':         { de: 'Lokale DB: {{n}} Objekte', en: 'Local DB: {{n}} objects' },
        'prep.plants.load_data':        { de: 'Daten laden & speichern', en: 'Load & Save Data' },
        'prep.results':                 { de: 'Ergebnisse', en: 'Results' },
        'prep.results.filter_reset':    { de: 'Filter zurücksetzen', en: 'Reset Filter' },
        'prep.results.search':          { de: 'Suchen (DOKNR, OBJKY, DOKOB...)', en: 'Search (DOKNR, OBJKY, DOKOB...)' },
        'prep.excel.title':             { de: 'Excel / CSV Datei', en: 'Excel / CSV File' },
        'prep.excel.choose_file':       { de: 'Datei wählen...', en: 'Choose file...' },
        'prep.excel.required_fields':   { de: 'Pflichtfelder: Documentnumber, Documentpart, Documenttype, Documentversion', en: 'Required fields: Documentnumber, Documentpart, Documenttype, Documentversion' },
        'prep.excel.download_template': { de: 'Template herunterladen:', en: 'Download template:' },
        'prep.file.intro':              { de: 'Lade eine Liste mit DMS-Keys hoch. Die Objekt-Verknüpfungen werden anschließend automatisch in DRAD ermittelt – wie bei "DMS Objekte".', en: 'Upload a list of DMS keys. The object links are then resolved automatically from DRAD – just like "DMS Objects".' },
        'prep.file.key_format':         { de: 'Key-Aufbau: <strong>Typ / Version / Teil / Dokumentnummer</strong> (z.&nbsp;B. <code>I71 / 00 / 000 / 0000000000000010002152984</code> intern oder <code>IY1 / 00 / 000 / EQUI330171928</code> extern)', en: 'Key structure: <strong>Type / Version / Part / Document number</strong> (e.g. <code>I71 / 00 / 000 / 0000000000000010002152984</code> internal or <code>IY1 / 00 / 000 / EQUI330171928</code> external)' },
        'prep.file.template_hint':      { de: 'Enthält die erforderlichen Spalten (ein Tabellenblatt): Documenttype, Documentversion, Documentpart, Documentnumber.', en: 'Contains the required columns (one sheet): Documenttype, Documentversion, Documentpart, Documentnumber.' },
        'prep.file.upload_label':       { de: 'DMS-Key-Liste (Excel / CSV)', en: 'DMS key list (Excel / CSV)' },
        'prep.file.required':           { de: 'Spalten: Documenttype, Documentversion, Documentpart, Documentnumber', en: 'Columns: Documenttype, Documentversion, Documentpart, Documentnumber' },
        'prep.file.load_keys':          { de: 'Keys laden & prüfen', en: 'Load & check keys' },
        'prep.file.loading':            { de: 'Suche Objektverknüpfungen in DRAD...', en: 'Resolving object links in DRAD...' },
        'prep.file.summary_title':      { de: 'Geprüfte Keys', en: 'Checked keys' },
        'prep.file.uploaded':           { de: 'Hochgeladen', en: 'Uploaded' },
        'prep.file.found':              { de: 'Gefundene Dokumente', en: 'Documents found' },
        'prep.file.links':              { de: 'Objektverknüpfungen', en: 'Object links' },
        'prep.file.not_found':          { de: 'Ohne Verknüpfung', en: 'Without link' },
        'prep.file.show_skipped':       { de: 'Übersprungene Keys anzeigen', en: 'Show skipped keys' },
        'prep.file.not_found_hint':     { de: 'Diese Keys haben keine (gültige) Objektverknüpfung in DRAD und werden nicht migriert.', en: 'These keys have no (valid) object link in DRAD and will not be migrated.' },
        'prep.file.next_hint':          { de: 'Fülle unten die Batch-Metadaten aus und klicke „Migration Batch erstellen“.', en: 'Fill in the batch metadata below and click “Create Migration Batch”.' },
        'prep.file.invalid':            { de: 'ungültige Zeilen', en: 'invalid rows' },
        'prep.file.msg.load_first':     { de: 'Bitte zuerst die DMS-Keys laden & prüfen.', en: 'Please load & check the DMS keys first.' },
        'prep.meta.title':              { de: 'Batch-Metadaten', en: 'Batch Metadata' },
        'prep.meta.wave':               { de: 'Wave *', en: 'Wave *' },
        'prep.meta.choose_wave':        { de: '-- Wave auswählen --', en: '-- Select Wave --' },
        'prep.meta.description':        { de: 'Beschreibung (max 40 Zeichen)', en: 'Description (max 40 chars)' },
        'prep.meta.description_ph':     { de: 'Kurzbeschreibung...', en: 'Short description...' },
        'prep.meta.notes':              { de: 'Notizen', en: 'Notes' },
        'prep.meta.notes_ph':           { de: 'Detaillierte Notizen...', en: 'Detailed notes...' },
        'prep.create_batch':            { de: 'Migration Batch erstellen', en: 'Create Migration Batch' },
        'prep.excl.title':              { de: 'Objekt-Ausschlüsse (optional)', en: 'Object Exclusions (optional)' },
        'prep.excl.info':               { de: 'Lade eine Excel-Datei hoch, um bestimmte Objekte vom Batch auszuschließen', en: 'Upload an Excel file to exclude specific objects from the batch' },
        'prep.excl.download_empty':     { de: 'Leeres Template herunterladen', en: 'Download Empty Template' },
        'prep.excl.choose_file':        { de: 'Ausschluss-Excel wählen...', en: 'Choose exclusion Excel...' },
        'prep.excl.remove':             { de: 'Entfernen', en: 'Remove' },

        // Exclusion rules modal
        'prep.excl_rules.title':        { de: 'Ausschluss-Regeln für DMS-Objekte', en: 'Exclusion Rules for DMS Objects' },
        'prep.excl_rules.info':         { de: 'DMS-Container werden nur geladen, wenn mindestens ein verknüpftes Objekt nicht gelöscht/geschlossen ist.', en: 'DMS containers are only loaded if at least one linked object is not deleted/closed.' },
        'prep.excl_rules.desc':         { de: 'Beschreibung', en: 'Description' },
        'prep.excl_rules.condition':    { de: 'Ausschluss wenn...', en: 'Exclude when...' },

        // DOKOB filter modal
        'prep.dokob.title':             { de: 'DOKOB-Filter', en: 'DOKOB Filter' },
        'prep.dokob.info':              { de: 'DMS-Objekte für die Migration vorbereitet', en: 'DMS objects prepared for migration' },
        'prep.dokob.filter':            { de: 'Objekttyp-Filter (DOKOB)', en: 'Object Type Filter (DOKOB)' },
        'prep.dokob.no_data':           { de: 'Noch keine Daten geladen', en: 'No data loaded yet' },
        'prep.dokob.all_selected':      { de: 'Alle Objekttypen ausgewählt', en: 'All object types selected' },
        'prep.dokob.create_batch':      { de: 'Batch erstellen', en: 'Create Batch' },

        // prepare.js messages
        'prep.msg.choose_wave':         { de: 'Bitte eine Wave auswählen!', en: 'Please select a wave!' },
        'prep.msg.choose_dokob':        { de: 'Bitte mindestens einen Objekttyp auswählen!', en: 'Please select at least one object type!' },
        'prep.msg.creating':            { de: 'Starte Batch-Erstellung...', en: 'Starting batch creation...' },
        'prep.msg.processing':          { de: 'Verarbeite...', en: 'Processing...' },
        'prep.msg.connection_error':    { de: 'Verbindungsfehler', en: 'Connection error' },
        'prep.msg.choose_file':         { de: 'Bitte eine Datei auswählen', en: 'Please choose a file' },
        'prep.msg.creating2':           { de: 'Wird erstellt...', en: 'Creating...' },
        'prep.msg.created_ok':          { de: 'Migration Batch erfolgreich erstellt!', en: 'Migration batch created successfully!' },
        'prep.msg.continue':            { de: 'Weiter: Anreichern & Vorschau', en: 'Continue: Enrich & Preview' },
        'prep.msg.excluded':            { de: 'Ausgeschlossen:', en: 'Excluded:' },
        'prep.msg.objects':             { de: 'Objekte', en: 'Objects' },
        'prep.msg.unknown_error':       { de: 'Unbekannter Fehler', en: 'Unknown error' },
        'prep.msg.retry':               { de: 'Erneut versuchen', en: 'Try Again' },
        'prep.msg.select_plant':        { de: 'Bitte mindestens ein Werk auswählen!', en: 'Please select at least one plant!' },
        'prep.msg.connecting_dil':      { de: 'Verbinde mit DIL...', en: 'Connecting to DIL...' },
        'prep.msg.cache_error':         { de: 'Werke-Cache Fehler', en: 'Plant cache error' },
        'prep.msg.no_dms_objects':      { de: 'Keine DMS-Objekte in der lokalen Datenbank. Bitte zuerst Daten laden!', en: 'No DMS objects in local database. Please load data first!' },
        'prep.result.batch_id':         { de: 'Batch ID:', en: 'Batch ID:' },
        'prep.result.records':          { de: 'Datensätze:', en: 'Records:' },
        'prep.result.overview':         { de: 'Übersicht', en: 'Overview' },
        'prep.msg.cache_date':          { de: '(Stand: {{date}})', en: '(As of: {{date}})' },
        'prep.msg.cache_updated':       { de: 'Aktualisiert ({{n}} Werke, {{time}})', en: 'Updated ({{n}} plants, {{time}})' },
        'prep.msg.done':                { de: 'Fertig!', en: 'Done!' },
        'prep.msg.server_conn_error':   { de: 'Verbindungsfehler zum Server', en: 'Server connection error' },
        'prep.msg.no_data':             { de: 'Keine Daten', en: 'No data' },
        'prep.msg.filtered_from':       { de: '(gefiltert aus {{n}})', en: '(filtered from {{n}})' },
        'prep.msg.entries_shown':       { de: '{{shown}} von {{total}} Einträgen{{filter}}', en: '{{shown}} of {{total}} entries{{filter}}' },
        'prep.stats.batch_label':       { de: 'Batch', en: 'Batch' },
        'prep.stats.of_total':          { de: 'von {{n}}', en: 'of {{n}}' },
        'prep.stats.no_file':           { de: 'Ohne Datei', en: 'No File' },
        'prep.stats.status_excl':       { de: 'Status', en: 'Status' },
        'prep.stats.no_file_tip':       { de: '{{n}} ohne Datei', en: '{{n}} without file' },
        'prep.stats.status_excl_tip':   { de: '{{n}} Status-ausgeschlossen', en: '{{n}} status-excluded' },
        'prep.stats.toggle_tip':        { de: 'Klicken zum An-/Abwählen für Batch', en: 'Click to select/deselect for batch' },
        'prep.msg.db_no_file':          { de: '{{n}} ohne Datei', en: '{{n}} without file' },
        'prep.msg.db_status':           { de: '{{n}} Status', en: '{{n}} status' },
        'prep.msg.no_export_data':      { de: 'Keine Daten zum Exportieren!', en: 'No data to export!' },
        'prep.msg.no_dokob':            { de: 'Keine Objekttypen!', en: 'No object types!' },
        'prep.msg.n_of_total_dokob':    { de: '{{n}} von {{total}} Objekttypen', en: '{{n}} of {{total}} object types' },
        'prep.msg.no_data_loaded':      { de: 'Noch keine Daten geladen — bitte zuerst Daten laden.', en: 'No data loaded yet — please load data first.' },
        'prep.msg.file_processing':     { de: 'Datei wird verarbeitet...', en: 'Processing file...' },
        'prep.msg.excl_keys_loaded':    { de: '{{n}} Ausschluss-Keys aus {{sheets}} Objekttypen geladen:', en: '{{n}} exclusion keys from {{sheets}} object types loaded:' },

        // Exclusion rules DOKOB names and conditions
        'prep.rules.equi':             { de: 'Equipment', en: 'Equipment' },
        'prep.rules.iflot':            { de: 'Techn. Platz', en: 'Functional Location' },
        'prep.rules.pmaufk':           { de: 'PM-Auftrag', en: 'PM Order' },
        'prep.rules.pmqmel':           { de: 'PM-Meldung', en: 'PM Notification' },
        'prep.rules.smqmel':           { de: 'Service-Meldung', en: 'Service Notification' },
        'prep.rules.pmafvc':           { de: 'PM-Vorgang', en: 'PM Operation' },
        'prep.rules.stko':             { de: 'Stücklistenkopf', en: 'BOM Header' },
        'prep.rules.stpo':             { de: 'Stücklistenpos.', en: 'BOM Item' },
        'prep.rules.plko':             { de: 'Arbeitsplan', en: 'Routing' },
        'prep.rules.no_filter':        { de: 'Keine Filterung: QMQMEL, DRAW, MARA, MARC und alle anderen DOKOB', en: 'No filtering: QMQMEL, DRAW, MARA, MARC and all other DOKOB' },
        'prep.rules.equi_cond':        { de: 'JEST Status: I0320, I0013, I0076 (gelöscht)', en: 'JEST Status: I0320, I0013, I0076 (deleted)' },
        'prep.rules.iflot_cond':       { de: 'JEST Status: I0320, I0013, I0076 (gelöscht)', en: 'JEST Status: I0320, I0013, I0076 (deleted)' },
        'prep.rules.pmaufk_cond':      { de: 'JEST Status: I0045 (TECO), I0046 (Closed) + I0013, I0076 (gelöscht)', en: 'JEST Status: I0045 (TECO), I0046 (Closed) + I0013, I0076 (deleted)' },
        'prep.rules.pmqmel_cond':      { de: 'JEST Status: I0072 (geschlossen) + I0076 (gelöscht)', en: 'JEST Status: I0072 (closed) + I0076 (deleted)' },
        'prep.rules.smqmel_cond':      { de: 'JEST Status: I0072 (geschlossen) + I0076 (gelöscht)', en: 'JEST Status: I0072 (closed) + I0076 (deleted)' },
        'prep.rules.pmafvc_cond':      { de: 'Wenn zugehöriger Auftrag TECO/Closed/gelöscht', en: 'When related order is TECO/Closed/deleted' },
        'prep.rules.stko_cond':        { de: "STKO.LOEKZ = 'X'", en: "STKO.LOEKZ = 'X'" },
        'prep.rules.stpo_cond':        { de: "STPO.LKENZ = 'X'", en: "STPO.LKENZ = 'X'" },
        'prep.rules.plko_cond':        { de: "PLKO.LOEKZ = 'X'", en: "PLKO.LOEKZ = 'X'" },
        'prep.rules.note':             { de: '<i class="fas fa-lightbulb"></i> <strong>Hinweis:</strong> JEST.INACT muss leer sein (\'\'), damit der Status aktiv ist.', en: '<i class="fas fa-lightbulb"></i> <strong>Note:</strong> JEST.INACT must be empty (\'\') for the status to be active.' },
        'prep.file.template_hint':     { de: 'Enthält alle erforderlichen Spalten und eine Anleitung.', en: 'Contains all required columns and instructions.' },
        'prep.th.ablage':              { de: 'Ablage', en: 'Storage' },
        'prep.dokob.filter_hint':      { de: 'Klicke auf die DOKOB-Karten oben um zu filtern.', en: 'Click on the DOKOB cards above to filter.' },
        'prep.plants.count_hint_title': { de: 'Die Angabe pro Werk ist eine ungefilterte Brutto-Zahl aus dem Cache (ohne Status-Ausschlüsse). Die tatsächliche Batch-Anzahl kann geringer sein.', en: 'The count per plant is an unfiltered gross number from cache (without status exclusions). The actual batch count may be lower.' },
        'prep.plants.refresh_title':   { de: 'Werke-Cache neu laden (dauert 2-3 Min)', en: 'Reload plant cache (takes 2-3 min)' },
        'prep.plants.rules_title':     { de: 'Ausschluss-Regeln anzeigen', en: 'Show exclusion rules' },
        'prep.plants.clear_title':     { de: 'Auswahl zurücksetzen', en: 'Reset selection' },
        'prep.btn.export_csv_title':   { de: 'Als CSV exportieren', en: 'Export as CSV' },
        'prep.btn.reset_filter_title': { de: 'Filter zurücksetzen', en: 'Reset filter' },
        'prep.meta.wave_hint':         { de: 'Wellen werden im <a href="/">Dashboard</a> verwaltet', en: 'Waves are managed in the <a href="/">Dashboard</a>' },

        // ══════════════════════════════════════════════════════════════
        // PREVIEW (preview.html + preview.js)
        // ══════════════════════════════════════════════════════════════
        'prev.title':                   { de: 'Batch-Vorschau', en: 'Batch Preview' },
        'prev.subtitle':                { de: 'Vorschau der Daten, die bei der Migration übertragen werden', en: 'Preview of data to be transferred during migration' },
        'prev.stats.total':             { de: 'Total', en: 'Total' },
        'prev.stats.excl':              { de: 'Excl.', en: 'Excl.' },
        'prev.stats.size':              { de: 'Größe', en: 'Size' },
        'prev.stats.pacing':            { de: 'Pacing', en: 'Pacing' },
        'prev.stats.est_runtime':       { de: 'Gesch. Laufzeit', en: 'Est. Runtime' },
        'prev.stats.runtime_details':   { de: 'Laufzeit-Details', en: 'Runtime Details' },
        'prev.staging_records':         { de: 'Staging-Datensätze', en: 'Staging Records' },
        'prev.records_selected':        { de: '{{n}} Datensätze ausgewählt', en: '{{n}} records selected' },
        'prev.btn.columns':             { de: 'Spalten', en: 'Columns' },
        'prev.btn.refresh':             { de: 'Daten anreichern', en: 'Enrich Data' },
        'prev.btn.exclude_99mb':        { de: '>99MB ausschließen', en: 'Exclude >99MB' },
        'prev.btn.execute_selected':    { de: 'Ausgewählte ausführen', en: 'Execute Selected' },
        'prev.btn.execute_all':         { de: 'Alle ausführen', en: 'Execute All' },
        'prev.btn.cancel_migration':    { de: 'Migration abbrechen', en: 'Cancel Migration' },
        'prev.btn.reset_failed':        { de: 'Fehler/Partial zurücksetzen', en: 'Reset Failed/Partial' },
        'prev.btn.retry_failed':        { de: 'Fehler/Partial wiederholen', en: 'Retry Failed/Partial' },
        'prev.search_ph':               { de: 'DOKNR / OBJKY / Beschreibung suchen (alle Datensätze)...', en: 'Search DOKNR / OBJKY / Description (all records)...' },

        // Status filters
        'prev.filter.all_status':       { de: 'Alle Status', en: 'All Status' },
        'prev.filter.pending':          { de: '⏳ Pending', en: '⏳ Pending' },
        'prev.filter.success':          { de: '✅ Erfolgreich', en: '✅ Successful' },
        'prev.filter.failed':           { de: '❌ Fehlgeschlagen', en: '❌ Failed' },
        'prev.filter.partial':          { de: '⚠️ Teilweise', en: '⚠️ Partial' },
        'prev.filter.orphan':           { de: '⊘ Verwaist', en: '⊘ Orphaned' },
        'prev.filter.unprocessed':      { de: '📋 Nur unbearbeitet', en: '📋 Unprocessed Only' },
        'prev.filter.all_errors':       { de: 'Alle Fehlerkategorien', en: 'All Error Categories' },

        // Column toggle modal
        'prev.columns.title':          { de: 'Spalten ein-/ausblenden', en: 'Show/Hide Columns' },
        'prev.columns.hint':           { de: 'Source/Target-Paare sind nebeneinander angeordnet.', en: 'Source/Target pairs are arranged side by side.' },
        'prev.columns.type':           { de: 'Typ/Version/Teil', en: 'Type/Version/Part' },
        'prev.columns.docstatus':      { de: 'Dokumentenstatus', en: 'Document Status' },
        'prev.columns.description':    { de: 'Beschreibung', en: 'Description' },
        'prev.columns.filename':       { de: 'Dateiname', en: 'Filename' },
        'prev.columns.filesize':       { de: 'Dateigröße', en: 'File Size' },
        'prev.columns.filecount':      { de: 'Dateianzahl (S/T)', en: 'File Count (S/T)' },
        'prev.columns.objlinks':       { de: 'Objektlinks (S/E/T)', en: 'Object Links (S/E/T)' },
        'prev.columns.storage':        { de: 'Ablage (KPRO/DB)', en: 'Storage (KPRO/DB)' },
        'prev.columns.source_authgrp': { de: 'Quell-Ber.gruppe', en: 'Source Auth Group' },
        'prev.columns.source_user':    { de: 'Pers. Resp. Source', en: 'Pers. Resp. Source' },
        'prev.columns.pers_resp_source':    { de: 'Pers. Resp. Source', en: 'Pers. Resp. Source' },
        'prev.columns.pers_resp_target':    { de: 'Pers. Resp. Target', en: 'Pers. Resp. Target' },
        'prev.columns.target_authgrp': { de: 'Ziel-Ber.gruppe', en: 'Target Auth Group' },
        'prev.columns.exec_status':    { de: 'Ausführungsstatus', en: 'Execution Status' },
        'prev.columns.link_status':    { de: 'Link-Status', en: 'Link Status' },
        'prev.columns.error_cat':      { de: 'Fehlerkategorie', en: 'Error Category' },
        'prev.columns.source_loio':    { de: 'Quell-LOIO-ID', en: 'Source LOIO ID' },
        'prev.columns.created_at':     { de: 'Erstellt am', en: 'Created At' },
        'prev.columns.created_by':     { de: 'Erstellt von', en: 'Created By' },
        'prev.columns.exec_started':   { de: 'Ausführung gestartet', en: 'Execution Started' },
        'prev.columns.exec_completed': { de: 'Ausführung abgeschlossen', en: 'Execution Completed' },
        'prev.columns.exec_error':     { de: 'Ausführungsfehler', en: 'Execution Error' },

        // Table header translations (short labels for <th>)
        'prev.th.source_doc':          { de: 'Quell-Dok.', en: 'Source Doc' },
        'prev.th.target_doc':          { de: 'Ziel-Dok.', en: 'Target Doc' },
        'prev.th.type_info':           { de: 'Typ/Ver./Teil', en: 'Type/Ver/Part' },
        'prev.th.target_type':         { de: 'Ziel-Typ', en: 'Target Type' },
        'prev.th.source_dokob':        { de: 'Quell-DOKOB', en: 'Source DOKOB' },
        'prev.th.target_dokob':        { de: 'Ziel-DOKOB', en: 'Target DOKOB' },
        'prev.th.source_objky':        { de: 'Quell-OBJKY', en: 'Source OBJKY' },
        'prev.th.target_objky':        { de: 'Ziel-OBJKY', en: 'Target OBJKY' },
        'prev.th.docstatus':           { de: 'Dok.-Status', en: 'Doc Status' },
        'prev.th.description':         { de: 'Beschreibung', en: 'Description' },
        'prev.th.filename':            { de: 'Dateiname', en: 'Filename' },
        'prev.th.file_size':           { de: 'Dateigröße', en: 'File Size' },
        'prev.th.file_count':          { de: 'Dateien (Q/Z)', en: 'Files (S/T)' },
        'prev.th.link_count':          { de: 'Links (Q/V/Z)', en: 'Links (S/E/T)' },
        'prev.th.ablage':              { de: 'Ablage', en: 'Storage' },
        'prev.th.source_auth_group':   { de: 'Quell-Ber.gr.', en: 'Src Auth' },
        'prev.th.source_user':          { de: 'Pers. Resp. (Q)', en: 'Pers. Resp. (S)' },
        'prev.th.pers_resp_source':     { de: 'Pers. Resp. (Q)', en: 'Pers. Resp. (S)' },
        'prev.th.pers_resp_target':     { de: 'Pers. Resp. (Z)', en: 'Pers. Resp. (T)' },
        'prev.th.target_auth_group':   { de: 'Ziel-Ber.gr.', en: 'Tgt Auth' },
        'prev.th.execution':           { de: 'Ausführung', en: 'Execution' },
        'prev.th.link_status':         { de: 'Link-Status', en: 'Link Status' },
        'prev.th.error_cat':           { de: 'Fehlerkategorie', en: 'Error Category' },
        'prev.th.source_loio':         { de: 'Quell-LOIO', en: 'Source LOIO' },
        'prev.th.mime_type':           { de: 'MIME-Typ', en: 'MIME Type' },
        'prev.th.created_at':          { de: 'Erstellt am', en: 'Created At' },
        'prev.th.created_by':          { de: 'Erstellt von', en: 'Created By' },
        'prev.th.exec_started':        { de: 'Ausf. gestartet', en: 'Exec Started' },
        'prev.th.exec_completed':      { de: 'Ausf. abgeschlossen', en: 'Exec Completed' },
        'prev.th.exec_error':          { de: 'Ausf.-Fehler', en: 'Exec Error' },
        'prev.th.actions':             { de: 'Aktionen', en: 'Actions' },

        // Column modal labels (for entries missing data-i18n)
        'prev.col.source_doc':         { de: 'Quell-Dok.', en: 'Source Doc' },
        'prev.col.target_doc':         { de: 'Ziel-Dok.', en: 'Target Doc' },
        'prev.col.target_type':        { de: 'Ziel-Typ', en: 'Target Type' },
        'prev.col.source_dokob':       { de: 'Quell-DOKOB', en: 'Source DOKOB' },
        'prev.col.target_dokob':       { de: 'Ziel-DOKOB', en: 'Target DOKOB' },
        'prev.col.source_objky':       { de: 'Quell-OBJKY', en: 'Source OBJKY' },
        'prev.col.target_objky':       { de: 'Ziel-OBJKY', en: 'Target OBJKY' },
        'prev.col.mime_type':          { de: 'MIME-Typ', en: 'MIME Type' },

        'prev.record_details':         { de: 'Datensatz-Details', en: 'Record Details' },
        'prev.pacing.response_tip':    { de: 'Response-basiert: Nächster Upload startet sofort nach API-Antwort', en: 'Response-based: Next upload starts immediately after API response' },
        'prev.pacing.fixed_tip':       { de: 'Fixierte Wartezeit zwischen Uploads', en: 'Fixed wait time between uploads' },
        'prev.pacing.fixed_label':     { de: 'Fixiert: {{n}}s', en: 'Fixed: {{n}}s' },
        'prev.searching':              { de: 'Suche...', en: 'Searching...' },
        'prev.filter_hits':            { de: '{{n}} Treffer ({{filters}})', en: '{{n}} hits ({{filters}})' },
        'prev.records_of_total':       { de: '{{n}} von {{total}} Datensätze', en: '{{n}} of {{total}} records' },
        'prev.filter_active':          { de: 'Filter: {{filter}} ({{n}} von {{total}})', en: 'Filter: {{filter}} ({{n}} of {{total}})' },
        'prev.stats.of_total':         { de: 'von {{n}} gesamt', en: 'of {{n}} total' },
        'prev.stats.all_done':         { de: '✓ Alle {{n}} erledigt', en: '✓ All {{n}} done' },
        'prev.stats.preview_info':     { de: 'Vorschau: 100 von {{n}} Records (Execute verarbeitet alle)', en: 'Preview: 100 of {{n}} records (Execute processes all)' },
        'prev.stats.n_records':        { de: '{{n}} Records', en: '{{n}} Records' },
        'prev.showing_filtered':       { de: 'Zeige {{n}} von {{total}}', en: 'Showing {{n}} of {{total}}' },
        'prev.n_records':              { de: '{{n}} Datensätze', en: '{{n}} records' },
        'prev.records_selected':       { de: '{{n}} Datensätze ausgewählt', en: '{{n}} records selected' },
        'prev.tip.file_count':         { de: 'Quelldateien: {{src}}, Zieldateien: {{tgt}}', en: 'Source files: {{src}}, Target files: {{tgt}}' },
        'prev.tip.file_count_mismatch': { de: 'Quelldateien: {{src}}, Zieldateien: {{tgt}} — Mismatch!', en: 'Source files: {{src}}, Target files: {{tgt}} — Mismatch!' },
        'prev.tip.all_links_excluded': { de: 'Alle {{n}} Links ausgeschlossen → wird bei Ausführung übersprungen (⊘ Verwaist)', en: 'All {{n}} links excluded → will be skipped during execution (⊘ Orphaned)' },
        'prev.tip.partial_excluded':   { de: 'Quelle: {{src}}, Ausgeschl.: {{excl}}, Ziel: {{tgt}} — Teilweise ausgeschlossen', en: 'Source: {{src}}, Excluded: {{excl}}, Target: {{tgt}} — Partially excluded' },
        'prev.filter.all':             { de: 'Alle', en: 'All' },
        'prev.stat.excl_title':        { de: 'Durch Ausschlüsse entfernte Objekte', en: 'Objects removed by exclusions' },
        'prev.btn.columns_title':      { de: 'Spalten ein-/ausblenden', en: 'Show/Hide columns' },
        'prev.btn.refresh_title':      { de: 'Metadaten, Dateinamen abrufen und Regeln anwenden', en: 'Fetch metadata, filenames and apply rules' },
        'prev.btn.exclude_title':      { de: 'Dateien größer als 99MB ausschließen', en: 'Exclude files larger than 99MB' },
        'prev.btn.percent_encode':     { de: 'Non-Latin %-Encoding', en: 'Non-Latin %-Encoding' },
        'prev.btn.percent_encode_title': { de: 'Non-Latin Zeichen percent-kodieren statt ersetzen', en: 'Percent-encode non-Latin characters instead of replacing' },

        // Execution badges
        'exec.success':                { de: 'Erfolgreich', en: 'Successful' },
        'exec.failed':                 { de: 'Fehlgeschlagen', en: 'Failed' },
        'exec.partial':                { de: 'Teilweise', en: 'Partial' },
        'exec.pending':                { de: 'Ausstehend', en: 'Pending' },
        'exec.orphan':                 { de: '⊘ Verwaist', en: '⊘ Orphaned' },
        'exec.orphan_tip':             { de: 'Übersprungen: Alle Objektlinks ausgeschlossen', en: 'Skipped: All object links excluded' },

        // Link status badges
        'link.open':                   { de: 'Offen', en: 'Open' },
        'link.linking':                { de: 'Verlinkt...', en: 'Linking...' },
        'link.linked':                 { de: 'Verlinkt', en: 'Linked' },
        'link.exists':                 { de: 'Existiert', en: 'Exists' },
        'link.error':                  { de: 'Fehler', en: 'Error' },
        'link.skipped':                { de: 'Übersprungen', en: 'Skipped' },
        'link.not_needed':             { de: 'Nicht notwendig', en: 'Not needed' },
        'link.not_needed_tip':         { de: 'Keine Dateien im Quellsystem – Link nicht notwendig', en: 'No files in source system – linking not needed' },

        // Validation warnings (non-Latin characters)
        'val.non_latin_summary':       { de: 'Records mit nicht-lateinischen Zeichen (z.B. Koreanisch, CJK)', en: 'Records with non-Latin characters (e.g. Korean, CJK)' },
        'val.non_latin_file_tip':      { de: 'Dateiname enthält nicht-lateinische Zeichen – wird im SAP Slug-Header durch _ ersetzt', en: 'Filename contains non-Latin chars – replaced with _ in SAP Slug header' },
        'link.open_tip':               { de: 'Bereit zur Verlinkung', en: 'Ready for linking' },
        'link.linking_tip':            { de: 'Wird verlinkt', en: 'Being linked' },
        'link.linked_tip':             { de: 'Verlinkt', en: 'Linked' },
        'link.exists_tip':             { de: 'Link existiert bereits', en: 'Link already exists' },
        'link.error_tip':              { de: 'Verlinkung fehlgeschlagen', en: 'Linking failed' },
        'link.skipped_tip':            { de: 'Kein Objekt-Mapping', en: 'No object mapping' },

        // Error categories
        'err.API_KEY':                 { de: 'API-Key ungültig', en: 'Invalid API Key' },
        'err.TOKEN_EXPIRED':           { de: 'Token abgelaufen', en: 'Token Expired' },
        'err.INVALID_TOKEN':           { de: 'Token ungültig', en: 'Invalid Token' },
        'err.CSRF_ERROR':              { de: 'CSRF Fehler', en: 'CSRF Error' },
        'err.NOT_FOUND':               { de: 'Nicht gefunden', en: 'Not Found' },
        'err.NO_FILES':                { de: 'Keine Dateien', en: 'No Files' },
        'err.READ_ERROR':              { de: 'Lesefehler', en: 'Read Error' },
        'err.CONTAINER_CREATE_FAIL':   { de: 'Anlage fehlgeschlagen', en: 'Container Creation Failed' },
        'err.ALREADY_EXISTS':          { de: 'Existiert bereits', en: 'Already Exists' },
        'err.LOCKED':                  { de: 'Gesperrt', en: 'Locked' },
        'err.PAYLOAD_TOO_LARGE':       { de: 'Zu groß', en: 'Too Large' },
        'err.TIMEOUT':                 { de: 'Timeout', en: 'Timeout' },
        'err.GATEWAY_TIMEOUT':         { de: 'Gateway Timeout', en: 'Gateway Timeout' },
        'err.RATE_LIMIT':              { de: 'Rate Limit', en: 'Rate Limit' },
        'err.SERVER_ERROR':            { de: 'Serverfehler', en: 'Server Error' },
        'err.BAD_REQUEST':             { de: 'Ungültige Anfrage', en: 'Bad Request' },
        'err.UNKNOWN':                 { de: 'Unbekannt', en: 'Unknown' },
        'err.NO_SOURCE_FILES':         { de: 'Keine Dateien im Quellsystem', en: 'No Files in Source System' },
        'err.TIMEOUT_RETRY':           { de: 'Timeout (Retry möglich)', en: 'Timeout (Retry Possible)' },
        'err.NOT_IMPLEMENTED':         { de: 'Serverfehler (501)', en: 'Server Error (501)' },
        'err.BUG_FIXED':               { de: 'Code-Bug behoben', en: 'Code Bug Fixed' },
        'err.CONNECTION_ERROR':        { de: 'Verbindungsfehler', en: 'Connection Error' },
        'err.AUTH_ERROR':              { de: 'Authentifizierung', en: 'Authentication' },
        'err.FORBIDDEN':               { de: 'Zugriff verweigert (403)', en: 'Access Denied (403)' },
        'err.CODE_BUG':                { de: 'Code-Bug', en: 'Code Bug' },
        'err.UPLOAD_FAIL':             { de: 'Upload-Fehler', en: 'Upload Error' },
        'err.FILE_TOO_LARGE':          { de: 'Dateigröße überschritten', en: 'File Size Exceeded' },

        // File size tooltips
        'filesize.high_risk':          { de: 'Hohes Risiko: >99MB kann fehlschlagen', en: 'High risk: >99MB may fail' },
        'filesize.medium':             { de: 'Mittlere Größe: 10-99MB', en: 'Medium size: 10-99MB' },
        'filesize.safe':               { de: 'Sichere Größe: ≤10MB', en: 'Safe size: ≤10MB' },

        // Migration progress
        'mig.running':                 { de: 'Migration läuft...', en: 'Migration running...' },
        'mig.starting':                { de: 'Starte...', en: 'Starting...' },
        'mig.eta_calc':                { de: 'ETA: berechne...', en: 'ETA: calculating...' },
        'mig.polling':                 { de: 'Polling aktiv', en: 'Polling active' },
        'mig.last_updated':            { de: 'Zuletzt aktualisiert: {{time}}', en: 'Last updated: {{time}}' },
        'mig.remaining':               { de: 'Verbleibend: {{n}}', en: 'Remaining: {{n}}' },

        // Migration confirmations/alerts
        'mig.confirm_all':             { de: 'Migration für alle Datensätze in diesem Batch ausführen?', en: 'Execute migration for all records in this batch?' },
        'mig.executing':               { de: 'Wird ausgeführt...', en: 'Executing...' },
        'mig.stopped':                 { de: 'Migration gestoppt!', en: 'Migration stopped!' },
        'mig.reason':                  { de: 'Grund:', en: 'Reason:' },
        'mig.processed':               { de: 'Verarbeitet:', en: 'Processed:' },
        'mig.successful':              { de: 'Erfolgreich:', en: 'Successful:' },
        'mig.failed':                  { de: 'Fehlgeschlagen:', en: 'Failed:' },
        'mig.remaining2':              { de: 'Verbleibend:', en: 'Remaining:' },
        'mig.token_expired':           { de: 'Token abgelaufen. Bitte neu einloggen.', en: 'Token expired. Please log in again.' },
        'mig.completed':               { de: 'Migration abgeschlossen!', en: 'Migration completed!' },
        'mig.total_label':             { de: 'Gesamt:', en: 'Total:' },
        'mig.not_logged_in':           { de: 'Nicht eingeloggt! Bitte zuerst bei SAP anmelden.', en: 'Not logged in! Please log in to SAP first.' },
        'mig.already_running':         { de: 'Migration läuft bereits!', en: 'Migration already running!' },
        'mig.wait_for_completion':     { de: 'Bitte warten Sie, bis die aktuelle Migration abgeschlossen ist.', en: 'Please wait until the current migration is completed.' },
        'mig.failed_msg':              { de: 'Migration fehlgeschlagen: {{msg}}', en: 'Migration failed: {{msg}}' },
        'mig.error_msg':               { de: 'Fehler bei der Migration: {{msg}}', en: 'Migration error: {{msg}}' },
        'mig.cancel_confirm':          { de: 'Migration wirklich abbrechen?\n\nBereits verarbeitete Datensätze bleiben erhalten.', en: 'Really cancel migration?\n\nAlready processed records will be kept.' },
        'mig.cancelling':              { de: 'Wird abgebrochen...', en: 'Cancelling...' },
        'mig.cancel_requested':        { de: 'Abbruch angefordert...', en: 'Cancellation requested...' },
        'mig.cancel_failed':           { de: 'Abbruch fehlgeschlagen: {{msg}}', en: 'Cancellation failed: {{msg}}' },
        'mig.cancel_error':            { de: 'Fehler beim Abbrechen: {{msg}}', en: 'Cancel error: {{msg}}' },
        'mig.select_records':          { de: 'Bitte Datensätze auswählen', en: 'Please select records' },
        'mig.confirm_selected':        { de: 'Migration für {{n}} ausgewählte Datensätze ausführen?', en: 'Execute migration for {{n}} selected records?' },
        'mig.executing_n':             { de: 'Führe {{n}} aus...', en: 'Executing {{n}}...' },
        'mig.selected':                { de: 'Datensätze ausgewählt', en: 'Records selected' },
        'mig.no_records':              { de: 'Keine Datensätze gefunden', en: 'No records found' },

        // >99MB exclusion
        'mig.no_99mb':                 { de: 'Keine Dateien größer als 99MB in diesem Batch gefunden.', en: 'No files larger than 99MB found in this batch.' },
        'mig.exclude_99mb':            { de: '{{n}} Dateien größer als 99MB ausschließen?', en: 'Exclude {{n}} files larger than 99MB?' },
        'mig.include_99mb':            { de: '{{n}} Dateien größer als 99MB wieder einschließen?', en: 'Re-include {{n}} files larger than 99MB?' },
        'mig.excluded_ok':             { de: 'Datensätze als übersprungen markiert.', en: 'Records marked as skipped.' },
        'mig.included_ok':             { de: 'Datensätze wieder eingeschlossen.', en: 'Records re-included.' },
        'mig.exclude_error':           { de: 'Fehler beim Ausschließen: {{msg}}', en: 'Exclusion error: {{msg}}' },

        // Reset/Retry
        'mig.reset_confirm':           { de: 'Alle fehlgeschlagenen und teilweise migrierten Datensätze auf "Ausstehend" zurücksetzen?', en: 'Reset all failed and partially migrated records to "Pending"?' },
        'mig.resetting':               { de: 'Wird zurückgesetzt...', en: 'Resetting...' },
        'mig.reset_done':              { de: 'Zurücksetzen abgeschlossen!', en: 'Reset completed!' },
        'mig.reset_failed':            { de: 'Zurücksetzen fehlgeschlagen: {{msg}}', en: 'Reset failed: {{msg}}' },
        'mig.reset_error':             { de: 'Fehler beim Zurücksetzen: {{msg}}', en: 'Reset error: {{msg}}' },
        'mig.refresh_confirm':         { de: 'Daten anreichern?\n\nDies führt folgende Schritte aus:\n1. Metadata aus DIL holen\n2. Dateinamen aus DIL.DRAW holen\n3. Migration Rules anwenden', en: 'Enrich data?\n\nThis will perform the following steps:\n1. Fetch metadata from DIL\n2. Fetch filenames from DIL.DRAW\n3. Apply migration rules' },
        'mig.metadata_updated':        { de: 'Metadata aktualisiert:', en: 'Metadata updated:' },
        'mig.filenames_found':         { de: 'Dateinamen gefunden:', en: 'Filenames found:' },
        'mig.rules_applied':           { de: 'Regeln angewendet:', en: 'Rules applied:' },
        'mig.objlinks_checked':        { de: 'Objektlinks geprüft:', en: 'Object links checked:' },
        'mig.orphan_warning':          { de: 'Datensätze haben keine verbleibenden Links (Waisen-Warnung)', en: 'Records have no remaining links (orphan warning)' },
        'mig.total_size':              { de: 'Gesamtgröße:', en: 'Total size:' },
        'mig.largest_file':            { de: 'Größte Datei:', en: 'Largest file:' },
        'mig.refresh_failed':          { de: 'Refresh fehlgeschlagen: {{msg}}', en: 'Refresh failed: {{msg}}' },
        'mig.refresh_conn_error':      { de: 'Verbindungsfehler beim Refresh', en: 'Connection error during refresh' },
        'mig.retry_confirm':           { de: 'Alle fehlgeschlagenen und teilweise migrierten Datensätze erneut ausführen?', en: 'Retry all failed and partially migrated records?' },
        'mig.retry_none':              { de: 'Keine fehlgeschlagenen oder teilweise migrierten Datensätze zum Wiederholen.', en: 'No failed or partially migrated records to retry.' },
        'mig.retrying_n':              { de: 'Wiederhole {{n}}...', en: 'Retrying {{n}}...' },
        'mig.retry_starting':          { de: 'Starte {{n}} fehlgeschlagene/teilweise Dokumente...', en: 'Starting {{n}} failed/partial documents...' },
        'mig.retry_init':              { de: 'Initialisiere Retry...', en: 'Initializing retry...' },
        'mig.retry_done':              { de: 'Wiederholung abgeschlossen!', en: 'Retry completed!' },
        'mig.retry_failed':            { de: 'Wiederholung fehlgeschlagen: {{msg}}', en: 'Retry failed: {{msg}}' },
        'mig.retry_error':             { de: 'Fehler bei der Wiederholung: {{msg}}', en: 'Retry error: {{msg}}' },

        // Runtime details
        'runtime.immediate':           { de: 'Nächster Upload startet sofort nach API-Response', en: 'Next upload starts immediately after API response' },
        'runtime.no_wait':             { de: 'Kein Zeit-basiertes Warten mehr', en: 'No more time-based waiting' },
        'runtime.faster':              { de: 'Schneller als zeit-basiertes Pacing!', en: 'Faster than time-based pacing!' },
        'runtime.no_pending':          { de: 'Keine ausstehenden Dokumente', en: 'No pending documents' },

        // Record detail
        'detail.doc_info':             { de: 'Dokumentinformationen', en: 'Document Information' },
        'detail.source_doc':           { de: 'Quelldokument', en: 'Source Document' },
        'detail.target_doc':           { de: 'Zieldokument', en: 'Target Document' },
        'detail.doc_type':             { de: 'Dokumentart', en: 'Document Type' },
        'detail.description':          { de: 'Beschreibung', en: 'Description' },
        'detail.source_auth_group':    { de: 'Quell-Ber.gruppe', en: 'Source Auth Group' },
        'detail.source_user':           { de: 'Pers. Resp. Source', en: 'Pers. Resp. Source' },
        'detail.pers_resp_source':      { de: 'Pers. Resp. Source', en: 'Pers. Resp. Source' },
        'detail.pers_resp_target':      { de: 'Pers. Resp. Target', en: 'Pers. Resp. Target' },
        'detail.target_auth_group':    { de: 'Ziel-Ber.gruppe', en: 'Target Auth Group' },
        'detail.exec_info':            { de: 'Ausführungsinformationen', en: 'Execution Information' },
        'detail.started':              { de: 'Gestartet', en: 'Started' },
        'detail.completed':            { de: 'Abgeschlossen', en: 'Completed' },
        'detail.file':                 { de: 'Datei', en: 'File' },
        'detail.files':                { de: 'Dateien (Quelle/Ziel)', en: 'Files (Source/Target)' },
        'detail.objlinks':             { de: 'Objektlinks (S/E/T)', en: 'Object Links (S/E/T)' },
        'detail.mime_type':            { de: 'MIME-Typ', en: 'MIME Type' },
        'detail.exec_error':           { de: 'Ausführungsfehler', en: 'Execution Error' },
        'detail.show':                 { de: 'Details anzeigen', en: 'Show Details' },
        'detail.record_not_found':     { de: 'Datensatz nicht in den Ausführungsergebnissen gefunden', en: 'Record not found in execution results' },
        'detail.load_error':           { de: 'Fehler beim Laden: {{msg}}', en: 'Loading error: {{msg}}' },
        'detail.loading':              { de: 'Lade Details...', en: 'Loading details...' },

        // Pagination
        'page.showing':                { de: 'Zeige {{from}} bis {{to}} von {{total}}', en: 'Showing {{from}} to {{to}} of {{total}}' },
        'page.records':                { de: 'Datensätze', en: 'Records' },
        'page.hits':                   { de: 'Treffer', en: 'Hits' },

        // ══════════════════════════════════════════════════════════════
        // SETTINGS (settings.html + settings.js)
        // ══════════════════════════════════════════════════════════════
        'set.title':                   { de: 'Einstellungen', en: 'Settings' },
        'set.subtitle':                { de: 'Konfiguriere die Migration-Parameter', en: 'Configure migration parameters' },
        'set.perf.title':              { de: 'Leistungseinstellungen', en: 'Performance Settings' },
        'set.perf.workers':            { de: 'Max API Workers', en: 'Max API Workers' },
        'set.perf.workers_info':       { de: 'Anzahl paralleler API-Aufrufe (1-50). Mehr Workers = schneller, aber höhere Last.', en: 'Number of parallel API calls (1-50). More workers = faster, but higher load.' },
        'set.perf.pacing':             { de: 'Pacing (Sekunden)', en: 'Pacing (Seconds)' },
        'set.perf.dynamic':            { de: 'Dynamisch', en: 'Dynamic' },
        'set.perf.fixed':              { de: 'Fixiert', en: 'Fixed' },
        'set.perf.dynamic_hint':       { de: '0 = Dynamisches Pacing (empfohlen)', en: '0 = Dynamic Pacing (recommended)' },
        'set.perf.fixed_hint':         { de: '>0 = Fixiertes Pacing', en: '>0 = Fixed Pacing' },
        'set.perf.recommendation':     { de: 'Empfehlung:', en: 'Recommendation:' },
        'set.perf.throughput':         { de: 'Berechneter Durchsatz:', en: 'Calculated Throughput:' },
        'set.perf.docs_per_min':       { de: 'Dokumente pro Minute (theoretisch)', en: 'Documents per minute (theoretical)' },
        'set.perf.save':               { de: 'Einstellungen speichern', en: 'Save Settings' },
        'set.config.title':            { de: 'Aktuelle Konfiguration', en: 'Current Configuration' },
        'set.config.source':           { de: 'Quellsystem', en: 'Source System' },
        'set.config.target':           { de: 'Zielsystem', en: 'Target System' },
        'set.config.workers':          { de: 'Max Workers', en: 'Max Workers' },
        'set.config.pacing':           { de: 'Pacing', en: 'Pacing' },
        'set.notices.title':           { de: 'Hinweise', en: 'Notices' },
        'set.notices.1':               { de: 'Zu viele Workers können zu Rate Limiting Fehlern führen', en: 'Too many workers can lead to rate limiting errors' },
        'set.notices.2':               { de: 'Zu wenig Pacing kann die API überlasten', en: 'Too little pacing can overload the API' },
        'set.notices.3':               { de: 'Änderungen gelten für neue Batch-Ausführungen', en: 'Changes apply to new batch executions' },
        'set.notices.4':               { de: 'Aktuelle Migrationen werden nicht beeinflusst', en: 'Current migrations are not affected' },
        'set.cred.title':              { de: 'SAP Zugangsdaten', en: 'SAP Credentials' },
        'set.cred.refresh':            { de: 'Aktualisieren', en: 'Refresh' },
        'set.cred.info':               { de: 'Zugangsdaten für SAP-Systeme', en: 'Credentials for SAP systems' },
        'set.cred.loading':            { de: 'Lade Zugangsdaten...', en: 'Loading credentials...' },
        'set.cred.no_systems':         { de: 'Keine SAP-Systeme in der Konfiguration vorhanden.', en: 'No SAP systems configured.' },
        'set.sys.title':               { de: 'API-Endpunkte konfigurieren', en: 'Configure API Endpoints' },
        'set.sys.new':                 { de: 'Neues System', en: 'New System' },
        'set.sys.info':                { de: 'API-Endpunkte konfigurieren', en: 'Configure API endpoints' },
        'set.sys.create':              { de: 'Neues System anlegen', en: 'Create New System' },
        'set.sys.id':                  { de: 'System-ID', en: 'System ID' },
        'set.sys.label':               { de: 'Label', en: 'Label' },
        'set.sys.type':                { de: 'Typ', en: 'Type' },
        'set.sys.host':                { de: 'Host', en: 'Host' },
        'set.sys.auth':                { de: 'Auth', en: 'Auth' },
        'set.sys.api_key':             { de: 'API-Key', en: 'API Key' },
        'set.sys.unique_lc':           { de: 'Eindeutig, lowercase', en: 'Unique, lowercase' },
        'set.sys.endpoints':           { de: 'API-Endpunkte', en: 'API Endpoints' },
        'set.sys.add_api':             { de: 'API hinzufügen', en: 'Add API' },
        'set.sys.loading':             { de: 'Lade SAP-Systeme...', en: 'Loading SAP systems...' },
        'set.pacing.title':            { de: 'Dynamisches Pacing - Historische Analyse', en: 'Dynamic Pacing - Historical Analysis' },
        'set.pacing.loading':          { de: 'Lade historische Daten...', en: 'Loading historical data...' },
        'set.pacing.no_data':          { de: 'Keine historischen Ausführungsdaten verfügbar', en: 'No historical execution data available' },
        'set.pacing.bucket':           { de: 'Größen-Bucket', en: 'Size Bucket' },
        'set.pacing.filesize':         { de: 'Dateigröße', en: 'File Size' },
        'set.pacing.count':            { de: 'Anzahl', en: 'Count' },
        'set.pacing.avg':              { de: 'Ø Zeit (s)', en: 'Avg Time (s)' },
        'set.pacing.min':              { de: 'Min (s)', en: 'Min (s)' },
        'set.pacing.max':              { de: 'Max (s)', en: 'Max (s)' },
        'set.pacing.current':          { de: 'Aktuell (s)', en: 'Current (s)' },
        'set.pacing.recommended':      { de: 'Empfohlen (s)', en: 'Recommended (s)' },
        'set.pacing.status':           { de: 'Status', en: 'Status' },
        'set.pacing.hint':             { de: 'Empfehlung: Das empfohlene Pacing', en: 'Recommendation: The recommended pacing' },
        'set.sys.source_yaml':          { de: 'Aus config-env.yml', en: 'From config-env.yml' },
        'set.sys.source_db':            { de: 'Nur in Datenbank', en: 'Only in database' },

        // settings.js
        'set.msg.saved':               { de: 'Einstellungen gespeichert!', en: 'Settings saved!' },
        'set.msg.save_error':          { de: 'Fehler beim Speichern: {{msg}}', en: 'Save error: {{msg}}' },
        'set.msg.stats_error':         { de: 'Fehler beim Laden der Statistiken: {{msg}}', en: 'Error loading statistics: {{msg}}' },
        'set.bucket.tiny':             { de: 'Winzig', en: 'Tiny' },
        'set.bucket.small':            { de: 'Klein', en: 'Small' },
        'set.bucket.medium':           { de: 'Mittel', en: 'Medium' },
        'set.bucket.large':            { de: 'Groß', en: 'Large' },
        'set.bucket.unknown':          { de: 'Unbekannt', en: 'Unknown' },
        'set.pacing_status.none':      { de: 'Keine Daten', en: 'No Data' },
        'set.pacing_status.faster':    { de: 'Schneller möglich', en: 'Can Be Faster' },
        'set.pacing_status.increase':  { de: 'Erhöhen empfohlen', en: 'Increase Recommended' },
        'set.cred.configured':         { de: 'Konfiguriert', en: 'Configured' },
        'set.cred.not_configured':     { de: 'Nicht konfiguriert', en: 'Not Configured' },
        'set.cred.user':               { de: 'Benutzer:', en: 'User:' },
        'set.cred.updated_at':         { de: 'Aktualisiert:', en: 'Updated:' },
        'set.cred.none':               { de: 'Keine Zugangsdaten hinterlegt', en: 'No credentials stored' },
        'set.cred.username':           { de: 'Benutzername', en: 'Username' },
        'set.cred.password':           { de: 'Passwort', en: 'Password' },
        'set.cred.test':               { de: 'Testen', en: 'Test' },
        'set.cred.test_conn':          { de: 'Verbindung testen', en: 'Test Connection' },
        'set.cred.change':             { de: 'Ändern', en: 'Change' },
        'set.cred.setup':              { de: 'Einrichten', en: 'Setup' },
        'set.cred.required':           { de: 'Benutzername ist erforderlich', en: 'Username is required' },
        'set.cred.password_required':   { de: 'Passwort ist erforderlich', en: 'Password is required' },
        'set.cred.password_unchanged':  { de: '●●●●●●●● (unverändert lassen oder neu eingeben)', en: '●●●●●●●● (leave unchanged or enter new)' },
        'set.cred.password_enter':      { de: 'Passwort eingeben', en: 'Enter password' },
        'set.cred.testing':             { de: 'Verbindung wird getestet...', en: 'Testing connection...' },
        'set.cred.delete_confirm':      { de: 'Zugangsdaten für {{system}} wirklich löschen?', en: 'Really delete credentials for {{system}}?' },
        'set.cred.updated_by':          { de: 'von', en: 'by' },
        'set.cred.ph_example':          { de: 'z.B. altnict', en: 'e.g. altnict' },
        'set.cred.csrf_received':       { de: '(CSRF-Token erhalten)', en: '(CSRF token received)' },
        'set.msg.dynamic_avg':          { de: '(Durchschnitt bei dynamischem Pacing)', en: '(Average with dynamic pacing)' },
        'set.msg.workers_range':        { de: 'Max Workers muss zwischen 1 und 50 liegen', en: 'Max Workers must be between 1 and 50' },
        'set.msg.pacing_range':         { de: 'Pacing muss zwischen 0 und 60 Sekunden liegen', en: 'Pacing must be between 0 and 60 seconds' },
        'set.msg.dynamic_info':         { de: '(5-45s basierend auf Dateigröße)', en: '(5-45s based on file size)' },
        'set.msg.seconds':              { de: 'Sekunden', en: 'seconds' },
        'set.sys.no_systems':           { de: 'Keine SAP-Systeme konfiguriert.', en: 'No SAP systems configured.' },
        'set.sys.remove_api':           { de: 'API entfernen', en: 'Remove API' },
        'set.sys.no_apis':              { de: 'Keine APIs konfiguriert', en: 'No APIs configured' },
        'set.sys.edit_system':          { de: 'System bearbeiten: {{system}}', en: 'Edit system: {{system}}' },
        'set.sys.api_name_ph':          { de: 'Name (z.B. document)', en: 'Name (e.g. document)' },
        'set.sys.id_label_required':    { de: 'System-ID und Label sind erforderlich', en: 'System ID and label are required' },
        'set.sys.delete_confirm':       { de: 'System {{system}} wirklich deaktivieren? (YAML-Defaults bleiben erhalten)', en: 'Really deactivate system {{system}}? (YAML defaults will be kept)' },
        'set.sys.api_required':         { de: 'API Name und Base URL sind erforderlich', en: 'API name and base URL are required' },
        'set.sys.api_delete_confirm':   { de: 'API "{{api}}" von {{system}} entfernen?', en: 'Remove API "{{api}}" from {{system}}?' },
        'set.sys.deactivate':           { de: 'Deaktivieren', en: 'Deactivate' },
        'set.sys.edit':                 { de: 'Bearbeiten', en: 'Edit' },
        'set.sys.source_col':           { de: 'Quelle', en: 'Source' },
        'set.pacing_status.no_size':    { de: 'Keine Größe', en: 'No size' },
        'set.sys.ph_id':               { de: 'z.B. zhl', en: 'e.g. zhl' },
        'set.sys.ph_name':             { de: 'z.B. ZHL Testsystem Ludwigshafen', en: 'e.g. ZHL Test System Ludwigshafen' },
        'set.sys.ph_host':             { de: 'z.B. qa-sap.api.basf.com:443', en: 'e.g. qa-sap.api.basf.com:443' },

        // Badge editor & sorting
        'set.badge.edit_title':         { de: 'Badges bearbeiten', en: 'Edit Badges' },
        'set.badge.click_edit':         { de: 'Klicken zum Bearbeiten', en: 'Click to edit' },
        'set.badge.add':                { de: 'Badge hinzufügen', en: 'Add Badge' },
        'set.badge.text_ph':            { de: 'Badge-Text', en: 'Badge text' },
        'set.sort.name':                { de: 'Name', en: 'Name' },
        'set.sort.type':                { de: 'Typ', en: 'Type' },
        'set.sort.status':              { de: 'Status', en: 'Status' },
        'set.sort.source':              { de: 'Quelle', en: 'Source' },
        'set.sort.env':                 { de: 'Umgebung', en: 'Environment' },
        'set.sort.badges':              { de: 'Badges', en: 'Badges' },
        'set.sort.label':               { de: 'Sortierung:', en: 'Sort:' },
        'set.sys.env':                  { de: 'Umgebung', en: 'Environment' },
        'set.env.all':                  { de: 'Alle', en: 'All' },
        'set.env.unassigned':           { de: 'Ohne', en: 'Unassigned' },
        'set.health.title':             { de: 'System-Status', en: 'System Status' },
        'set.health.check':             { de: 'Prüfen', en: 'Check' },
        'set.health.checking':          { de: 'Prüfe...', en: 'Checking...' },
        'set.health.system':            { de: 'System', en: 'System' },
        'set.health.ok':                { de: 'Erreichbar', en: 'Reachable' },
        'set.health.error':             { de: 'Nicht erreichbar', en: 'Unreachable' },
        'set.health.warn':              { de: 'Teilweise erreichbar', en: 'Partially reachable' },
        'set.health.skip':              { de: 'Nicht geprüft', en: 'Not checked' },
        'set.sys.id_title':            { de: 'Nur Kleinbuchstaben, Zahlen, Unterstrich', en: 'Only lowercase letters, numbers, underscore' },
        'set.pacing_hint':             { de: '<strong>0 = Dynamisches Pacing</strong> (empfohlen): 5s für ≤1MB, 10s für 1-10MB, 20s für 10-50MB, 45s für >50MB<br><strong>>0 = Fixiertes Pacing</strong>: Gleiche Zeit für alle Dokumente', en: '<strong>0 = Dynamic Pacing</strong> (recommended): 5s for ≤1MB, 10s for 1-10MB, 20s for 10-50MB, 45s for >50MB<br><strong>>0 = Fixed Pacing</strong>: Same time for all documents' },
        'set.pacing_recommendation':   { de: '<i class="fas fa-info-circle"></i> <strong>Empfehlung:</strong><br><ul class="mb-0"><li>Formel: <code>Pacing / Workers ≈ 1.5</code> für optimalen Durchsatz</li><li>Beispiel: 2 Workers, 3s Pacing → 1.5s effektive Zeit pro Request</li><li>Beispiel: 10 Workers, 15s Pacing → 1.5s effektive Zeit pro Request</li></ul>', en: '<i class="fas fa-info-circle"></i> <strong>Recommendation:</strong><br><ul class="mb-0"><li>Formula: <code>Pacing / Workers ≈ 1.5</code> for optimal throughput</li><li>Example: 2 Workers, 3s Pacing → 1.5s effective time per request</li><li>Example: 10 Workers, 15s Pacing → 1.5s effective time per request</li></ul>' },
        'set.pace.based_on':           { de: '<strong>Basierend auf <span id="totalRecords">0</span> ausgeführten Dokumenten:</strong>', en: '<strong>Based on <span id="totalRecords">0</span> executed documents:</strong>' },
        'set.pace.recommendation':     { de: '<i class="fas fa-lightbulb"></i> <strong>Empfehlung:</strong> Das empfohlene Pacing ist die maximale Ausführungszeit + 20% Buffer. Wenn das empfohlene Pacing niedriger ist als das aktuelle, läuft die Migration schneller.', en: '<i class="fas fa-lightbulb"></i> <strong>Recommendation:</strong> The recommended pacing is the max execution time + 20% buffer. If the recommended pacing is lower than the current, the migration runs faster.' },

        // ══════════════════════════════════════════════════════════════
        // TRANSLATIONS / RULES (translations.html + translations.js)
        // ══════════════════════════════════════════════════════════════
        'rules.title':                 { de: 'Migrationsregeln', en: 'Migration Rules' },
        'rules.subtitle':              { de: 'Transformationen und Überschreibungen mit optionalen Bedingungen definieren', en: 'Define transformations and overwrites with optional conditions' },
        'rules.add':                   { de: 'Neue Regel hinzufügen', en: 'Add New Rule' },
        'rules.th.order':              { de: 'Reihenfolge', en: 'Order' },
        'rules.th.type':               { de: 'Typ', en: 'Type' },
        'rules.th.source_col':         { de: 'Quellspalte', en: 'Source Column' },
        'rules.th.target_col':         { de: 'Zielspalte', en: 'Target Column' },
        'rules.th.source_val':         { de: 'Quellwert', en: 'Source Value' },
        'rules.th.target_val':         { de: 'Zielwert', en: 'Target Value' },
        'rules.th.condition':          { de: 'Bedingung', en: 'Condition' },
        'rules.th.notes':              { de: 'Notizen', en: 'Notes' },
        'rules.th.created_by':         { de: 'Erstellt von', en: 'Created By' },
        'rules.th.created_at':         { de: 'Erstellt am', en: 'Created At' },
        'rules.th.actions':            { de: 'Aktionen', en: 'Actions' },
        'rules.modal.add':             { de: 'Migrationsregel hinzufügen', en: 'Add Migration Rule' },
        'rules.modal.edit':            { de: 'Migrationsregel bearbeiten', en: 'Edit Migration Rule' },
        'rules.rule_type':             { de: 'Regeltyp *', en: 'Rule Type *' },
        'rules.select':                { de: '-- Auswählen --', en: '-- Select --' },
        'rules.opt_condition':         { de: 'Optionale Bedingung', en: 'Optional Condition' },
        'rules.add_condition':         { de: 'Bedingung hinzufügen', en: 'Add Condition' },
        'rules.condition_info':        { de: 'Diese Regel nur anwenden, wenn die Bedingung erfüllt ist.', en: 'Only apply this rule when the condition is met.' },
        'rules.cond_column':           { de: 'Bedingungsspalte', en: 'Condition Column' },
        'rules.cond_operator':         { de: 'Bedingungsoperator', en: 'Condition Operator' },
        'rules.cond_value':            { de: 'Bedingungswert', en: 'Condition Value' },
        'rules.op_contains':           { de: 'enthält', en: 'contains' },
        'rules.op_not_contains':       { de: 'enthält nicht', en: 'does not contain' },
        'rules.op_equals':             { de: 'gleich', en: 'equals' },
        'rules.op_not_equals':         { de: 'ungleich', en: 'not equal' },
        'rules.notes_ph':              { de: 'Optionale Beschreibung', en: 'Optional description' },
        'rules.remove_condition':      { de: 'Bedingung entfernen', en: 'Remove Condition' },
        'rules.load_error':            { de: 'Migrationsregeln konnten nicht geladen werden', en: 'Could not load migration rules' },
        'rules.empty':                 { de: 'Noch keine Migrationsregeln definiert', en: 'No migration rules defined yet' },
        'rules.move_up':               { de: 'Nach oben', en: 'Move Up' },
        'rules.move_down':             { de: 'Nach unten', en: 'Move Down' },
        'rules.edit':                  { de: 'Bearbeiten', en: 'Edit' },
        'rules.clone':                 { de: 'Duplizieren', en: 'Duplicate' },
        'rules.val.translation_required': { de: 'source_column, target_column und target_value sind erforderlich', en: 'source_column, target_column and target_value are required' },
        'rules.val.overwrite_required': { de: 'target_column und target_value sind für Überschreibungen erforderlich', en: 'target_column and target_value are required for overwrites' },
        'rules.val.target_required':   { de: 'Zielwert ist erforderlich', en: 'Target value is required' },
        'rules.add_success':           { de: 'Regel erfolgreich hinzugefügt', en: 'Rule added successfully' },
        'rules.add_error':             { de: 'Regel konnte nicht hinzugefügt werden', en: 'Could not add rule' },
        'rules.update_success':        { de: 'Regel erfolgreich aktualisiert', en: 'Rule updated successfully' },
        'rules.update_error':          { de: 'Regel konnte nicht aktualisiert werden', en: 'Could not update rule' },
        'rules.delete_confirm':        { de: 'Diese Migrationsregel wirklich löschen?', en: 'Really delete this migration rule?' },
        'rules.delete_success':        { de: 'Regel erfolgreich gelöscht', en: 'Rule deleted successfully' },
        'rules.delete_error':          { de: 'Regel konnte nicht gelöscht werden', en: 'Could not delete rule' },
        'rules.move_error':            { de: 'Regel konnte nicht verschoben werden', en: 'Could not move rule' },
        'rules.opt.docstatus_source':  { de: 'Dokumentenstatus (source_document_status)', en: 'Document Status (source_document_status)' },
        'rules.opt.docstatus_target':  { de: 'Dokumentenstatus (target_document_status)', en: 'Document Status (target_document_status)' },
        'rules.notes_label':           { de: 'Notizen', en: 'Notes' },
        'rules.th.active':             { de: 'Aktiv', en: 'Active' },
        'rules.activate':              { de: 'Aktivieren', en: 'Activate' },
        'rules.deactivate':            { de: 'Deaktivieren', en: 'Deactivate' },
        'rules.toggle_error':          { de: 'Regelstatus konnte nicht geändert werden', en: 'Could not toggle rule status' },

        // ══════════════════════════════════════════════════════════════
        // OBJECT MAPPING (object_mapping.html)
        // ══════════════════════════════════════════════════════════════
        'map.title':                   { de: 'Objekt-Zuordnung', en: 'Object Mapping' },
        'map.wave':                    { de: 'Wave:', en: 'Wave:' },
        'map.records':                 { de: 'Datensätze:', en: 'Records:' },
        'map.back':                    { de: '← Zurück zum Batch', en: '← Back to Batch' },
        'map.upload_excel':            { de: '2. 📤 Zuordnung importieren', en: '2. 📤 Import Mapping' },
        'map.export':                  { de: '1. 💾 Zuordnung exportieren', en: '1. 💾 Export Mapping' },
        'map.apply':                   { de: '3. ✨ Zuordnung → Staging', en: '3. ✨ Mapping → Staging' },
        'map.link_all':                { de: '4. 🔗 Zuordnung verlinken', en: '4. 🔗 Link Mapping' },
        'map.link_selected':           { de: '🔗 Ausgewählte verlinken', en: '🔗 Link Selected' },
        'map.cancel_linking':          { de: '⛔ Verlinkung abbrechen', en: '⛔ Cancel Linking' },
        'map.linking_progress':        { de: 'Verlinkung wird ausgeführt...', en: 'Linking in progress...' },
        'map.stat.total':              { de: 'Zuordnungen gesamt', en: 'Total Mappings' },
        'map.stat.unique_source':      { de: 'Eindeutige Quellen', en: 'Unique Sources' },
        'map.stat.unique_target':      { de: 'Eindeutige Ziele', en: 'Unique Targets' },
        'map.stat.unmapped':           { de: 'Nicht zugeordnet', en: 'Unmapped' },
        'map.tab.unmapped':            { de: 'Nicht zugeordnet', en: 'Unmapped' },
        'map.tab.mappings':            { de: 'Zuordnungen', en: 'Mappings' },
        'map.unmapped.title':          { de: 'Nicht zugeordnete Objekte in diesem Batch', en: 'Unmapped objects in this batch' },
        'map.unmapped.info':           { de: 'Dies sind DOKOB/OBJKY-Kombinationen in diesem Batch, für die keine Zuordnung definiert ist.', en: 'These are DOKOB/OBJKY combinations in this batch without a defined mapping.' },
        'map.unmapped.refresh':        { de: '🔄 Aktualisieren', en: '🔄 Refresh' },
        'map.unmapped.count':          { de: 'Anzahl', en: 'Count' },
        'map.unmapped.action':         { de: 'Aktion', en: 'Action' },
        'map.mappings.title':          { de: 'Objekt-Zuordnungen', en: 'Object Mappings' },
        'map.mappings.count':          { de: '{{n}} Zuordnungen', en: '{{n}} Mappings' },
        'map.mappings.search':         { de: 'Zuordnungen suchen...', en: 'Search mappings...' },
        'map.mappings.source':         { de: 'Quell-DOKOB', en: 'Source DOKOB' },
        'map.mappings.source_key':     { de: 'Quell-OBJKY', en: 'Source OBJKY' },
        'map.mappings.target':         { de: 'Ziel-DOKOB', en: 'Target DOKOB' },
        'map.mappings.target_key':     { de: 'Ziel-OBJKY', en: 'Target OBJKY' },
        'map.mappings.created':        { de: 'Erstellt', en: 'Created' },
        'map.mappings.loading':        { de: 'Lade Zuordnungen...', en: 'Loading mappings...' },
        'map.upload.title':            { de: 'Objekt-Zuordnung Excel hochladen', en: 'Upload Object Mapping Excel' },
        'map.upload.info':             { de: 'Excel-Datei mit Spalten hochladen: source_dokob, source_objky, target_dokob, target_objky', en: 'Upload Excel with columns: source_dokob, source_objky, target_dokob, target_objky' },
        'map.upload.drop':             { de: 'Klicken oder Excel-Datei hierhin ziehen', en: 'Click or drag Excel file here' },
        'map.upload.formats':          { de: 'Unterstützt .xlsx und .xls Dateien', en: 'Supports .xlsx and .xls files' },
        'map.upload.btn':              { de: 'Hochladen', en: 'Upload' },
        'map.edit.title':              { de: 'Zuordnung bearbeiten', en: 'Edit Mapping' },
        'map.edit.save':               { de: 'Änderungen speichern', en: 'Save Changes' },

        // object_mapping.js dynamic strings
        'map.no_description':          { de: 'Keine Beschreibung', en: 'No description' },
        'map.load_error':              { de: 'Fehler beim Laden der Zuordnungen', en: 'Error loading mappings' },
        'map.empty':                   { de: 'Keine Zuordnungen für diesen Batch definiert', en: 'No mappings defined for this batch' },
        'map.empty_hint':              { de: 'Excel-Datei hochladen oder Zuordnungen manuell hinzufügen', en: 'Upload Excel file or add mappings manually' },
        'map.unmapped_load_error':     { de: 'Fehler beim Laden der nicht zugeordneten Objekte', en: 'Error loading unmapped objects' },
        'map.all_count':               { de: 'Alle ({{n}})', en: 'All ({{n}})' },
        'map.all_mapped':              { de: 'Alle Objekte in diesem Batch sind zugeordnet!', en: 'All objects in this batch are mapped!' },
        'map.add_mapping':             { de: 'Zuordnung hinzufügen', en: 'Add mapping' },
        'map.add_via_upload':          { de: 'Bitte verwenden Sie "Zuordnungen exportieren" und "Excel hochladen" um Zuordnungen hinzuzufügen.', en: 'Please use "Export Mappings" and "Upload Excel" to add mappings.' },
        'map.error_unknown':           { de: 'Unbekannter Fehler', en: 'Unknown error' },
        'map.update_error':            { de: 'Fehler beim Aktualisieren der Zuordnung: {{msg}}', en: 'Error updating mapping: {{msg}}' },
        'map.delete_confirm':          { de: 'Möchten Sie diese Zuordnung wirklich löschen?', en: 'Do you really want to delete this mapping?' },
        'map.delete_error':            { de: 'Fehler beim Löschen der Zuordnung: {{msg}}', en: 'Error deleting mapping: {{msg}}' },
        'map.file_selected':           { de: 'Ausgewählt: {{name}}', en: 'Selected: {{name}}' },
        'map.uploading':               { de: 'Wird hochgeladen...', en: 'Uploading...' },
        'map.upload_success':          { de: '✅ {{n}} Zuordnungen hochgeladen!', en: '✅ {{n}} mappings uploaded!' },
        'map.upload_error_msg':        { de: '❌ Fehler: {{msg}}', en: '❌ Error: {{msg}}' },
        'map.upload_failed':           { de: '❌ Hochladen fehlgeschlagen: {{msg}}', en: '❌ Upload failed: {{msg}}' },
        'map.apply_confirm':           { de: 'Alle Zuordnungen auf Staging-Datensätze in diesem Batch anwenden?\n\nHINWEIS: Objekt-Zuordnungen werden jetzt ON-THE-FLY während der Migration angewendet.\nDieser Button aktualisiert nur Datensätze, die bereits source_dokob/source_objky Werte haben\n(aus einem vorherigen, teilweisen Migrationslauf).', en: 'Apply all mappings to staging records in this batch?\n\nNOTE: Object mappings are now applied ON-THE-FLY during migration.\nThis button only updates records that already have source_dokob/source_objky values\n(from a previous, partial migration run).' },
        'map.apply_no_records':        { de: 'ℹ️ Keine Datensätze aktualisiert.\n\nDies ist für neue Batches erwartet.\nObjekt-Zuordnungen werden automatisch während der Migration angewendet.', en: 'ℹ️ No records updated.\n\nThis is expected for new batches.\nObject mappings are applied automatically during migration.' },
        'map.apply_success':           { de: '✅ Zuordnungen angewendet!\n\nAktualisiert: {{n}} Datensätze', en: '✅ Mappings applied!\n\nUpdated: {{n}} records' },
        'map.apply_error':             { de: 'Fehler beim Anwenden der Zuordnungen: {{msg}}', en: 'Error applying mappings: {{msg}}' },
        'map.link_progress':           { de: 'Verlinkung: {{completed}}/{{total}} ({{linked}} verlinkt, {{exists}} existiert, {{failed}} Fehler, {{skipped}} übersprungen)', en: 'Linking: {{completed}}/{{total}} ({{linked}} linked, {{exists}} exists, {{failed}} errors, {{skipped}} skipped)' },
        'map.link_phase':              { de: 'Phase: {{phase}}', en: 'Phase: {{phase}}' },
        'map.link_complete_msg':       { de: 'Verlinkung abgeschlossen!\n\nGesamt: {{total}}\nVerlinkt: {{linked}}\nBereits vorhanden: {{existed}}\nFehlgeschlagen: {{failed}}\nDauer: {{duration}}', en: 'Linking completed!\n\nTotal: {{total}}\nLinked: {{linked}}\nAlready existed: {{existed}}\nFailed: {{failed}}\nDuration: {{duration}}' },
        'map.link_complete_note':      { de: '\n\nHinweis: {{reason}}', en: '\n\nNote: {{reason}}' },
        'map.link_failed_msg':         { de: 'Verlinkung fehlgeschlagen: {{msg}}', en: 'Linking failed: {{msg}}' },
        'map.linking_status':          { de: '⏳ Wird verlinkt...', en: '⏳ Linking...' },
        'map.link_confirm':            { de: 'Objektlinks für alle zugeordneten Datensätze erstellen?\n\nNur Links mit vorhandener Zuordnung werden verarbeitet.\nNicht zugeordnete Links werden übersprungen.', en: 'Create object links for all mapped records?\n\nOnly links with existing mappings will be processed.\nUnmapped links will be skipped.' },
        'map.link_not_logged_in':      { de: '⚠️ Nicht eingeloggt!\n\nBitte zuerst bei SAP anmelden.', en: '⚠️ Not logged in!\n\nPlease log in to SAP first.' },
        'map.link_start_error':        { de: 'Verlinkung konnte nicht gestartet werden: {{msg}}', en: 'Could not start linking: {{msg}}' },
        'map.link_conn_error':         { de: 'Fehler beim Starten der Verlinkung: {{msg}}', en: 'Error starting linking: {{msg}}' },
        'map.link_use_all':            { de: 'Bitte verwenden Sie "Zuordnungen verlinken" auf dieser Seite,\noder wählen Sie einzelne Datensätze in der Batch-Vorschau aus.', en: 'Please use "Link Mapped" on this page,\nor select individual records in the batch preview.' },
        'map.cancel_confirm':          { de: 'Verlinkung wirklich abbrechen?\n\nBereits verlinkte Datensätze bleiben erhalten.', en: 'Really cancel linking?\n\nAlready linked records will be kept.' },
        'map.cancel_requested':        { de: '⏳ Abbruch angefordert...', en: '⏳ Cancellation requested...' },
        'map.cancel_failed_msg':       { de: 'Abbruch fehlgeschlagen: {{msg}}', en: 'Cancellation failed: {{msg}}' },
        'map.cancel_error':            { de: 'Fehler beim Abbrechen: {{msg}}', en: 'Error cancelling: {{msg}}' },
        'map.edit.src_dokob':          { de: 'Quell-DOKOB', en: 'Source DOKOB' },
        'map.edit.src_objky':          { de: 'Quell-OBJKY', en: 'Source OBJKY' },
        'map.edit.tgt_dokob':          { de: 'Ziel-DOKOB', en: 'Target DOKOB' },
        'map.edit.tgt_objky':          { de: 'Ziel-OBJKY', en: 'Target OBJKY' },
        'map.th.actions':              { de: 'Aktionen', en: 'Actions' },
        'map.link_all_title':          { de: 'Nur zugeordnete Objektlinks verlinken', en: 'Link only mapped object links' },
        'map.link_selected_title':     { de: 'Objektlinks für ausgewählte Datensätze erstellen', en: 'Create object links for selected records' },

        // Link errors tab
        'map.tab.link_errors':         { de: 'Link-Fehler', en: 'Link Errors' },
        'map.link_errors.title':       { de: 'Link-Fehler', en: 'Link Errors' },
        'map.link_errors.info':        { de: 'Datensätze mit fehlgeschlagener Verlinkung. "Zurücksetzen & neu verlinken" setzt die Fehler zurück und startet die Verlinkung sofort erneut.', en: 'Records with failed linking. "Reset & Relink" resets errors and immediately starts linking again.' },
        'map.link_errors.none':        { de: 'Keine Link-Fehler — alles verlinkt!', en: 'No link errors — all linked!' },
        'map.link_errors.load_error':  { de: 'Fehler beim Laden der Link-Fehler', en: 'Error loading link errors' },
        'map.link_errors.showing':     { de: '{{n}} fehlerhafte Datensätze', en: '{{n}} failed records' },
        'map.link_errors.source_doc':  { de: 'Quell-Dok', en: 'Source Doc' },
        'map.link_errors.target_doc':  { de: 'Ziel-Dok', en: 'Target Doc' },
        'map.link_errors.target_mapping': { de: 'Ziel-Mapping', en: 'Target Mapping' },
        'map.link_errors.error':       { de: 'Fehler', en: 'Error' },
        'map.link_errors.error_cat':   { de: 'Kategorie', en: 'Category' },
        'map.link_errors.search':      { de: 'Fehler suchen...', en: 'Search errors...' },
        'map.link_errors.select_all':  { de: 'Alle auswählen', en: 'Select all' },
        'map.link_errors.reset_all':   { de: 'Alle zurücksetzen', en: 'Reset All' },
        'map.link_errors.reset_selected': { de: 'Ausgewählte zurücksetzen', en: 'Reset Selected' },
        'map.link_errors.reset_n':     { de: '{{n}} zurücksetzen', en: 'Reset {{n}}' },
        'map.link_errors.reset_all_confirm': { de: 'Alle {{n}} fehlerhaften Link-Datensätze auf "Ausstehend" zurücksetzen?', en: 'Reset all {{n}} failed link records to "Pending"?' },
        'map.link_errors.reset_selected_confirm': { de: '{{n}} ausgewählte Datensätze auf "Ausstehend" zurücksetzen?', en: 'Reset {{n}} selected records to "Pending"?' },
        'map.link_errors.reset_done':  { de: '{{n}} Datensätze zurückgesetzt.', en: '{{n}} records reset.' },
        'map.link_errors.reset_error': { de: 'Fehler beim Zurücksetzen: {{msg}}', en: 'Reset error: {{msg}}' },
        'map.link_errors.validation':  { de: 'Validierung öffnen', en: 'Open Validation' },
        'map.link_errors.reset_and_relink':  { de: 'Zurücksetzen & neu verlinken', en: 'Reset & Relink' },
        'map.link_errors.reset_sel_relink':  { de: 'Ausgewählte zurücksetzen & verlinken', en: 'Reset Selected & Relink' },
        'map.link_errors.reset_n_relink':    { de: '{{n}} zurücksetzen & verlinken', en: 'Reset {{n}} & Relink' },
        'map.link_errors.reset_relink_confirm':     { de: 'Alle {{n}} fehlerhaften Datensätze zurücksetzen und Verlinkung sofort neu starten?', en: 'Reset all {{n}} failed records and immediately restart linking?' },
        'map.link_errors.reset_relink_sel_confirm': { de: '{{n}} ausgewählte Datensätze zurücksetzen und Verlinkung sofort neu starten?', en: 'Reset {{n}} selected records and immediately restart linking?' },
        'map.link_errors.show_detail': { de: 'Details anzeigen', en: 'Show details' },
        'map.link_errors.detail_title':  { de: 'Fehler-Details', en: 'Error Details' },
        'map.link_errors.detail_source': { de: 'Quell-Dokument', en: 'Source Document' },
        'map.link_errors.detail_target': { de: 'Ziel-Dokument', en: 'Target Document' },
        'map.link_errors.detail_docnr':  { de: 'Dokumentnummer', en: 'Document Number' },
        'map.link_errors.detail_type':   { de: 'Dokumentart', en: 'Document Type' },
        'map.link_errors.detail_version':{ de: 'Version', en: 'Version' },
        'map.link_errors.detail_part':   { de: 'Teil', en: 'Part' },
        'map.link_errors.detail_error_msg': { de: 'Fehlermeldung', en: 'Error Message' },
        'map.link_errors.reset_this':    { de: 'Diesen zurücksetzen', en: 'Reset this record' },
        'map.link_errors.cat_auth':      { de: 'Authentifizierung', en: 'Authentication' },
        'map.link_errors.cat_duplicate': { de: 'Bereits vorhanden', en: 'Already exists' },
        'map.link_errors.cat_connection':{ de: 'Verbindungsfehler', en: 'Connection Error' },
        'map.link_errors.cat_no_mapping':{ de: 'Kein Mapping', en: 'No Mapping' },
        'map.link_errors.cat_other':     { de: 'Sonstige', en: 'Other' },
        'map.link_errors.cat_unknown':   { de: 'Unbekannt', en: 'Unknown' },
        'close':                         { de: 'Schließen', en: 'Close' },

        // ══════════════════════════════════════════════════════════════
        // MIGRATION DETAILS (migration_details.html)
        // ══════════════════════════════════════════════════════════════
        'det.title':                   { de: 'Migrationsdetails', en: 'Migration Details' },
        'det.subtitle':                { de: 'Dokument- und Datei-Ergebnisse der Migration', en: 'Document and file results of the migration' },
        'det.loading':                 { de: 'Lade Details...', en: 'Loading details...' },
        'det.select_batch':            { de: 'Batch auswählen...', en: 'Select batch...' },
        'det.summary.title':           { de: 'Batch-Übersicht', en: 'Batch Overview' },
        'det.summary.docs':            { de: 'Dokumente', en: 'Documents' },
        'det.summary.files':           { de: 'Dateien', en: 'Files' },
        'det.summary.success':         { de: '✓ Erfolgreich', en: '✓ Successful' },
        'det.summary.partial':         { de: '⚠ Teilweise', en: '⚠ Partial' },
        'det.summary.failed':          { de: '✗ Fehlgeschlagen', en: '✗ Failed' },
        'det.summary.total_size':      { de: 'Gesamtgröße', en: 'Total Size' },
        'det.summary.avg_time':        { de: 'Ø Zeit', en: 'Avg Time' },
        'det.export.title':            { de: 'Export', en: 'Export' },
        'det.export.docs_csv':         { de: 'Dokumente (CSV)', en: 'Documents (CSV)' },
        'det.export.files_csv':        { de: 'Dateien (CSV)', en: 'Files (CSV)' },
        'det.export.raw_json':         { de: 'Raw JSON', en: 'Raw JSON' },
        'det.errors.title':            { de: 'Fehlerübersicht', en: 'Error Overview' },
        'det.errors.category':         { de: 'Kategorie', en: 'Category' },
        'det.errors.description':      { de: 'Beschreibung', en: 'Description' },
        'det.errors.count':            { de: 'Anzahl', en: 'Count' },
        'det.errors.action':           { de: 'Aktion', en: 'Action' },
        'det.errors.retry_all':        { de: 'Alle Fehler erneut versuchen', en: 'Retry All Errors' },
        'det.filter.quick':            { de: 'Schnellfilter:', en: 'Quick Filters:' },
        'det.filter.all':              { de: 'Alle', en: 'All' },
        'det.filter.success':          { de: 'Erfolgreich', en: 'Successful' },
        'det.filter.partial':          { de: 'Teilweise', en: 'Partial' },
        'det.filter.failed':           { de: 'Fehlgeschlagen', en: 'Failed' },
        'det.filter.pending':          { de: 'Ausstehend', en: 'Pending' },
        'det.filter.size_error':       { de: 'Größenfehler', en: 'Size Error' },
        'det.filter.expand_all':       { de: 'Alle aufklappen', en: 'Expand All' },
        'det.filter.collapse_all':     { de: 'Alle zuklappen', en: 'Collapse All' },
        'det.filter.status':           { de: 'Status', en: 'Status' },
        'det.filter.error_cat':        { de: 'Fehlerkategorie', en: 'Error Category' },
        'det.filter.doknr':            { de: 'Dokumentnummer', en: 'Document Number' },
        'det.filter.filename':         { de: 'Dateiname', en: 'Filename' },
        'det.filter.all_status':       { de: 'Alle Status', en: 'All Status' },
        'det.filter.all_cats':         { de: 'Alle Kategorien', en: 'All Categories' },
        'det.page.showing':            { de: 'Zeige {{from}} von {{total}} Dokumenten', en: 'Showing {{from}} of {{total}} documents' },
        'det.empty.no_records':        { de: 'Keine Datensätze gefunden', en: 'No records found' },
        'det.empty.no_match':          { de: 'Keine passenden Dokumente für die aktuellen Filter gefunden.', en: 'No matching documents found for current filters.' },
        'det.empty.select':            { de: 'Batch auswählen', en: 'Select Batch' },
        'det.empty.select_info':       { de: 'Wähle einen Migration-Batch aus dem Dropdown oben, um Details anzuzeigen.', en: 'Select a migration batch from the dropdown above to view details.' },

        // migration_details.js — ERROR_DETAILS descriptions
        'det.errdesc.API_KEY_INVALID':    { de: 'API-Key ungültig', en: 'Invalid API Key' },
        'det.errdesc.TOKEN_EXPIRED':      { de: 'OAuth Token abgelaufen', en: 'OAuth Token Expired' },
        'det.errdesc.TOKEN_INVALID':      { de: 'OAuth Token ungültig', en: 'Invalid OAuth Token' },
        'det.errdesc.CSRF_FAILED':        { de: 'CSRF Token Fehler', en: 'CSRF Token Error' },
        'det.errdesc.SOURCE_NOT_FOUND':   { de: 'Dokument nicht gefunden', en: 'Document Not Found' },
        'det.errdesc.SOURCE_EMPTY':       { de: 'Container ohne Dateien', en: 'Container Without Files' },
        'det.errdesc.SOURCE_READ_ERROR':  { de: 'Lesefehler im Quellsystem', en: 'Source System Read Error' },
        'det.errdesc.LOCAL_LINK':         { de: 'Lokaler Pfad-Verweis', en: 'Local Path Reference' },
        'det.errdesc.TARGET_CREATE_FAILED': { de: 'Anlage fehlgeschlagen', en: 'Creation Failed' },
        'det.errdesc.TARGET_EXISTS':      { de: 'Dokument existiert bereits', en: 'Document Already Exists' },
        'det.errdesc.TARGET_LOCKED':      { de: 'Dokument gesperrt', en: 'Document Locked' },
        'det.errdesc.UPLOAD_SIZE_EXCEEDED': { de: 'Datei zu groß', en: 'File Too Large' },
        'det.errdesc.UPLOAD_TIMEOUT':     { de: 'Upload Timeout', en: 'Upload Timeout' },
        'det.errdesc.GATEWAY_TIMEOUT':    { de: 'API Gateway Timeout (504)', en: 'API Gateway Timeout (504)' },
        'det.errdesc.RATE_LIMITED':       { de: 'API Rate Limit erreicht', en: 'API Rate Limit Reached' },
        'det.errdesc.SERVER_ERROR':       { de: 'SAP Serverfehler (5xx)', en: 'SAP Server Error (5xx)' },
        'det.errdesc.BAD_REQUEST':        { de: 'Ungültige Anfrage (400)', en: 'Bad Request (400)' },
        'det.errdesc.UNKNOWN':            { de: 'Unbekannter Fehler', en: 'Unknown Error' },

        // migration_details.js — ERROR_DETAILS actions
        'det.erract.API_KEY_INVALID':     { de: 'API im APIM freischalten', en: 'Activate API in APIM' },
        'det.erract.TOKEN_EXPIRED':       { de: 'Neu einloggen', en: 'Log in again' },
        'det.erract.TOKEN_INVALID':       { de: 'Neu einloggen', en: 'Log in again' },
        'det.erract.CSRF_FAILED':         { de: 'Session erneuern', en: 'Renew session' },
        'det.erract.SOURCE_NOT_FOUND':    { de: 'Quelldaten prüfen', en: 'Check source data' },
        'det.erract.SOURCE_EMPTY':        { de: 'Erwartet - leer', en: 'Expected - empty' },
        'det.erract.SOURCE_READ_ERROR':   { de: 'R/3 API prüfen', en: 'Check R/3 API' },
        'det.erract.LOCAL_LINK':          { de: '.url Shortcut erstellt', en: '.url shortcut created' },
        'det.erract.TARGET_CREATE_FAILED': { de: 'SAP Log prüfen', en: 'Check SAP log' },
        'det.erract.TARGET_EXISTS':       { de: 'Zieldaten prüfen', en: 'Check target data' },
        'det.erract.TARGET_LOCKED':       { de: 'Sperre aufheben', en: 'Release lock' },
        'det.erract.UPLOAD_SIZE_EXCEEDED': { de: 'Datei aufteilen', en: 'Split file' },
        'det.erract.UPLOAD_TIMEOUT':      { de: 'Später erneut versuchen', en: 'Retry later' },
        'det.erract.GATEWAY_TIMEOUT':     { de: 'Später erneut versuchen', en: 'Retry later' },
        'det.erract.RATE_LIMITED':        { de: 'Warten und erneut versuchen', en: 'Wait and retry' },
        'det.erract.SERVER_ERROR':        { de: 'SAP Support kontaktieren', en: 'Contact SAP Support' },
        'det.erract.BAD_REQUEST':         { de: 'Daten validieren', en: 'Validate data' },
        'det.erract.UNKNOWN':             { de: 'Log prüfen', en: 'Check log' },
        'det.erract.fallback':            { de: 'Details prüfen', en: 'Check details' },

        // migration_details.js — UI strings
        'det.retry_tooltip':             { de: 'Erneut versuchen', en: 'Retry' },
        'det.retry_all_btn':             { de: 'Alle {{n}} Fehler erneut versuchen', en: 'Retry all {{n}} errors' },
        'det.retry_cat_confirm':         { de: 'Alle "{{category}}" Fehler erneut versuchen?', en: 'Retry all "{{category}}" errors?' },
        'det.retry_cat_success':         { de: '{{n}} Datensätze zurückgesetzt.\nStarte Migration im Hintergrund...', en: '{{n}} records reset.\nStarting migration in background...' },
        'det.retry_all_confirm':         { de: 'Alle fehlgeschlagenen Migrationen erneut versuchen?', en: 'Retry all failed migrations?' },
        'det.retry_all_success':         { de: '{{n}} Datensätze zurückgesetzt.\nStarte Migration...', en: '{{n}} records reset.\nStarting migration...' },
        'det.loading_files':             { de: 'Lade Dateien...', en: 'Loading files...' },
        'det.file_load_error':           { de: 'Fehler beim Laden der Dateidetails: {{msg}}', en: 'Error loading file details: {{msg}}' },
        'det.no_file_details':           { de: 'Keine Dateidetails verfügbar', en: 'No file details available' },
        'det.th.filename':               { de: 'Dateiname', en: 'Filename' },
        'det.th.size':                   { de: 'Größe', en: 'Size' },
        'det.th.status':                 { de: 'Status', en: 'Status' },
        'det.th.category':               { de: 'Kategorie', en: 'Category' },
        'det.th.time':                   { de: 'Zeit', en: 'Time' },
        'det.error_detail_label':        { de: 'Fehlerdetails:', en: 'Error Details:' },
        'det.notes_label':               { de: 'Notizen:', en: 'Notes:' },
        'det.th.actions':              { de: 'Aktionen', en: 'Actions' },

        // ══════════════════════════════════════════════════════════════
        // VALIDATION DASHBOARD (validation.html + validation.js)
        // ══════════════════════════════════════════════════════════════
        'val.title':                   { de: 'Validierung', en: 'Validation' },
        'val.subtitle':                { de: 'Ergebnisübersicht nach Verlinkung', en: 'Results overview after linking' },
        'val.back_to_batch':           { de: 'Zurück zum Batch', en: 'Back to Batch' },
        'val.refresh':                 { de: 'Aktualisieren', en: 'Refresh' },
        'val.export_csv':              { de: 'Excel Export', en: 'Excel Export' },
        'val.loading':                 { de: 'Lade Validierungsdaten...', en: 'Loading validation data...' },
        'val.no_data':                 { de: 'Keine Daten vorhanden', en: 'No data available' },
        'val.no_errors':               { de: 'Keine Fehler — alles in Ordnung!', en: 'No errors — all good!' },

        // KPI cards
        'val.kpi.total':               { de: 'Gesamt', en: 'Total' },
        'val.kpi.linked':              { de: 'Verlinkt', en: 'Linked' },
        'val.kpi.link_failed':         { de: 'Link-Fehler', en: 'Link Errors' },
        'val.kpi.pending':             { de: 'Ausstehend', en: 'Pending' },
        'val.kpi.files':               { de: 'Dateien', en: 'Files' },
        'val.kpi.skipped':             { de: 'Übersprungen', en: 'Skipped' },
        'val.kpi.coverage':            { de: 'Abdeckung', en: 'Coverage' },

        // Progress bars
        'val.progress.upload':         { de: 'Upload-Fortschritt', en: 'Upload Progress' },
        'val.progress.linking':        { de: 'Verlinkung-Fortschritt', en: 'Linking Progress' },

        // DOKOB mapping section
        'val.dokob.title':             { de: 'Mapping-Abdeckung nach DOKOB', en: 'Mapping Coverage by DOKOB' },
        'val.dokob.source':            { de: 'Quell-DOKOB', en: 'Source DOKOB' },
        'val.dokob.total_records':     { de: 'Datensätze', en: 'Records' },
        'val.dokob.mapped':            { de: 'Gemappt', en: 'Mapped' },
        'val.dokob.unmapped':          { de: 'Ungemappt', en: 'Unmapped' },
        'val.dokob.linked':            { de: 'Verlinkt', en: 'Linked' },
        'val.dokob.link_failed':       { de: 'Fehler', en: 'Errors' },
        'val.dokob.coverage':          { de: 'Abdeckung', en: 'Coverage' },

        // Error analysis
        'val.errors.link_title':       { de: 'Link-Fehler Analyse', en: 'Link Error Analysis' },
        'val.errors.upload_title':     { de: 'Upload-Fehler Analyse', en: 'Upload Error Analysis' },
        'val.errors.pattern':          { de: 'Fehlermuster', en: 'Error Pattern' },
        'val.errors.count':            { de: 'Anzahl', en: 'Count' },

        // Source → Target comparison
        'val.comp.title':              { de: 'Quell- / Ziel-Vergleich', en: 'Source / Target Comparison' },
        'val.comp.all':                { de: 'Alle', en: 'All' },
        'val.comp.failed':             { de: 'Fehler', en: 'Errors' },
        'val.comp.pending':            { de: 'Ausstehend', en: 'Pending' },
        'val.comp.linked':             { de: 'Verlinkt', en: 'Linked' },
        'val.comp.skipped':            { de: 'Übersprungen', en: 'Skipped' },
        'val.comp.search':             { de: 'Suchen...', en: 'Search...' },
        'val.comp.source_doc':         { de: 'Quell-Dok', en: 'Source Doc' },
        'val.comp.target_doc':         { de: 'Ziel-Dok', en: 'Target Doc' },
        'val.comp.target_dokob':       { de: 'Ziel-DOKOB', en: 'Target DOKOB' },
        'val.comp.target_objky':       { de: 'Ziel-OBJKY', en: 'Target OBJKY' },
        'val.comp.upload':             { de: 'Upload', en: 'Upload' },
        'val.comp.link':               { de: 'Link', en: 'Link' },
        'val.comp.error':              { de: 'Fehler', en: 'Error' },
        'val.comp.showing':            { de: 'Zeige {{shown}} von {{total}} Datensätzen', en: 'Showing {{shown}} of {{total}} records' },
        'val.comp.showing_limit':      { de: 'Zeige {{shown}} von {{filtered}} gefilterten ({{total}} gesamt) — Export enthält alle', en: 'Showing {{shown}} of {{filtered}} filtered ({{total}} total) — Export includes all' },
        'val.display_limit':           { de: 'Anzeige', en: 'Display' },

        // Tabs
        'val.tab.files':               { de: 'Dateien', en: 'Files' },
        'val.tab.links':               { de: 'Objektlinks', en: 'Object Links' },
        'val.tab.errors':              { de: 'Fehleranalyse', en: 'Error Analysis' },

        // Files tab
        'val.files.source_doc':        { de: 'Quell-Dok', en: 'Source Doc' },
        'val.files.src_tvt':           { de: 'Quell-Typ/Ver./Teil', en: 'Source Type/Ver./Part' },
        'val.files.target_doc':        { de: 'Ziel-Dok', en: 'Target Doc' },
        'val.files.tgt_tvt':           { de: 'Ziel-Typ/Ver./Teil', en: 'Target Type/Ver./Part' },
        'val.files.src_desc':          { de: 'Quell-Beschreibung', en: 'Source Description' },
        'val.files.tgt_desc':          { de: 'Ziel-Beschreibung', en: 'Target Description' },
        'val.files.src_filename':      { de: 'Quell-Dateiname', en: 'Source Filename' },
        'val.files.tgt_filename':      { de: 'Ziel-Dateiname', en: 'Target Filename' },
        'val.files.filename':          { de: 'Dateiname', en: 'Filename' },
        'val.files.type':              { de: 'Typ', en: 'Type' },
        'val.files.size':              { de: 'Größe', en: 'Size' },
        'val.files.status':            { de: 'Status', en: 'Status' },
        'val.files.error':             { de: 'Fehler', en: 'Error' },
        'val.filter.success':          { de: 'Erfolgreich', en: 'Success' },
        'val.filter.error':            { de: 'Fehler', en: 'Errors' },
        'val.filter.diff_desc':        { de: 'Beschreibung ≠', en: 'Description ≠' },
        'val.filter.diff_fn':          { de: 'Dateiname ≠', en: 'Filename ≠' },
        'val.filter.diff_any':         { de: 'Alle Unterschiede', en: 'All diffs' },

        // Object links tab
        'val.links.source_doc':        { de: 'Quell-Dok', en: 'Source Doc' },
        'val.links.src_tvt':           { de: 'Quell-Typ/Ver./Teil', en: 'Source Type/Ver./Part' },
        'val.links.target_doc':        { de: 'Ziel-Dok', en: 'Target Doc' },
        'val.links.tgt_tvt':           { de: 'Ziel-Typ/Ver./Teil', en: 'Target Type/Ver./Part' },
        'val.links.src_dokob':         { de: 'Quell-DOKOB', en: 'Source DOKOB' },
        'val.links.src_objky':         { de: 'Quell-OBJKY', en: 'Source OBJKY' },
        'val.links.tgt_dokob':         { de: 'Ziel-DOKOB', en: 'Target DOKOB' },
        'val.links.tgt_objky':         { de: 'Ziel-OBJKY', en: 'Target OBJKY' },
        'val.links.status':            { de: 'Link-Status', en: 'Link Status' },
        'val.links.error':             { de: 'Fehler', en: 'Error' },
        'val.links.not_linked':        { de: 'Linking nicht durchgeführt', en: 'Linking not performed' },

        // ══════════════════════════════════════════════════════════════
        // LANGUAGE TOGGLE
        // ══════════════════════════════════════════════════════════════
        'lang.de':                     { de: 'Deutsch', en: 'German' },
        'lang.en':                     { de: 'Englisch', en: 'English' },
        'lang.toggle_tip':             { de: 'Sprache wechseln', en: 'Switch Language' }
    };

    // ── State ────────────────────────────────────────────────────────
    const STORAGE_KEY = 'dms_migration_lang';
    let currentLang = localStorage.getItem(STORAGE_KEY) || 'de';

    // ── Core Translation Function ────────────────────────────────────
    function t(key, params) {
        const entry = TRANSLATIONS[key];
        if (!entry) {
            console.warn('[i18n] Missing translation key:', key);
            return key;
        }
        let text = entry[currentLang] || entry['de'] || key;
        if (params) {
            Object.keys(params).forEach(k => {
                text = text.replace(new RegExp('\\{\\{' + k + '\\}\\}', 'g'), params[k]);
            });
        }
        return text;
    }

    // ── Apply translations to DOM ────────────────────────────────────
    function applyAll() {
        // data-i18n → textContent
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translated = t(key);
            if (translated !== key) {
                el.textContent = translated;
            }
        });

        // data-i18n-html → innerHTML
        document.querySelectorAll('[data-i18n-html]').forEach(el => {
            const key = el.getAttribute('data-i18n-html');
            const translated = t(key);
            if (translated !== key) {
                el.innerHTML = translated;
            }
        });

        // data-i18n-placeholder → placeholder
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            const translated = t(key);
            if (translated !== key) {
                el.placeholder = translated;
            }
        });

        // data-i18n-title → title
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            const translated = t(key);
            if (translated !== key) {
                el.title = translated;
            }
        });

        // data-inline-help with i18n key
        document.querySelectorAll('[data-i18n-help]').forEach(el => {
            const key = el.getAttribute('data-i18n-help');
            const translated = t(key);
            if (translated !== key) {
                el.setAttribute('data-inline-help', translated);
            }
        });

        // Update html lang attribute
        document.documentElement.lang = currentLang;

        // Update language toggle display
        updateToggleDisplay();
    }

    // ── Update Toggle UI ─────────────────────────────────────────────
    function updateToggleDisplay() {
        const toggle = document.getElementById('langToggle');
        if (toggle) {
            const flag = currentLang === 'de' ? '🇩🇪' : '🇬🇧';
            const label = currentLang === 'de' ? 'DE' : 'EN';
            toggle.innerHTML = flag + ' ' + label;
        }
    }

    // ── Set Language ─────────────────────────────────────────────────
    function setLang(lang) {
        if (lang !== 'de' && lang !== 'en') return;
        currentLang = lang;
        localStorage.setItem(STORAGE_KEY, lang);
        applyAll();

        // Dispatch event for other modules (contextual_help, inline_help, etc.).
        // Dispatched on `document` because those modules listen on `document`
        // (an event dispatched on `window` does NOT reach document-level listeners).
        document.dispatchEvent(new CustomEvent('languageChanged', { detail: { lang: lang } }));
    }

    // ── Public API ───────────────────────────────────────────────────
    window.t = t;
    window.I18n = {
        t: t,
        getLang: function() { return currentLang; },
        setLang: setLang,
        applyAll: applyAll,
        getTranslations: function() { return TRANSLATIONS; }
    };

    // ── Auto-apply on DOM ready ──────────────────────────────────────
    function init() {
        applyAll();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
