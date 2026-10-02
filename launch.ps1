$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$pythonPath = Join-Path $taskRoot '.venv\Scripts\python.exe'
$scriptPath = Join-Path $taskRoot 'app.py'
$logDirectory = Join-Path $taskRoot 'data'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
try {
    $state = Invoke-RestMethod 'http://127.0.0.1:8765/api/state' -TimeoutSec 2
    $ready = $null -ne $state.rows
} catch { $ready = $false }
if (-not $ready) {
    Start-Process -FilePath $pythonPath -ArgumentList ('"' + $scriptPath + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'service.log') -RedirectStandardError (Join-Path $logDirectory 'service-error.log') | Out-Null
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            Invoke-RestMethod 'http://127.0.0.1:8765/api/state' -TimeoutSec 1 | Out-Null
            $ready = $true
            break
        } catch {}
    }
}
if (-not $ready) { throw 'Service failed to start. See data/service-error.log.' }
Start-Process 'http://127.0.0.1:8765'
