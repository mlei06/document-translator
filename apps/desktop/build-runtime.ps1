# Development packaging only. Signing and approved release provisioning are separate gates.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$output = Join-Path $repo 'data/desktop-build'
New-Item -ItemType Directory -Force $output | Out-Null
$desktopBuildSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $output /inheritance:r /grant:r "*${desktopBuildSid}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict private build directory' }
Push-Location $repo
try {
    uv pip install --python .venv/Scripts/python.exe pyinstaller==6.22.3 pyinstaller-hooks-contrib==2026.8
    if ($LASTEXITCODE -ne 0) { throw "Packaging dependency installation failed" }
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm --onedir --console `
        --name doctranslator-server --distpath "$output/dist" --workpath "$output/build" `
        --specpath $output --paths packages/core/src --paths apps/server/src `
        --collect-all ctranslate2 --collect-all sentencepiece --collect-all doctranslator_core `
        --collect-all doctranslator_server --collect-all uvicorn `
        --copy-metadata doctranslator-core --copy-metadata doctranslator-server `
        apps/desktop/runtime_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Runtime build failed' }
    Copy-Item -Recurse -Force apps/server/migrations "$output/dist/doctranslator-server/migrations"
    Write-Output "Development runtime: $output/dist/doctranslator-server"
} finally { Pop-Location }
