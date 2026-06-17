# DMS Migration – Setup Guide (English)

This guide walks you through the complete setup of the DMS Migration application on a Windows PC – from scratch, assuming no prior experience with Python or Git.

---

## Prerequisites

### 1. Install Python

Python is the programming language this application is built with. You need to install it first.

- **Required version:** Python 3.10 or higher (tested with 3.14.3)
- **Download:** https://www.python.org/downloads/
- Run the installer and **check the box "Add Python to PATH"** (this is critical!)
- After installation, verify by opening PowerShell (press `Win+X` → "Windows PowerShell") and typing:

```powershell
python --version
```

You should see something like `Python 3.14.3`. If you get an error, restart your PC and try again.

### 2. Install Git (optional)

Git is a version control tool. It is **only needed** if a central Git server (remote) is set up. If you receive the project as a folder copy or ZIP file, you can skip this step.

- **Download:** https://git-scm.com/download/win
- Run the installer with default settings
- Verify installation:

```powershell
git --version
```

### 3. Network Access

The application connects to several backend systems. You **must be on the BASF network** (either on-site or via VPN).

| System | Host | Port | Purpose |
|--------|------|------|---------|
| MS SQL Server | win10240611.BASFAD.BASF.net | 1433 | Database (Staging, MISC) |
| SAP HANA | lo1hdb.dmz.basf-ag.de | 30015 | DIL database |
| SAP OData APIs | varies by system (Q01, P01 etc.) | 443 | Document upload/download |
| Azure AD | login.microsoftonline.com | 443 | OAuth authentication |

> **Note:** VPN or direct BASF network connection is required for all operations.

---

## Installation

### Step 1: Get the Project Files

**Option A – Copy the folder or extract a ZIP file (recommended):**

Get the `DMS_Migration` folder from a colleague – either as a direct copy or as a ZIP file. Place it under `C:\App_Archive\Apps\`:

```powershell
# Example: Extract a ZIP file
Expand-Archive -Path "$HOME\Downloads\DMS_Migration.zip" -DestinationPath "C:\App_Archive\Apps"

# Or: Copy the folder from a network share or USB drive
Copy-Item -Recurse "\\SOURCE-PC\C$\App_Archive\Apps\DMS_Migration" "C:\App_Archive\Apps\"
```

> **Important:** Do **not** copy the `.venv` subfolder – the virtual environment will be created fresh in Step 2.

**Option B – Clone with Git (if a remote is configured):**

Currently no Git remote is set up. If one is added in the future:

```powershell
cd C:\App_Archive\Apps
git clone <repository-url> DMS_Migration
cd DMS_Migration
```

> **What does "clone" mean?** It downloads a copy of the entire application code from a central Git server to your PC.

### Step 2: Run the Setup Script

The project includes an automated setup script that creates a virtual environment and installs all required packages:

```powershell
# Allow PowerShell to run scripts (one-time setup)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

# Run the setup
.\setup.ps1
```

> **What is a virtual environment?** It's an isolated Python installation specific to this project, so it doesn't interfere with other Python projects on your PC.

### Or install manually:

If the script doesn't work, you can do it step by step:

```powershell
# Create the virtual environment
python -m venv .venv

# Activate it (you'll see "(.venv)" appear in your prompt)
.\.venv\Scripts\Activate.ps1

# Install all required packages
pip install -r requirements.txt
```

### Step 3: Configure the Application

The file `config-env.yml` in the project directory contains all connection settings. A template is already included. The following sections need to be reviewed/adjusted:

```yaml
# Basic settings
path_to_userdata: userdata
base_url: http://localhost:5000
deployment_environment: local       # "local" for developer PC, "iis" for server
FLASK_SECRET_KEY: <your-key>        # Any random string, generate via: python -c "import secrets; print(secrets.token_hex(16))"

# Azure AD OAuth (get credentials from the team)
auth:
  auth_url: https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0
  payload:
    client_id: <app-registration-client-id>
    client_secret: <client-secret>
    scope: openid profile
    response_type: code
    redirect_uri: http://localhost:5000/callback
    grant_type: authorization_code

# Database connections
db:
  datastore:
    db_host: <mssql-host>
    db_port: 1433
    db_user: <db-user>
    db_pw: <db-password>
    db_driver: mssql+pymssql
    db_name: <database-name>
    db_con_str: "{db_driver}://{db_user}:{db_pw}@{db_host}:{db_port}/{db_name}"

  dil:
    db_host: <hana-host>
    db_port: 30015
    db_user: <hana-user>
    db_pw: <hana-password>
    db_driver: hana+hdbcli
    db_con_str: "{db_driver}://{db_user}:{db_pw}@{db_host}:{db_port}?encrypt=true&validateCertificate=true"
```

> **Important:** The `config-env.yml` contains sensitive credentials and must **never** be committed to public repositories.

---

## Copying the Database (Settings & Passwords)

The application stores SAP system configurations and encrypted credentials in the central MS SQL database (`dbo.sap_systems`, `dbo.sap_system_apis`, `dbo.sap_credentials`). Additionally, there is a local SQLite database at `userdata/dms_objects.db` that caches loaded DMS objects.

### Taking Over the Database from Another PC

If a colleague already has the application set up, you can copy settings and data:

#### 1. Copy the local SQLite database

```powershell
# Copy the entire userdata folder from the source PC
Copy-Item -Recurse "\\SOURCE-PC\C$\App_Archive\Apps\DMS_Migration\userdata" "C:\App_Archive\Apps\DMS_Migration\userdata"
```

Or copy only the database file:
```powershell
Copy-Item "\\SOURCE-PC\C$\App_Archive\Apps\DMS_Migration\userdata\dms_objects.db" "C:\App_Archive\Apps\DMS_Migration\userdata\"
```

> **Note:** The `userdata/` folder must exist. If not, create it: `mkdir userdata`

#### 2. Copy config-env.yml

The `config-env.yml` file contains all connection settings. The easiest approach is to copy it from a colleague:

```powershell
Copy-Item "\\SOURCE-PC\C$\App_Archive\Apps\DMS_Migration\config-env.yml" "C:\App_Archive\Apps\DMS_Migration\"
```

#### 3. Important: FLASK_SECRET_KEY

The SAP credentials in the database (`dbo.sap_credentials`) are protected with **Fernet encryption**. The encryption key is derived from the `FLASK_SECRET_KEY` in `config-env.yml`.

> **Critical:** If the `FLASK_SECRET_KEY` is changed, existing encrypted passwords **cannot be decrypted** anymore. In that case, SAP credentials must be re-entered in the application under *Settings > Configure API Endpoints*.

#### 4. Central Database (MS SQL)

The SAP system configurations and encrypted credentials are stored in the central MISC database. As long as your `config-env.yml` contains the correct DB connection details and the `FLASK_SECRET_KEY` matches, all settings are automatically available – no manual transfer needed.

---

## Starting the Application

```powershell
# Navigate to the project directory
cd C:\App_Archive\Apps\DMS_Migration

# Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# Start the server
python server.py
```

The application will be available at: **http://localhost:5000**

Open this URL in your web browser (Chrome, Edge, or Firefox recommended).

---

## Installed Packages (Overview)

| Package | Purpose |
|---------|---------|
| Flask, Flask-Session, Flask-CORS | Web server & session management |
| SQLAlchemy | Database ORM (object-relational mapping) |
| pandas, openpyxl | Data processing & Excel export |
| pymssql | MS SQL Server connection |
| hdbcli, sqlalchemy-hana | SAP HANA connection |
| requests | HTTP calls to SAP APIs |
| PyYAML | Reading configuration files |
| cryptography | Encryption of credentials |
| Werkzeug | WSGI utilities |

---

## Troubleshooting

### "Module not found" Error
→ Is the virtual environment activated? (Your prompt should show `(.venv)`)
```powershell
.\.venv\Scripts\Activate.ps1
```

### Packages are missing
```powershell
pip install -r requirements.txt
pip check   # Check for conflicts
```

### Database not reachable
→ Is VPN active? Firewall rules in place?
```powershell
Test-NetConnection -ComputerName win10240611.BASFAD.BASF.net -Port 1433
```

### OAuth login fails
→ The `redirect_uri` in `config-env.yml` must exactly match the Azure App Registration (including the port number).

### Port 5000 already in use
→ Kill the other process or change the port in `config-env.yml` under `base_url`.

You can check what's using port 5000:
```powershell
Get-NetTCPConnection -LocalPort 5000 | Select-Object OwningProcess
Get-Process -Id <PID>
```

### PowerShell won't run scripts
If you get an error about execution policy:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### pip install fails with SSL errors
→ This typically means your corporate proxy is intercepting HTTPS. Try:
```powershell
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

---

## Project Structure

```
DMS_Migration/
├── server.py              # Main entry point (Flask server)
├── app_config.py          # Configuration loader (Singleton pattern)
├── authentication.py      # OAuth / Azure AD login
├── config-env.yml         # Environment configuration (DO NOT commit!)
├── requirements.txt       # Python dependencies
├── setup.ps1              # Automated setup script
├── app/                   # Application logic (Routes, DB, Execute)
├── static/                # CSS, JS, images
├── templates/             # HTML templates (Jinja2)
├── tests/                 # Automated tests
├── userdata/              # Local user data / SAP credentials
│   ├── dms_objects.db     # SQLite cache for DMS objects
│   └── werke_cache.json   # Cached plant list
└── flask_session/         # Session files (created automatically)
```

---

## Quick Start Summary

1. Install Python 3.10+ (with PATH checkbox!)
2. Install Git
3. Clone the repository
4. Run `.\setup.ps1` (or create venv manually)
5. Get `config-env.yml` from a colleague (or fill in the template)
6. Copy `userdata/` folder from a colleague (optional, for cached data)
7. Activate venv: `.\.venv\Scripts\Activate.ps1`
8. Start: `python server.py`
9. Open http://localhost:5000 in your browser
