export type OutboxMessage = { id: string; text: string; createdAt: number; status: 'queued' | 'sending' | 'accepted' | 'failed' | 'choice'; baseTurn: number; error?: string };

export function restoreOutbox(raw: string | null): OutboxMessage[] {
  try {
    const value: unknown = JSON.parse(raw || '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is OutboxMessage => Boolean(item && typeof item.id === 'string' && typeof item.text === 'string' && typeof item.createdAt === 'number')).slice(0, 30).map(item => {
      const status = item.status === 'failed' || item.status === 'choice' || item.status === 'accepted' ? item.status : 'queued';
      return { ...item, baseTurn:Number.isInteger(item.baseTurn)&&item.baseTurn>=0?item.baseTurn:0, text: item.text.slice(0, 4000), status,
        error: status === 'queued' && item.status === 'sending' ? 'Checking delivery… This message will be retried with the same ID.' : item.error };
    });
  } catch { return []; }
}

export function nextOutboxMessage(items: OutboxMessage[]): OutboxMessage | undefined {
  // A confirmed failure or mode decision must not strand unrelated messages.
  // The hook still allows only one unaccepted send at a time, preserving order
  // for the normal (successful) path.
  return items.filter(item => item.status === 'queued').sort((a, b) => a.createdAt - b.createdAt)[0];
}
