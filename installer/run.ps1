# Batch Audio Normalizer — запуск с меню.
# Перетащите папку/файл на "Audio Normalizer.bat" или запустите его и выберите папку.

param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Items)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$InstallerDir = $PSScriptRoot
$ProjectDir   = Split-Path -Parent $InstallerDir
$ConfigFile   = Join-Path $InstallerDir 'config.json'

function Stop-WithPause($text, $color = 'Red') {
    Write-Host ''
    Write-Host $text -ForegroundColor $color
    Read-Host 'Нажмите Enter, чтобы закрыть' | Out-Null
    exit 1
}

if (-not (Test-Path $ConfigFile)) {
    Stop-WithPause 'Программа ещё не установлена. Сначала запустите "Установить.bat" в папке программы.'
}
$cfg = Get-Content $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path $cfg.python)) {
    Stop-WithPause 'Не найден Python. Запустите "Установить.bat" ещё раз.'
}
$env:Path = "$($cfg.ffmpeg_dir);$env:Path"
$env:PYTHONIOENCODING = 'utf-8'

# --- что обрабатываем -----------------------------------------------------
$target = $null
if ($Items -and $Items.Count -gt 0) { $target = $Items[0].Trim('"') }
if (-not $target) {
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = 'Выберите папку с аудиофайлами'
    $dlg.ShowNewFolderButton = $false
    if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $target = $dlg.SelectedPath
}
if (-not (Test-Path -LiteralPath $target)) { Stop-WithPause "Не найдено: $target" }

Write-Host '==============================================' -ForegroundColor Cyan
Write-Host '   Batch Audio Normalizer' -ForegroundColor Cyan
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host "Источник: $target"
Write-Host ''
Write-Host '  1  Только анализ (ничего не меняет, только отчёт)'
Write-Host '  2  Spotify / YouTube   -14 LUFS   WAV 24 бит'
Write-Host '  3  Apple Music         -16 LUFS   WAV 24 бит'
Write-Host '  4  Подкаст стерео      -16 LUFS   MP3 320k'
Write-Host '  5  Подкаст моно        -19 LUFS   MP3 192k'
Write-Host '  6  Аудиокнига ACX      MP3 192k, 44.1 kHz, моно + проверка ACX'
Write-Host '  7  Broadcast EBU R128  -23 LUFS   WAV 24 бит'
Write-Host '  8  Свой уровень (ввести LUFS и True Peak)'
Write-Host ''
$choice = Read-Host 'Выберите вариант (1-8)'

switch ($choice) {
    '1' { $opts = @('--analyze', '--acx-check') }
    '2' { $opts = @('--preset', 'spotify', '--format', 'wav', '--bits', '24') }
    '3' { $opts = @('--preset', 'apple', '--format', 'wav', '--bits', '24') }
    '4' { $opts = @('--preset', 'podcast', '--format', 'mp3', '--mp3-bitrate', '320k') }
    '5' { $opts = @('--preset', 'podcast-mono', '--format', 'mp3', '--mp3-bitrate', '192k', '--mono') }
    '6' { $opts = @('--preset', 'acx', '--format', 'mp3', '--mp3-bitrate', '192k', '--sr', '44100', '--mono', '--acx-check') }
    '7' { $opts = @('--preset', 'broadcast', '--format', 'wav', '--bits', '24') }
    '8' {
        $lufs = (Read-Host 'Целевой LUFS, например -14').Replace(',', '.')
        $tp   = (Read-Host 'True Peak в dBTP, например -1').Replace(',', '.')
        $fmt  = Read-Host 'Формат: wav / flac / mp3 (Enter = wav)'
        if (-not $fmt) { $fmt = 'wav' }
        $opts = @("--lufs=$lufs", "--tp=$tp", '--format', $fmt)
    }
    default { Stop-WithPause 'Неизвестный вариант.' }
}

$item = Get-Item -LiteralPath $target
if ($item.PSIsContainer) { $outDir = Join-Path $item.FullName 'normalized' }
else                     { $outDir = Join-Path $item.DirectoryName 'normalized' }

Write-Host ''
Push-Location $ProjectDir
try {
    & $cfg.python 'normalize.py' $item.FullName '--recursive' @opts
    $code = $LASTEXITCODE
} finally { Pop-Location }

Write-Host ''
if (Test-Path -LiteralPath $outDir) {
    Write-Host "Результат и report.csv: $outDir" -ForegroundColor Green
    Start-Process explorer.exe -ArgumentList "`"$outDir`""
}
if ($code -ne 0) { Write-Host 'Некоторые файлы не обработались — смотрите строки ERROR выше и колонку notes в отчёте.' -ForegroundColor Yellow }
Read-Host 'Нажмите Enter, чтобы закрыть' | Out-Null
