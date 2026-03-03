/**
 * Contextual In-App Help System for DMS Migration Tool
 * Provides page-aware step-by-step guidance via a slide-in panel.
 */
(function() {
    'use strict';

    // ── Help Content Database ────────────────────────────────────────
    const HELP_CONTENT = {

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
                { num: '2',  label: 'Vorschau & Daten aktualisieren',page: 'preview',     desc: 'Batch prüfen, Daten aktualisieren (LOIO, Dateigröße, Regeln anwenden), Datensätze überspringen' },
                { num: '3a', label: 'Migration ausführen',           page: 'preview',     desc: 'Dokumente ins Zielsystem hochladen — Container erstellen und Dateien übertragen' },
                { num: '3b', label: 'Objekt-Zuordnung & Verlinkung', page: 'mapping',     desc: 'Quell-Objekte auf Ziel-Objekte mappen, dann Verlinkung im Zielsystem erstellen' },
                { num: '4',  label: 'Auswertung',                    page: 'details',     desc: 'Ergebnisse analysieren, Fehler untersuchen, fehlgeschlagene Datensätze erneut versuchen' },
            ]
        },

        // ── Page-Specific Help ───────────────────────────────────────

        dashboard: {
            title: 'Dashboard — Batch-Übersicht',
            icon: 'fas fa-tachometer-alt',
            intro: 'Das Dashboard zeigt alle Migrationsbatches als Kanban-Board, gruppiert nach Wellen. Hier starten Sie neue Batches und verfolgen den Fortschritt.',
            sections: [
                {
                    title: 'KPI-Karten',
                    content: 'Am oberen Rand sehen Sie Gesamtstatistiken: Anzahl Dokumente, Erfolgsrate und Datenvolumen über alle Batches hinweg.'
                },
                {
                    title: 'Kanban-Board',
                    content: 'Jeder Batch erscheint als Karte in der Spalte seiner Wave. Die farbige Markierung zeigt die aktuelle Phase:\n• <b>Grau</b> = Vorbereitung\n• <b>Blau</b> = Upload läuft\n• <b>Grün</b> = Upload fertig\n• <b>Orange</b> = Verlinkung\n• <b>Dunkelgrün</b> = Abgeschlossen'
                },
                {
                    title: 'Batch-Karte — Aufbau im Detail',
                    content: '<b>Jede Batch-Karte besteht aus 5 Bereichen:</b>\n\n<b>① Kopfzeile</b>\nLinks: Batch-Beschreibung + Dokumentenanzahl\nRechts: Status-Badge (farbig)\n\n<b>② Upload-Fortschrittsbalken</b>\n<span style="color:#28a745">■</span> <b>Grün</b> = Erfolgreich hochgeladen\n<span style="color:#dc3545">■</span> <b>Rot</b> = Fehlgeschlagen\nAnzeige: ↑ Erfolg/Gesamt + Prozent\n\n<b>③ Link-Fortschrittsbalken</b> (nur wenn Verlinkung gestartet)\n<span style="color:#17a2b8">■</span> <b>Cyan</b> = Erfolgreich verlinkt\n<span style="color:#dc3545">■</span> <b>Rot</b> = Link-Fehler\nAnzeige: 🔗 Verlinkt/Gesamt + Prozent\n\n<b>④ Phase-Fortschritt</b> (3 kleine Balken)\nDie drei Balken zeigen: <b>Vorbereitung → Upload → Verlinkung</b>\n<span style="color:#28a745">■</span> Grün = Abgeschlossen\n<span style="color:#007bff">■</span> Blau (pulsierend) = Aktiv/läuft\n<span style="color:#e9ecef">■</span> Grau = Ausstehend\n<span style="color:#dc3545">■</span> Rot = Fehler\n\n<b>⑤ Farbiger Rand links</b>\nDer seitliche Farbbalken zeigt die aktuelle Phase:\n• <span style="color:#6c757d">■</span> <b>Grau</b> — Vorbereitet\n• <span style="color:#007bff">■</span> <b>Blau</b> — Upload aktiv\n• <span style="color:#28a745">■</span> <b>Grün</b> — Upload fertig\n• <span style="color:#17a2b8">■</span> <b>Cyan</b> — Verlinkung läuft\n• <span style="color:#28a745">■</span> <b>Dunkelgrün</b> — Abgeschlossen\n• <span style="color:#dc3545">■</span> <b>Rot</b> — Fehler'
                },
                {
                    title: 'Status-Badges (Farben & Bedeutung)',
                    content: 'Das Badge oben rechts auf jeder Karte zeigt den genauen Status:\n\n<span class="badge badge-secondary">Vorbereitet</span> — Batch erstellt, noch nicht gestartet\n<span class="badge badge-warning">Upload...</span> — Upload läuft gerade\n<span class="badge badge-success">Hochgeladen</span> — Alle Dokumente erfolgreich hochgeladen\n<span class="badge badge-warning">Upload (Fehler)</span> — Upload fertig, aber mit Fehlern\n<span class="badge badge-danger">Fehlgeschlagen</span> — Upload fehlgeschlagen\n<span class="badge badge-info">Verlinke...</span> — Verlinkung läuft\n<span class="badge badge-success">Fertig</span> — Alles erledigt ✓\n<span class="badge badge-warning">Verlinkt (Fehler)</span> — Verlinkung mit Fehlern\n<span class="badge badge-danger">Link-Fehler</span> — Verlinkungsfehler\n<span class="badge badge-secondary">Abgebrochen</span> — Verlinkung abgebrochen'
                },
                {
                    title: 'Neuen Batch erstellen',
                    content: 'Klicken Sie auf <b>„+ Neuer Batch"</b> um zur Batch-Erstellung zu gelangen. Dort wählen Sie Werke und laden DMS-Objekte aus der Quelldatenbank.'
                },
                {
                    title: 'Batch öffnen',
                    content: 'Klicken Sie auf eine Batch-Karte, um die <b>Vorschau</b> zu öffnen. Dort können Sie den Batch prüfen und die Migration starten.'
                },
                {
                    title: 'Wellenverwaltung',
                    content: 'Über <b>„Wellenverwaltung"</b> in der Navbar können Sie Wave-Pläne erstellen und zeitlich planen (Qual-Load, Qual-Link, Prod-Load, Prod-Link Phasen).'
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
                    title: 'SAP-Systeme verwalten',
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
            intro: 'Regeln transformieren Dokumentfelder automatisch während „Daten aktualisieren" (Phase 4/4). Sie werden in der festgelegten Reihenfolge auf jeden Datensatz angewandt.',
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
                    title: 'Bedingungen (Conditions)',
                    content: 'Jede Regel kann eine optionale Bedingung haben:\n• <b>enthält</b> (contains)\n• <b>gleich</b> (equals)\n• <b>beginnt mit</b> (starts_with)\n\nDie Bedingung prüft ein frei wählbares Feld und Wert.'
                },
                {
                    title: 'Reihenfolge',
                    content: 'Regeln werden in der angezeigten Reihenfolge ausgeführt (niedrigere Nummer = zuerst). Nutzen Sie die Pfeil-Buttons zum Umsortieren.\n\n⚠️ Die Reihenfolge ist wichtig, wenn mehrere Regeln das gleiche Feld betreffen!'
                }
            ],
            warnings: [
                'Regeln werden nur beim „Daten aktualisieren" in der Vorschau angewandt — nicht beim Batch-Erstellen.',
                'Änderungen an Regeln erfordern ein erneutes „Daten aktualisieren" für bestehende Batches.'
            ]
        },

        prepare: {
            title: 'Schritt 1 — Batch erstellen',
            icon: 'fas fa-plus-circle',
            intro: 'Erstellen Sie einen neuen Migrationsbach, indem Sie Werke auswählen und DMS-Objekte aus dem Quellsystem laden.',
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
                    content: 'Oben sehen Sie:\n• <b>Gesamtanzahl</b> Datensätze\n• <b>Dateigrößen-Verteilung</b> (Mini/Klein/Mittel/Groß)\n• <b>Ablage-Typ</b>: KPRO (Content Repository) vs. DB (Datenbank)\n• <b>Status-Verteilung</b>: Pending, Success, Failed, Partial'
                },
                {
                    title: '⭐ 2. „Daten aktualisieren" ausführen',
                    content: '<b>Das ist der wichtigste Schritt!</b> Klicken Sie den Button „Daten aktualisieren" / „Refresh". Das System durchläuft 5 Phasen:\n\n<b>Phase 1/4</b>: LOIO-Lookup — Dateireferenzen aus dem Content Repository laden\n<b>Phase 2/4</b>: Dateigrößen — Tatsächliche Dateigrößen ermitteln\n<b>Phase 3/4</b>: Dateinamen + Beschreibungen — aus DRAW/DRAT (Englisch bevorzugt, dann Deutsch)\n<b>Phase 4/4</b>: Migrationsregeln anwenden — Übersetzungs-/Überschreibungsregeln ausführen\n<b>Phase 5/5</b>: Linkzählung — Quell-/Ziel-Verknüpfungen zählen',
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
                '⚠️ WICHTIG: „Daten aktualisieren" MUSS vor der Ausführung gemacht werden! Ohne dies fehlen LOIO-IDs, Dateigrößen und Dateinamen.',
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
                    content: 'Jedes Quellsystem-Objekt (z.B. Equipmentnummer im R/3) muss einem Zielsystem-Objekt (z.B. Equipmentnummer im S/4) zugeordnet werden.\n\nDie Zuordnung besteht aus:\n• <b>Quell-DOKOB</b> + <b>Quell-OBJKY</b> → <b>Ziel-DOKOB</b> + <b>Ziel-OBJKY</b>\n\n In vielen Fällen bleiben DOKOB und OBJKY gleich (z.B. Equipment behält seine Nummer).'
                },
                {
                    title: '2. Excel-Mapping-Template',
                    content: '<b>Empfohlener Weg:</b>\n1. Klicken Sie <b>„Template herunterladen"</b>\n2. Die Excel-Datei enthält Tabellenblätter:\n   • <b>Mappings</b>: Bestehende Zuordnungen\n   • <b>Batch Objects</b>: Alle Quell-Objekte des Batches\n   • <b>Unmapped</b>: Objekte ohne Zuordnung\n   • <b>Info</b>: Erklärungen\n3. Füllen Sie die Ziel-Spalten aus\n4. Laden Sie die Datei über <b>„Template hochladen"</b> wieder hoch'
                },
                {
                    title: '3. Zuordnungen anwenden',
                    content: 'Klicken Sie <b>„Zuordnungen anwenden"</b> um die Mappings auf die Staging-Datensätze zu übertragen. Dadurch werden target_dokob und target_objky in den Datensätzen gesetzt.'
                },
                {
                    title: '4. Verlinkung starten',
                    content: 'Nach erfolgreichem Upload (Schritt 2) klicken Sie <b>„Verlinkung starten"</b>:\n• Das System erstellt Objekt-Verknüpfungen im Zielsystem\n• Jedes Dokument wird mit seinem Ziel-Geschäftsobjekt verlinkt\n• Der Fortschritt wird live angezeigt\n\n<b>Link-Status pro Datensatz:</b>\n• <b>linked</b> — Erfolgreich verknüpft\n• <b>link_exists</b> — Verknüpfung existierte bereits\n• <b>link_failed</b> — Fehler bei der Verlinkung'
                }
            ],
            warnings: [
                'Die Verlinkung kann nur für Datensätze mit Status „success" und erstelltem Container durchgeführt werden.',
                'Ohne Objekt-Zuordnung kann keine Verlinkung im Zielsystem erstellt werden.',
                'Prüfen Sie die „Unmapped"-Liste im Excel-Template — nicht zugeordnete Objekte werden nicht verlinkt.'
            ]
        },

        details: {
            title: 'Schritt 4 — Auswertung & Ergebnisse',
            icon: 'fas fa-chart-bar',
            intro: 'Analysieren Sie die Migrationsergebnisse, untersuchen Sie Fehler und starten Sie fehlgeschlagene Datensätze erneut.',
            sections: [
                {
                    title: 'Zusammenfassung',
                    content: 'Die Übersichtskarte zeigt:\n• <b>Erfolgreiche</b> Datensätze (grün)\n• <b>Fehlgeschlagene</b> Datensätze (rot)\n• <b>Teilweise</b> (Container erstellt, aber nicht alle Dateien) (orange)\n• <b>Ausstehende</b> Datensätze (grau)'
                },
                {
                    title: 'Fehler-Kategorien',
                    content: 'Filter Sie nach Fehlerarten:\n• <b>AUTH_ERROR</b> — Authentifizierungsproblem\n• <b>RATE_LIMIT</b> — API-Ratenlimit erreicht\n• <b>UPLOAD_FAIL</b> — Upload-Fehler\n• <b>PAYLOAD_TOO_LARGE</b> — Datei zu groß\n• <b>CONTAINER_CREATE_FAIL</b> — Container-Erstellung fehlgeschlagen'
                },
                {
                    title: 'Datei-Details',
                    content: 'Klicken Sie auf einen Datensatz, um die <b>einzelnen Dateien</b> und deren Upload-Status zu sehen. Bei mehrteiligen Dokumenten kann eine Datei erfolgreich sein, während eine andere fehlschlägt (= „Partial").'
                },
                {
                    title: 'CSV-Export',
                    content: 'Klicken Sie <b>„CSV Export"</b> um alle Datei-Details als CSV-Datei herunterzuladen. Nützlich für externe Analyse oder Berichterstellung.'
                },
                {
                    title: 'Fehlgeschlagene erneut versuchen',
                    content: '<b>Nach Kategorie</b>: Klicken Sie den „Retry"-Button neben einer Fehlerkategorie, um alle Datensätze dieser Kategorie zurückzusetzen.\n\n<b>Alle Fehler</b>: „Alle Fehler zurücksetzen" setzt alle Failed/Partial-Datensätze zurück. Gehen Sie dann zurück zur Vorschau und starten Sie die Migration erneut.'
                }
            ]
        },

        waves: {
            title: 'Wellen-Übersicht & Planung',
            icon: 'fas fa-stream',
            intro: 'Verwalten Sie Migrationswellen und planen Sie die zeitliche Abfolge der Migration.',
            sections: [
                {
                    title: 'Wellen-Konzept',
                    content: 'Batches werden in <b>Wellen (Waves)</b> gruppiert. Jede Welle hat typischerweise 4 Phasen:\n1. <b>Qual Load</b> — Qualitätssystem: Upload\n2. <b>Qual Link</b> — Qualitätssystem: Verlinkung\n3. <b>Prod Load</b> — Produktivsystem: Upload\n4. <b>Prod Link</b> — Produktivsystem: Verlinkung'
                },
                {
                    title: 'Wellenplan erstellen',
                    content: 'Für jede Phase können Sie Start-/Enddatum und Status festlegen:\n• <b>Vorbereitung</b> — Noch nicht begonnen\n• <b>Arbeit</b> — In Bearbeitung\n• <b>Fertig</b> — Abgeschlossen'
                }
            ]
        }
    };

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
        if (path.includes('/wave-overview'))                  return 'waves';

        return 'dashboard'; // fallback
    }

    // ── Build HTML ───────────────────────────────────────────────────
    function buildHelpPanel() {
        const currentPage = detectCurrentPage();
        const pageHelp = HELP_CONTENT[currentPage];
        const workflow = HELP_CONTENT.workflow;
        const glossary = HELP_CONTENT.glossary;

        let html = '';

        // Header
        html += `
            <div class="help-panel-header">
                <div class="d-flex align-items-center justify-content-between">
                    <h5 class="mb-0"><i class="fas fa-question-circle"></i> Hilfe</h5>
                    <button class="btn btn-sm btn-outline-light" onclick="ContextualHelp.close()" title="Schließen">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
        `;

        // Tab navigation
        html += `
            <div class="help-tabs">
                <button class="help-tab active" data-tab="page"><i class="${pageHelp.icon}"></i> Diese Seite</button>
                <button class="help-tab" data-tab="workflow"><i class="${workflow.icon}"></i> Workflow</button>
                <button class="help-tab" data-tab="glossary"><i class="${glossary.icon}"></i> Glossar</button>
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
            html += `<div class="help-warnings-title"><i class="fas fa-exclamation-triangle"></i> Wichtige Hinweise</div>`;
            pageHelp.warnings.forEach(w => {
                html += `<div class="help-warning">${w}</div>`;
            });
        }
        html += `</div>`;

        // ── Tab: Workflow ────────────────────────────────────────────
        html += `<div class="help-tab-content" data-tab="workflow" style="display:none;">`;
        html += `<div class="help-section-title"><i class="${workflow.icon}"></i> ${workflow.title}</div>`;
        html += `<div class="help-intro">Der Migrationsprozess folgt diesen Schritten:</div>`;
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
        btn.title = 'Hilfe anzeigen (H)';
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

})();
