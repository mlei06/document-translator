# Creates a workbook whose formulas depend on translatable labels, authored in native Excel so the
# formula caches are real Excel values. Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File docs/experiments/xlsx-recalc/make_fixture.ps1
# Writes data/experiments/xlsx-recalc/labels.xlsx. Synthetic content only.
$ErrorActionPreference = 'Stop'
$out = Join-Path (Get-Location) 'data\experiments\xlsx-recalc'
New-Item -ItemType Directory -Force $out | Out-Null
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
    $book = $xl.Workbooks.Add()
    $data = $book.Worksheets.Item(1)
    $data.Name = '数据'
    $data.Range('A1').Value2 = '苹果'; $data.Range('B1').Value2 = 10
    $data.Range('A2').Value2 = '香蕉'; $data.Range('B2').Value2 = 20
    $data.Range('A3').Value2 = '苹果'; $data.Range('B3').Value2 = 30
    $data.Range('C1').Formula = '=COUNTIF(A1:A3,"苹果")'
    $data.Range('C2').Formula = '=A1&"汇总"'
    $data.Range('C3').Formula = '=IF(A2="香蕉","是","否")'
    $data.Range('C4').Formula = '=SUMIF(A1:A3,"苹果",B1:B3)'
    $data.Range('C5').Formula = '=VLOOKUP("香蕉",A1:B3,2,FALSE)'
    $data.Range('C6').Formula = '=SUM(B1:B3)'
    $sum = $book.Worksheets.Add([Type]::Missing, $data)
    $sum.Name = '汇总'
    $sum.Range('A1').Value2 = '苹果数量'
    $sum.Range('B1').Formula = "='数据'!C1"
    $book.SaveAs((Join-Path $out 'labels.xlsx'), 51)  # xlOpenXMLWorkbook
    $book.Close($false)
    'xlsx: written'
} finally { $xl.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null }
