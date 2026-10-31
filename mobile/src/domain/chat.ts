export const MAX_CHAT_QUESTION = 2000;
export type ChatTurn = {
  id: string;
  question: string;
  answer: string | null;
  status: "ready" | "running" | "failed" | "complete";
  error: string | null;
  created_at: string;
  finished_at: string | null;
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
