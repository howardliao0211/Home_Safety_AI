export const MAX_CHAT_QUESTION = 2000;
export type ChatTurn = {
  id: string;
  question: string;
  answer: string | null;
  /** "ready": legacy accepted but never started; continue explicitly. */
  status: "ready" | "queued" | "running" | "failed" | "complete";
  error: string | null;
  /** Safe failure category, e.g. interrupted, truncated, context_limit. */
  error_code?: string | null;
  created_at: string;
  finished_at: string | null;
  /** Text received so far by the current attempt; kept when it fails. */
  partial?: string;
  /** Monotonic progress version: older snapshots never replace newer ones. */
  version?: number;
  /** Preview only: simulated attempts, so a scenario can fail once. */
  attempts?: number;
};
export type Conversation = {
  turns: ChatTurn[];
  blocked_reason: string | null;
  retry_blocked_reason?: string | null;
  max_question_length: number;
};
export type LocalChat = {
  draft: string;
  outbound?: { id: string; question: string };
  preview?: Conversation;
};
export const emptyConversation = (): Conversation => ({
  turns: [],
  blocked_reason: null,
  max_question_length: MAX_CHAT_QUESTION,
});
export function validateQuestion(text: string) {
  if (!text.trim()) return "Write a question before sending.";
  if (text.length > MAX_CHAT_QUESTION)
    return "Keep your question to 2,000 characters or fewer.";
  return undefined;
}
export const isActive = (turn: ChatTurn) =>
  turn.status === "queued" || turn.status === "running";
/** A failed attempt that produced some text: shown, labelled, never complete. */
export const isIncomplete = (turn: ChatTurn) =>
  turn.status === "failed" && !!turn.partial;
/**
 * Combine an observed snapshot with what is shown. Out-of-order reads, such as
 * a late partial after the final answer or a manual retry, are ignored per turn.
 */
export function mergeConversation(
  current: Conversation | undefined,
  incoming: Conversation,
): Conversation {
  if (!current) return incoming;
  return {
    ...incoming,
    turns: incoming.turns.map((turn) => {
      const shown = current.turns.find((t) => t.id === turn.id);
      return shown && (shown.version ?? 0) > (turn.version ?? 0) ? shown : turn;
    }),
  };
}
