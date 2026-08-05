# BillboardAI deployment helper

param(
    [string]$EnvFile = ".env",
    [string]$BatchFile = "urls.txt",
    [string]$OutputCsv = "output/smartlead.csv",
    [string]$Template = "auto",
    [switch]$Upload
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "== BillboardAI Deployment Helper =="

if (-Not (Test-Path $EnvFile)) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example. Please edit .env with Cloudinary credentials."
    } else {
        Write-Host "Missing environment file: $EnvFile"
        Write-Host "Create .env with Cloudinary credentials or add a .env.example file."
        exit 1
    }
}

Write-Host "Importing environment settings from $EnvFile..."
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^(\s*[^#][^=]+)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        if (-Not [string]::IsNullOrEmpty($name)) {
            [System.Environment]::SetEnvironmentVariable($name, $value)
        }
    }
}

$venvPath = Join-Path $scriptDir ".venv"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
$pyVenvCfg = Join-Path $venvPath "pyvenv.cfg"

function Initialize-Venv {
    if (Test-Path $venvPath) {
        Write-Host "Removing incomplete virtual environment..."
        Remove-Item -Recurse -Force $venvPath
    }
    Write-Host "Creating virtual environment..."
    & python -m venv $venvPath
}

if (-Not (Test-Path $venvPath) -or -Not (Test-Path $pyVenvCfg)) {
    Initialize-Venv
}

if (-Not (Test-Path $pythonExe)) {
    Write-Host "Virtual environment was not created correctly."
    exit 1
}

Write-Host "Installing dependencies..."
& $pythonExe -m pip install -r requirements.txt

Write-Host "Installing Playwright browsers..."
& $pythonExe -m playwright install chromium

if (-Not (Test-Path $BatchFile)) {
    Write-Host "Batch file $BatchFile not found. Creating placeholder with https://example.com"
    "https://example.com" | Out-File -Encoding utf8 -NoBom $BatchFile
}

$uploadFlag = ""
if ($Upload) {
    $uploadFlag = "--upload"
}

Write-Host "Running batch command..."
& $pythonExe main.py --batch-file $BatchFile --output-csv $OutputCsv --template $Template $uploadFlag

Write-Host "Deployment command completed."
