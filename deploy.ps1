# BillboardAI deployment helper

param(
    [string]$EnvFile = ".env",
    [string]$BatchFile = "urls.txt",
    [string]$OutputCsv = "output/smartlead.csv",
    [string]$Template = "auto",
    [switch]$Upload,
    [switch]$LaunchApp,
    [switch]$RegisterTask,
    [string]$TaskName = "BillboardAI Daily Batch",
    [string]$TaskTime = "08:00"
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

if ($LaunchApp) {
    Write-Host "Launching the BillboardAI desktop app..."
    & $pythonExe -m app
    Write-Host "Desktop app closed."
    exit 0
}

if ($RegisterTask) {
    Write-Host "Registering Windows scheduled task '$TaskName' to run at $TaskTime..."
    $uploadFlag = ""
    if ($Upload) {
        $uploadFlag = "--upload"
    }

    $actionArguments = "main.py --batch-file `"$BatchFile`" --output-csv `"$OutputCsv`" --template $Template $uploadFlag"
    $action = New-ScheduledTaskAction -Execute $pythonExe -Argument $actionArguments
    $trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description "Run BillboardAI batch processing daily." -Force | Out-Null

    Write-Host "Scheduled task '$TaskName' registered."
    exit 0
}

$uploadFlag = ""
if ($Upload) {
    $uploadFlag = "--upload"
}

Write-Host "Running batch command..."
& $pythonExe main.py --batch-file $BatchFile --output-csv $OutputCsv --template $Template $uploadFlag

Write-Host "Deployment command completed."
