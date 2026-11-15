"""Synthetic XLSX template only; never copies internal/merchant resources."""
import io,zipfile
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
def template(extra=None):
 parts={
 '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
 '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
 'xl/workbook.xml':f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="短标题" sheetId="1" r:id="rId1"/></sheets></workbook>',
 'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>',
 'xl/worksheets/sheet1.xml':f'<worksheet xmlns="{NS}"><dimension ref="A1:B3"/><cols><col min="1" max="2" width="30" customWidth="1"/></cols><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>填写说明：短标题最多30字符（synthetic template）</t></is></c></row><row r="2"><c r="A2" t="s"><v>0</v></c><c r="B2" t="s"><v>1</v></c></row><row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3" t="s"><v>3</v></c></row></sheetData><pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>',
 'xl/sharedStrings.xml':f'<sst xmlns="{NS}" count="4" uniqueCount="4"><si><t>SKUID</t></si><si><t>短标题</t></si><si><t>SYNTHETIC-EXAMPLE-ID</t></si><si><t>SYNTHETIC-EXAMPLE-TITLE</t></si></sst>',
 'docProps/core.xml':'<coreProperties xmlns="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"><created xmlns="http://purl.org/dc/terms/">2000-01-01T00:00:00Z</created></coreProperties>'}
 if extra:parts.update(extra)
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for name,body in parts.items():z.writestr(name,body)
 return out.getvalue()
