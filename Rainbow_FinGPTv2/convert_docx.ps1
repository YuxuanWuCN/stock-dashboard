
 = New-Object -ComObject Word.Application
.Visible = False
 = 'd:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_产业命题申报表_Rainbow-FinGPT(附件3填报版).docx'
 = 'd:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_产业命题申报表_Rainbow-FinGPT(附件3填报版).pdf'
 = .Documents.Open()
.SaveAs([ref], [ref]17)
.Close()
.Quit()
Write-Host 'Success: Exported attachment 3 PDF!'
