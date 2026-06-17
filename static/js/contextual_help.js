/**
 * Contextual In-App Help System for DMS Migration Tool
 * Provides page-aware step-by-step guidance via a slide-in panel.
 */
(function() {
    'use strict';

    // ── Help Content Database ────────────────────────────────────────
    const HELP_CONTENT_DE = {

        // ── Glossary (shared) ────────────────────────────────────────
        glossary: {
            title: 'Begriffe / Glossar',
            icon: 'fas fa-book',
            items: [
                { term: 'DOKOB',   desc: 'Document Object Type — SAP-Geschäftsobjekttyp, an den ein Dokument geknüpft ist (z.B. EQUI, IFLOT, PMAUFK)' },
                { term: 'DOKNR',   desc: 'Dokumentennummer — eindeutige Nummer eines DMS-Dokuments' },
                { term: 'DOKAR',   desc: 'Dokumentenart — Klassifikation (z.B. ZLH, IY1, IY2)' },
                { term: 'DOKVR',   desc: 'Dokumentversion (z.B. 00, 01)' },
                { term: 'DOKTL',   desc: 'Dokumentteil (z.B. 000, 001)' },
                { term: 'OBJKY',   desc: 'Objektschlüssel — Schlüssel des verknüpften Geschäftsobjekts (z.B. Equipmentnummer, Technischer Platz)' },
                { term: 'WERK',    desc: 'Werkscode — identifiziert einen BASF-Standort' },
                { term: 'DRAD',    desc: 'Dokument-Objekt-Verknüpfungstabelle — verbindet Dokumente mit Geschäftsobjekten' },
                { term: 'LOIO',    desc: 'Logical Information Object — Referenz auf die Datei im SAP Content Repository' },
                { term: 'Ablage',  desc: 'Speicherort: KPRO (Datei im Content Repository) oder DB (in DRAO-Datenbanktabelle gespeichert)' },
                { term: 'DRAW',    desc: 'Dokumentinfosatz-Stammtabelle — enthält Dateinamen, Status' },
                { term: 'DIL',     desc: 'Data Integration Layer — Quelldatenbank, die SAP R/3-Tabellen spiegelt' },
                { term: 'Wave',    desc: 'Migrationswelle — zeitliche Gruppierung von Batches für die Planung' },
                { term: 'Batch',   desc: 'Migrationspaket — eine Gruppe von Dokumenten, die zusammen migriert werden' },
            ]
        },

        // ── Workflow Overview ────────────────────────────────────────
        workflow: {
            title: 'Migrations-Workflow',
            icon: 'fas fa-route',
            steps: [
                { num: '0',  label: 'Einstellungen',                 page: 'settings',    desc: 'SAP-Systeme konfigurieren, Credentials speichern, Performance-Parameter setzen' },
                { num: '0b', label: 'Regeln definieren',             page: 'rules',       desc: 'Übersetzungs- und Überschreibungsregeln für Dokumenttypen und -felder festlegen' },
                { num: '1',  label: 'Batch erstellen',               page: 'prepare',     desc: 'Werke auswählen, DMS-Objekte laden, optional Ausschlüsse definieren, Batch anlegen' },
                { num: '2',  label: 'Vorschau & Daten anreichern',page: 'preview',     desc: 'Batch prüfen, Daten anreichern (LOIO, Dateigröße, Regeln anwenden), Datensätze überspringen' },
                { num: '3a', label: 'Migration ausführen',           page: 'preview',     desc: 'Dokumente ins Zielsystem hochladen — Container erstellen und Dateien übertragen' },
                { num: '3b', label: 'Objekt-Zuordnung & Verlinkung', page: 'mapping',     desc: 'Quell-Objekte auf Ziel-Objekte mappen, dann Verlinkung im Zielsystem erstellen' },
                { num: '4',  label: 'Validierung',                    page: 'validation',  desc: 'Dateien, Objektlinks und Fehler analysieren, Quell-/Ziel-Vergleich prüfen' },
            ]
        },

        // ── Page-Specific Help ───────────────────────────────────────

        dashboard: {
            title: 'Dashboard — Batch-Übersicht',
            icon: 'fas fa-tachometer-alt',
            intro: 'Das Dashboard zeigt alle Migrationsbatches gruppiert nach Wellen als Wellen-Übersicht. Hier behalten Sie den Fortschritt im Blick und öffnen einzelne Batches.',
            sections: [
                {
                    title: 'KPI-Karten',
                    content: 'Am oberen Rand sehen Sie vier Gesamtkennzahlen über alle Batches:\n• <b>Wellen</b> — Anzahl der Migrationswellen\n• <b>Batches</b> — Anzahl aller Batches\n• <b>Dokumente</b> — Gesamtzahl der DMS-Dokumente\n• <b>Fehler</b> (rot) — Fehlgeschlagene Uploads/Verlinkungen'
                },
                {
                    title: 'Wellen-Übersicht',
                    content: 'Die Batches sind nach Wellen gruppiert. Jede Welle zeigt aggregierte Fortschrittsbalken für Upload und Verlinkung sowie die enthaltenen Batches als Karten. Mit dem <b>Wellen-Filter</b> darüber blenden Sie einzelne Wellen ein/aus. Geplante, aber noch leere Wellen werden ebenfalls angezeigt.'
                },
                {
                    title: 'Batch-Karte — Aufbau im Detail',
                    content: '<b>Jede Batch-Karte besteht aus 5 Bereichen:</b>\n\n<b>① Kopfzeile</b>\nLinks: Batch-Beschreibung + Dokumentenanzahl\nRechts: Status-Badge (farbig)\n\n<b>② Upload-Fortschrittsbalken</b>\n<span style="color:#28a745">■</span> <b>Grün</b> = Erfolgreich hochgeladen\n<span style="color:#dc3545">■</span> <b>Rot</b> = Fehlgeschlagen\nAnzeige: ↑ Erfolg/Gesamt + Prozent\n\n<b>③ Link-Fortschrittsbalken</b> (nur wenn Verlinkung gestartet)\n<span style="color:#17a2b8">■</span> <b>Cyan</b> = Erfolgreich verlinkt\n<span style="color:#dc3545">■</span> <b>Rot</b> = Link-Fehler\nAnzeige: 🔗 Verlinkt/Gesamt + Prozent\n\n<b>④ Phase-Fortschritt</b> (3 kleine Balken)\nDie drei Balken zeigen: <b>Vorbereitung → Upload → Verlinkung</b>\n<span style="color:#28a745">■</span> Grün = Abgeschlossen\n<span style="color:#007bff">■</span> Blau (pulsierend) = Aktiv/läuft\n<span style="color:#e9ecef">■</span> Grau = Ausstehend\n<span style="color:#dc3545">■</span> Rot = Fehler\n\n<b>⑤ Farbiger Rand links</b>\nDer seitliche Farbbalken zeigt die aktuelle Phase:\n• <span style="color:#6c757d">■</span> <b>Grau</b> — Vorbereitet\n• <span style="color:#007bff">■</span> <b>Blau</b> — Upload aktiv\n• <span style="color:#28a745">■</span> <b>Grün</b> — Upload fertig\n• <span style="color:#17a2b8">■</span> <b>Cyan</b> — Verlinkung läuft\n• <span style="color:#28a745">■</span> <b>Dunkelgrün</b> — Abgeschlossen\n• <span style="color:#dc3545">■</span> <b>Rot</b> — Fehler'
                },
                {
                    title: 'Status-Badges (Farben & Bedeutung)',
                    content: 'Das Badge oben rechts auf jeder Karte zeigt den genauen Status:\n\n<span class="badge badge-secondary">Vorbereitet</span> — Batch erstellt, noch nicht gestartet\n<span class="badge badge-warning">Upload...</span> — Upload läuft gerade\n<span class="badge badge-success">Hochgeladen</span> — Alle Dokumente erfolgreich hochgeladen\n<span class="badge badge-warning">Upload (Fehler)</span> — Upload fertig, aber mit Fehlern\n<span class="badge badge-danger">Fehlgeschlagen</span> — Upload fehlgeschlagen\n<span class="badge badge-info">Verlinke...</span> — Verlinkung läuft\n<span class="badge badge-success">Fertig</span> — Alles erledigt ✓\n<span class="badge badge-warning">Teilw. verlinkt</span> — Verlinkung abgeschlossen, aber Datensätze übersprungen (fehlendes Mapping)\n<span class="badge badge-warning">Verlinkt (Fehler)</span> — Verlinkung mit Fehlern\n<span class="badge badge-danger">Link-Fehler</span> — Verlinkungsfehler\n<span class="badge badge-secondary">Abgebrochen</span> — Verlinkung abgebrochen'
                },
                {
                    title: 'Neuen Batch erstellen',
                    content: 'Klicken Sie oben auf den Workflow-Schritt <b>„1. Batch erstellen"</b> um zur Batch-Erstellung zu gelangen. Dort wählen Sie Werke und laden DMS-Objekte aus der Quelldatenbank.'
                },
                {
                    title: 'Batch öffnen',
                    content: 'Klicken Sie auf eine Batch-Karte, um die <b>Vorschau</b> zu öffnen. Dort können Sie den Batch prüfen und die Migration starten.'
                },
                {
                    title: 'Wellenverwaltung',
                    content: 'Über <b>„Wellenverwaltung"</b> in der Navbar oder den Button <b>„Welle planen"</b> legen Sie eine Welle an. Ein Wellenplan besteht aus dem Wellennamen und optionalen Notizen — die zugeordneten Batches erscheinen anschließend in der Wellen-Übersicht.'
                }
            ]
        },

        settings: {
            title: 'Einstellungen — Systemkonfiguration',
            icon: 'fas fa-cog',
            intro: 'Hier konfigurieren Sie SAP-Systeme, Zugangsdaten und Performance-Parameter. Diese Einstellungen müssen vor der ersten Migration gesetzt werden.',
            sections: [
                {
                    title: 'Performance-Einstellungen',
                    content: '<b>Max API Workers</b> (1–50): Anzahl paralleler API-Aufrufe. Mehr = schneller, aber höhere Last auf dem Zielsystem.\n\n<b>Pacing</b> (Sekunden): Verzögerung zwischen API-Aufrufen.\n• <b>0 = Dynamisch</b> (empfohlen): Passt die Verzögerung automatisch an die Dateigröße an\n• Fester Wert: Konstante Verzögerung'
                },
                {
                    title: 'API-Endpunkte konfigurieren',
                    content: 'Fügen Sie Quellsysteme (R/3) und Zielsysteme (S/4HANA) hinzu:\n• <b>System-ID</b>: Eindeutiger Kurzname (z.B. „zv1", „s4qual")\n• <b>Typ</b>: R3 (Quelle) oder S4 (Ziel)\n• <b>Auth-Typ</b>: OAuth oder Basic Auth\n• <b>API-Endpunkte</b>: URLs für die verschiedenen APIs (Metadata, Download, Upload, Link)'
                },
                {
                    title: 'Zugangsdaten (Credentials)',
                    content: 'Für Basic-Auth-Systeme (ZV-Instanzen) können Sie Benutzername und Passwort verschlüsselt speichern.\n\n<b>Testen</b>: Klicken Sie „Testen" um die Verbindung zu prüfen — das System holt ein CSRF-Token.'
                },
                {
                    title: 'Quell-/Zielsystem wählen',
                    content: 'In der <b>Navbar</b> oben rechts können Sie das aktive Quell- und Zielsystem per Dropdown wechseln. Achten Sie darauf, das richtige System zu wählen bevor Sie eine Migration starten!\n\n⚠️ <b>Prod-Systeme</b> werden rot markiert.'
                }
            ],
            warnings: [
                'Stellen Sie sicher, dass OAuth-Tokens gültig sind, bevor Sie eine Migration starten.',
                'Bei Basic Auth müssen die Credentials gespeichert UND getestet sein.'
            ]
        },

        rules: {
            title: 'Migrationsregeln',
            icon: 'fas fa-tasks',
            intro: 'Regeln transformieren Dokumentfelder automatisch während „Daten anreichern" (Phase 4/4). Sie werden in der festgelegten Reihenfolge auf jeden Datensatz angewandt.',
            sections: [
                {
                    title: 'Übersetzungsregeln (Translation)',
                    content: 'Wandeln einen Quellwert in einen Zielwert um.\n\n<b>Beispiel</b>: Dokumentenart „ZLH" im Quellsystem → „IY1" im Zielsystem\n• <b>Quellspalte</b>: Das Feld, das geprüft wird (z.B. source_documenttype)\n• <b>Quellwert</b>: Der zu ersetzende Wert\n• <b>Zielspalte</b>: Das Feld, das gesetzt wird\n• <b>Zielwert</b>: Der neue Wert'
                },
                {
                    title: 'Überschreibungsregeln (Overwrite)',
                    content: 'Setzen ein Feld auf einen festen Wert — unabhängig vom Quellwert.\n\n<b>Beispiel</b>: Alle Dokumente bekommen target_documenttype = „IY1"\n• Optionale <b>Bedingung</b>: Nur anwenden, wenn ein bestimmtes Feld einen bestimmten Wert hat'
                },
                {
                    title: 'Präfix-Ersetzungsregeln (Replace Prefix)',
                    content: 'Ersetzt den Anfang eines Feldwertes durch einen anderen Präfix.\n\n<b>Beispiel</b>: Quellwert beginnt mit „CB" → wird zu „SIT" (z.B. CB-L525 → SIT-L525)\n• <b>Quellspalte</b>: Das Feld, das geprüft wird (z.B. target_documentnumber)\n• <b>Quellwert</b>: Der zu suchende Präfix (z.B. „CB")\n• <b>Zielspalte</b>: Das Feld, das geändert wird\n• <b>Zielwert</b>: Der neue Präfix (z.B. „SIT")\n\nNur der Anfang wird ersetzt, der Rest des Wertes bleibt erhalten.'
                },
                {
                    title: 'Bedingungen (Conditions)',
                    content: 'Jede Regel kann eine optionale Bedingung haben:\n• <b>enthält</b> (contains)\n• <b>gleich</b> (equals)\n• <b>beginnt mit</b> (starts_with)\n\nDie Bedingung prüft ein frei wählbares Feld und Wert.'
                },
                {
                    title: 'Reihenfolge',
                    content: 'Regeln werden in der angezeigten Reihenfolge ausgeführt (niedrigere Nummer = zuerst). Nutzen Sie die Pfeil-Buttons zum Umsortieren.\n\n⚠️ Die Reihenfolge ist wichtig, wenn mehrere Regeln das gleiche Feld betreffen!'
                }
            ],
            warnings: [
                'Regeln werden nur beim „Daten anreichern" in der Vorschau angewandt — nicht beim Batch-Erstellen.',
                'Änderungen an Regeln erfordern ein erneutes „Daten anreichern" für bestehende Batches.'
            ]
        },

        prepare: {
            title: 'Schritt 1 — Batch erstellen',
            icon: 'fas fa-plus-circle',
            intro: 'Erstellen Sie einen neuen Migrationsbatch. Dafür gibt es zwei Wege: Werke auswählen und DMS-Objekte laden (Tab „DMS Objekte"), oder eine fertige DMS-Key-Liste hochladen (Tab „DMS-Key Liste").',
            sections: [
                {
                    title: '1. Werke auswählen',
                    content: 'Wählen Sie die Werke (Standorte) aus, deren Dokumente migriert werden sollen. Die Werksliste wird beim ersten Laden aus der DIL-Datenbank geladen und lokal zwischengespeichert.'
                },
                {
                    title: '2. DMS-Objekte laden',
                    content: 'Klicken Sie <b>„DMS Objekte laden"</b>. Das System fragt 11 Objekttypen ab:\n\n• <b>EQUI</b> — Equipment\n• <b>IFLOT</b> — Technischer Platz\n• <b>MPLA</b> — Wartungsplan\n• <b>PMPLKO</b> — Planungsobjekt\n• <b>PMAUFK</b> — Instandhaltungsauftrag\n• <b>PMAFVC</b> — Auftragsvorgang\n• <b>PMQMEL</b> — PM-Meldung\n• <b>SMQMEL</b> — SM-Meldung\n• <b>STKO_DOC</b> / <b>STPO_DOC</b> — Stücklisten\n• <b>IMPTT</b> — Messpunkte\n\n<b>Automatische Ausschlüsse</b> per JEST-Status:\n• Gelöschte Equipments/Techn. Plätze (I0320, I0013, I0076)\n• TECO/Closed-Aufträge (I0045, I0046)\n• Geschlossene Meldungen (I0072)\n• Löschkennzeichen bei Plänen und Stücklisten'
                },
                {
                    title: '3. Ausschluss-Template (optional)',
                    content: 'Laden Sie ein <b>Excel-Template</b> herunter, tragen Sie OBJKY-Werte ein, die ausgeschlossen werden sollen, und laden Sie es wieder hoch. So können Sie z.B. bestimmte Equipments oder Aufträge gezielt von der Migration ausschließen.'
                },
                {
                    title: '4. Batch-Metadaten',
                    content: '• <b>Wave</b> (Pflicht): Welcher Migrationswelle gehört der Batch an?\n• <b>Beschreibung</b> (max. 40 Zeichen): Kurzbeschreibung\n• <b>Notizen</b>: Zusätzliche Informationen\n• <b>DOKOB-Filter</b>: Optional nur bestimmte Objekttypen in den Batch aufnehmen'
                },
                {
                    title: '5. Batch erstellen',
                    content: 'Klicken Sie <b>„Batch erstellen"</b>. Das System:\n• Liest die lokalen DMS-Objekte\n• Wendet Filter und Ausschlüsse an\n• Erstellt den Batch (ID: DMS_YYYYMMDD_HHMMSS)\n• Generiert Ziel-Dokumentennummern (intern: automatisch, extern: beibehalten)\n\nSie werden anschließend zur Vorschau weitergeleitet.'
                },
                {
                    title: 'Alternative: DMS-Key Liste hochladen',
                    content: 'Statt Werke zu wählen, können Sie im Tab <b>„DMS-Key Liste"</b> eine fertige Liste von DMS-Keys hochladen (Excel/CSV):\n\n• <b>Template</b> über „Template herunterladen" laden — benötigte Spalten: <b>Documenttype, Documentversion, Documentpart, Documentnumber</b>\n• Key-Aufbau: <b>Typ / Version / Teil / Dokumentnummer</b> (intern oder extern)\n• Datei wählen und <b>„Keys laden & prüfen"</b> klicken\n• Die Objekt-Verknüpfungen werden anschließend automatisch in DRAD ermittelt — wie bei „DMS Objekte"\n• Nach der Prüfung erstellen Sie den Batch wie gewohnt'
                }
            ],
            warnings: [
                'Die DMS-Objekte werden lokal gespeichert. Bei erneuter Auswahl derselben Werke werden die Daten überschrieben.',
                'Interne Nummernkreise (IY1, IY2) bekommen automatisch neue Nummern im Zielsystem.',
                'Stellen Sie sicher, dass das richtige Quellsystem in der Navbar gewählt ist!'
            ]
        },

        preview: {
            title: 'Schritt 2 — Vorschau & Migration',
            icon: 'fas fa-search',
            intro: 'Prüfen Sie den Batch, aktualisieren Sie die Metadaten und führen Sie die Migration aus.',
            sections: [
                {
                    title: '1. Batch-Statistiken prüfen',
                    content: 'Oben sehen Sie:\n• <b>Gesamtanzahl</b> Datensätze (mit ✓ Erfolge)\n• <b>Ausgeschlossen / KPRO / DB</b> — Herkunft & Ablage\n• <b>Gesamtgröße</b> und eine Warnung bei <b>großen Dateien (>99MB)</b>\n• <b>Pacing</b> — aktuelle Verzögerungseinstellung\n• <b>Status-Verteilung</b> im Filter: Pending, Success, Failed, Partial'
                },
                {
                    title: '⭐ 2. „Daten anreichern" ausführen',
                    content: '<b>Das ist der wichtigste Schritt!</b> Klicken Sie den Button „Daten anreichern" / „Enrich Data". Das System durchläuft 5 Phasen:\n\n<b>Phase 1/4</b>: LOIO-Lookup — Dateireferenzen aus dem Content Repository laden\n<b>Phase 2/4</b>: Dateigrößen — Tatsächliche Dateigrößen ermitteln\n<b>Phase 3/4</b>: Dateinamen + Beschreibungen — aus DRAW/DRAT (Englisch bevorzugt, dann Deutsch)\n<b>Phase 4/4</b>: Migrationsregeln anwenden — Übersetzungs-/Überschreibungsregeln ausführen\n<b>Phase 5/5</b>: Linkzählung — Quell-/Ziel-Verknüpfungen zählen',
                    highlight: true
                },
                {
                    title: '3. Datensätze durchsuchen',
                    content: 'Die Tabelle zeigt alle Datensätze (5000 pro Seite). Nutzen Sie die Filter:\n• <b>Status-Filter</b>: Pending, Success, Failed, Partial\n• <b>Fehler-Kategorie</b>: Art des Fehlers\n• <b>Ablage</b>: KPRO oder DB\n• <b>Volltextsuche</b>: Über alle Felder'
                },
                {
                    title: '4. Datensätze überspringen',
                    content: 'Einzelne Datensätze können mit der <b>„Überspringen"</b>-Funktion von der Migration ausgeschlossen werden. Geben Sie einen Grund an. Übersprungene Datensätze werden bei der Ausführung ignoriert.'
                },
                {
                    title: '5. Migration starten',
                    content: 'Klicken Sie <b>„Migration starten"</b>. Für jeden Datensatz wird:\n1. Ein Dokumenten-Container im Zielsystem erstellt\n2. Die Datei(en) vom Quellsystem heruntergeladen\n3. Die Datei(en) ins Zielsystem hochgeladen\n\nDer Fortschritt wird live aktualisiert. Sie können die Migration jederzeit <b>abbrechen</b>.'
                },
                {
                    title: '6. Fehlgeschlagene zurücksetzen',
                    content: 'Nach der Ausführung können Sie <b>fehlgeschlagene Datensätze zurücksetzen</b> und erneut versuchen. Datensätze mit Status „Partial" (Container erstellt, Dateien teilweise hochgeladen) werden beim erneuten Versuch nur die fehlenden Dateien übertragen.'
                }
            ],
            warnings: [
                '⚠️ WICHTIG: „Daten anreichern" MUSS vor der Ausführung gemacht werden! Ohne dies fehlen LOIO-IDs, Dateigrößen und Dateinamen.',
                'Stellen Sie sicher, dass Sie angemeldet sind und das Token gültig ist.',
                'Große Batches (>10.000 Dokumente) können mehrere Stunden dauern. Die Session wird automatisch am Leben gehalten.'
            ]
        },

        mapping: {
            title: 'Schritt 3 — Objekt-Zuordnung & Verlinkung',
            icon: 'fas fa-project-diagram',
            intro: 'Ordnen Sie Quell-Geschäftsobjekte den Ziel-Geschäftsobjekten zu und erstellen Sie die Verknüpfungen im Zielsystem.',
            sections: [
                {
                    title: '1. Zuordnungen verwalten',
                    content: 'Jedes Quellsystem-Objekt muss einem Zielsystem-Objekt zugeordnet werden.\n\nDie Zuordnung besteht aus:\n• <b>Quell-DOKOB</b> + <b>Quell-OBJKY</b> → <b>Ziel-DOKOB</b> + <b>Ziel-OBJKY</b>\n\n<b>Wichtig — SAP-Schlüsselformat:</b>\nDie OBJKY-Werte müssen im SAP-internen Format angegeben werden:\n• <b>EQUI</b>: 18-stellig, führende Nullen (z.B. <code>000000000010045127</code>)\n• <b>IFLOT</b> (Techn. Platz): SAP-interner Schlüssel, NICHT die Anzeige-Darstellung (z.B. <code>CB-L525-SIT-01</code> statt <code>CB-L525/SIT/01</code>)\n• <b>PMAUFK</b>: 12-stellig, führende Nullen (z.B. <code>000004001234</code>)\n• <b>MPLA</b>: Wartungsplannummer + Wartungspositionsnummer\n• <b>STPO_DOC/STKO_DOC</b>: Stücklistennummer\n\nIn vielen Fällen bleiben DOKOB und OBJKY gleich (z.B. Equipment behält seine Nummer). Bei Standort-Umbenennungen (z.B. CB → SIT) müssen die Ziel-OBJKY entsprechend angepasst werden.'
                },
                {
                    title: '2. Excel-Mapping-Template',
                    content: '<b>Empfohlener Weg:</b>\n1. Klicken Sie <b>„Template herunterladen"</b>\n2. Die Excel-Datei enthält Tabellenblätter:\n   • <b>Mappings</b>: Bestehende Zuordnungen\n   • <b>Batch Objects</b>: Alle Quell-Objekte des Batches\n   • <b>Unmapped</b>: Objekte ohne Zuordnung\n   • <b>Info</b>: Erklärungen\n3. Füllen Sie die Ziel-Spalten aus\n4. Laden Sie die Datei über <b>„Template hochladen"</b> wieder hoch\n\n⚠️ <b>OBJKY-Format beachten</b>: Verwenden Sie immer das SAP-interne Schlüsselformat (siehe oben).'
                },
                {
                    title: '3. Zuordnungen anwenden',
                    content: 'Klicken Sie <b>„Zuordnungen anwenden"</b> um die Mappings auf die Staging-Datensätze zu übertragen. Dadurch werden target_dokob und target_objky in den Datensätzen gesetzt.'
                },
                {
                    title: '4. Verlinkung starten',
                    content: 'Nach erfolgreichem Upload (Schritt 2) klicken Sie <b>„Zuordnungen verlinken"</b>:\n• Datensätze ohne passendes Mapping werden automatisch als <b>übersprungen</b> markiert (kein API-Aufruf)\n• Datensätze mit Mapping werden im Zielsystem verlinkt\n• Der Fortschritt wird live aktualisiert\n\n<b>Link-Status pro Datensatz:</b>\n• <b>linked</b> — Erfolgreich verknüpft\n• <b>link_exists</b> — Verknüpfung existierte bereits\n• <b>link_failed</b> — Fehler bei der Verlinkung\n• <b>link_skipped</b> — Kein Mapping vorhanden, übersprungen\n\n<b>Fortschrittsanzeige:</b>\nDer Fortschritt zeigt <b>Verlinkt / Gesamt</b>, wobei „Gesamt" auch die übersprungenen umfasst. So ist der echte Fortschritt erkennbar (z.B. 64% = nur IFLOT gemappt, EQUI fehlt noch).'
                }
            ],
            warnings: [
                'Die Verlinkung kann nur für Datensätze mit Status „success" und erstelltem Container durchgeführt werden.',
                'Ohne Objekt-Zuordnung werden Datensätze automatisch übersprungen (link_skipped).',
                'Prüfen Sie die „Unmapped"-Liste im Excel-Template — nicht zugeordnete Objekte werden nicht verlinkt.',
                'OBJKY muss im SAP-internen Format sein, nicht in der Anzeige-Darstellung!'
            ]
        },

        details: {
            title: 'Schritt 4 — Validierung & Prüfung',
            icon: 'fas fa-check-double',
            intro: 'Prüfen Sie Dateien, Objektlinks und Fehler. Vergleichen Sie Quell- und Zieldaten mit farblicher Hervorhebung.',
            sections: [
                {
                    title: 'KPI-Karten & Fortschritt',
                    content: 'Oben sehen Sie 6 Kennzahlen:\n• <b>Gesamt</b> — Alle Datensätze im Batch\n• <b>Verlinkt</b> (grün) — Erfolgreich verlinkte Datensätze\n• <b>Fehler</b> (rot) — Fehlgeschlagene Verlinkungen\n• <b>Ausstehend</b> (gelb) — Noch nicht verlinkte Datensätze\n• <b>Übersprungen</b> (grau) — Kein Mapping vorhanden\n• <b>Abdeckung</b> (blau) — Prozent der verlinkten Datensätze\n\nDarunter zwei Fortschrittsbalken für Upload und Verlinkung.'
                },
                {
                    title: 'Tab 1: Dateien',
                    content: 'Vergleicht Quell- und Zieldaten pro Datei mit 12 Spalten:\n\n<b>Spalten:</b>\n• Quell-Dok / Quell-Typ,Ver.,Teil\n• Ziel-Dok / Ziel-Typ,Ver.,Teil\n• <b>Quell-Beschreibung</b> — Original aus DIL/DRAT (SAP-Quelle)\n• <b>Ziel-Beschreibung</b> — was ins Zielsystem übertragen wurde\n• <b>Quell-Dateiname</b> — Original-Dateiname (aus DRAW)\n• <b>Ziel-Dateiname</b> — Hochgeladener Dateiname\n• Typ, Größe, Status, Fehler\n\n<b>Farbliche Hervorhebung:</b>\n• <span style="background:#fff3cd;padding:2px 6px">Gelb</span> = Quell- und Zielwert unterscheiden sich\n\n<b>Filter-Buttons:</b>\n• <b>Alle</b> — Alle Dateien\n• <b>Erfolgreich</b> — Nur erfolgreiche Uploads\n• <b>Fehler</b> — Nur fehlgeschlagene\n• <b>Beschreibung ≠</b> — Nur Zeilen mit abweichender Beschreibung\n• <b>Dateiname ≠</b> — Nur Zeilen mit abweichendem Dateinamen\n• <b>Alle Unterschiede</b> — Zeilen mit irgendeiner Abweichung'
                },
                {
                    title: 'Tab 2: Objektlinks',
                    content: 'Zeigt die aufgelösten Objekt-Verknüpfungen pro Datensatz. Jeder Quell-Link (aus source_object_links) wird einzeln als Zeile dargestellt.\n\n<b>Spalten:</b>\n• Quell-/Ziel-Dokumentennummer + Typ/Ver./Teil\n• Quell-DOKOB → Ziel-DOKOB (farbig markiert)\n• Quell-OBJKY → Ziel-OBJKY (farbig markiert)\n• Link-Status, Fehler\n\n<b>Farben:</b>\n• <span style="background:#d4edda;padding:2px 6px">Grün</span> = Quell=Ziel (identisch)\n• <span style="background:#fff3cd;padding:2px 6px">Gelb</span> = Mapping vorhanden, Wert geändert\n• <span style="background:#f8d7da;padding:2px 6px">Rot</span> = Kein Zielwert (nicht gemappt)\n\n<b>Filter:</b> Alle, Linked, Fehler, Pending, Übersprungen'
                },
                {
                    title: 'Tab 3: Fehleranalyse',
                    content: 'Enthält vier Analyse-Tabellen:\n• <b>DAPPL/Extension-Analyse</b> (per Button ladbar)\n• <b>DOKOB Mapping Coverage</b> — Zeigt pro Objekttyp wie viele gemappt/ungemappt sind\n• <b>Link-Fehler</b> — Fehlermuster mit Häufigkeit\n• <b>Upload-Fehler</b> — Fehlermuster mit Häufigkeit'
                },
                {
                    title: 'Excel-Export',
                    content: 'Klicken Sie <b>„Export"</b> um alle Datei-Details als formatierte Excel-Datei herunterzuladen:\n• Gleiche 12 Spalten wie die Web-Ansicht\n• Farbliche Hervorhebung bei Unterschieden (gelb)\n• Grün/Rot für Status\n• Autofilter, fixierte Kopfzeile, automatische Spaltenbreite'
                }
            ]
        }
    };

    // ── Help Content — English ───────────────────────────────────────
    const HELP_CONTENT_EN = {

        // ── Glossary (shared) ────────────────────────────────────────
        glossary: {
            title: 'Terms / Glossary',
            icon: 'fas fa-book',
            items: [
                { term: 'DOKOB',   desc: 'Document Object Type — SAP business object type to which a document is attached (e.g. EQUI, IFLOT, PMAUFK)' },
                { term: 'DOKNR',   desc: 'Document Number — unique number of a DMS document' },
                { term: 'DOKAR',   desc: 'Document Type — classification (e.g. ZLH, IY1, IY2)' },
                { term: 'DOKVR',   desc: 'Document Version (e.g. 00, 01)' },
                { term: 'DOKTL',   desc: 'Document Part (e.g. 000, 001)' },
                { term: 'OBJKY',   desc: 'Object Key — key of the linked business object (e.g. Equipment number, Functional Location)' },
                { term: 'WERK',    desc: 'Plant Code — identifies a BASF site' },
                { term: 'DRAD',    desc: 'Document-Object Link Table — connects documents with business objects' },
                { term: 'LOIO',    desc: 'Logical Information Object — reference to the file in the SAP Content Repository' },
                { term: 'Ablage',  desc: 'Storage type: KPRO (file in Content Repository) or DB (stored in DRAO database table)' },
                { term: 'DRAW',    desc: 'Document Info Record Master Table — contains file names, status' },
                { term: 'DIL',     desc: 'Data Integration Layer — source database mirroring SAP R/3 tables' },
                { term: 'Wave',    desc: 'Migration wave — time-based grouping of batches for planning' },
                { term: 'Batch',   desc: 'Migration batch — a group of documents that are migrated together' },
            ]
        },

        // ── Workflow Overview ────────────────────────────────────────
        workflow: {
            title: 'Migration Workflow',
            icon: 'fas fa-route',
            steps: [
                { num: '0',  label: 'Settings',                      page: 'settings',    desc: 'Configure SAP systems, save credentials, set performance parameters' },
                { num: '0b', label: 'Define Rules',                   page: 'rules',       desc: 'Define translation and overwrite rules for document types and fields' },
                { num: '1',  label: 'Create Batch',                   page: 'prepare',     desc: 'Select plants, load DMS objects, optionally define exclusions, create batch' },
                { num: '2',  label: 'Preview & Refresh Data',         page: 'preview',     desc: 'Review batch, refresh data (LOIO, file size, apply rules), skip records' },
                { num: '3a', label: 'Run Migration',                  page: 'preview',     desc: 'Upload documents to target system — create containers and transfer files' },
                { num: '3b', label: 'Object Mapping & Linking',       page: 'mapping',     desc: 'Map source objects to target objects, then create links in target system' },
                { num: '4',  label: 'Analysis',                       page: 'details',     desc: 'Review files, object links and errors. Compare source/target data with diff highlighting' },
            ]
        },

        // ── Page-Specific Help ───────────────────────────────────────

        dashboard: {
            title: 'Dashboard — Batch Overview',
            icon: 'fas fa-tachometer-alt',
            intro: 'The dashboard shows all migration batches grouped by waves as a wave overview. Here you track progress and open individual batches.',
            sections: [
                {
                    title: 'KPI Cards',
                    content: 'At the top you see four overall metrics across all batches:\n• <b>Waves</b> — Number of migration waves\n• <b>Batches</b> — Number of all batches\n• <b>Documents</b> — Total number of DMS documents\n• <b>Errors</b> (red) — Failed uploads/linkings'
                },
                {
                    title: 'Wave Overview',
                    content: 'Batches are grouped by wave. Each wave shows aggregated progress bars for upload and linking, plus the contained batches as cards. Use the <b>wave filter</b> above to show/hide individual waves. Planned but still empty waves are also shown.'
                },
                {
                    title: 'Batch Card — Detailed Structure',
                    content: '<b>Each batch card consists of 5 areas:</b>\n\n<b>① Header</b>\nLeft: Batch description + document count\nRight: Status badge (colored)\n\n<b>② Upload Progress Bar</b>\n<span style="color:#28a745">■</span> <b>Green</b> = Successfully uploaded\n<span style="color:#dc3545">■</span> <b>Red</b> = Failed\nDisplay: ↑ Success/Total + Percent\n\n<b>③ Link Progress Bar</b> (only when linking has started)\n<span style="color:#17a2b8">■</span> <b>Cyan</b> = Successfully linked\n<span style="color:#dc3545">■</span> <b>Red</b> = Link error\nDisplay: 🔗 Linked/Total + Percent\n\n<b>④ Phase Progress</b> (3 small bars)\nThe three bars show: <b>Preparation → Upload → Linking</b>\n<span style="color:#28a745">■</span> Green = Completed\n<span style="color:#007bff">■</span> Blue (pulsing) = Active/running\n<span style="color:#e9ecef">■</span> Gray = Pending\n<span style="color:#dc3545">■</span> Red = Error\n\n<b>⑤ Colored Left Border</b>\nThe side color bar shows the current phase:\n• <span style="color:#6c757d">■</span> <b>Gray</b> — Prepared\n• <span style="color:#007bff">■</span> <b>Blue</b> — Upload active\n• <span style="color:#28a745">■</span> <b>Green</b> — Upload complete\n• <span style="color:#17a2b8">■</span> <b>Cyan</b> — Linking in progress\n• <span style="color:#28a745">■</span> <b>Dark green</b> — Completed\n• <span style="color:#dc3545">■</span> <b>Red</b> — Error'
                },
                {
                    title: 'Status Badges (Colors & Meaning)',
                    content: 'The badge at the top right of each card shows the exact status:\n\n<span class="badge badge-secondary">Prepared</span> — Batch created, not yet started\n<span class="badge badge-warning">Uploading...</span> — Upload in progress\n<span class="badge badge-success">Uploaded</span> — All documents successfully uploaded\n<span class="badge badge-warning">Upload (Errors)</span> — Upload finished, but with errors\n<span class="badge badge-danger">Failed</span> — Upload failed\n<span class="badge badge-info">Linking...</span> — Linking in progress\n<span class="badge badge-success">Done</span> — All done ✓\n<span class="badge badge-warning">Partially Linked</span> — Linking finished, but records skipped (missing mapping)\n<span class="badge badge-warning">Linked (Errors)</span> — Linking with errors\n<span class="badge badge-danger">Link Error</span> — Linking error\n<span class="badge badge-secondary">Cancelled</span> — Linking cancelled'
                },
                {
                    title: 'Create New Batch',
                    content: 'Click the workflow step <b>"1. Create Batch"</b> at the top to go to the batch creation page. There you select plants and load DMS objects from the source database.'
                },
                {
                    title: 'Open Batch',
                    content: 'Click on a batch card to open the <b>Preview</b>. There you can review the batch and start the migration.'
                },
                {
                    title: 'Wave Management',
                    content: 'Via <b>"Wave Management"</b> in the navbar or the <b>"Plan Wave"</b> button you create a wave. A wave plan consists of the wave name and optional notes — the assigned batches then appear in the wave overview.'
                }
            ]
        },

        settings: {
            title: 'Settings — System Configuration',
            icon: 'fas fa-cog',
            intro: 'Here you configure SAP systems, credentials and performance parameters. These settings must be configured before the first migration.',
            sections: [
                {
                    title: 'Performance Settings',
                    content: '<b>Max API Workers</b> (1–50): Number of parallel API calls. More = faster, but higher load on the target system.\n\n<b>Pacing</b> (seconds): Delay between API calls.\n• <b>0 = Dynamic</b> (recommended): Automatically adjusts the delay based on file size\n• Fixed value: Constant delay'
                },
                {
                    title: 'Manage SAP Systems',
                    content: 'Add source systems (R/3) and target systems (S/4HANA):\n• <b>System ID</b>: Unique short name (e.g. "zv1", "s4qual")\n• <b>Type</b>: R3 (source) or S4 (target)\n• <b>Auth Type</b>: OAuth or Basic Auth\n• <b>API Endpoints</b>: URLs for the various APIs (Metadata, Download, Upload, Link)'
                },
                {
                    title: 'Credentials',
                    content: 'For Basic Auth systems (ZV instances) you can store username and password encrypted.\n\n<b>Test</b>: Click "Test" to verify the connection — the system fetches a CSRF token.'
                },
                {
                    title: 'Select Source/Target System',
                    content: 'In the <b>Navbar</b> at the top right you can switch the active source and target system via dropdown. Make sure to select the correct system before starting a migration!\n\n⚠️ <b>Prod systems</b> are highlighted in red.'
                }
            ],
            warnings: [
                'Make sure OAuth tokens are valid before starting a migration.',
                'For Basic Auth, credentials must be saved AND tested.'
            ]
        },

        rules: {
            title: 'Migration Rules',
            icon: 'fas fa-tasks',
            intro: 'Rules automatically transform document fields during "Refresh Data" (Phase 4/4). They are applied to each record in the defined order.',
            sections: [
                {
                    title: 'Translation Rules',
                    content: 'Convert a source value to a target value.\n\n<b>Example</b>: Document type "ZLH" in source system → "IY1" in target system\n• <b>Source column</b>: The field to check (e.g. source_documenttype)\n• <b>Source value</b>: The value to replace\n• <b>Target column</b>: The field to set\n• <b>Target value</b>: The new value'
                },
                {
                    title: 'Overwrite Rules',
                    content: 'Set a field to a fixed value — regardless of the source value.\n\n<b>Example</b>: All documents get target_documenttype = "IY1"\n• Optional <b>Condition</b>: Only apply when a specific field has a specific value'
                },
                {
                    title: 'Replace Prefix Rules',
                    content: 'Replaces the beginning of a field value with a different prefix.\n\n<b>Example</b>: Source value starts with "CB" → becomes "SIT" (e.g. CB-L525 → SIT-L525)\n• <b>Source column</b>: The field to check (e.g. target_documentnumber)\n• <b>Source value</b>: The prefix to look for (e.g. "CB")\n• <b>Target column</b>: The field to modify\n• <b>Target value</b>: The new prefix (e.g. "SIT")\n\nOnly the beginning is replaced, the rest of the value is preserved.'
                },
                {
                    title: 'Conditions',
                    content: 'Each rule can have an optional condition:\n• <b>contains</b>\n• <b>equals</b>\n• <b>starts_with</b>\n\nThe condition checks any field for a given value.'
                },
                {
                    title: 'Order',
                    content: 'Rules are executed in the displayed order (lower number = first). Use the arrow buttons to reorder.\n\n⚠️ The order matters when multiple rules affect the same field!'
                }
            ],
            warnings: [
                'Rules are only applied during "Refresh Data" in the preview — not when creating a batch.',
                'Changes to rules require a new "Refresh Data" for existing batches.'
            ]
        },

        prepare: {
            title: 'Step 1 — Create Batch',
            icon: 'fas fa-plus-circle',
            intro: 'Create a new migration batch by selecting plants and loading DMS objects from the source system.',
            sections: [
                {
                    title: '1. Select Plants',
                    content: 'Select the plants (sites) whose documents should be migrated. The plant list is loaded from the DIL database on first access and cached locally.'
                },
                {
                    title: '2. Load DMS Objects',
                    content: 'Click <b>"Load DMS Objects"</b>. The system queries 11 object types:\n\n• <b>EQUI</b> — Equipment\n• <b>IFLOT</b> — Functional Location\n• <b>MPLA</b> — Maintenance Plan\n• <b>PMPLKO</b> — Planning Object\n• <b>PMAUFK</b> — Maintenance Order\n• <b>PMAFVC</b> — Order Operation\n• <b>PMQMEL</b> — PM Notification\n• <b>SMQMEL</b> — SM Notification\n• <b>STKO_DOC</b> / <b>STPO_DOC</b> — Bills of Material\n• <b>IMPTT</b> — Measurement Points\n\n<b>Automatic exclusions</b> via JEST status:\n• Deleted Equipments/Functional Locations (I0320, I0013, I0076)\n• TECO/Closed Orders (I0045, I0046)\n• Closed Notifications (I0072)\n• Deletion flags on plans and BOMs'
                },
                {
                    title: '3. Exclusion Template (optional)',
                    content: 'Download an <b>Excel template</b>, enter OBJKY values that should be excluded, and upload it back. This allows you to specifically exclude certain equipments or orders from the migration.'
                },
                {
                    title: '4. Batch Metadata',
                    content: '• <b>Wave</b> (required): Which migration wave does the batch belong to?\n• <b>Description</b> (max 40 chars): Short description\n• <b>Notes</b>: Additional information\n• <b>DOKOB Filter</b>: Optionally include only specific object types in the batch'
                },
                {
                    title: '5. Create Batch',
                    content: 'Click <b>"Create Batch"</b>. The system:\n• Reads the local DMS objects\n• Applies filters and exclusions\n• Creates the batch (ID: DMS_YYYYMMDD_HHMMSS)\n• Generates target document numbers (internal: automatic, external: retained)\n\nYou will then be redirected to the preview.'
                },
                {
                    title: 'Alternative: Upload DMS Key List',
                    content: 'Instead of selecting plants, you can upload a ready-made list of DMS keys in the <b>"DMS Key List"</b> tab (Excel/CSV):\n\n• Download the <b>template</b> via "Download Template" — required columns: <b>Documenttype, Documentversion, Documentpart, Documentnumber</b>\n• Key format: <b>Type / Version / Part / Document number</b> (internal or external)\n• Choose the file and click <b>"Load & check keys"</b>\n• The object links are then automatically determined in DRAD — like with "DMS Objects"\n• After the check, create the batch as usual'
                }
            ],
            warnings: [
                'DMS objects are stored locally. Re-selecting the same plants will overwrite the data.',
                'Internal number ranges (IY1, IY2) automatically get new numbers in the target system.',
                'Make sure the correct source system is selected in the navbar!'
            ]
        },

        preview: {
            title: 'Step 2 — Preview & Migration',
            icon: 'fas fa-search',
            intro: 'Review the batch, refresh metadata and run the migration.',
            sections: [
                {
                    title: '1. Review Batch Statistics',
                    content: 'At the top you see:\n• <b>Total count</b> of records (with ✓ successes)\n• <b>Excluded / KPRO / DB</b> — origin & storage\n• <b>Total size</b> and a warning for <b>large files (>99MB)</b>\n• <b>Pacing</b> — current delay setting\n• <b>Status distribution</b> in the filter: Pending, Success, Failed, Partial'
                },
                {
                    title: '⭐ 2. Run "Refresh Data"',
                    content: '<b>This is the most important step!</b> Click the "Refresh Data" button. The system runs through 5 phases:\n\n<b>Phase 1/4</b>: LOIO Lookup — Load file references from the Content Repository\n<b>Phase 2/4</b>: File Sizes — Determine actual file sizes\n<b>Phase 3/4</b>: File Names + Descriptions — from DRAW/DRAT (English preferred, then German)\n<b>Phase 4/4</b>: Apply Migration Rules — Execute translation/overwrite rules\n<b>Phase 5/5</b>: Link Count — Count source/target links',
                    highlight: true
                },
                {
                    title: '3. Browse Records',
                    content: 'The table shows all records (5000 per page). Use the filters:\n• <b>Status filter</b>: Pending, Success, Failed, Partial\n• <b>Error category</b>: Type of error\n• <b>Storage</b>: KPRO or DB\n• <b>Full-text search</b>: Across all fields'
                },
                {
                    title: '4. Skip Records',
                    content: 'Individual records can be excluded from migration using the <b>"Skip"</b> function. Provide a reason. Skipped records will be ignored during execution.'
                },
                {
                    title: '5. Start Migration',
                    content: 'Click <b>"Start Migration"</b>. For each record:\n1. A document container is created in the target system\n2. The file(s) are downloaded from the source system\n3. The file(s) are uploaded to the target system\n\nProgress is updated live. You can <b>cancel</b> the migration at any time.'
                },
                {
                    title: '6. Reset Failed',
                    content: 'After execution you can <b>reset failed records</b> and retry them. Records with status "Partial" (container created, files partially uploaded) will only transfer the missing files on retry.'
                }
            ],
            warnings: [
                '⚠️ IMPORTANT: "Refresh Data" MUST be done before execution! Without it, LOIO IDs, file sizes and file names are missing.',
                'Make sure you are logged in and the token is valid.',
                'Large batches (>10,000 documents) can take several hours. The session is automatically kept alive.'
            ]
        },

        mapping: {
            title: 'Step 3 — Object Mapping & Linking',
            icon: 'fas fa-project-diagram',
            intro: 'Map source business objects to target business objects and create the links in the target system.',
            sections: [
                {
                    title: '1. Manage Mappings',
                    content: 'Each source system object must be mapped to a target system object.\n\nThe mapping consists of:\n• <b>Source DOKOB</b> + <b>Source OBJKY</b> → <b>Target DOKOB</b> + <b>Target OBJKY</b>\n\n<b>Important — SAP Key Format:</b>\nOBJKY values must use the SAP internal format:\n• <b>EQUI</b>: 18-digit, leading zeros (e.g. <code>000000000010045127</code>)\n• <b>IFLOT</b> (Func. Location): SAP internal key, NOT the display format (e.g. <code>CB-L525-SIT-01</code> not <code>CB-L525/SIT/01</code>)\n• <b>PMAUFK</b>: 12-digit, leading zeros (e.g. <code>000004001234</code>)\n• <b>MPLA</b>: Maintenance plan number + position\n• <b>STPO_DOC/STKO_DOC</b>: BOM number\n\nIn many cases DOKOB and OBJKY stay the same (e.g. Equipment keeps its number). For site renames (e.g. CB → SIT) the target OBJKY must be adjusted accordingly.'
                },
                {
                    title: '2. Excel Mapping Template',
                    content: '<b>Recommended approach:</b>\n1. Click <b>"Download Template"</b>\n2. The Excel file contains worksheets:\n   • <b>Mappings</b>: Existing mappings\n   • <b>Batch Objects</b>: All source objects of the batch\n   • <b>Unmapped</b>: Objects without mapping\n   • <b>Info</b>: Explanations\n3. Fill in the target columns\n4. Upload the file via <b>"Upload Template"</b>\n\n⚠️ <b>OBJKY format</b>: Always use the SAP internal key format (see above).'
                },
                {
                    title: '3. Apply Mappings',
                    content: 'Click <b>"Apply Mappings"</b> to transfer the mappings to the staging records. This sets target_dokob and target_objky in the records.'
                },
                {
                    title: '4. Start Linking',
                    content: 'After successful upload (Step 2) click <b>"Link Mappings"</b>:\n• Records without a matching mapping are automatically <b>skipped</b> (no API call)\n• Records with mapping are linked in the target system\n• Progress is updated live\n\n<b>Link status per record:</b>\n• <b>linked</b> — Successfully linked\n• <b>link_exists</b> — Link already existed\n• <b>link_failed</b> — Linking error\n• <b>link_skipped</b> — No mapping found, skipped\n\n<b>Progress display:</b>\nProgress shows <b>Linked / Total</b>, where "Total" includes skipped records. This shows real progress (e.g. 64% = only IFLOT mapped, EQUI still missing).'
                }
            ],
            warnings: [
                'Linking can only be performed for records with status "success" and a created container.',
                'Without object mappings, records are automatically skipped (link_skipped).',
                'Check the "Unmapped" list in the Excel template — unmapped objects will not be linked.',
                'OBJKY must be in SAP internal format, not the display format!'
            ]
        },

        details: {
            title: 'Step 4 — Validation & Review',
            icon: 'fas fa-check-double',
            intro: 'Review files, object links and errors. Compare source and target data with color highlighting.',
            sections: [
                {
                    title: 'KPI Cards & Progress',
                    content: 'At the top you see 6 metrics:\n• <b>Total</b> — All records in the batch\n• <b>Linked</b> (green) — Successfully linked records\n• <b>Failed</b> (red) — Failed linkings\n• <b>Pending</b> (yellow) — Not yet linked records\n• <b>Skipped</b> (gray) — No mapping available\n• <b>Coverage</b> (blue) — Percentage of linked records\n\nBelow that, two progress bars for Upload and Linking.'
                },
                {
                    title: 'Tab 1: Files',
                    content: 'Compares source and target data per file with 12 columns:\n\n<b>Columns:</b>\n• Source Doc / Source Type,Ver.,Part\n• Target Doc / Target Type,Ver.,Part\n• <b>Source Description</b> — Original from DIL/DRAT (SAP source)\n• <b>Target Description</b> — What was sent to the target system\n• <b>Source Filename</b> — Original filename (from DRAW)\n• <b>Target Filename</b> — Uploaded filename\n• Type, Size, Status, Error\n\n<b>Color highlighting:</b>\n• <span style="background:#fff3cd;padding:2px 6px">Yellow</span> = Source and target values differ\n\n<b>Filter buttons:</b>\n• <b>All</b> — All files\n• <b>Success</b> — Only successful uploads\n• <b>Errors</b> — Only failed\n• <b>Description ≠</b> — Only rows with different description\n• <b>Filename ≠</b> — Only rows with different filename\n• <b>All diffs</b> — Rows with any difference'
                },
                {
                    title: 'Tab 2: Object Links',
                    content: 'Shows the resolved object links per record. Each source link (from source_object_links) is displayed as a separate row.\n\n<b>Columns:</b>\n• Source/Target document number + Type/Ver./Part\n• Source DOKOB → Target DOKOB (color-coded)\n• Source OBJKY → Target OBJKY (color-coded)\n• Link Status, Error\n\n<b>Colors:</b>\n• <span style="background:#d4edda;padding:2px 6px">Green</span> = Source=Target (identical)\n• <span style="background:#fff3cd;padding:2px 6px">Yellow</span> = Mapping exists, value changed\n• <span style="background:#f8d7da;padding:2px 6px">Red</span> = No target value (not mapped)\n\n<b>Filters:</b> All, Linked, Failed, Pending, Skipped'
                },
                {
                    title: 'Tab 3: Error Analysis',
                    content: 'Contains four analysis tables:\n• <b>DAPPL/Extension Analysis</b> (loadable via button)\n• <b>DOKOB Mapping Coverage</b> — Shows per object type how many are mapped/unmapped\n• <b>Link Errors</b> — Error patterns with frequency\n• <b>Upload Errors</b> — Error patterns with frequency'
                },
                {
                    title: 'Excel Export',
                    content: 'Click <b>"Export"</b> to download all file details as a formatted Excel file:\n• Same 12 columns as the web view\n• Color highlighting for differences (yellow)\n• Green/Red for status\n• Autofilter, frozen header row, auto-width columns'
                }
            ]
        }
    };

    // ── Language Helper ──────────────────────────────────────────────
    function getHelpContent() {
        return (typeof I18n !== 'undefined' && I18n.getLang() === 'en') ? HELP_CONTENT_EN : HELP_CONTENT_DE;
    }

    // ── Page Detection ───────────────────────────────────────────────
    function detectCurrentPage() {
        const path = window.location.pathname;
        const search = window.location.search;

        if (path === '/' || path === '/index')               return 'dashboard';
        if (path === '/settings')                             return 'settings';
        if (path === '/rules')                                return 'rules';
        if (path === '/prepare')                              return 'prepare';
        if (path.includes('/preview') || (path === '/preview' && search.includes('batch_id')))
                                                              return 'preview';
        if (path.includes('/object-mapping'))                 return 'mapping';
        if (path.includes('/details') || path === '/details') return 'details';
        if (path.includes('/validation'))                     return 'details';

        return 'dashboard'; // fallback
    }

    // ── Build HTML ───────────────────────────────────────────────────
    function buildHelpPanel() {
        const currentPage = detectCurrentPage();
        const hc = getHelpContent();
        const isEn = typeof I18n !== 'undefined' && I18n.getLang() === 'en';
        const pageHelp = hc[currentPage];
        const workflow = hc.workflow;
        const glossary = hc.glossary;

        let html = '';

        // Header
        html += `
            <div class="help-panel-header">
                <div class="d-flex align-items-center justify-content-between">
                    <h5 class="mb-0"><i class="fas fa-question-circle"></i> ${isEn ? 'Help' : 'Hilfe'}</h5>
                    <button class="btn btn-sm btn-outline-light" onclick="ContextualHelp.close()" title="${isEn ? 'Close' : 'Schließen'}">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
        `;

        // Tab navigation
        html += `
            <div class="help-tabs">
                <button class="help-tab active" data-tab="page"><i class="${pageHelp.icon}"></i> ${isEn ? 'This Page' : 'Diese Seite'}</button>
                <button class="help-tab" data-tab="workflow"><i class="${workflow.icon}"></i> Workflow</button>
                <button class="help-tab" data-tab="glossary"><i class="${glossary.icon}"></i> ${isEn ? 'Glossary' : 'Glossar'}</button>
            </div>
        `;

        // ── Tab: Current Page ────────────────────────────────────────
        html += `<div class="help-tab-content" data-tab="page">`;
        html += `<div class="help-section-title"><i class="${pageHelp.icon}"></i> ${pageHelp.title}</div>`;
        if (pageHelp.intro) {
            html += `<div class="help-intro">${pageHelp.intro}</div>`;
        }

        if (pageHelp.sections) {
            pageHelp.sections.forEach((section, idx) => {
                const highlightClass = section.highlight ? ' help-highlight' : '';
                html += `
                    <div class="help-accordion${highlightClass}">
                        <button class="help-accordion-btn" data-idx="${idx}">
                            <span>${section.title}</span>
                            <i class="fas fa-chevron-down"></i>
                        </button>
                        <div class="help-accordion-body" data-idx="${idx}">
                            <div class="help-accordion-inner">${formatContent(section.content)}</div>
                        </div>
                    </div>
                `;
            });
        }

        if (pageHelp.warnings && pageHelp.warnings.length > 0) {
            html += `<div class="help-warnings-title"><i class="fas fa-exclamation-triangle"></i> ${isEn ? 'Important Notes' : 'Wichtige Hinweise'}</div>`;
            pageHelp.warnings.forEach(w => {
                html += `<div class="help-warning">${w}</div>`;
            });
        }
        html += `</div>`;

        // ── Tab: Workflow ────────────────────────────────────────────
        html += `<div class="help-tab-content" data-tab="workflow" style="display:none;">`;
        html += `<div class="help-section-title"><i class="${workflow.icon}"></i> ${workflow.title}</div>`;
        html += `<div class="help-intro">${isEn ? 'The migration process follows these steps:' : 'Der Migrationsprozess folgt diesen Schritten:'}</div>`;
        html += `<div class="help-workflow-steps">`;
        workflow.steps.forEach(step => {
            const isActive = step.page === currentPage;
            html += `
                <div class="help-workflow-step${isActive ? ' active' : ''}">
                    <div class="help-step-num">${step.num}</div>
                    <div class="help-step-body">
                        <div class="help-step-label">${step.label}</div>
                        <div class="help-step-desc">${step.desc}</div>
                    </div>
                </div>
            `;
        });
        html += `</div></div>`;

        // ── Tab: Glossary ────────────────────────────────────────────
        html += `<div class="help-tab-content" data-tab="glossary" style="display:none;">`;
        html += `<div class="help-section-title"><i class="${glossary.icon}"></i> ${glossary.title}</div>`;
        html += `<div class="help-glossary">`;
        glossary.items.forEach(item => {
            html += `
                <div class="help-glossary-item">
                    <span class="help-glossary-term">${item.term}</span>
                    <span class="help-glossary-desc">${item.desc}</span>
                </div>
            `;
        });
        html += `</div></div>`;

        return html;
    }

    function formatContent(text) {
        // Convert \n to <br> and preserve basic formatting
        return text.replace(/\n/g, '<br>');
    }

    // ── Create & Inject DOM Elements ─────────────────────────────────
    function createHelpElements() {
        // Floating help button
        const btn = document.createElement('button');
        btn.id = 'helpFloatingBtn';
        btn.className = 'help-floating-btn';
        btn.innerHTML = '<i class="fas fa-question"></i>';
        btn.title = (typeof I18n !== 'undefined' && I18n.getLang() === 'en') ? 'Show help (H)' : 'Hilfe anzeigen (H)';
        btn.onclick = function() { ContextualHelp.toggle(); };
        document.body.appendChild(btn);

        // Help panel overlay
        const overlay = document.createElement('div');
        overlay.id = 'helpOverlay';
        overlay.className = 'help-overlay';
        overlay.onclick = function() { ContextualHelp.close(); };
        document.body.appendChild(overlay);

        // Help panel
        const panel = document.createElement('div');
        panel.id = 'helpPanel';
        panel.className = 'help-panel';
        panel.innerHTML = buildHelpPanel();
        document.body.appendChild(panel);

        // Attach event listeners
        attachTabListeners();
        attachAccordionListeners();
    }

    function attachTabListeners() {
        document.querySelectorAll('.help-tab').forEach(tab => {
            tab.addEventListener('click', function() {
                const targetTab = this.getAttribute('data-tab');
                document.querySelectorAll('.help-tab').forEach(t => t.classList.remove('active'));
                this.classList.add('active');
                document.querySelectorAll('.help-tab-content').forEach(tc => {
                    tc.style.display = tc.getAttribute('data-tab') === targetTab ? 'block' : 'none';
                });
            });
        });
    }

    function attachAccordionListeners() {
        document.querySelectorAll('.help-accordion-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const idx = this.getAttribute('data-idx');
                const body = document.querySelector(`.help-accordion-body[data-idx="${idx}"]`);
                const isOpen = body.classList.contains('open');

                // Close all
                document.querySelectorAll('.help-accordion-body').forEach(b => b.classList.remove('open'));
                document.querySelectorAll('.help-accordion-btn').forEach(b => b.classList.remove('open'));

                // Toggle current
                if (!isOpen) {
                    body.classList.add('open');
                    this.classList.add('open');
                }
            });
        });
    }

    // ── Inject Styles ────────────────────────────────────────────────
    function injectStyles() {
        const style = document.createElement('style');
        style.textContent = `
            /* ── Floating Help Button ─────────────────────────────── */
            .help-floating-btn {
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 10000;
                width: 48px;
                height: 48px;
                border-radius: 50%;
                background: linear-gradient(135deg, #004a96, #0066cc);
                color: #fff;
                border: none;
                box-shadow: 0 4px 12px rgba(0,74,150,0.4);
                font-size: 20px;
                cursor: pointer;
                transition: all 0.25s ease;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .help-floating-btn:hover {
                transform: scale(1.1);
                box-shadow: 0 6px 20px rgba(0,74,150,0.5);
            }
            .help-floating-btn.active {
                background: linear-gradient(135deg, #cc3300, #ff4444);
                transform: rotate(45deg);
            }

            /* ── Overlay ──────────────────────────────────────────── */
            .help-overlay {
                position: fixed;
                top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.3);
                z-index: 10001;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.3s ease;
            }
            .help-overlay.open {
                opacity: 1;
                pointer-events: auto;
            }

            /* ── Help Panel ───────────────────────────────────────── */
            .help-panel {
                position: fixed;
                top: 0;
                right: -420px;
                width: 400px;
                max-width: 90vw;
                height: 100vh;
                z-index: 10002;
                background: #fff;
                box-shadow: -4px 0 20px rgba(0,0,0,0.15);
                transition: right 0.35s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }
            .help-panel.open {
                right: 0;
            }

            /* ── Panel Header ─────────────────────────────────────── */
            .help-panel-header {
                background: linear-gradient(135deg, #004a96, #0066cc);
                color: #fff;
                padding: 16px 20px;
                flex-shrink: 0;
            }
            .help-panel-header h5 {
                font-size: 16px;
                font-weight: 600;
            }
            .help-panel-header .btn-outline-light {
                border-color: rgba(255,255,255,0.5);
                color: #fff;
                padding: 2px 8px;
            }
            .help-panel-header .btn-outline-light:hover {
                background: rgba(255,255,255,0.2);
            }

            /* ── Tabs ─────────────────────────────────────────────── */
            .help-tabs {
                display: flex;
                border-bottom: 2px solid #e9ecef;
                flex-shrink: 0;
                background: #f8f9fa;
            }
            .help-tab {
                flex: 1;
                padding: 10px 8px;
                border: none;
                background: none;
                cursor: pointer;
                font-size: 12px;
                font-weight: 500;
                color: #6c757d;
                transition: all 0.2s;
                border-bottom: 3px solid transparent;
                white-space: nowrap;
            }
            .help-tab:hover {
                color: #004a96;
                background: #e9ecef;
            }
            .help-tab.active {
                color: #004a96;
                border-bottom-color: #004a96;
                font-weight: 600;
            }
            .help-tab i {
                margin-right: 4px;
            }

            /* ── Tab Content ──────────────────────────────────────── */
            .help-tab-content {
                flex: 1;
                overflow-y: auto;
                padding: 16px 20px;
            }

            /* ── Section Elements ─────────────────────────────────── */
            .help-section-title {
                font-size: 15px;
                font-weight: 700;
                color: #004a96;
                margin-bottom: 8px;
                padding-bottom: 6px;
                border-bottom: 1px solid #e9ecef;
            }
            .help-intro {
                font-size: 13px;
                color: #495057;
                margin-bottom: 16px;
                line-height: 1.5;
                padding: 10px 12px;
                background: #f0f6ff;
                border-radius: 6px;
                border-left: 3px solid #004a96;
            }

            /* ── Accordion ────────────────────────────────────────── */
            .help-accordion {
                margin-bottom: 6px;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                overflow: hidden;
            }
            .help-accordion.help-highlight {
                border-color: #ffc107;
                box-shadow: 0 0 0 1px #ffc107;
            }
            .help-accordion-btn {
                width: 100%;
                padding: 10px 14px;
                border: none;
                background: #f8f9fa;
                text-align: left;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 13px;
                font-weight: 600;
                color: #343a40;
                transition: background 0.2s;
            }
            .help-accordion.help-highlight .help-accordion-btn {
                background: #fff8e1;
            }
            .help-accordion-btn:hover {
                background: #e9ecef;
            }
            .help-accordion-btn i {
                transition: transform 0.25s;
                font-size: 11px;
                color: #6c757d;
            }
            .help-accordion-btn.open i {
                transform: rotate(180deg);
            }
            .help-accordion-body {
                max-height: 0;
                overflow: hidden;
                transition: max-height 0.35s ease;
            }
            .help-accordion-body.open {
                max-height: 600px;
            }
            .help-accordion-inner {
                padding: 10px 14px;
                font-size: 12.5px;
                color: #495057;
                line-height: 1.6;
                background: #fff;
            }

            /* ── Warnings ─────────────────────────────────────────── */
            .help-warnings-title {
                font-size: 13px;
                font-weight: 700;
                color: #856404;
                margin-top: 16px;
                margin-bottom: 8px;
            }
            .help-warning {
                font-size: 12px;
                color: #856404;
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 5px;
                padding: 8px 12px;
                margin-bottom: 6px;
                line-height: 1.5;
            }

            /* ── Workflow Steps ────────────────────────────────────── */
            .help-workflow-steps {
                padding-left: 0;
            }
            .help-workflow-step {
                display: flex;
                gap: 12px;
                padding: 10px 0;
                border-bottom: 1px solid #f0f0f0;
                align-items: flex-start;
            }
            .help-workflow-step:last-child {
                border-bottom: none;
            }
            .help-workflow-step.active {
                background: #f0f6ff;
                margin: 0 -20px;
                padding: 10px 20px;
                border-radius: 0;
            }
            .help-step-num {
                flex-shrink: 0;
                width: 28px;
                height: 28px;
                border-radius: 50%;
                background: #e9ecef;
                color: #495057;
                font-size: 11px;
                font-weight: 700;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .help-workflow-step.active .help-step-num {
                background: #004a96;
                color: #fff;
            }
            .help-step-label {
                font-size: 13px;
                font-weight: 600;
                color: #343a40;
            }
            .help-workflow-step.active .help-step-label {
                color: #004a96;
            }
            .help-step-desc {
                font-size: 12px;
                color: #6c757d;
                margin-top: 2px;
                line-height: 1.4;
            }

            /* ── Glossary ─────────────────────────────────────────── */
            .help-glossary-item {
                padding: 8px 0;
                border-bottom: 1px solid #f0f0f0;
                display: flex;
                flex-wrap: wrap;
                gap: 4px;
            }
            .help-glossary-item:last-child {
                border-bottom: none;
            }
            .help-glossary-term {
                font-weight: 700;
                font-size: 13px;
                color: #004a96;
                font-family: 'Consolas', 'Monaco', monospace;
                background: #f0f6ff;
                padding: 1px 6px;
                border-radius: 3px;
                flex-shrink: 0;
            }
            .help-glossary-desc {
                font-size: 12.5px;
                color: #495057;
                line-height: 1.5;
            }

            /* ── Keyboard shortcut hint ───────────────────────────── */
            .help-floating-btn::after {
                content: 'H';
                position: absolute;
                bottom: -4px;
                right: -4px;
                width: 18px;
                height: 18px;
                border-radius: 3px;
                background: #343a40;
                color: #fff;
                font-size: 9px;
                font-weight: 700;
                display: flex;
                align-items: center;
                justify-content: center;
                box-shadow: 0 1px 3px rgba(0,0,0,0.3);
            }

            /* ── Scrollbar ────────────────────────────────────────── */
            .help-tab-content::-webkit-scrollbar {
                width: 6px;
            }
            .help-tab-content::-webkit-scrollbar-track {
                background: #f0f0f0;
            }
            .help-tab-content::-webkit-scrollbar-thumb {
                background: #c0c0c0;
                border-radius: 3px;
            }
            .help-tab-content::-webkit-scrollbar-thumb:hover {
                background: #a0a0a0;
            }

            /* ── Print: hide help ─────────────────────────────────── */
            @media print {
                .help-floating-btn, .help-panel, .help-overlay { display: none !important; }
            }
        `;
        document.head.appendChild(style);
    }

    // ── Public API ───────────────────────────────────────────────────
    window.ContextualHelp = {
        open: function() {
            document.getElementById('helpPanel').classList.add('open');
            document.getElementById('helpOverlay').classList.add('open');
            document.getElementById('helpFloatingBtn').classList.add('active');
        },
        close: function() {
            document.getElementById('helpPanel').classList.remove('open');
            document.getElementById('helpOverlay').classList.remove('open');
            document.getElementById('helpFloatingBtn').classList.remove('active');
        },
        toggle: function() {
            const panel = document.getElementById('helpPanel');
            if (panel.classList.contains('open')) {
                this.close();
            } else {
                this.open();
            }
        }
    };

    // ── Keyboard shortcut: H key ─────────────────────────────────────
    document.addEventListener('keydown', function(e) {
        // Don't trigger when typing in inputs/textareas
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT' || e.target.isContentEditable) return;
        if (e.key === 'h' || e.key === 'H') {
            if (!e.ctrlKey && !e.altKey && !e.metaKey) {
                e.preventDefault();
                ContextualHelp.toggle();
            }
        }
        if (e.key === 'Escape') {
            ContextualHelp.close();
        }
    });

    // ── Init on DOM ready ────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        injectStyles();
        createHelpElements();
    }

    // ── Language Change Listener ─────────────────────────────────────
    document.addEventListener('languageChanged', () => {
        // Rebuild the help panel with new language content
        const panel = document.getElementById('helpPanel');
        if (panel) {
            panel.innerHTML = buildHelpPanel();
            attachTabListeners();
            attachAccordionListeners();
        }
        // Update floating button tooltip
        const btn = document.getElementById('helpFloatingBtn');
        if (btn) {
            const isEn = typeof I18n !== 'undefined' && I18n.getLang() === 'en';
            btn.title = isEn ? 'Show help (H)' : 'Hilfe anzeigen (H)';
        }
    });

})();
