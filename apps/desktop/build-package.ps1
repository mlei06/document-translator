param(
    [string]$Publisher = 'CN=Lenny Development',
    [string]$CertificateThumbprint,
    [switch]$Release,
    [switch]$SkipRuntimeBuild,
    [switch]$DevelopmentBuild
)
$ErrorActionPreference = 'Stop'
$desktopRepo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$desktopOutput = Join-Path $desktopRepo 'data/desktop-build'
$desktopPayload = Join-Path $desktopOutput 'payload'
$desktopSdk = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin/10.0.26100.0/x64'
if ($Release -and $DevelopmentBuild) { throw 'Release cannot contain a development shell' }
if ($Release -and !$CertificateThumbprint) { throw 'A trusted release signing certificate is required' }
New-Item -ItemType Directory -Force $desktopOutput | Out-Null
$desktopBuildSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $desktopOutput /inheritance:r /grant:r "*${desktopBuildSid}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict private build directory' }
Push-Location $desktopRepo
try {
    if (!$SkipRuntimeBuild) { & "$PSScriptRoot/build-runtime.ps1" }
    $desktopProfile = if ($DevelopmentBuild) { "debug" } else { "release" }
    $desktopCargoArgs = @("build", "-j", "2", "--manifest-path", "apps/desktop/src-tauri/Cargo.toml")
    if (!$DevelopmentBuild) { $desktopCargoArgs += "--release" }
    & "$env:USERPROFILE/.cargo/bin/cargo.exe" @desktopCargoArgs
    if ($LASTEXITCODE -ne 0) { throw 'Native shell build failed' }
    cmd /c apps\desktop\explorer\build.cmd
    if ($LASTEXITCODE -ne 0) { throw 'Explorer extension build failed' }
    New-Item -ItemType Directory -Force $desktopPayload | Out-Null
    Copy-Item "apps/desktop/src-tauri/target/$desktopProfile/lenny-desktop.exe" $desktopPayload -Force
    Copy-Item apps/desktop/src-tauri/target/lenny-explorer.dll $desktopPayload -Force
    Copy-Item apps/desktop/src-tauri/icons/icon.png $desktopPayload -Force
    Copy-Item apps/desktop/installer/register-explorer.ps1 $desktopPayload -Force
    New-Item -ItemType Directory -Force "$desktopPayload/runtime" | Out-Null
    Copy-Item "$desktopOutput/dist/doctranslator-server/*" "$desktopPayload/runtime" -Recurse -Force
    $desktopResourceArgs = @("run", "python", "scripts/prepare_desktop_resources.py")
    if ($CertificateThumbprint) { $desktopResourceArgs += @("--certificate-thumbprint", $CertificateThumbprint) }
    uv @desktopResourceArgs
    if ($LASTEXITCODE -ne 0) { throw "Runtime resource preparation failed" }
    $desktopSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $desktopPayload /inheritance:r /grant:r "*${desktopSid}:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot restrict private payload access" }
    Copy-Item "$desktopOutput/resources/*" "$desktopPayload/runtime" -Recurse -Force
    $desktopSparse = Join-Path $desktopOutput 'sparse'
    New-Item -ItemType Directory -Force $desktopSparse | Out-Null
    $desktopManifest = (Get-Content apps/desktop/explorer/AppxManifest.xml.in -Raw).Replace('@PUBLISHER@', [System.Security.SecurityElement]::Escape($Publisher))
    Set-Content -LiteralPath "$desktopSparse/AppxManifest.xml" -Value $desktopManifest -Encoding utf8
    Copy-Item apps/desktop/src-tauri/icons/icon.png $desktopSparse -Force
    & "$desktopSdk/makeappx.exe" pack /d $desktopSparse /p "$desktopPayload/Lenny.Identity.msix" /o /nv
    if ($LASTEXITCODE -ne 0) { throw 'Sparse package validation failed' }
    if ($CertificateThumbprint) {
        foreach ($desktopBinary in @("$desktopPayload/lenny-desktop.exe", "$desktopPayload/lenny-explorer.dll", "$desktopPayload/runtime/doctranslator-server.exe", "$desktopPayload/Lenny.Identity.msix")) {
            & "$desktopSdk/signtool.exe" sign /sha1 $CertificateThumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $desktopBinary
            if ($LASTEXITCODE -ne 0) { throw 'Artifact signing failed' }
            & "$desktopSdk/signtool.exe" verify /pa $desktopBinary
            if ($LASTEXITCODE -ne 0) { throw 'Artifact signature validation failed' }
        }
    }
    Copy-Item apps/desktop/installer/setup.nsi "$desktopOutput/setup.nsi" -Force
    & "${env:ProgramFiles(x86)}/NSIS/makensis.exe" "/DAppPayload=$desktopPayload" "/DOutputPath=$desktopOutput/Lenny-Translator-Online-Setup.exe" "$desktopOutput/setup.nsi"
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
    if ($CertificateThumbprint) {
        & "$desktopSdk/signtool.exe" sign /sha1 $CertificateThumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "$desktopOutput/Lenny-Translator-Online-Setup.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Installer signing failed' }
    }
    $desktopMedia = Join-Path $desktopOutput 'offline-media'
    New-Item -ItemType Directory -Force $desktopMedia | Out-Null
    Copy-Item data/models/gguf/HY-MT1.5-1.8B-Q8_0.gguf $desktopMedia -Force
    & "${env:ProgramFiles(x86)}/NSIS/makensis.exe" "/DAppPayload=$desktopPayload" "/DOfflinePayload=$desktopMedia" "/DOutputPath=$desktopOutput/Lenny-Translator-Offline-Setup.exe" "$desktopOutput/setup.nsi"
    if ($LASTEXITCODE -ne 0) { throw 'Full offline installer build failed' }
    if ($CertificateThumbprint) {
        & "$desktopSdk/signtool.exe" sign /sha1 $CertificateThumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "$desktopOutput/Lenny-Translator-Offline-Setup.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Full offline installer signing failed' }
    }
    Write-Output "Built private installer: $desktopOutput/Lenny-Translator-Online-Setup.exe"
} finally { Pop-Location }
