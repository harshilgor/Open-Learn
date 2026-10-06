"""Local deterministic material scale probe; no provider/hosted claims."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
import tracemalloc
from uuid import uuid4
import fitz
from backend.app.storage import Store
from backend.app.material_service import MaterialService
from backend.app.material_models import UploadRequest
from backend.app.material_index import MaterialIndexService

def run():
    root=Path('work')/('material-scale-'+uuid4().hex);root.mkdir(parents=True)
    os.environ['AI_TUTOR_MATERIAL_DIR']=str(root/'objects')
    os.environ['OPENLEARN_OCR_ENABLED']='false'
    db=Store(root/'scale.sqlite');svc=MaterialService(db);index=MaterialIndexService(db)
    results=[]
    for name,pages,raster in [('small',20,False),('long',1000,False),('scanned_image_rich',200,True)]:
        doc=fitz.open()
        for p in range(pages):
            page=doc.new_page(width=400,height=600)
            if raster:
                scratch=fitz.open();imagepage=scratch.new_page(width=400,height=600)
                imagepage.insert_text((40,80),'Membrane transport diagram')
                page.insert_image(page.rect,stream=imagepage.get_pixmap().tobytes('png'));scratch.close()
            else:
                page.insert_textbox(fitz.Rect(30,30,380,580),f'Chapter {p+1}\nFigure {p+1}.1 Membrane transport.\n'+('Cells require energy for membrane transport.\n'*25))
        path=root/(name+'.pdf');doc.save(path);doc.close()
        item=svc.create('scale',UploadRequest(title=name,media_type='application/pdf',byte_count=path.stat().st_size,course_id='scale'))
        svc.upload_file('scale',item['materialId'],item['versionId'],path)
        tracemalloc.start();start=time.perf_counter();svc.process_one();seconds=time.perf_counter()-start
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        status=svc.details('scale',item['materialId'])['status']
        timings=[]
        for _ in range(20):
            start=time.perf_counter();index.lookup('scale','scale',query='membrane transport');timings.append((time.perf_counter()-start)*1000)
        results.append({'shape':name,'pages':pages,'bytes':path.stat().st_size,'indexSeconds':round(seconds,3),
            'pythonPeakMiB':round(peak/1024**2,2),'status':status,'lookupP50Ms':round(statistics.median(timings),2),
            'lookupP90Ms':round(sorted(timings)[17],2),'progress':index.progress('scale',item['versionId'])})
    # Streaming object-storage admission near the configured cap; this is not
    # claimed to be a 499-MiB searchable document or a cloud-storage benchmark.
    path=root/'near-cap.bin';digest=hashlib.sha256();chunk=b'x'*(1024*1024)
    with path.open('wb') as output:
        for _ in range(499):output.write(chunk);digest.update(chunk)
    tracemalloc.start();start=time.perf_counter()
    svc.objects.put_file('scale-near-cap',path,byte_count=path.stat().st_size,sha256=digest.hexdigest())
    elapsed=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    results.append({'shape':'near_cap_stream_storage','bytes':path.stat().st_size,'seconds':round(elapsed,3),'pythonPeakMiB':round(peak/1024**2,2)})
    svc.objects.delete('scale-near-cap');path.unlink()
    db.close()
    output={'environment':'Local Windows SQLite/LocalObjectStore; PyMuPDF; no OCR/provider calls',
            'limitations':['Python heap excludes native PDF allocations','Scanned pages intentionally OCR-disabled; worker OCR tested separately with deterministic adapter','No hosted/provider/device acceptance'],
            'results':results}
    print(json.dumps(output,indent=2))
    return output

if __name__=='__main__':run()
