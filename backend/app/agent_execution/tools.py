"""Bounded deterministic lab adapter. No generated code runs on the API host."""
import csv
import io
import math
import re
import struct
import zlib
import zipfile
from xml.etree import ElementTree as ET

FIXTURE = 'trial,distance,time\n1,10,2\n2,20,4\n3,999,1\n'


def parse_csv(value):
    reader = csv.DictReader(io.StringIO(value))
    if reader.fieldnames != ['trial', 'distance', 'time']: raise ValueError('CSV must have trial,distance,time columns; time is in seconds.')
    result = []
    for row in reader:
        if len(result) >= 1000: raise ValueError('This development adapter supports at most 1000 rows.')
        trial = int(row['trial']); distance = float(row['distance']); seconds = float(row['time'])
        if not math.isfinite(distance) or distance < 0 or not math.isfinite(seconds) or seconds <= 0: raise ValueError('Distances must be finite and nonnegative; time must be positive.')
        if any(item['trial'] == trial for item in result): raise ValueError('Trial IDs must be unique.')
        result.append({'trial':trial,'distance':distance,'time':seconds})
    if not result: raise ValueError('CSV has no data rows.')
    return result


def constraints_from(text, previous, rows):
    value = dict(previous)
    lower = text.lower()
    units = []
    if re.search(r'\b(centimeters?|centimetres?|cm)\b', lower): units.append('cm')
    if re.search(r'\b(meters?|metres?|m)\b', lower): units.append('m')
    if len(units) > 1: raise ValueError('Specify one distance unit: centimeters or meters.')
    if units: value['distanceUnit'] = units[0]
    excluded = set(value.get('excludedTrials', []))
    for match in re.finditer(r'(?:ignore|exclude|remove)\s+(?:trial|row)\s*(\d+)', lower): excluded.add(int(match.group(1)))
    if re.search(r'(?:ignore|exclude|remove).{0,15}(?:last|final).{0,8}row', lower): excluded.add(rows[-1]['trial'])
    if excluded - {row['trial'] for row in rows}: raise ValueError('The excluded trial does not exist.')
    value['excludedTrials'] = sorted(excluded)
    return value


def workbook(rows, unit):
    cells = [['trial','distance','time_s',f'speed_{unit}_per_s']] + [[r['trial'],r['distance'],r['time'],r['speed']] for r in rows]
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    root = ET.Element('worksheet', xmlns=ns); data = ET.SubElement(root, 'sheetData')
    for index, values in enumerate(cells, 1):
        row = ET.SubElement(data, 'row', r=str(index))
        for col, value in enumerate(values):
            cell = ET.SubElement(row, 'c', r=f'{chr(65+col)}{index}', t='inlineStr' if isinstance(value,str) else 'n')
            if isinstance(value,str): ET.SubElement(ET.SubElement(cell,'is'),'t').text = value
            else: ET.SubElement(cell,'v').text = str(value)
    files = {
        '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Analysis" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': ET.tostring(root, encoding='utf-8'),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2026,1,1,0,0,0)); entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry,value)
    return out.getvalue()


def chart(rows,unit):
    width,height=640,360
    pixels = bytearray([255] * width * height * 3)
    def paint(x,y,color):
        at=(y*width+x)*3;pixels[at:at+3]=bytes(color)
    glyphs={
        '0':'111/101/101/101/111','1':'010/110/010/010/111','2':'111/001/111/100/111','3':'111/001/111/001/111','4':'101/101/111/001/001','5':'111/100/111/001/111','6':'111/100/111/101/111','7':'111/001/010/010/010','8':'111/101/111/101/111','9':'111/101/111/001/111',
        'S':'111/100/111/001/111','P':'110/101/110/100/100','E':'111/100/110/100/111','D':'110/101/101/101/110','C':'111/100/100/100/111','M':'101/111/111/101/101','T':'111/010/010/010/010','R':'110/101/110/101/101','I':'111/010/010/010/111','A':'010/101/111/101/101','L':'100/100/100/100/111','/':'001/001/010/100/100','.':'000/000/000/000/010',
    }
    def label(value,x,y):
        for char in str(value).upper():
            for dy,line in enumerate(glyphs.get(char,'000/000/000/000/000').split('/')):
                for dx,bit in enumerate(line):
                    if bit=='1':
                        for sy in range(2):
                            for sx in range(2):
                                px=x+dx*2+sx;py=y+dy*2+sy
                                if 0<=px<width and 0<=py<height:paint(px,py,(40,40,40))
            x+=8
    label('SPEED '+unit+'/S',44,4)
    for x in range(40,width-20): paint(x,height-30,(80,80,80))
    for y in range(20,height-30): paint(40,y,(80,80,80))
    maximum = max(abs(r['speed']) for r in rows) or 1
    spacing=(width-80)/len(rows)
    for index,row in enumerate(rows):
        start=int(50+index*spacing);end=min(width-20,int(start+max(1,spacing*.65)))
        top=int(height-31-abs(row['speed'])/maximum*(height-70))
        for y in range(top,height-31):
            for x in range(start,end):paint(x,y,(50,110,210))
        if len(rows)<=20:
            label(f"{row['speed']:g}",start,max(21,top-14))
            label('TRIAL '+str(row['trial']),start,height-23)
    raw=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(name, content): return struct.pack('!I',len(content))+name+content+struct.pack('!I',zlib.crc32(name+content)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def analyze(task):
    rows=parse_csv(task['csvText']); unit=task['constraints']['distanceUnit']
    selected=[{**r,'speed':r['distance']/r['time']} for r in rows if r['trial'] not in task['constraints']['excludedTrials']]
    if not selected: raise ValueError('At least one trial must remain.')
    lineage={'inputHash':task['inputHash'],'inputRevision':task['desired_input_revision'],'units':unit,'excludedTrials':task['constraints']['excludedTrials'],'toolVersion':'lab-analysis-v1'}
    csv_out=io.StringIO();writer=csv.DictWriter(csv_out,fieldnames=['trial','distance','time','speed']);writer.writeheader();writer.writerows(selected)
    summary = f"Retained trials {', '.join(str(r['trial']) for r in selected)}; speeds: " + ', '.join(f"{r['speed']:g} {unit}/s" for r in selected) + '. Time is documented in seconds.'
    return {'outputs':[
        {'name':'analysis.xlsx','mediaType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','content':workbook(selected,unit),'lineage':lineage},
        {'name':'speeds.png','mediaType':'image/png','content':chart(selected,unit),'lineage':lineage},
        {'name':'analysis.csv','mediaType':'text/csv','content':csv_out.getvalue().encode(),'lineage':lineage},
    ], 'summary':summary,'sources':[], 'completion':{'policyVersion':'lab-v1','checks':[{'criterion':'filtered_rows_and_units','status':'pass','rows':selected,'unit':unit},{'criterion':'numeric_speed','status':'pass'}],'status':'verified'}}


def validate_output(output):
    content=output['content']
    if len(content)>5_000_000: raise ValueError('Output exceeds 5 MiB limit.')
    if output['name'].endswith('.xlsx'):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.testzip(): raise ValueError('Workbook integrity failed.')
            ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
    elif output['mediaType']=='image/png':
        if not content.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('Invalid PNG.')
        at=8;compressed=[]
        while at<len(content):
            length=struct.unpack('!I',content[at:at+4])[0]; name=content[at+4:at+8];data=content[at+8:at+8+length]
            if zlib.crc32(name+data)&0xffffffff != struct.unpack('!I',content[at+8+length:at+12+length])[0]: raise ValueError('PNG integrity failed.')
            if name==b'IDAT':compressed.append(data)
            at+=12+length
        zlib.decompress(b''.join(compressed))
    elif output['mediaType'] in {'text/csv','text/markdown','text/plain','application/json'}: content.decode('utf-8')
    else: raise ValueError('Unsupported output format.')
