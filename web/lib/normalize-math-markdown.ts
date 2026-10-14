/**
 * Prepare LLM Markdown for remark-math / rehype-katex.
 *
 * micromark-extension-math only recognizes `$…$` / `$$…$$`. Models often emit
 * TeX delimiters `\(...\)` / `\[…\]`, which CommonMark then escapes into `[…]`
 * and eats matrix `\\` row breaks — producing the raw LaTeX screenshot bug.
 *
 * Normalization runs only outside fenced/inline code so code samples stay literal.
 */

const FENCE_OR_INLINE = /(```[\s\S]*?```|`[^`\n]+`)/g;
const DISPLAY_TEX = /\\\[([\s\S]*?)\\\]/g;
const INLINE_TEX = /\\\(([\s\S]*?)\\\)/g;
const BARE_ENV =
  /\\begin\{(bmatrix|pmatrix|vmatrix|Vmatrix|matrix|smallmatrix|aligned|align\*?|cases|gather\*?|eqnarray\*?|array)\}[\s\S]*?\\end\{\1\}/g;

function mapOutsideCode(source: string, transform: (segment: string) => string): string {
  const parts = source.split(FENCE_OR_INLINE);
  return parts.map((part, index) => (index % 2 === 1 ? part : transform(part))).join('');
}

function alreadyMath(segment: string, matchIndex: number): boolean {
  const before = segment.slice(0, matchIndex);
  const dollars = before.match(/\$\$?/g) || [];
  return dollars.length % 2 === 1;
}

function wrapBareEnvironments(segment: string): string {
  return segment.replace(BARE_ENV, (match, _env, offset) => {
    if (alreadyMath(segment, offset)) return match;
    const trimmed = match.trim();
    return `\n\n$$\n${trimmed}\n$$\n\n`;
  });
}

function softenIncompleteOpeners(segment: string): string {
  // Unclosed TeX openers would otherwise become `[` / `(` via Markdown escapes.
  // Promote them to dollar openers so remark-math owns the trailing fragment;
  // rehype-katex uses throwOnError:false for incomplete bodies during streaming.
  // Note: String.replace treats `$$` as a single `$`, so use a replacer function.
  if (/\\\[[\s\S]*$/.test(segment) && !/\\\[[\s\S]*\\\]/.test(segment)) {
    segment = segment.replace(/\\\[/, () => '$$\n');
  }
  if (/\\\([\s\S]*$/.test(segment) && !/\\\([\s\S]*\\\)/.test(segment)) {
    segment = segment.replace(/\\\(/, () => '$');
  }
  return segment;
}

/** Several ordinary words in a row: a span of prose, not a formula. */
const PROSE = /[A-Za-z]{2,}[ ,;]+[A-Za-z]{2,}[ ,;]+[A-Za-z]{2,}/;
/** An amount followed by a word ("$20 discount"): a price, not the start of a formula. */
const PRICE = /^\d[\d,.]*(?:\s*(?:k|m|bn|million|billion|thousand))?\s+[A-Za-z]{2,}/i;

/**
 * Decide which single `$` signs delimit inline math and escape the rest.
 *
 * remark-math pairs any two `$`, so "buy $100,000 of goods … £1 = $1.25"
 * became one garbled italic formula. This applies Pandoc's rules: an opening
 * `$` is followed by a non-space, a closing `$` follows a non-space and is not
 * followed by a digit. A span that reads as prose, or starts as a price, is not math either.
 * Unpaired and rejected signs are escaped, so prices stay plain text.
 */
function escapeTextDollars(text: string): string {
  const signs: number[] = [];
  for (let index = 0; index < text.length; index++) {
    if (text[index] !== '$' || text[index - 1] === '\\') continue;
    if (text[index + 1] === '$') { index++; continue; } // `$$` display delimiters are left alone.
    signs.push(index);
  }
  if (!signs.length) return text;
  const math = new Set<number>();
  for (let k = 0; k < signs.length; k++) {
    const open = signs[k];
    if (!text[open + 1] || /\s/.test(text[open + 1])) continue;
    for (let m = k + 1; m < signs.length; m++) {
      const close = signs[m];
      const body = text.slice(open + 1, close);
      if (/\n\s*\n/.test(body) || (PROSE.test(body) && !body.includes('\\')) || PRICE.test(body)) break;
      if (/\s/.test(text[close - 1]) || /\d/.test(text[close + 1] || '')) continue;
      math.add(open); math.add(close); k = m;
      break;
    }
  }
  let output = '', last = 0;
  for (const index of signs) {
    if (math.has(index)) continue;
    output += `${text.slice(last, index)}\\$`;
    last = index + 1;
  }
  return output + text.slice(last);
}

/** Apply escapeTextDollars outside `$$…$$` display blocks. */
function escapeCurrency(segment: string): string {
  return segment.split(/(\$\$[\s\S]*?\$\$)/g).map((part, index) => (index % 2 === 1 ? part : escapeTextDollars(part))).join('');
}

export function normalizeMathMarkdown(source: string): string {
  if (!source) return source;
  return mapOutsideCode(source, (segment) => {
    // Currency runs first, on the author's own dollars, before TeX delimiters become `$`.
    let next = escapeCurrency(segment)
      .replace(DISPLAY_TEX, (_match, body: string) => `\n\n$$\n${String(body).trim()}\n$$\n\n`)
      .replace(INLINE_TEX, (_match, body: string) => `$${String(body).trim()}$`);
    next = wrapBareEnvironments(next);
    next = softenIncompleteOpeners(next);
    return next;
  });
}
