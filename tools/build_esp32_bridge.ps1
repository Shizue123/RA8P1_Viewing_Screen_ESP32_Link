$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$arduinoCli = Join-Path $workspaceRoot ".tools\arduino-cli\arduino-cli.exe"
$sketchDir = Join-Path $workspaceRoot "esp32-s3-uart-link-arduino\esp32_s3_uart_link"
$buildDir = Join-Path $sketchDir "build\esp32.esp32.esp32s3"
$fqbn = "esp32:esp32:esp32s3"

if (-not (Test-Path $arduinoCli)) {
    throw "arduino-cli not found: $arduinoCli"
}

if (-not (Test-Path $sketchDir)) {
    throw "sketch dir not found: $sketchDir"
}

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

& $arduinoCli compile `
    --fqbn $fqbn `
    --output-dir $buildDir `
    $sketchDir

Write-Host ""
Write-Host "Build completed."
Get-ChildItem $buildDir |
    Where-Object { $_.Name -match "esp32_s3_uart_link\\.ino\\.(bin|elf|map)$" -or $_.Name -eq "esp32_s3_uart_link.ino.merged.bin" } |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize
