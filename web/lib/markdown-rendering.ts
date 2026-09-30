import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

export const readingRemarkPlugins = [remarkGfm, [remarkMath, { singleDollarTextMath: true }]];
export const readingRehypePlugins = [[rehypeKatex, { throwOnError: false, trust: false, maxExpand: 1000, maxSize: 20, output: 'htmlAndMathml', strict: 'warn' }]];
