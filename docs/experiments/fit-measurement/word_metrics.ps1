# Reads Word's own layout of the comparison document: lines per table cell and text box, and the
# vertical distance between successive lines. Read-only; nothing is saved (Word saves hang on the
# experiment host). Run from the repository root after make_word_cases.py:
#   powershell -ExecutionPolicy Bypass -File docs/experiments/fit-measurement/word_metrics.ps1
# Writes data/experiments/fit-measurement/word.json.
$ErrorActionPreference = 'Stop'
$path = (Resolve-Path 'data\experiments\fit-measurement\word-cases.docx').Path
$out = Join-Path (Split-Path $path) 'word.json'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

function Measure-Range($range) {
    $lines = $range.ComputeStatistics(1)  # wdStatisticLines
    $first = $range.Characters.Item(1).Information(6)  # wdVerticalPositionRelativeToPage
    $last = $range.Characters.Item($range.Characters.Count).Information(6)
    $pitch = if ($lines -gt 1) { ($last - $first) / ($lines - 1) } else { $null }
    return @{ lines = $lines; first_y = $first; last_y = $last; pitch = $pitch }
}

try {
    $m = [Reflection.Missing]::Value
    $doc = $word.Documents.Open($path, $false, $true, $false, $m, $m, $m, $m, $m, $m, $m, $false, $false)
    $doc.Repaginate()
    $rows = @()
    $table = $doc.Tables.Item(1)
    for ($r = 1; $r -le $table.Rows.Count; $r++) {
        for ($c = 1; $c -le 3; $c++) {
            $range = $table.Cell($r, $c).Range
            $range.MoveEnd(1, -1) | Out-Null  # exclude the end-of-cell mark
            $metrics = Measure-Range $range
            $rows += [ordered]@{ id = "t1/r$($r)c$($c)"; lines = $metrics.lines; pitch = $metrics.pitch }
        }
    }
    foreach ($shape in $doc.Shapes) {
        if ($shape.Name -notmatch '^textbox\d+$') { continue }
        $range = $shape.TextFrame.TextRange
        if ($null -eq $range) { $rows += [ordered]@{ id = $shape.Name; error = 'no text range' }; continue }
        $range.MoveEnd(1, -1) | Out-Null
        $metrics = Measure-Range $range
        $rows += [ordered]@{ id = $shape.Name; lines = $metrics.lines; pitch = $metrics.pitch }
    }
    $doc.Close(0)
    [ordered]@{ version = $word.Version; build = $word.Build; cases = $rows } | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $out
    "cases: $($rows.Count) -> $out"
} finally { $word.Quit() }
