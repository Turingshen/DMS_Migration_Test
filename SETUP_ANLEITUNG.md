# DMS Migration – Installationsanleitung

## Voraussetzungen

### 1. Python installieren

- **Version:** Python 3.10 oder höher (getestet mit 3.14.3)
- **Download:** https://www.python.org/downloads/
- Bei der Installation **"Add Python to PATH"** aktivieren
- Prüfen mit: `python --version`

### 2. Git installieren (optional)

> Nur nötig, falls ein zentrales Git-Remote eingerichtet wird. Für die Weitergabe per Ordnerkopie/ZIP ist Git nicht erforderlich.

- **Download:** https://git-scm.com/download/win
- Prüfen mit: `git --version`

### 3. Netzwerkzugang

Folgende Systeme müssen erreichbar sein:

| System | Host | Port | Zweck |
|--------|------|------|-------|
| MS SQL Server | win10240611.BASFAD.BASF.net | 1433 | Datenbank (Staging, MISC) |
| SAP HANA | lo1hdb.dmz.basf-ag.de | 30015 | DIL-Datenbank |
| SAP OData APIs | je nach System (Q01, P01 etc.) | 443 | Dokumenten-Upload/-Download |
| Azure AD | login.microsoftonline.com | 443 | OAuth-Anmeldung |

> **Hinweis:** VPN bzw. BASF-Netzwerk erforderlich.

---

## Installation

### Schritt 1: Projektordner bereitstellen

**Option A – Ordner kopieren oder ZIP entpacken (empfohlen):**

Den Ordner `DMS_Migration` vom Kollegen als Kopie oder ZIP-Datei erhalten und nach `C:\App_Archive\Apps\` entpacken bzw. kopieren:

```powershell
# Beispiel: ZIP entpacken
Expand-Archive -Path "$HOME\Downloads\DMS_Migration.zip" -DestinationPath "C:\App_Archive\Apps"

# Oder: Ordner direkt vom Netzlaufwerk/USB kopieren
Copy-Item -Recurse "\\QUELL-PC\C$\App_Archive\Apps\DMS_Migration" "C:\App_Archive\Apps\"
```

> **Hinweis:** Den Unterordner `.venv` dabei **nicht** mitkopieren – die virtuelle Umgebung wird in Schritt 2 neu erstellt.

**Option B – Mit Git klonen (falls ein Remote eingerichtet ist):**

Aktuell ist kein Remote konfiguriert. Falls eines eingerichtet wird:

```powershell
cd C:\App_Archive\Apps
git clone <repository-url> DMS_Migration
cd DMS_Migration
```

### Schritt 2: Setup-Script ausführen

Das mitgelieferte Setup-Script erstellt automatisch die virtuelle Umgebung und installiert alle Abhängigkeiten:

```powershell
# PowerShell Execution Policy erlauben (einmalig)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

# Setup ausführen
.\setup.ps1
```

### Oder manuell:

```powershell
# Virtuelle Umgebung erstellen
python -m venv .venv

# Aktivieren
.\.venv\Scripts\Activate.ps1

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### Schritt 3: Konfiguration anpassen

Die Datei `config-env.yml` im Projektverzeichnis enthält alle Verbindungseinstellungen.
Eine Vorlage ist im Repository enthalten. Folgende Abschnitte müssen geprüft/angepasst werden:

```yaml
# Grundeinstellungen
path_to_userdata: userdata
base_url: http://localhost:5000
deployment_environment: local       # "local" für Entwickler-PC, "iis" für Server
FLASK_SECRET_KEY: <eigener-key>     # Beliebiger String, z.B. via: python -c "import secrets; print(secrets.token_hex(16))"

# Azure AD OAuth (Zugangsdaten vom Team erhalten)
auth:
  auth_url: https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0
  payload:
    client_id: <app-registration-client-id>
    client_secret: <client-secret>
    scope: openid profile
    response_type: code
    redirect_uri: http://localhost:5000/callback
    grant_type: authorization_code

# Datenbank-Verbindungen
db:
  datastore:
    db_host: <mssql-host>
    db_port: 1433
    db_user: <db-benutzer>
    db_pw: <db-passwort>
    db_driver: mssql+pymssql
    db_name: <datenbank-name>
    db_con_str: "{db_driver}://{db_user}:{db_pw}@{db_host}:{db_port}/{db_name}"

  dil:
    db_host: <hana-host>
    db_port: 30015
    db_user: <hana-benutzer>
    db_pw: <hana-passwort>
    db_driver: hana+hdbcli
    db_con_str: "{db_driver}://{db_user}:{db_pw}@{db_host}:{db_port}?encrypt=true&validateCertificate=true"
```

> **Wichtig:** Die `config-env.yml` enthält sensible Zugangsdaten und darf **nicht** in öffentliche Repositories committed werden.

---

## Anwendung starten

```powershell
# In das Projektverzeichnis wechseln
cd C:\App_Archive\Apps\DMS_Migration

# Virtuelle Umgebung aktivieren
.\.venv\Scripts\Activate.ps1

# Server starten
python server.py
```

Die Anwendung ist dann erreichbar unter: **http://localhost:5000**

---

## Installierte Pakete (Überblick)

| Paket | Zweck |
|-------|-------|
| Flask, Flask-Session, Flask-CORS | Webserver & Session-Management |
| SQLAlchemy | Datenbank-ORM |
| pandas, openpyxl | Datenverarbeitung & Excel-Export |
| pymssql | MS SQL Server Verbindung |
| hdbcli, sqlalchemy-hana | SAP HANA Verbindung |
| requests | HTTP-Aufrufe an SAP APIs |
| PyYAML | Konfigurationsdateien lesen |
| cryptography | Verschlüsselung von Credentials |
| Werkzeug | WSGI-Utilities |

---

## Fehlerbehebung

### "Module not found" Fehler
→ Virtuelle Umgebung aktiviert? (Prompt zeigt `(.venv)` an)
```powershell
.\.venv\Scripts\Activate.ps1
```

### Pakete fehlen
```powershell
pip install -r requirements.txt
pip check   # Prüft auf Konflikte
```

### Datenbank nicht erreichbar
→ VPN aktiv? Firewall-Freigabe vorhanden?
```powershell
Test-NetConnection -ComputerName win10240611.BASFAD.BASF.net -Port 1433
```

### OAuth-Login schlägt fehl
→ `redirect_uri` in `config-env.yml` muss exakt mit der Azure App Registration übereinstimmen (inkl. Port).

### Port 5000 bereits belegt
→ Anderen Prozess beenden oder Port in `config-env.yml` unter `base_url` ändern.

---

## Lokale Datenbank übernehmen (Settings & Passwörter)

Die Anwendung speichert SAP-Systemkonfigurationen und verschlüsselte Zugangsdaten in der zentralen MS SQL-Datenbank (`dbo.sap_systems`, `dbo.sap_system_apis`, `dbo.sap_credentials`). Zusätzlich gibt es eine lokale SQLite-Datenbank unter `userdata/dms_objects.db`, die geladene DMS-Objekte cached.

### Datenbank von einem anderen PC übernehmen

Wenn ein Kollege die Anwendung bereits eingerichtet hat, können Settings und Daten übernommen werden:

#### 1. Lokale SQLite-Datenbank kopieren

```powershell
# Den gesamten userdata-Ordner vom Quell-PC kopieren
Copy-Item -Recurse "\\QUELL-PC\C$\App_Archive\Apps\DMS_Migration\userdata" "C:\App_Archive\Apps\DMS_Migration\userdata"
```

Alternativ nur die Datenbankdatei:
```powershell
Copy-Item "\\QUELL-PC\C$\App_Archive\Apps\DMS_Migration\userdata\dms_objects.db" "C:\App_Archive\Apps\DMS_Migration\userdata\"
```

> **Hinweis:** Der Ordner `userdata/` muss existieren. Falls nicht: `mkdir userdata`

#### 2. config-env.yml übernehmen

Die Datei `config-env.yml` enthält alle Verbindungseinstellungen. Am einfachsten vom Kollegen kopieren:

```powershell
Copy-Item "\\QUELL-PC\C$\App_Archive\Apps\DMS_Migration\config-env.yml" "C:\App_Archive\Apps\DMS_Migration\"
```

#### 3. FLASK_SECRET_KEY beachten

Die SAP-Zugangsdaten in der Datenbank (`dbo.sap_credentials`) sind mit **Fernet-Verschlüsselung** geschützt. Der Schlüssel wird aus dem `FLASK_SECRET_KEY` in `config-env.yml` abgeleitet.

> **Wichtig:** Wenn der `FLASK_SECRET_KEY` geändert wird, können bestehende verschlüsselte Passwörter **nicht mehr entschlüsselt** werden. In diesem Fall müssen die SAP-Zugangsdaten in der Anwendung unter *Settings > API-Endpunkte konfigurieren* neu eingegeben werden.

#### 4. Zentrale Datenbank (MS SQL)

Die SAP-System-Konfigurationen und verschlüsselten Credentials liegen in der zentralen MISC-Datenbank. Solange die `config-env.yml` die korrekten DB-Verbindungsdaten enthält und der `FLASK_SECRET_KEY` übereinstimmt, sind alle Settings automatisch verfügbar – keine manuelle Übertragung nötig.

---

## Projektstruktur

```
DMS_Migration/
├── server.py              # Haupteinstiegspunkt (Flask-Server)
├── app_config.py          # Konfiguration laden (Singleton)
├── authentication.py      # OAuth / Azure AD Login
├── config-env.yml         # Umgebungskonfiguration (NICHT committen!)
├── requirements.txt       # Python-Abhängigkeiten
├── setup.ps1              # Automatisches Setup-Script
├── app/                   # Anwendungslogik (Routes, DB, Execute)
├── static/                # CSS, JS, Bilder
├── templates/             # HTML-Templates (Jinja2)
├── tests/                 # Automatisierte Tests
├── userdata/              # Lokale Benutzerdaten / SAP Credentials
│   ├── dms_objects.db     # SQLite-Cache für DMS-Objekte
│   └── werke_cache.json   # Zwischengespeicherte Werksliste
└── flask_session/         # Session-Dateien (wird automatisch erstellt)
```
