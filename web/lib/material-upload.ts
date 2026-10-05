export type MaterialUploadSession = {
  uploadId: string;
  sessionUrl: string;
  totalBytes: number;
  chunkBytes: number;
  chunkCount: number;
  receivedParts: number[];
  status: 'open' | 'assembling' | 'completed';
  expiresAt: number;
};

type ChunkUploadOptions<T> = {
  putPart: (sessionUrl: string, partIndex: number, part: Blob) => Promise<unknown>;
  complete: (sessionUrl: string) => Promise<T>;
  onProgress?: (percentage: number) => void;
};

async function completeWithRetry<T>(sessionUrl: string, complete: (sessionUrl: string) => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await complete(sessionUrl);
    } catch (cause) {
      const code = cause && typeof cause === 'object' && 'code' in cause ? String((cause as { code?: unknown }).code) : '';
      if (code !== 'upload_in_progress' || attempt >= 11) throw cause;
      await new Promise(resolve => window.setTimeout(resolve, 1000));
    }
  }
}

export async function uploadMaterialParts<T>(
  file: Blob,
  session: MaterialUploadSession,
  options: ChunkUploadOptions<T>,
): Promise<T> {
  if (file.size !== session.totalBytes) throw new Error('This upload session belongs to a file with a different size.');
  const received = new Set(session.receivedParts);
  let uploadedBytes = session.receivedParts.reduce((sum, index) => {
    const start = index * session.chunkBytes;
    return sum + Math.max(0, Math.min(session.chunkBytes, file.size - start));
  }, 0);
  options.onProgress?.(Math.min(100, Math.round(uploadedBytes / Math.max(1, file.size) * 100)));

  for (let index = 0; index < session.chunkCount; index++) {
    if (received.has(index)) continue;
    const start = index * session.chunkBytes;
    const end = Math.min(file.size, start + session.chunkBytes);
    await options.putPart(session.sessionUrl, index, file.slice(start, end));
    uploadedBytes += end - start;
    options.onProgress?.(Math.min(100, Math.round(uploadedBytes / Math.max(1, file.size) * 100)));
  }
  return completeWithRetry(session.sessionUrl, options.complete);
}
