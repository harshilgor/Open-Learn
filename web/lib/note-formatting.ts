export type NoteFormat = 'heading' | 'bold' | 'italic' | 'bullet' | 'numbered' | 'checklist' | 'quote' | 'link';

export type NoteEdit = { body: string; selectionStart: number; selectionEnd: number };

export function formatNote(body: string, start: number, end: number, format: NoteFormat): NoteEdit {
  if (format === 'bold' || format === 'italic' || format === 'link') {
    const selected = body.slice(start, end);
    if (format === 'link') {
      const label = selected || 'link text';
      const replacement = `[${label}](https://)`;
      const urlStart = start + label.length + 3;
      return {
        body: body.slice(0, start) + replacement + body.slice(end),
        selectionStart: selected ? urlStart : start + 1,
        selectionEnd: selected ? urlStart + 8 : start + 1 + label.length,
      };
    }
    const mark = format === 'bold' ? '**' : '*';
    const content = selected || (format === 'bold' ? 'bold text' : 'italic text');
    return {
      body: body.slice(0, start) + mark + content + mark + body.slice(end),
      selectionStart: start + mark.length,
      selectionEnd: start + mark.length + content.length,
    };
  }

  const lineStart = start === 0 ? 0 : body.lastIndexOf('\n', start - 1) + 1;
  const lastSelected = end > start && body[end - 1] === '\n' ? end - 1 : end;
  const nextBreak = body.indexOf('\n', lastSelected);
  const lineEnd = nextBreak === -1 ? body.length : nextBreak;
  const lines = body.slice(lineStart, lineEnd).split('\n');
  const prefixFor = (index: number) => ({
    heading: '## ', bullet: '- ', numbered: `${index + 1}. `,
    checklist: '- [ ] ', quote: '> ',
  })[format];
  const transformed = lines.map((line, index) => {
    const prefix = prefixFor(index);
    return line.startsWith(prefix) ? line.slice(prefix.length) : prefix + line;
  }).join('\n');
  return {
    body: body.slice(0, lineStart) + transformed + body.slice(lineEnd),
    selectionStart: lineStart,
    selectionEnd: lineStart + transformed.length,
  };
}

export function continueNoteList(body: string, start: number, end: number): NoteEdit | null {
  if (start !== end) return null;
  const lineStart = start === 0 ? 0 : body.lastIndexOf('\n', start - 1) + 1;
  const line = body.slice(lineStart, start);
  const match = line.match(/^(\s*)(- \[[ x]\] |[-*+] |\d+\. )/);
  if (!match) return null;
  const content = line.slice(match[0].length);
  if (!content.trim() && (start === body.length || body[start] === '\n')) {
    const next = body.slice(0, lineStart) + body.slice(start);
    return { body: next, selectionStart: lineStart, selectionEnd: lineStart };
  }
  const marker = match[2];
  const nextMarker = /^\d+\. $/.test(marker) ? `${Number.parseInt(marker, 10) + 1}. ` : marker === '- [x] ' ? '- [ ] ' : marker;
  const inserted = `\n${match[1]}${nextMarker}`;
  const cursor = start + inserted.length;
  return { body: body.slice(0, start) + inserted + body.slice(start), selectionStart: cursor, selectionEnd: cursor };
}
