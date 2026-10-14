"use client";

import { useState } from 'react';
import Link from 'next/link';
import { LessonReader, type ReadingBlock } from '@/components/lesson-reader';
import { RichContent } from '@/components/rich-content';

const blocks: ReadingBlock[] = [
  { id: 'intuition', heading: 'A small adjustment, a better prediction', body: String.raw`A neural network learns by adjusting its **weights**. Each adjustment should move its prediction closer to the desired answer.

> **Key idea:** The gradient tells us which direction increases the error. We move in the opposite direction.

Keep the learning rate small enough that we can make a useful adjustment rather than overshooting.` },
  { id: 'equation', heading: 'The update rule', body: String.raw`The rule combines the current weight, the learning rate, and the gradient:

$$
w_{\mathrm{new}} = w_{\mathrm{old}} - \eta\frac{\partial L}{\partial w}
$$

Here, $w$ is a weight, $\eta$ is the **learning rate**, and $L$ is the loss. The derivative measures how the loss changes as the weight changes.

If the gradient is positive, subtracting it reduces the weight. A negative gradient leads to an increase.` },
  { id: 'currency', heading: 'Prices and formulas together', body: String.raw`**Example 1: An importer.** A UK company agrees to buy $100,000 of goods from a US supplier, payable in 3 months. The current rate is £1 = $1.25, so the cost is about £80,000. It enters a 3-month forward contract to buy $100,000 at a rate of £1 = $1.24.

- If the pound falls to $1.20, the company still pays only about £80,645.
- The cost in pounds is $C = rac{100{,}000}{F}$, where $F$ is the forward rate.` },
  { id: 'example', heading: 'Show it with numbers', body: String.raw`Suppose $w_{\mathrm{old}}=2$, $\eta=0.1$, and $\frac{\partial L}{\partial w}=3$.

$$
\begin{aligned}
w_{\mathrm{new}} &= 2 - 0.1(3) \\
&= 2 - 0.3 \\
&= 1.7
\end{aligned}
$$

1. Multiply the gradient by the learning rate: the adjustment is $0.3$.
2. Subtract the adjustment from the old weight.
3. The new weight is $1.7$. Whether the next prediction improves must still be checked.` },
  { id: 'detail', heading: 'Follow the computation', body: '```text\nInput → Prediction → Loss\n                       ↓\nUpdated weights ← Gradient\n```\n\n```details\nWhy subtract the gradient?\nFor a sufficiently small step, moving opposite the gradient tends to decrease the loss. The step size matters: a large jump can overshoot.\n\n**The rule is local**, so we measure the loss again after updating.\n```' },
  { id: 'comparison', heading: 'Compare the roles', body: '| Quantity | Role |\n| --- | --- |\n| Weight | Controls the computation |\n| Learning rate | Controls the adjustment size |\n| Gradient | Measures local sensitivity |\n\nChanging a reading preference changes the presentation only. It does not change your learning progress.' },
];

export default function ReadingPreview() {
  const [selected, setSelected] = useState('');
  return <main style={{ maxWidth: 760, margin: '0 auto', padding: '48px 24px 100px' }}><Link href="/">← Back to chat</Link><p style={{ margin: '24px 0 8px', color: '#73806b', fontSize: 13 }}>READING PREVIEW · AUTHORED SAMPLE</p><h1 style={{ fontSize: 32, marginBottom: 32 }}>Understanding gradient descent</h1><p><Link href="/visualization-preview">Explore the visualization previews →</Link></p><LessonReader id="preview" blocks={blocks} onSelect={(_, raw) => setSelected(raw)} />{selected && <aside aria-label="Selected source preview" style={{ border: '1px solid #ddd', borderRadius: 12, padding: 20 }}><button onClick={() => setSelected('')}>Close preview</button><p>This sample shows the selected source; live chat adds it to the composer as context.</p><RichContent body={selected} /></aside>}</main>;
}
