# Creates synthetic PPTX and DOCX fixtures with native PowerPoint and Word (COM automation).
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File docs/experiments/ooxml-roundtrip/make_fixtures.ps1 [-Part all|pptx|docx]
# Writes data/experiments/ooxml-roundtrip/fixtures/{deck.pptx,report.docx}. Synthetic text only.
# PowerPoint opens a window briefly: charts need a presentation window. Office automation is slow
# on this host (about a minute per application start).
param([ValidateSet('all', 'pptx', 'docx')] [string] $Part = 'all')

$ErrorActionPreference = 'Stop'
$out = Join-Path (Get-Location) 'data\experiments\ooxml-roundtrip\fixtures'
New-Item -ItemType Directory -Force $out | Out-Null

if ($Part -in 'all', 'pptx') {
    $pp = New-Object -ComObject PowerPoint.Application
    try {
        $pres = $pp.Presentations.Add(-1)
        # Slide 1: title layout placeholders and speaker notes
        $s1 = $pres.Slides.Add(1, 1)
        $s1.Shapes.Item(1).TextFrame.TextRange.Text = '季度业务回顾'
        $s1.Shapes.Item(2).TextFrame.TextRange.Text = '销售部 2026年第三季度'
        $s1.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = '演讲者备注：先介绍团队，再讲结果。'
        # Slide 2: bullets with rich runs and a hyperlink
        $s2 = $pres.Slides.Add(2, 2)
        $s2.Shapes.Item(1).TextFrame.TextRange.Text = '主要结果'
        $body = $s2.Shapes.Item(2).TextFrame.TextRange
        $body.Text = "销售额增长了百分之十二`r利润率保持稳定`r详情请见内部网站"
        $body.Paragraphs(1).Characters(1, 3).Font.Bold = -1
        $body.Paragraphs(1).Characters(1, 3).Font.Color.RGB = 255
        $body.Paragraphs(2).Characters(3, 2).Font.Italic = -1
        $body.Paragraphs(3).Characters(4, 4).ActionSettings(1).Hyperlink.Address = 'https://intranet.example.com/q3'
        # Slide 3: table, grouped shapes, text box and slide-number field
        $s3 = $pres.Slides.Add(3, 12)
        $tbl = $s3.Shapes.AddTable(3, 2, 40, 40, 400, 120).Table
        $cells = @(@('地区', '收入'), @('华东', '1,250 万元'), @('华南', '980 万元'))
        for ($r = 0; $r -lt 3; $r++) { for ($c = 0; $c -lt 2; $c++) { $tbl.Cell($r + 1, $c + 1).Shape.TextFrame.TextRange.Text = $cells[$r][$c] } }
        $a = $s3.Shapes.AddShape(1, 60, 220, 160, 60); $a.TextFrame.TextRange.Text = '第一步：收集数据'
        $b = $s3.Shapes.AddShape(1, 260, 220, 160, 60); $b.TextFrame.TextRange.Text = '第二步：分析趋势'
        $s3.Shapes.Range([string[]]@($a.Name, $b.Name)).Group() | Out-Null
        $tb = $s3.Shapes.AddTextbox(1, 460, 40, 220, 80); $tb.TextFrame.TextRange.Text = '注意：数据截至九月底'
        $num = $s3.Shapes.AddTextbox(1, 620, 480, 80, 30); $num.TextFrame.TextRange.InsertSlideNumber() | Out-Null
        # Slide 4: a chart, content outside the translation scope that must survive
        $s4 = $pres.Slides.Add(4, 12)
        $chart = $s4.Shapes.AddChart2(-1, 51, 460, 40, 300, 250)
        $chart.Chart.ChartData.Workbook.Close()
        $pres.SaveAs((Join-Path $out 'deck.pptx'), 24)
        $pres.Close()
        'pptx: written'
    } finally { $pp.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null }
}

if ($Part -in 'all', 'docx') {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try {
        $doc = $word.Documents.Add()
        function Add-Para([string] $text) {
            $doc.Content.InsertParagraphAfter()
            $p = $doc.Paragraphs.Item($doc.Paragraphs.Count)
            $p.Range.InsertBefore($text)
            return $doc.Paragraphs.Item($doc.Paragraphs.Count)
        }
        $doc.Paragraphs.Item(1).Range.Text = '项目进度报告'
        $doc.Paragraphs.Item(1).Style = -2  # Heading 1
        $p2 = Add-Para '本项目已完成第一阶段的全部工作。'
        $p2.Style = -1
        $s = $p2.Range.Start
        $doc.Range($s + 5, $s + 9).Font.Bold = 1
        $fn = $doc.Footnotes.Add($doc.Range($p2.Range.End - 1, $p2.Range.End - 1))
        $fn.Range.Text = '数据来源：内部系统。'
        'docx: rich run and footnote'
        $p3 = Add-Para '更多信息请访问项目主页。'
        $s = $p3.Range.Start
        $doc.Hyperlinks.Add($doc.Range($s + 7, $s + 11), 'https://intranet.example.com/project') | Out-Null
        'docx: hyperlink'
        # Fields are not authored here: a document with fields made Word's save hang behind a
        # hidden prompt in this automation context. XML-built test fixtures cover fields.
        Add-Para '报告日期：九月三十日' | Out-Null
        $p5 = Add-Para ''
        $t = $doc.Tables.Add($p5.Range, 2, 2)
        $t.Borders.Enable = 1
        $t.Cell(1, 1).Range.Text = '任务'
        $t.Cell(1, 2).Range.Text = '状态'
        $t.Cell(2, 1).Range.Text = '需求分析'
        $inner = $t.Cell(2, 2).Tables.Add($t.Cell(2, 2).Range, 1, 2)
        $inner.Cell(1, 1).Range.Text = '已完成'
        $inner.Cell(1, 2).Range.Text = '九月'
        'docx: nested table'
        $box = $doc.Shapes.AddTextbox(1, 300, 400, 180, 60)
        $box.TextFrame.TextRange.Text = '重要提示：请按时提交'
        'docx: text box'
        $sec = $doc.Sections.Item(1)
        $sec.Headers.Item(1).Range.Text = '内部资料 请勿外传'
        $sec.Footers.Item(1).Range.Text = '版权所有'
        'docx: header and footer'
        # Comments and tracked changes are not authored here: with them, Word's save waits on a
        # hidden privacy prompt (the user's "warn before saving markup" option, which this script
        # does not change). XML-built test fixtures cover them.
        # Save under %TEMP% first: saving directly into the repository folder hung behind a
        # hidden prompt on this host.
        $tmp = Join-Path $env:TEMP 'doctranslator-report.docx'
        $doc.SaveAs2($tmp, 16)
        $doc.Close(0)
        Move-Item -Force $tmp (Join-Path $out 'report.docx')
        'docx: written'
    } finally { $word.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null }
}

Get-ChildItem $out | Select-Object Name, Length
