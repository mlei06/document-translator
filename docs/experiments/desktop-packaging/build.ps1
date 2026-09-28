# Run from the repository root after the README's build-environment setup.
# Generated binaries, logs and reports stay under ignored data/.
$ErrorActionPreference = 'Stop'
$experimentRoot = Join-Path (Get-Location) 'data/experiments/desktop-packaging'
New-Item -ItemType Directory -Force -Path $experimentRoot | Out-Null
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
& $python -m PyInstaller --noconfirm --onedir --console --name doctranslator-runtime `
    --distpath "$experimentRoot/dist" --workpath "$experimentRoot/build" `
    --specpath $experimentRoot `
    --paths packages/core/src --paths apps/cli/src `
    --collect-all ctranslate2 --collect-all sentencepiece `
    --copy-metadata doctranslator-core --copy-metadata doctranslator-cli `
    --copy-metadata keyring `
    docs/experiments/desktop-packaging/entry.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Bundle: $experimentRoot/dist/doctranslator-runtime"
