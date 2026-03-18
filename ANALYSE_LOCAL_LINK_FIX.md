# Analyse: DAPPL vs Datei-Extension Mismatch

## Problem-Zusammenfassung

Die aktuelle Logik in `execute.py` erkennt lokale Links nur wenn `ws_appl in ('HTM', '')`:

```python
# Zeile 2183 execute.py - AKTUELL (FEHLERHAFT)
if ws_appl in ('HTM', '') and file_index == 0:  # Nur HTM!
    _filep = get_filep_from_draw(...)
    if _filep:
        if is_local_path(_filep):
            _is_local_link = True
```

**Das Problem:** Dokumente mit lokalen Pfaden in FILEP haben verschiedene DAPPLs:

| DAPPL | Anzahl mit lokalem Pfad |
|-------|-------------------------|
| PDF   | 79.218 |
| JPG   | 9.441 |
| XLS   | 2.904 |
| PNG   | 1.151 |
| MSG   | 929 |
| ZSG   | 772 |
| DOC   | 759 |
| ... | ... |
| HTM   | nur 78! |

**Konsequenz:** 100.000+ Dokumente schlagen fehl, weil:
1. DAPPL = PDF/JPG/XLS (nicht HTM)
2. `ws_appl` aus API ist auch PDF/JPG/XLS
3. Local-Link-Check wird übersprungen
4. KPRO-Download schlägt fehl (kein Content dort)

## Lösung

### Option A: FILEP-Prüfung für alle DAPPLs (Empfohlen)

```python
# Zeile 2179-2200 execute.py - NEU
_is_local_link = False
_is_web_url_link = False
_link_path = ''

# NEU: FILEP-Prüfung für ALLE Dateien, nicht nur HTM
# Lokale Pfade können jede DAPPL haben (PDF, JPG, XLS, etc.)
if file_index == 0:  # Nur erste Datei prüfen (Batch-Header)
    _filep = get_filep_from_draw(
        staging_record['source_documentnumber'],
        staging_record['source_documenttype'],
        staging_record['source_documentversion'],
        staging_record['source_documentpart']
    )
    if _filep:
        if is_local_path(_filep):
            _is_local_link = True
            _link_path = _filep
            logger.info(f"LOCAL_LINK detected (DAPPL={ws_appl}) — path: {_filep[:100]}...", category="READ")
        elif is_web_url(_filep):
            _is_web_url_link = True
            _link_path = _filep
            logger.info(f"WEB_URL detected (DAPPL={ws_appl}) — URL: {_filep[:100]}...", category="READ")
```

### Option B: Zusätzliche Early-Exit bei Empty Download (Fallback)

Falls Download fehlschlägt UND FILEP ein lokaler Pfad ist:

```python
# Nach Download-Fehler bzw. Response-Size = 0
if response.status_code == 200 and len(response.content) == 0:
    # Prüfe ob es ein lokaler Link ist
    _filep = get_filep_from_draw(...)
    if _filep and is_local_path(_filep):
        # Erstelle .url Shortcut statt Fehler
        logger.info(f"Empty download + local path detected — creating .url shortcut", category="READ")
        # ... URL shortcut erstellen ...
```

## Implementierung

Die Änderung betrifft hauptsächlich eine Zeile (2183):

**Vorher:**
```python
if ws_appl in ('HTM', '') and file_index == 0:
```

**Nachher:**
```python
if file_index == 0:  # Prüfe ALLE Dateien auf lokale Pfade
```

## Testfälle

| Fall | DAPPL | FILEP | Erwartetes Verhalten |
|------|-------|-------|---------------------|
| 1 | PDF | C:\Users\...\doc.pdf | .url Shortcut erstellen |
| 2 | JPG | D:\Photos\img.jpg | .url Shortcut erstellen |
| 3 | HTM | https://... | .url Shortcut erstellen |
| 4 | PDF | (leer) | Normal KPRO Download |
| 5 | ZIP | B:\Shared\file.zip | .url Shortcut erstellen |

## Risiko-Analyse

**Gering:** Die Funktion `is_local_path()` prüft bereits korrekt:
- Alle Drive-Letters (A-Z)
- UNC Pfade (\\\\server\\share)
- file:// URLs

Die Änderung erweitert nur den Aufruf-Scope.
