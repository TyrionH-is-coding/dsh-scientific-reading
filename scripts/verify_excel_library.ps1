param([Parameter(Mandatory=$true)][string]$DataRoot)
$ErrorActionPreference = 'Stop'
$dataPath = (Resolve-Path -LiteralPath $DataRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $dataPath '.excel-test-fixture'))) { throw '仅接受隔离的 Excel 验收夹具' }
$file = [System.IO.Path]::GetFullPath((Join-Path $dataPath 'library/scientific-reading.xlsx'))
$excel = New-Object -ComObject Excel.Application
$book = $null
try {
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $book = $excel.Workbooks.Open($file, 0, $false)
  if ($book.ReadOnly) { throw '工作簿被只读打开' }
  $sheet = $book.Worksheets.Item('文献')
  if ($sheet.ListObjects.Count -ne 1) { throw '缺少原生表格' }
  $headers = @{}
  for ($col = 1; $col -le $sheet.UsedRange.Columns.Count; $col++) { $headers[$sheet.Cells.Item(1, $col).Value2] = $col }
  $paperId = $sheet.Cells.Item(2, $headers['文献 ID']).Value2
  $sheet.Cells.Item(2, $headers['用户笔记']).Value2 = '原生 Excel 排序回写验证'
  $sheet.Cells.Item(2, $headers['阅读进度']).Value2 = '待复读'
  $table = $sheet.ListObjects.Item(1)
  $table.Sort.SortFields.Clear()
  $null = $table.Sort.SortFields.Add($table.ListColumns.Item('文献名').Range, 0, 2)
  $table.Sort.Header = 1
  $table.Sort.Apply()
  $excel.CalculateFullRebuild()
  $formulas = 0
  foreach ($tabName in @('文献','阅读成果','图表索引')) {
    $tab = $book.Worksheets.Item($tabName)
    foreach ($cell in $tab.UsedRange.Cells) {
      if ($cell.HasFormula) {
        $formulas++
        if ([string]$cell.Text -match '^#(REF!|VALUE!|NAME\?|N/A|NUM!)') { throw "无效链接公式：$tabName $($cell.Address())" }
      }
    }
  }
  $book.Save()
  $sheet.PageSetup.PrintArea = '$A$1:$I$4'
  $sheet.ExportAsFixedFormat(0, (Join-Path $dataPath 'native-excel-preview.pdf'))
  @{ excelVersion=$excel.Version; paperId=$paperId; formulas=$formulas; sort='whole_table'; saved=$true } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataPath 'native-excel-result.json') -Encoding UTF8
} finally {
  if ($null -ne $book) { $book.Close($false) }
  $excel.Quit()
  [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
}
