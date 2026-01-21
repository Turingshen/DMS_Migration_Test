# Setup script for Document Migration Application
# This script creates a virtual environment and installs all dependencies

Write-Host "`n=== Document Migration Application Setup ===" -ForegroundColor Cyan
Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Create a Python virtual environment (venv)" -ForegroundColor Yellow
Write-Host "  2. Install all required dependencies" -ForegroundColor Yellow
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "  Please install Python 3.8 or higher from https://www.python.org/" -ForegroundColor Yellow
    exit 1
}

# Check if venv already exists
if (Test-Path "venv") {
    Write-Host "`n[WARNING] Virtual environment already exists" -ForegroundColor Yellow
    $response = Read-Host "Do you want to recreate it? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        Write-Host "Removing existing virtual environment..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force venv
    } else {
        Write-Host "Keeping existing virtual environment" -ForegroundColor Green
        Write-Host "`nTo activate the environment, run:" -ForegroundColor Cyan
        Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor White
        exit 0
    }
}

# Create virtual environment
Write-Host "`nCreating virtual environment..." -ForegroundColor Cyan
python -m venv venv

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Virtual environment created" -ForegroundColor Green

# Activate virtual environment
Write-Host "`nActivating virtual environment..." -ForegroundColor Cyan
& .\venv\Scripts\Activate.ps1

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to activate virtual environment" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Virtual environment activated" -ForegroundColor Green

# Upgrade pip
Write-Host "`nUpgrading pip..." -ForegroundColor Cyan
python -m pip install --upgrade pip --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Failed to upgrade pip, continuing anyway..." -ForegroundColor Yellow
} else {
    Write-Host "[OK] Pip upgraded" -ForegroundColor Green
}

# Install requirements
if (Test-Path "requirements.txt") {
    Write-Host "`nInstalling dependencies from requirements.txt..." -ForegroundColor Cyan
    pip install -r requirements.txt
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install some dependencies" -ForegroundColor Red
        Write-Host "  Please check the error messages above" -ForegroundColor Yellow
        exit 1
    }
    
    Write-Host "[OK] All dependencies installed successfully" -ForegroundColor Green
} else {
    Write-Host "[WARNING] requirements.txt not found" -ForegroundColor Yellow
}

# Success message
Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "`nTo start the application:" -ForegroundColor Cyan
Write-Host "  1. Activate the virtual environment:" -ForegroundColor White
Write-Host "     .\venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "  2. Run the server:" -ForegroundColor White
Write-Host "     python server.py" -ForegroundColor Gray
Write-Host "  3. Open your browser to:" -ForegroundColor White
Write-Host "     http://localhost:5000" -ForegroundColor Gray
Write-Host ""
