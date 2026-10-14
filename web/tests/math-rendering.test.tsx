import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import { expect, it } from 'vitest';
import { normalizeMathMarkdown } from '@/lib/normalize-math-markdown';
import { readingRehypePlugins, readingRemarkPlugins } from '@/lib/markdown-rendering';

const html = (markdown: string) => renderToStaticMarkup(<ReactMarkdown remarkPlugins={readingRemarkPlugins as never} rehypePlugins={readingRehypePlugins as never}>{normalizeMathMarkdown(markdown)}</ReactMarkdown>);

it('keeps prices as text instead of pairing them into one formula', () => {
  const answer = 'A UK company agrees to buy $100,000 of goods from a US supplier, payable in 3 months. The current rate is £1 = $1.25, so the cost is about £80,000. It enters a forward contract to buy $100,000 at a rate of £1 = $1.24.';
  const rendered = html(answer);
  expect(rendered).not.toContain('katex');
  expect(rendered).toContain('$100,000 of goods from a US supplier');
  expect(rendered).toContain('£1 = $1.25');
  expect(html('It costs $5 and $10 later.')).not.toContain('katex');
  expect(html('Between $5, $10 and $20.')).not.toContain('katex');
});

it('still renders real inline and display math', () => {
  expect(html('The slope of $y = mx + b$ is $m$.').match(/class="katex"/g)).toHaveLength(2);
  expect(html('Solve $2x+1=5$ for x.')).toContain('katex');
  expect(html('$$\nE = mc^2\n$$')).toContain('katex-display');
  expect(html('Use \\(a^2+b^2=c^2\\) here.')).toContain('katex');
  expect(html('Price is \\$4 already escaped.')).not.toContain('katex');
});

it('mixes prices and math in one answer', () => {
  const rendered = html('If $P = 100$ then a $20 discount leaves $P - 20 = 80$ dollars.');
  expect(rendered.match(/class="katex"/g)).toHaveLength(2);
  expect(rendered).toContain('a $20 discount');
});
