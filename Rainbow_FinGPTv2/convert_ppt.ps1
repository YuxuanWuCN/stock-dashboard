
 = New-Object -ComObject PowerPoint.Application
 = [System.IO.Path]::GetFullPath('d:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_网评路演PPT_Rainbow-FinGPT.pptx')
 = [System.IO.Path]::GetFullPath('d:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_网评路演PPT_Rainbow-FinGPT.pdf')
 = .Presentations.Open(, [Microsoft.Office.Core.MsoTriState]::msoTrue, [Microsoft.Office.Core.MsoTriState]::msoFalse, [Microsoft.Office.Core.MsoTriState]::msoFalse)
.SaveAs(, 32)
.Close()
.Quit()
Write-Host 'Success PPT PDF'
