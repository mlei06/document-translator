<#
.SYNOPSIS
Opens Office documents in the native Microsoft Office application and records whether they open
cleanly. Used for native-open evidence (P2-P6 release matrix); a library reopen is not a substitute.

.DESCRIPTION
For each file: opens it read-only in PowerPoint (.pptx), Word (.docx) or Excel (.xlsx) without
repair, optionally exports a PDF next to -OutDir for visual inspection, and for workbooks lists the
values of formula cells after Excel's load-time recalculation. Prints one JSON object per file:
{file, app, version, build, ok, error, pdf, formulas}. Exit code 1 if any file failed to open.

A file that needs repair fails instead of being silently fixed: Word opens with OpenAndRepair=false,
PowerPoint throws on corrupt content, and Excel's open either fails or yields a "[Repaired]" workbook,
which is reported as a failure (verified with a truncated-XML workbook). Excel is opened with
UpdateLinks=0 so external links are never refreshed. Word's PDF export hangs on some hosts (a hidden
prompt); use -NoPdf there.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts/native_office_check.ps1 -OutDir data/native out.pptx out.docx
#>
param(
    [string] $OutDir = '',
    [switch] $NoPdf,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Files
)

$ErrorActionPreference = 'Stop'
$failed = $false
if ($OutDir) { New-Item -ItemType Directory -Force $OutDir | Out-Null; $OutDir = (Resolve-Path $OutDir).Path }

function Emit($record) { $record | ConvertTo-Json -Compress -Depth 5 }

$apps = @{}
function Get-App([string] $kind) {
    if (-not $apps.ContainsKey($kind)) {
        switch ($kind) {
            'pptx' { $a = New-Object -ComObject PowerPoint.Application }
            'docx' { $a = New-Object -ComObject Word.Application; $a.Visible = $false; $a.DisplayAlerts = 0 }
            'xlsx' { $a = New-Object -ComObject Excel.Application; $a.Visible = $false; $a.DisplayAlerts = $false; $a.AskToUpdateLinks = $false }
        }
        $apps[$kind] = $a
    }
    return $apps[$kind]
}

foreach ($file in $Files) {
    $path = (Resolve-Path $file).Path
    $kind = [IO.Path]::GetExtension($path).TrimStart('.').ToLowerInvariant()
    $record = [ordered]@{ file = $path; app = $kind; version = $null; build = $null; ok = $false; error = $null; pdf = $null; formulas = $null }
    $pdf = if ($OutDir -and -not $NoPdf) { Join-Path $OutDir ([IO.Path]::GetFileName($path) + '.pdf') } else { $null }
    try {
        $app = Get-App $kind
        $record.version = $app.Version
        $record.build = $app.Build
        switch ($kind) {
            'pptx' {
                # ReadOnly, Untitled=false, WithWindow=false
                $doc = $app.Presentations.Open($path, -1, 0, 0)
                if ($pdf) { $doc.SaveAs($pdf, 32); $record.pdf = $pdf }  # ppSaveAsPDF
                $doc.Close()
            }
            'docx' {
                # FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, ..., OpenAndRepair (arg 13)
                $m = [Reflection.Missing]::Value
                $doc = $app.Documents.Open($path, $false, $true, $false, $m, $m, $m, $m, $m, $m, $m, $false, $false)
                if ($pdf) { $doc.ExportAsFixedFormat($pdf, 17); $record.pdf = $pdf }  # wdExportFormatPDF
                $doc.Close(0)
            }
            'xlsx' {
                # FileName, UpdateLinks=0, ReadOnly. Passing CorruptLoad (arg 15) through PowerShell
                # makes Workbooks.Open fail for valid files, so a repaired open is detected by the
                # "[Repaired]" suffix Excel gives the workbook (verified with a corrupted file).
                $book = $app.Workbooks.Open($path, 0, $true)
                if ($book.Name -match 'Repaired') { $book.Close($false); throw "Excel repaired the workbook ($($book.Name))" }
                $values = @()
                foreach ($sheet in $book.Worksheets) {
                    $used = $sheet.UsedRange
                    foreach ($cell in $used.Cells) {
                        if ($cell.HasFormula -and $values.Count -lt 200) {
                            $values += [ordered]@{ sheet = $sheet.Name; cell = $cell.Address($false, $false); formula = $cell.Formula; value = [string] $cell.Text }
                        }
                    }
                }
                $record.formulas = $values
                if ($pdf) { $book.ExportAsFixedFormat(0, $pdf); $record.pdf = $pdf }  # xlTypePDF
                $book.Close($false)
            }
            default { throw "unsupported extension: $kind" }
        }
        $record.ok = $true
    } catch {
        $record.error = $_.Exception.Message
        $failed = $true
    }
    Emit $record
}

foreach ($a in $apps.Values) {
    try { $a.Quit() } catch { }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($a) | Out-Null
}
if ($failed) { exit 1 }
