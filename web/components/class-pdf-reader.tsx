'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
const pdfWorkerUrl = '/pdf.worker.min.mjs';
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist';
import type { ClassReferenceGeometry } from '@/lib/in-class';
import styles from './in-class-workspace.module.css';

type PdfSource = { url: string; httpHeaders: Record<string, string> };
type PdfTextContent = Awaited<ReturnType<PDFPageProxy['getTextContent']>>;
type PdfjsModule = typeof import('pdfjs-dist');
type PageSize = { width: number; height: number };
type ClassPdfReaderProps = {
  source: PdfSource;
  pageIndex: number;
  pageCount: number;
  geometry?: ClassReferenceGeometry | null;
  onPageChange: (pageIndex: number) => void;
};

const DEFAULT_PAGE_SIZE: PageSize = { width: 612, height: 792 };
const PAGE_OVERSCAN = 2;
const MAX_CACHED_PAGE_DATA = 24;

function rememberRecent<T>(cache: Map<number, Promise<T>>, index: number, promise: Promise<T>) {
  cache.delete(index);
  cache.set(index, promise);
  while (cache.size > MAX_CACHED_PAGE_DATA) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
  return promise;
}

function normalizedText(value: string) {
  return value.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
}

function contentText(content: PdfTextContent) {
  return normalizedText(content.items.map(item => 'str' in item ? item.str : '').join(' '));
}

export function ClassPdfReader({ source, pageIndex, pageCount, geometry, onPageChange }: ClassPdfReaderProps) {
  const sourceKey = `${source.url}:${JSON.stringify(source.httpHeaders)}`;
  return <ClassPdfReaderDocument key={sourceKey} source={source} pageIndex={pageIndex} pageCount={pageCount} geometry={geometry} onPageChange={onPageChange} />;
}

function ClassPdfReaderDocument({ source, pageIndex, pageCount, geometry, onPageChange }: ClassPdfReaderProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const pagesRef = useRef<HTMLDivElement | null>(null);
  const slotRefs = useRef<Array<HTMLDivElement | null>>([]);
  const textContentRef = useRef(new Map<number, Promise<PdfTextContent>>());
  const pageRef = useRef(new Map<number, Promise<PDFPageProxy>>());
  const searchGenerationRef = useRef(0);
  const frameRequestRef = useRef<number | null>(null);
  const visiblePageRef = useRef(0);
  const controlledPageRef = useRef(pageIndex);
  const initialDocumentScrollRef = useRef(true);

  const [pdfjs, setPdfjs] = useState<PdfjsModule | null>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [pageSizes, setPageSizes] = useState<Record<number, PageSize>>({});
  const [renderRange, setRenderRange] = useState({ start: 0, end: PAGE_OVERSCAN * 2 + 2 });
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchPages, setSearchPages] = useState<number[]>([]);
  const [activeSearchResult, setActiveSearchResult] = useState(0);
  const [searchStatus, setSearchStatus] = useState('');
  const [searching, setSearching] = useState(false);

  const headersKey = JSON.stringify(source.httpHeaders);

  useEffect(() => {
    let live = true;
    let task: PDFDocumentLoadingTask | undefined;

    void (async () => {
      try {
        const pdfjsModule = await import('pdfjs-dist');
        if (!live) return;
        pdfjsModule.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        task = pdfjsModule.getDocument({
          url: source.url,
          httpHeaders: source.httpHeaders,
          rangeChunkSize: 1024 * 1024,
          disableStream: true,
          disableAutoFetch: true,
        });
        const document = await task.promise;
        if (live) {
          setPdfjs(pdfjsModule);
          setPdf(document);
        }
      } catch {
        if (live) setLoadError(true);
      }
    })();

    return () => {
      live = false;
      searchGenerationRef.current += 1;
      void task?.destroy();
    };
  }, [source.url, source.httpHeaders, headersKey]);

  const totalPages = pdf?.numPages || pageCount;
  const clampedPageIndex = Math.max(0, Math.min(pageIndex, Math.max(0, totalPages - 1)));
  const fallbackSize = pageSizes[0] || DEFAULT_PAGE_SIZE;
  const pageWidthAvailable = Math.max(80, viewportWidth - 24);
  const regions = geometry && ['estimated','measured'].includes(geometry.status) ? geometry.regions || [] : [];

  const getPage = useCallback((index: number) => {
    if (!pdf) return Promise.reject(new Error('The PDF is not ready'));
    const cached = pageRef.current.get(index);
    if (cached) return rememberRecent(pageRef.current, index, cached);
    const entry: { promise: Promise<PDFPageProxy> | null } = { promise: null };
    const promise = pdf.getPage(index + 1).catch(error => {
      if (pageRef.current.get(index) === entry.promise) pageRef.current.delete(index);
      throw error;
    });
    entry.promise = promise;
    return rememberRecent(pageRef.current, index, promise);
  }, [pdf]);

  const getTextContent = useCallback(async (index: number) => {
    const cached = textContentRef.current.get(index);
    if (cached) return rememberRecent(textContentRef.current, index, cached);
    const entry: { promise: Promise<PdfTextContent> | null } = { promise: null };
    const promise = getPage(index).then(page => page.getTextContent()).catch(error => {
      if (textContentRef.current.get(index) === entry.promise) textContentRef.current.delete(index);
      throw error;
    });
    entry.promise = promise;
    return rememberRecent(textContentRef.current, index, promise);
  }, [getPage]);

  const reportPageSize = useCallback((index: number, size: PageSize) => {
    setPageSizes(current => {
      const previous = current[index];
      if (previous && Math.abs(previous.width - size.width) < 0.1 && Math.abs(previous.height - size.height) < 0.1) return current;
      return { ...current, [index]: size };
    });
  }, []);

  const dimensionsFor = useCallback((index: number) => {
    const pageSize = pageSizes[index] || fallbackSize;
    const scale = Math.min(3, Math.max(0.25, pageWidthAvailable / pageSize.width) * zoom);
    return { width: pageSize.width * scale, height: pageSize.height * scale, scale };
  }, [fallbackSize, pageSizes, pageWidthAvailable, zoom]);

  const updateVisiblePages = useCallback(() => {
    frameRequestRef.current = null;
    const viewport = viewportRef.current;
    const pages = pagesRef.current;
    if (!viewport || !pages || !totalPages) return;

    const top = viewport.scrollTop;
    const bottom = top + viewport.clientHeight;
    let low = 0;
    let high = totalPages - 1;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      const slot = slotRefs.current[middle];
      if (slot && slot.offsetTop + slot.offsetHeight < top) low = middle + 1;
      else high = middle;
    }
    const firstVisible = low;
    let lastVisible = firstVisible;
    while (lastVisible < totalPages - 1) {
      const slot = slotRefs.current[lastVisible];
      if (!slot || slot.offsetTop > bottom) break;
      lastVisible += 1;
    }
    if (lastVisible > firstVisible) lastVisible -= 1;
    const nextRenderRange = {
      start: Math.max(0, firstVisible - PAGE_OVERSCAN),
      end: Math.min(totalPages - 1, lastVisible + PAGE_OVERSCAN),
    };
    setRenderRange(current => current.start === nextRenderRange.start && current.end === nextRenderRange.end ? current : nextRenderRange);

    const viewportCenter = top + viewport.clientHeight / 2;
    let active = firstVisible;
    const firstSlot = slotRefs.current[firstVisible];
    const nextSlot = slotRefs.current[firstVisible + 1];
    if (firstSlot && nextSlot) {
      const firstCenter = firstSlot.offsetTop + firstSlot.offsetHeight / 2;
      const nextCenter = nextSlot.offsetTop + nextSlot.offsetHeight / 2;
      if (Math.abs(nextCenter - viewportCenter) < Math.abs(firstCenter - viewportCenter)) active = firstVisible + 1;
    }
    active = Math.max(0, Math.min(active, totalPages - 1));
    if (active !== visiblePageRef.current) {
      visiblePageRef.current = active;
      onPageChange(active);
    }
  }, [onPageChange, totalPages]);

  const scheduleVisibleUpdate = useCallback(() => {
    if (frameRequestRef.current !== null) return;
    frameRequestRef.current = window.requestAnimationFrame(updateVisiblePages);
  }, [updateVisiblePages]);

  useEffect(() => {
    scheduleVisibleUpdate();
  }, [pageSizes, scheduleVisibleUpdate]);

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => {
      setViewportWidth(entries[0]?.contentRect.width || 0);
      scheduleVisibleUpdate();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [scheduleVisibleUpdate]);

  const scrollToPage = useCallback((index: number) => {
    const target = slotRefs.current[index];
    const viewport = viewportRef.current;
    if (!target || !viewport) return;
    viewport.scrollTo({
      top: Math.max(0, target.offsetTop - (viewport.clientHeight - target.offsetHeight) / 2),
      behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    });
  }, []);

  const goToPage = useCallback((index: number) => {
    const target = Math.max(0, Math.min(index, Math.max(0, totalPages - 1)));
    onPageChange(target);
    scrollToPage(target);
  }, [onPageChange, scrollToPage, totalPages]);

  useEffect(() => {
    if (!pdf || !viewportWidth) return;
    let live = true;
    void getPage(0).then(page => {
      if (!live) return;
      const viewport = page.getViewport({ scale: 1 });
      reportPageSize(0, { width: viewport.width, height: viewport.height });
      scheduleVisibleUpdate();
    }).catch(() => undefined);
    return () => { live = false; };
  }, [pdf, viewportWidth, getPage, reportPageSize, scheduleVisibleUpdate]);

  useEffect(() => {
    if (!pdf) return;
    if (initialDocumentScrollRef.current) {
      initialDocumentScrollRef.current = false;
      controlledPageRef.current = clampedPageIndex;
      if (visiblePageRef.current !== clampedPageIndex) scrollToPage(clampedPageIndex);
      return;
    }
    if (controlledPageRef.current === clampedPageIndex) return;
    controlledPageRef.current = clampedPageIndex;
    if (visiblePageRef.current !== clampedPageIndex) scrollToPage(clampedPageIndex);
  }, [pdf, clampedPageIndex, scrollToPage]);

  useEffect(() => () => {
    if (frameRequestRef.current !== null) window.cancelAnimationFrame(frameRequestRef.current);
  }, []);

  async function searchDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchInput.trim();
    const normalizedQuery = normalizedText(query);
    const generation = ++searchGenerationRef.current;
    setSearchQuery(query);
    setSearchPages([]);
    setActiveSearchResult(0);
    if (!pdf || !normalizedQuery) {
      setSearchStatus(query ? 'The document is still loading.' : '');
      return;
    }

    setSearching(true);
    setSearchStatus('Searching document text…');
    const matches: number[] = [];
    try {
      const batchSize = 4;
      for (let start = 0; start < pdf.numPages; start += batchSize) {
        if (generation !== searchGenerationRef.current) return;
        const indexes = Array.from({ length: Math.min(batchSize, pdf.numPages - start) }, (_, offset) => start + offset);
        const results = await Promise.all(indexes.map(async index => {
          try { return { index, text: contentText(await getTextContent(index)) }; }
          catch { return { index, text: '' }; }
        }));
        if (generation !== searchGenerationRef.current) return;
        for (const result of results) if (result.text.includes(normalizedQuery)) matches.push(result.index);
        setSearchStatus(`Searching document text… ${Math.min(start + batchSize, pdf.numPages)} of ${pdf.numPages} pages`);
      }
      setSearchPages(matches);
      if (matches.length) {
        setSearchStatus(`${matches.length} page${matches.length === 1 ? '' : 's'} with matches`);
        goToPage(matches[0]);
      } else {
        setSearchStatus('No matching selectable text found. This PDF may contain scanned pages.');
      }
    } catch {
      if (generation === searchGenerationRef.current) setSearchStatus('The document text could not be searched.');
    } finally {
      if (generation === searchGenerationRef.current) setSearching(false);
    }
  }

  function clearSearch() {
    searchGenerationRef.current += 1;
    setSearching(false);
    setSearchInput('');
    setSearchQuery('');
    setSearchPages([]);
    setActiveSearchResult(0);
    setSearchStatus('');
  }

  const pageSlots = useMemo(() => Array.from({ length: totalPages }, (_, index) => index), [totalPages]);

  return <section className={styles.pdfReader} aria-label="PDF page reader">
    <div className={styles.pdfReaderControls}>
      <button type="button" disabled={clampedPageIndex <= 0} onClick={() => goToPage(clampedPageIndex - 1)}>Previous</button>
      <span aria-live="polite">PDF page {clampedPageIndex + 1} of {totalPages || '…'}</span>
      <button type="button" disabled={!totalPages || clampedPageIndex >= totalPages - 1} onClick={() => goToPage(clampedPageIndex + 1)}>Next</button>
      <button type="button" aria-label="Zoom out" disabled={zoom <= 0.75} onClick={() => setZoom(value => Math.max(0.75, Number((value - 0.25).toFixed(2))))}>−</button>
      <span>{Math.round(zoom * 100)}%</span>
      <button type="button" aria-label="Zoom in" disabled={zoom >= 1.75} onClick={() => setZoom(value => Math.min(1.75, Number((value + 0.25).toFixed(2))))}>+</button>
      <button type="button" onClick={() => setZoom(1)}>Fit</button>
    </div>
    <form className={styles.pdfSearch} role="search" onSubmit={event => void searchDocument(event)}>
      <label htmlFor="class-pdf-search">Find in PDF</label>
      <input id="class-pdf-search" type="search" value={searchInput} onChange={event => setSearchInput(event.target.value)} placeholder="Search this document" />
      <button type="submit" disabled={searching || !searchInput.trim() || !pdf}>{searching ? 'Searching…' : 'Find'}</button>
      {searchQuery ? <button type="button" onClick={clearSearch}>Clear</button> : null}
      {searchPages.length ? <div className={styles.pdfSearchResults}>
        <button type="button" aria-label="Previous search result" onClick={() => {
          const next = (activeSearchResult + searchPages.length - 1) % searchPages.length;
          setActiveSearchResult(next);
          goToPage(searchPages[next]);
        }}>‹</button>
        <span>Result {activeSearchResult + 1} of {searchPages.length} · page {searchPages[activeSearchResult] + 1}</span>
        <button type="button" aria-label="Next search result" onClick={() => {
          const next = (activeSearchResult + 1) % searchPages.length;
          setActiveSearchResult(next);
          goToPage(searchPages[next]);
        }}>›</button>
      </div> : null}
      <span className={styles.pdfSearchStatus} role="status" aria-live="polite">{searchStatus}</span>
    </form>
    {loadError ? <p className={styles.pdfReaderStatus} role="status">This page could not be rendered here. You can open the original PDF in a new tab.</p> : null}
    <div ref={viewportRef} className={styles.pdfReaderViewport} tabIndex={0} aria-label="Scrollable PDF pages" onScroll={scheduleVisibleUpdate}>
      <div ref={pagesRef} className={styles.pdfPages}>
        {pageSlots.map(index => {
          const dimensions = dimensionsFor(index);
          const inWindow = index >= renderRange.start && index <= renderRange.end;
          const isCitationPage = index === clampedPageIndex;
          return <div
            key={index}
            ref={element => { slotRefs.current[index] = element; }}
            className={styles.pdfPageSlot}
            style={{ height: `${dimensions.height + 16}px` }}
            aria-label={`PDF page ${index + 1}`}
            data-pdf-page={index + 1}
          >
            {inWindow && pdf && pdfjs ? <PdfPageView
              pdfjs={pdfjs}
              getPage={getPage}
              getTextContent={getTextContent}
              reportPageSize={reportPageSize}
              pageIndex={index}
              width={dimensions.width}
              height={dimensions.height}
              scale={dimensions.scale}
              regions={isCitationPage ? regions : []}
              searchQuery={searchQuery}
              isSearchResult={searchPages.includes(index)}
            /> : <div className={styles.pdfPagePlaceholder} style={{ width: `${dimensions.width}px`, height: `${dimensions.height}px` }} aria-hidden="true" />}
          </div>;
        })}
      </div>
    </div>
    {regions.length ? <small className={styles.pdfEstimateNotice}>{geometry?.status==='measured'?'Extracted text location.':'Approximate passage location.'} Confirm the wording in the extracted citation below.</small> : null}
  </section>;
}

type PdfPageViewProps = {
  pdfjs: PdfjsModule;
  getPage: (index: number) => Promise<PDFPageProxy>;
  getTextContent: (index: number) => Promise<PdfTextContent>;
  reportPageSize: (index: number, size: PageSize) => void;
  pageIndex: number;
  width: number;
  height: number;
  scale: number;
  regions: NonNullable<ClassReferenceGeometry['regions']>;
  searchQuery: string;
  isSearchResult: boolean;
};

function PdfPageView({ pdfjs, getPage, getTextContent, reportPageSize, pageIndex, width, height, scale, regions, searchQuery, isSearchResult }: PdfPageViewProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textLayerRef = useRef<HTMLDivElement | null>(null);
  const [renderError, setRenderError] = useState(false);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    let live = true;
    let renderTask: RenderTask | undefined;
    let textLayer: InstanceType<PdfjsModule['TextLayer']> | undefined;
    const textLayerElement = textLayerRef.current;
    const canvas = canvasRef.current;
    if (!textLayerElement || !canvas) return;

    setRenderError(false);
    setRendered(false);
    textLayerElement.replaceChildren();

    void (async () => {
      try {
        const page = await getPage(pageIndex);
        if (!live) return;
        const baseViewport = page.getViewport({ scale: 1 });
        reportPageSize(pageIndex, { width: baseViewport.width, height: baseViewport.height });
        const viewport = page.getViewport({ scale });
        const pixelRatio = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
        canvas.width = Math.ceil(viewport.width * pixelRatio);
        canvas.height = Math.ceil(viewport.height * pixelRatio);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        if (!canvas.getContext('2d')) throw new Error('Canvas is unavailable');

        renderTask = page.render({ canvas, viewport, transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0] });
        const textContent = await getTextContent(pageIndex);
        if (!live) { renderTask.cancel(); return; }
        textLayerElement.style.setProperty('--total-scale-factor', String(scale));
        textLayer = new pdfjs.TextLayer({ textContentSource: textContent, container: textLayerElement, viewport });
        const [renderResult] = await Promise.all([renderTask.promise, textLayer.render()]);
        void renderResult;
        if (!live) return;

        const query = normalizedText(searchQuery);
        if (query && isSearchResult) {
          for (const element of textLayer.textDivs) {
            if (normalizedText(element.textContent || '').includes(query)) element.classList.add(styles.pdfSearchMatch);
          }
        }
        setRendered(true);
      } catch {
        if (live) setRenderError(true);
      }
    })();

    return () => {
      live = false;
      renderTask?.cancel();
      textLayer?.cancel();
      textLayerElement.replaceChildren();
    };
  }, [getPage, getTextContent, height, isSearchResult, pageIndex, pdfjs, reportPageSize, scale, searchQuery, width]);

  return <div className={styles.pdfPageFrame} style={{ width: `${width}px`, height: `${height}px` }} role="group" aria-label={`PDF page ${pageIndex + 1}`}>
    <canvas aria-hidden="true" ref={canvasRef} aria-label={`PDF page ${pageIndex + 1} visual rendering`} />
    <div ref={textLayerRef} className={styles.pdfTextLayer} aria-label={`Selectable text for PDF page ${pageIndex + 1}`} />
    {regions.map((region, index) => <div key={index} className={styles.pdfEstimatedRegion} aria-hidden="true" style={{ left: `${region.x * 100}%`, top: `${region.y * 100}%`, width: `${region.width * 100}%`, height: `${region.height * 100}%` }} />)}
    {renderError ? <span className={styles.pdfReaderStatus} role="status">This page could not be rendered here.</span> : null}
    {!rendered && !renderError ? <span className={styles.pdfReaderStatus} role="status">Rendering page…</span> : null}
  </div>;
}
