import { notFound } from 'next/navigation';
import { VoicePreview } from '@/components/voice/voice-preview';

export default function VoiceFixtures() {
  if (process.env.NODE_ENV !== 'development') notFound();
  return <VoicePreview />;
}
