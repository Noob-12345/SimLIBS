from pathlib import Path
import zipfile
dest=Path('.herdrflow/tasks/T002/two-sheet-ui-test.xlsx')
with zipfile.ZipFile(dest,'w') as z:
    z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="first" r:id="r1"/><sheet name="second" r:id="r2"/></sheets></workbook>')
    z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>')
    for index in (1,2):
        rows=''.join(f'<row r="{i+1}"><c r="A{i+1}"><v>{400+i}</v></c><c r="B{i+1}"><v>{index*(-i-1)}</v></c><c r="C{i+1}"><v>{index*(i+3)}</v></c></row>' for i in range(5))
        z.writestr(f'xl/worksheets/sheet{index}.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+rows+'</sheetData></worksheet>')
