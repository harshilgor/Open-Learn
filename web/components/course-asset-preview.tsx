'use client';

import { useEffect, useState } from 'react';
import { FileText } from 'lucide-react';
import { request } from '@/lib/api';
import { Button } from '@/components/ui/button';

type Asset = { id: string; title: string; role: string; status: string };

export function CourseAssetPreview({courseId, onOpen}: {courseId: string; onOpen: () => void}) {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    void request<{materials: Asset[]}>(`/v1/materials?course_id=${encodeURIComponent(courseId)}`).then(result => {
      if (active) { setAssets(result.materials); setError(false); }
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [courseId, retry]);
  return <section className="course-folder-section" aria-label="Course assets">
    <div className="course-folder-section-head"><div><h2>Your course assets</h2><p>Source material for your next study session</p></div><Button variant="outline" onClick={onOpen}>Manage materials</Button></div>
    {error ? <p role="alert">Could not load materials. <Button variant="ghost" onClick={()=>setRetry(value=>value+1)}>Retry</Button></p> : assets === null ? <p role="status">Loading materials…</p> : assets.length ? <div className="course-folder-list">{assets.slice(0, 3).map(asset=><button key={asset.id} className="course-folder-row course-folder-row-title" onClick={onOpen}><FileText size={18}/><span>{asset.title}</span><small>{asset.role.replaceAll('_', ' ')} · {asset.status.replaceAll('_', ' ')}</small></button>)}{assets.length > 3 ? <Button variant="ghost" onClick={onOpen}>View all {assets.length} materials</Button> : null}</div> : <p className="course-folder-empty">Add your textbook, lecture slides or a past paper to start building your course library.</p>}
  </section>;
}
