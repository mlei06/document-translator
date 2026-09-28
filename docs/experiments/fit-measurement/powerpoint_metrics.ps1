# Reads PowerPoint's own layout of every case text box: line count and text bounds (points).
# Run from the repository root after make_cases.py:
#   powershell -ExecutionPolicy Bypass -File docs/experiments/fit-measurement/powerpoint_metrics.ps1
# Writes data/experiments/fit-measurement/powerpoint.json.
$ErrorActionPreference = 'Stop'
$deck = (Resolve-Path 'data\experiments\fit-measurement\cases.pptx').Path
$out = Join-Path (Split-Path $deck) 'powerpoint.json'
$pp = New-Object -ComObject PowerPoint.Application
try {
    $pres = $pp.Presentations.Open($deck, -1, 0, 0)  # read-only, no window
    $rows = @()
    foreach ($slide in $pres.Slides) {
        foreach ($shape in $slide.Shapes) {
            if (-not $shape.HasTextFrame -or $shape.Name -notmatch '^c\d{3}$') { continue }
            $range = $shape.TextFrame.TextRange
            $lines = 0
            for ($i = 1; $i -le 500; $i++) {
                if ($range.Lines($i, 1).Length -eq 0) { break }
                $lines = $i
            }
            $text2 = $shape.TextFrame2.TextRange
            $rows += [ordered]@{
                id = $shape.Name
                lines = $lines
                bound_height = [double] $text2.BoundHeight
                bound_width = [double] $text2.BoundWidth
                bound_top = [double] $text2.BoundTop
                shape_top = [double] $shape.Top
                margin_top = [double] $shape.TextFrame2.MarginTop
                shape_width = [double] $shape.Width
                margin_left = [double] $shape.TextFrame2.MarginLeft
                margin_right = [double] $shape.TextFrame2.MarginRight
            }
        }
    }
    $pres.Close()
    [ordered]@{ version = $pp.Version; build = $pp.Build; cases = $rows } | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $out
    "cases: $($rows.Count) -> $out"
} finally { $pp.Quit() }
