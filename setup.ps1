param([switch]$Mirror)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.tools\python'
$uv = Join-Path $PSScriptRoot '.tools\uv.exe'
if (-not (Test-Path -LiteralPath $uv)) {
    New-Item -ItemType Directory -Force -Path '.tools' | Out-Null
    Write-Host 'Downloading portable Python manager...'
    Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile '.tools\uv.zip'
    Expand-Archive -LiteralPath '.tools\uv.zip' -DestinationPath '.tools' -Force
}
& $uv venv --python 3.12 --managed-python --allow-existing .venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed.' }
& $uv pip install --python '.venv\Scripts\python.exe' -r requirements.lock --index-url 'https://mirrors.huaweicloud.com/repository/pypi/simple' --link-mode copy
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host 'Installing optional NVIDIA runtime into the project environment...'
    & $uv pip install --python '.venv\Scripts\python.exe' -r requirements-gpu.txt --index-url 'https://mirrors.huaweicloud.com/repository/pypi/simple' --link-mode copy
    if ($LASTEXITCODE -ne 0) { Write-Warning 'NVIDIA runtime installation failed; captions will use CPU fallback.' }
}
if ($Mirror) { $env:HF_ENDPOINT = 'https://hf-mirror.com'; $env:HF_HUB_DISABLE_XET = '1' }
& '.\.venv\Scripts\python.exe' download_models.py
if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Check network and run setup again.' }
Write-Host 'Ready. Double-click start.cmd to open subtitles.'
