= New-Object -ComObject PowerPoint.Application
 = 'D:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_网评路演PPT_Rainbow-FinGPT.pptx'
 = 'D:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_网评路演PPT_Rainbow-FinGPT.pdf'
 = .Presentations.Open(, 1, 0, 0)
.SaveAs(, 32)
.Close()
.Quit()
Write-Host 'PPT PDF Done'

 = New-Object -ComObject Word.Application
.Visible = False
 = 'D:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_产业命题申报表_Rainbow-FinGPT(附件3填报版).docx'
 = 'D:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_产业命题申报表_Rainbow-FinGPT(附件3填报版).pdf'
 = .Documents.Open()
.SaveAs([ref], [ref]17)
.Close()
.Quit()
Write-Host 'Word PDF Done'