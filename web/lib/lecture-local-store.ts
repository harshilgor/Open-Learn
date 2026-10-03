/** Durable browser manifest and independently playable audio slices. */
export type LocalLecturePhase = 'recording' | 'paused' | 'stop_requested' | 'interrupted' | 'completed';
export type LocalChunkState = 'persisted' | 'uploading' | 'server_confirmed' | 'failed';
export type LecturePreferences = { depth: 'concise' | 'standard' | 'detailed'; definitions: boolean; examples: boolean; equations: boolean; derivations: boolean; studentQuestions: boolean; professorEmphasis: boolean; examHints: boolean; administrative: boolean; keepAudio: boolean };

export const defaultLecturePreferences: LecturePreferences = { depth: 'standard', definitions: true, examples: true, equations: true, derivations: true, studentQuestions: true, professorEmphasis: true, examHints: true, administrative: false, keepAudio: true };

export type LocalLecture = {
  id: string; title: string; courseId: string | null; noteFolder: string | null; noteId: string | null;
  startedAtMs: number; durationMs: number; phase: LocalLecturePhase; expectedChunkCount: number | null;
  nextSequenceNumber: number; markersMs: number[]; preferences: LecturePreferences; captureInterrupted: boolean;
  lastError: string | null; createdAt: string; updatedAt: string;
};

export type LocalAudioChunk = {
  recordingId: string; sequenceNumber: number; startMs: number; endMs: number; mimeType: string;
  blob: Blob; byteSize: number; sha256: string; state: LocalChunkState;
  uploadAttempts: number; lastError: string | null; createdAt: string;
  captureEpoch?: number; epochSequence?: number; independentMedia?: boolean;
};

const DB_NAME = 'open-learn-lecture-recordings';

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(DB_NAME, 1);
    open.onupgradeneeded = () => {
      const db = open.result;
      db.createObjectStore('sessions', { keyPath: 'id' });
      const chunks = db.createObjectStore('chunks', { keyPath: ['recordingId', 'sequenceNumber'] });
      chunks.createIndex('by-recording', 'recordingId');
    };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

function value<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
}

function finished(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error || new Error('Local recording storage was interrupted.'));
    transaction.onerror = () => reject(transaction.error || new Error('Local recording storage failed.'));
  });
}

export async function createLocalLecture(input: Omit<LocalLecture, 'createdAt' | 'updatedAt' | 'noteId' | 'expectedChunkCount' | 'nextSequenceNumber' | 'markersMs' | 'durationMs' | 'phase' | 'captureInterrupted' | 'lastError'>): Promise<LocalLecture> {
  const now = new Date().toISOString();
  const session: LocalLecture = { ...input, noteId: null, expectedChunkCount: null, nextSequenceNumber: 0, markersMs: [], durationMs: 0, phase: 'recording', captureInterrupted: false, lastError: null, createdAt: now, updatedAt: now };
  const db = await openDatabase();
  try { const tx = db.transaction('sessions', 'readwrite'); tx.objectStore('sessions').add(session); await finished(tx); return session; }
  finally { db.close(); }
}

export async function getLocalLecture(id: string): Promise<LocalLecture | null> {
  const db = await openDatabase();
  try { const tx = db.transaction('sessions', 'readonly'); return (await value(tx.objectStore('sessions').get(id))) || null; }
  finally { db.close(); }
}

export async function listLocalLectures(): Promise<LocalLecture[]> {
  const db = await openDatabase();
  try { const tx = db.transaction('sessions', 'readonly'); return await value(tx.objectStore('sessions').getAll()); }
  finally { db.close(); }
}

export async function updateLocalLecture(id: string, patch: Partial<LocalLecture>): Promise<LocalLecture> {
  const db = await openDatabase();
  try {
    const tx = db.transaction('sessions', 'readwrite');
    const store = tx.objectStore('sessions');
    const current = await value<LocalLecture | undefined>(store.get(id));
    if (!current) throw new Error('Local lecture manifest is missing.');
    const next = { ...current, ...patch, id, updatedAt: new Date().toISOString() };
    store.put(next);
    await finished(tx);
    return next;
  } finally { db.close(); }
}

export async function persistAudioSlice(id: string, blob: Blob, startMs: number, endMs: number): Promise<LocalAudioChunk> {
  const sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))).map(byte => byte.toString(16).padStart(2, '0')).join('');
  const db = await openDatabase();
  try {
    const tx = db.transaction(['sessions', 'chunks'], 'readwrite');
    const sessionStore = tx.objectStore('sessions');
    const session = await value<LocalLecture | undefined>(sessionStore.get(id));
    if (!session) throw new Error('Local lecture manifest is missing.');
    const sequenceNumber = session.nextSequenceNumber;
    const chunk: LocalAudioChunk = { recordingId: id, sequenceNumber, startMs, endMs, mimeType: blob.type.split(';')[0] || 'audio/webm', blob, byteSize: blob.size, sha256, state: 'persisted', uploadAttempts: 0, lastError: null, createdAt: new Date().toISOString() };
    // Each stop/start slice is a complete capture epoch with initialization
    // bytes. Timeslice blobs from a continuous recorder are never treated as
    // standalone files by this adapter.
    chunk.captureEpoch = sequenceNumber;
    chunk.epochSequence = 0;
    chunk.independentMedia = true;
    tx.objectStore('chunks').add(chunk);
    sessionStore.put({ ...session, nextSequenceNumber: sequenceNumber + 1, durationMs: endMs, updatedAt: new Date().toISOString() });
    await finished(tx);
    return chunk;
  } finally { db.close(); }
}

export async function listLocalChunks(id: string): Promise<LocalAudioChunk[]> {
  const db = await openDatabase();
  try {
    const tx = db.transaction('chunks', 'readonly');
    const chunks = await value<LocalAudioChunk[]>(tx.objectStore('chunks').index('by-recording').getAll(id));
    return chunks.sort((left, right) => left.sequenceNumber - right.sequenceNumber);
  } finally { db.close(); }
}

export async function setLocalChunkState(id: string, sequence: number, state: LocalChunkState, error: string | null = null): Promise<void> {
  const db = await openDatabase();
  try {
    const tx = db.transaction('chunks', 'readwrite');
    const store = tx.objectStore('chunks');
    const chunk = await value<LocalAudioChunk | undefined>(store.get([id, sequence]));
    if (!chunk) throw new Error('Local audio slice is missing.');
    store.put({ ...chunk, state, lastError: error, uploadAttempts: chunk.uploadAttempts + (state === 'uploading' ? 1 : 0) });
    await finished(tx);
  } finally { db.close(); }
}

export async function clearLocalAudio(id: string): Promise<void> {
  const db = await openDatabase();
  try {
    const tx = db.transaction('chunks', 'readwrite');
    const index = tx.objectStore('chunks').index('by-recording');
    const keys = await value<IDBValidKey[]>(index.getAllKeys(id));
    for (const key of keys) tx.objectStore('chunks').delete(key);
    await finished(tx);
  } finally { db.close(); }
}

export async function discardEmptyLocalLecture(id: string): Promise<void> {
  const db = await openDatabase();
  try {
    const tx = db.transaction(['sessions', 'chunks'], 'readwrite');
    const session = await value<LocalLecture | undefined>(tx.objectStore('sessions').get(id));
    if (!session || session.phase !== 'interrupted' || session.nextSequenceNumber !== 0) throw new Error('Only an empty interrupted recording can be discarded.');
    const keys = await value<IDBValidKey[]>(tx.objectStore('chunks').index('by-recording').getAllKeys(id));
    if (keys.length) throw new Error('This recording still has saved audio.');
    tx.objectStore('sessions').delete(id);
    await finished(tx);
  } finally { db.close(); }
}

export async function clearAllLocalLectures(): Promise<void> {
  const db = await openDatabase();
  try {
    const tx = db.transaction(['sessions', 'chunks'], 'readwrite');
    tx.objectStore('sessions').clear();
    tx.objectStore('chunks').clear();
    await finished(tx);
  } finally { db.close(); }
}

/** Preserve initialized media files separately; concatenating containers can
 * silently corrupt audio. TAR uses Blob parts without reading all audio into
 * one JavaScript byte array, and includes offsets and integrity hashes. */
export async function exportLocalLecture(id: string): Promise<void> {
  const session = await getLocalLecture(id);
  if (!session) throw new Error('The saved recording manifest is unavailable.');
  const chunks = await listLocalChunks(id);
  const entries = [{name: 'manifest.json', blob: new Blob([JSON.stringify({session, chunks: chunks.map(({blob: _blob, ...metadata}) => metadata)}, null, 2)], {type: 'application/json'})}, ...chunks.map(c => ({name: `audio/${String(c.sequenceNumber).padStart(6,'0')}.${c.mimeType === 'audio/mp4' ? 'm4a' : c.mimeType === 'audio/ogg' ? 'ogg' : 'webm'}`, blob: c.blob}))];
  const parts: BlobPart[] = [];
  for (const entry of entries) {
    const header = new Uint8Array(512);
    const write = (offset:number, value:string) => header.set(new TextEncoder().encode(value), offset);
    write(0,entry.name); write(100,'0000600\0'); write(108,'0000000\0'); write(116,'0000000\0'); write(124,entry.blob.size.toString(8).padStart(11,'0')+'\0'); write(136,Math.floor(Date.now()/1000).toString(8).padStart(11,'0')+'\0'); header.fill(32,148,156); write(156,'0'); write(257,'ustar\0'); write(263,'00');
    const checksum = header.reduce((sum,byte) => sum+byte,0); write(148,checksum.toString(8).padStart(6,'0')+'\0 ');
    parts.push(header,entry.blob,new Uint8Array((512-entry.blob.size%512)%512));
  }
  parts.push(new Uint8Array(1024));
  const url=URL.createObjectURL(new Blob(parts,{type:'application/x-tar'}));
  const link=document.createElement('a'); link.href=url; link.download=`${id}.tar`; link.click();
  window.setTimeout(()=>URL.revokeObjectURL(url),60000);
}
