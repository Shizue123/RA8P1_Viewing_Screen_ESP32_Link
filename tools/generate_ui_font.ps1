$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$uiSource = Join-Path $workspaceRoot "src\app_ui.c"
$fontSource = Join-Path $workspaceRoot "UI\fonts\NotoSansCJKsc-Regular.otf"
$fontOutput = Join-Path $workspaceRoot "src\ui_font_sc_14.c"

if (-not (Test-Path $uiSource)) {
    throw "UI source not found: $uiSource"
}
if (-not (Test-Path $fontSource)) {
    throw "Font source not found: $fontSource"
}

$symbols = @'
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const symbols = [...new Set(source.match(/[\u3400-\u9fff]/g) || [])].sort();
process.stdout.write(symbols.join(""));
'@ | node - $uiSource

if ([string]::IsNullOrWhiteSpace($symbols)) {
    throw "No Chinese symbols found in app_ui.c"
}

Push-Location $workspaceRoot
try {
    npx --yes lv_font_conv `
        --size 14 `
        --bpp 1 `
        --format lvgl `
        --font $fontSource `
        -r "0x20-0x7E" `
        --symbols $symbols `
        --no-compress `
        --no-prefilter `
        --no-kerning `
        --lv-include "lvgl.h" `
        --lv-font-name "ui_font_sc_14" `
        --lv-fallback "lv_font_montserrat_14" `
        -o $fontOutput

    $generated = [System.IO.File]::ReadAllText($fontOutput).TrimEnd()
    [System.IO.File]::WriteAllText($fontOutput, $generated + [Environment]::NewLine)
}
finally {
    Pop-Location
}

Write-Host "Generated ui_font_sc_14.c with $($symbols.Length) Chinese symbols."
