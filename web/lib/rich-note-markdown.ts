function escapeText(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/([*_`])/g, '\\$1');
}

function inline(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return escapeText(node.textContent || '');
  if (!(node instanceof HTMLElement)) return '';
  if (node.classList.contains('katex')) {
    const source = node.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
    if (source) return `$${source}$`;
  }
  const tag = node.tagName.toLowerCase();
  if (tag === 'br') return '\n';
  if (tag === 'input' && (node as HTMLInputElement).type === 'checkbox') return (node as HTMLInputElement).checked ? '[x] ' : '[ ] ';
  if (tag === 'img') return node.getAttribute('alt') || '';
  const content = Array.from(node.childNodes).map(inline).join('');
  if (tag === 'strong' || tag === 'b') return `**${content}**`;
  if (tag === 'em' || tag === 'i') return `*${content}*`;
  if (tag === 'code') return `\`${content}\``;
  if (tag === 'a') return `[${content}](${node.getAttribute('href') || ''})`;
  if (tag === 's' || tag === 'strike' || tag === 'del') return `~~${content}~~`;
  return content;
}

function block(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return (node.textContent || '').trim();
  if (!(node instanceof HTMLElement)) return '';
  if (node.classList.contains('katex-display')) {
    const source = node.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
    if (source) return `$$\n${source}\n$$`;
  }
  const tag = node.tagName.toLowerCase();
  if (tag === 'hr') return '---';
  if (tag === 'table') {
    const rows = Array.from(node.querySelectorAll('tr')).map(row => Array.from(row.querySelectorAll('th, td')).map(cell => Array.from(cell.childNodes).map(inline).join('').replace(/\|/g, '\\|').trim()));
    if (!rows.length) return '';
    const width = Math.max(...rows.map(row => row.length));
    const line = (cells: string[]) => `| ${Array.from({ length: width }, (_, index) => cells[index] || '').join(' | ')} |`;
    return [line(rows[0]), line(Array(width).fill('---')), ...rows.slice(1).map(line)].join('\n');
  }
  if (tag === 'ul' || tag === 'ol') {
    return Array.from(node.children).map((item, index) => {
      const prefix = tag === 'ol' ? `${index + 1}. ` : '- ';
      return `${prefix}${Array.from(item.childNodes).map(child => child instanceof HTMLElement && /^(ul|ol)$/i.test(child.tagName) ? `\n${block(child)}` : inline(child)).join('').trim()}`;
    }).join('\n');
  }
  if (tag === 'blockquote') return Array.from(node.childNodes).map(block).join('\n').split('\n').map(line => `> ${line}`).join('\n');
  if (tag === 'pre') return `\`\`\`\n${node.textContent || ''}\n\`\`\``;
  if (/^h[1-6]$/.test(tag)) return `${'#'.repeat(Number(tag[1]))} ${Array.from(node.childNodes).map(inline).join('').trim()}`;
  if (tag === 'div' && node.children.length && Array.from(node.children).some(child => /^(p|div|h[1-6]|ul|ol)$/i.test(child.tagName))) return Array.from(node.childNodes).map(block).filter(Boolean).join('\n\n');
  return Array.from(node.childNodes).map(inline).join('').trim();
}

/** Serialize the supported rich-text surface to the workspace note's Markdown format. */
export function richNoteToMarkdown(root: HTMLElement): string {
  return Array.from(root.childNodes).map(block).filter(Boolean).join('\n\n').trim();
}
