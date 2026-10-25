# Create a clean Windows desktop shortcut for Deskling / 桌角同学.
# Run through create_shortcut.bat (or with -ExecutionPolicy Bypass).

$ErrorActionPreference = "Stop"

$Project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$MainPy = Join-Path $Project "main.py"
$IconSource = Join-Path $Project "assets\deskling.ico"

if (-not (Test-Path -LiteralPath $MainPy)) {
    throw "找不到 main.py：$MainPy"
}
if (-not (Test-Path -LiteralPath $IconSource)) {
    throw "找不到图标：$IconSource。请先运行 python tools\generate_assets.py"
}

# Explorer on this machine refused to resolve an .ico kept on the D: project
# drive.  Copy it to the user's LOCALAPPDATA, which the shell can always read.
$IconDir = Join-Path $env:LOCALAPPDATA "Deskling"
New-Item -ItemType Directory -Force -Path $IconDir | Out-Null
$IconPath = Join-Path $IconDir "deskling.ico"
Copy-Item -LiteralPath $IconSource -Destination $IconPath -Force

$pythonw = $null
# Prefer the pythonw that belongs to the same "python" used by start.bat,
# because that is the interpreter where PyQt6 was installed.
$command = Get-Command "python.exe" -ErrorAction SilentlyContinue
if ($command) {
    $candidate = Join-Path (Split-Path $command.Source) "pythonw.exe"
    if (Test-Path -LiteralPath $candidate) {
        $pythonw = $candidate
    }
}
if (-not $pythonw -or -not (Test-Path -LiteralPath $pythonw)) {
    $command = Get-Command "pythonw.exe" -ErrorAction SilentlyContinue
    if ($command) {
        $pythonw = $command.Source
    }
}
if (-not $pythonw) {
    throw "没有找到 pythonw.exe，请先安装 Python 并加入 PATH。"
}

$desktop = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path -LiteralPath $desktop)) {
    throw "找不到桌面目录：$desktop"
}
$shortcutPath = Join-Path $desktop "桌角同学.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $MainPy + '"'
$shortcut.WorkingDirectory = $Project
$shortcut.IconLocation = "$IconPath,0"
$shortcut.Description = "桌角同学 Deskling - 桌面纸片人桌宠"
$shortcut.WindowStyle = 7
$shortcut.Save()

if (-not (Test-Path -LiteralPath $shortcutPath)) {
    throw "快捷方式创建失败：$shortcutPath"
}

Write-Host ""
Write-Host "桌面快捷方式已创建："
Write-Host "  $shortcutPath"
Write-Host "  启动器：$pythonw"
Write-Host "  图标：$IconPath"
Write-Host "  项目：$Project"
