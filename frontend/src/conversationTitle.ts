/** Deriving a sidebar label from a conversation's first question. */

import type { ChatMessage } from './api/client';

/** Longest title the sidebar shows before truncating. */
const TITLE_LIMIT = 45;

/**
 * A short, scannable title from the conversation's first question.
 *
 * Truncates on a word boundary when there is a sensible one, so the sidebar
 * does not cut mid-word.
 */
export function getConversationTitle(firstUserMessage: string | undefined): string {
  const text = (firstUserMessage ?? '').replace(/\s+/g, ' ').trim();
  if (!text) return 'New conversation';
  if (text.length <= TITLE_LIMIT) return text;

  const clipped = text.slice(0, TITLE_LIMIT);
  const lastSpace = clipped.lastIndexOf(' ');
  // Only respect the word boundary if it does not throw most of the title away.
  const head = lastSpace > TITLE_LIMIT * 0.6 ? clipped.slice(0, lastSpace) : clipped;
  return `${head.replace(/[,.;:!?]$/, '')}…`;
}

/** The conversation's first question, which the title is derived from. */
export function firstQuestion(messages: ChatMessage[]): string {
  return messages.find((message) => message.role === 'user')?.content ?? '';
}
