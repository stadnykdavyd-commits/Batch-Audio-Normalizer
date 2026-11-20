# Batch Audio Normalizer — установщик для Windows
# Ставит Python 3.12 и FFmpeg (через winget), проверяет программу тестами
# и создаёт ярлык "Audio Normalizer" на рабочем столе.

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$InstallerDir = $PSScriptRoot
$ProjectDir   = Split-Path -Parent $InstallerDir
$ConfigFile   = Join-Path $InstallerDir 'config.json'

function Write-Step($text) { Write-Host ''; Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "    OK: $text" -ForegroundColor Green }
function Write-Warn2($text){ Write-Host "    !  $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ''
    Write-Host "ОШИБКА: $text" -ForegroundColor Red
    exit 1
}

function Update-PathFromRegistry {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

# Возвращает полный путь к python.exe версии 3.10+ или $null
function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[string]

    # 1) py launcher -> спрашиваем у него реальный путь
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $p = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($p) { $candidates.Add(($p | Select-Object -First 1).Trim()) }
        } catch {}
    }
    # 2) python в PATH (пропускаем заглушку Microsoft Store в WindowsApps)
    foreach ($cmd in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        if ($cmd.Source -notmatch 'WindowsApps') { $candidates.Add($cmd.Source) }
    }
    # 3) стандартные папки установки
    foreach ($root in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles\Python312", "$env:ProgramFiles")) {
        if (Test-Path $root) {
            Get-ChildItem -Path $root -Filter python.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                ForEach-Object { $candidates.Add($_.FullName) }
        }
    }

    foreach ($exe in $candidates) {
        if (-not (Test-Path $exe)) { continue }
        try {
            $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        } catch { continue }
        if ($v -match '^3\.(\d+)') {
            if ([int]$Matches[1] -ge 10) { return $exe }
        }
    }
    return $null
}

# Возвращает папку, где лежит ffmpeg.exe, или $null
function Find-FFmpegDir {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return (Split-Path -Parent $cmd.Source) }
    $roots = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
        "$env:ProgramFiles\ffmpeg",
        "C:\ffmpeg"
    )
    foreach ($root in $roots) {
        if (Test-Path $root) {
            $f = Get-ChildItem -Path $root -Filter ffmpeg.exe -Recurse -Depth 5 -ErrorAction SilentlyContinue |
                 Select-Object -First 1
            if ($f) { return $f.DirectoryName }
        }
    }
    return $null
}

function Install-WithWinget($id, $name) {
    Write-Host "    Устанавливаю $name через winget (может занять пару минут)..."
    & winget install -e --id $id --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        # уже установлен / нужна другая область установки - не страшно, дальше проверим поиском
        Write-Warn2 "winget вернул код $LASTEXITCODE для $name — проверяю, появился ли он"
    }
    Update-PathFromRegistry
}

Write-Host '==============================================' -ForegroundColor Cyan
Write-Host '   Batch Audio Normalizer — установка'         -ForegroundColor Cyan
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host "Папка программы: $ProjectDir"

# --- winget ---------------------------------------------------------------
Write-Step 'Проверяю winget'
$hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
if ($hasWinget) { Write-Ok 'winget есть' } else { Write-Warn2 'winget не найден' }

# --- Python ---------------------------------------------------------------
Write-Step 'Проверяю Python'
$python = Find-Python
if (-not $python) {
    if (-not $hasWinget) {
        Fail ("Python не найден, и winget тоже. Установите 'App Installer' из Microsoft Store " +
              "или Python 3.12 с python.org (галочка 'Add python.exe to PATH'), потом запустите установку ещё раз.")
    }
    Install-WithWinget 'Python.Python.3.12' 'Python 3.12'
    $python = Find-Python
    if (-not $python) { Fail 'Python установился, но не найден. Перезагрузите компьютер и запустите установку ещё раз.' }
}
Write-Ok "Python: $python"

# --- FFmpeg ---------------------------------------------------------------
Write-Step 'Проверяю FFmpeg'
$ffmpegDir = Find-FFmpegDir
if (-not $ffmpegDir) {
    if (-not $hasWinget) {
        Fail 'FFmpeg не найден, и winget тоже. Установите FFmpeg вручную (https://www.gyan.dev/ffmpeg/builds/) и добавьте папку bin в PATH.'
    }
    Install-WithWinget 'Gyan.FFmpeg' 'FFmpeg'
    $ffmpegDir = Find-FFmpegDir
    if (-not $ffmpegDir) { Fail 'FFmpeg установился, но не найден. Перезагрузите компьютер и запустите установку ещё раз.' }
}
if (-not (Test-Path (Join-Path $ffmpegDir 'ffprobe.exe'))) {
    Fail "В папке $ffmpegDir нет ffprobe.exe — нужна полная сборка FFmpeg."
}
Write-Ok "FFmpeg: $ffmpegDir"

# --- сохраняем пути для запуска -------------------------------------------
@{ python = $python; ffmpeg_dir = $ffmpegDir } | ConvertTo-Json | Set-Content -Path $ConfigFile -Encoding UTF8
Write-Ok 'Пути сохранены в installer\config.json'

# --- тесты ----------------------------------------------------------------
Write-Step 'Проверяю, что всё работает (автотесты)'
$env:Path = "$ffmpegDir;$env:Path"
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $ProjectDir
try {
    & $python -m unittest discover -s tests
    $testCode = $LASTEXITCODE
} finally { Pop-Location }
if ($testCode -ne 0) { Fail 'Тесты не прошли. Пришлите текст выше Claude — разберёмся.' }
Write-Ok 'Все тесты прошли'

# --- ярлык на рабочем столе ----------------------------------------------
Write-Step 'Создаю ярлык на рабочем столе'
try {
    $desktop  = [Environment]::GetFolderPath('Desktop')
    $lnkPath  = Join-Path $desktop 'Audio Normalizer.lnk'
    $shell    = New-Object -ComObject WScript.Shell
    $lnk      = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath       = Join-Path $ProjectDir 'Audio Normalizer.bat'
    $lnk.WorkingDirectory = $ProjectDir
    $lnk.Description      = 'Batch Audio Normalizer — перетащите сюда папку с аудио'
    $lnk.IconLocation     = "$env:SystemRoot\System32\SndVol.exe,0"
    $lnk.Save()
    Write-Ok "Ярлык: $lnkPath"
} catch {
    Write-Warn2 "Ярлык создать не удалось ($($_.Exception.Message)). Запускайте 'Audio Normalizer.bat' из папки программы."
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host '   Готово!' -ForegroundColor Green
Write-Host '   Перетащите папку с аудио на ярлык "Audio Normalizer"' -ForegroundColor Green
Write-Host '   или дважды кликните по нему и выберите папку.' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
