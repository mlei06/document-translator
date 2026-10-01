param([Parameter(Mandatory=$true)][string]$InstallDir, [switch]$Remove, [switch]$CheckPaths)
$ErrorActionPreference = 'Stop'
$expected = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs/Lenny Translator'
if ([IO.Path]::GetFullPath($InstallDir).TrimEnd('\') -ne [IO.Path]::GetFullPath($expected).TrimEnd('\')) { throw 'Unexpected application directory' }
if ($CheckPaths) {
    $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ([IO.Path]::GetFullPath($_.ExecutablePath).StartsWith([IO.Path]::GetFullPath($InstallDir) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) -and $_.Name -ne 'Uninstall.exe' }
    if ($running) { throw 'Application processes have not finished shutting down' }
    foreach ($candidate in @($InstallDir, (Join-Path $InstallDir 'runtime'))) {
        if (Test-Path -LiteralPath $candidate) {
            if ((Get-Item -LiteralPath $candidate).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point refused' }
            if (Get-ChildItem -LiteralPath $candidate -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Nested reparse point refused' }
        }
    }
    exit 0
}
if ($Remove) {
    Get-AppxPackage -Name Lenny.Translator | Remove-AppxPackage -ErrorAction Stop
} else {
    Add-AppxPackage -Path (Join-Path $InstallDir 'Lenny.Identity.msix') -ExternalLocation $InstallDir -ErrorAction Stop
}
