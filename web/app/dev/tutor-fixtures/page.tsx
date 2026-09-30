import { notFound } from 'next/navigation';
import { RichContent } from '@/components/rich-content';
import { VerificationBadge } from '@/components/message-action-bar';

export default function TutorFixtures() {
  if (process.env.NODE_ENV !== 'development') notFound();
  const sample = '## Why gradients travel backward\n\n[[Backpropagation|Computes parameter gradients by applying the chain rule backward through a network.]] relates each layer to the next.\n\n### Try it\n\n```exercise\n{"id":"chain-rule-1","type":"numeric","prompt":"If y = 3x and x = 2t, what is dy/dt?","answer":"6","hint":"Multiply the two local derivatives.","explanation":"dy/dx = 3 and dx/dt = 2, so dy/dt = 6."}\n```';
  return <main style={{ maxWidth: 720, padding: 30, margin: 'auto' }}><h1>Tutor response fixtures</h1><RichContent body={sample}/><h2>Verification states</h2><VerificationBadge verification={{ status: 'verified', agents: 2, sources: [{ title: 'Example source', url: 'https://example.com' }] }}/><VerificationBadge verification={{ status: 'partial', agents: 1, sources: [] }}/><VerificationBadge verification={{ status: 'unverified', agents: 0, sources: [] }}/></main>;
}
