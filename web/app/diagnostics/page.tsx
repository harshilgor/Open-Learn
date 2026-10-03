import Link from 'next/link';
import { HypothesisPanel } from '@/components/hypothesis-panel';
import { QuizWorkspace } from '@/components/quiz-workspace';

export default async function DiagnosticsPage({ searchParams }: { searchParams: Promise<{ quiz?: string }> }) {
  const { quiz } = await searchParams;
  return <main className="mx-auto max-w-3xl p-6"><Link href="/" className="underline">← Back to learning</Link><h1 className="my-5 text-3xl font-semibold">A short understanding check</h1><p>You can skip this or return to your lesson whenever you want.</p>{quiz ? <QuizWorkspace quizId={quiz} /> : <HypothesisPanel />}</main>;
}
