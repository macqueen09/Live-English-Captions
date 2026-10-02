$ErrorActionPreference = 'Stop'
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Live English Captions.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $PSScriptRoot 'start.cmd'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Start Live English Captions'
$shortcut.WindowStyle = 7
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,21"
$shortcut.Save()
Write-Host "Desktop shortcut ready: $shortcutPath"
