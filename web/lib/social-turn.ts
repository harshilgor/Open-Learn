// Only whole-message social turns qualify; tasks attached to greetings must
// still be routed. The backend remains responsible for the actual reply.
const socialTurns = new Set(['hi','hello','hey','hiya','hey there','hello there','hi there','hey buddy','hello buddy','good morning','good afternoon','good evening','morning','thanks','thank you','thanks buddy','thank you buddy','ty','bye','goodbye','see you','see you later']);
export function isSocialTurn(message: string): boolean {
  return socialTurns.has(message.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}_\s]/gu,' ').trim().replace(/\s+/g,' '));
}
