import { useState } from 'react';

import type { Session } from '../api/client';
import { getConversationTitle } from '../conversationTitle';
import { IconTrash } from './icons';

interface SessionListProps {
  sessions: Session[];
  activeId: string | null;
  /** Full first question per session; the title is derived at render. */
  questions: Record<string, string>;
  loading: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

/** Buckets the sidebar groups by, newest first. */
function bucketOf(session: Session): string {
  const day = 24 * 60 * 60 * 1000;
  const age = Date.now() - new Date(session.updated_at).getTime();
  if (age < day) return 'Today';
  if (age < 2 * day) return 'Yesterday';
  if (age < 7 * day) return 'Previous 7 days';
  if (age < 30 * day) return 'Previous 30 days';
  return 'Older';
}

function group(sessions: Session[]): [string, Session[]][] {
  const buckets = new Map<string, Session[]>();
  for (const session of sessions) {
    const key = bucketOf(session);
    const found = buckets.get(key);
    if (found) found.push(session);
    else buckets.set(key, [session]);
  }
  return [...buckets.entries()];
}

export function SessionList({
  sessions,
  activeId,
  questions,
  loading,
  onSelect,
  onDelete,
}: SessionListProps) {
  // Which row is asking "delete?" -- a click never deletes straight away.
  const [confirming, setConfirming] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="session-skeleton" aria-label="Loading conversations">
        {[0, 1, 2, 3, 4].map((n) => (
          <span key={n} />
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="sidebar-empty">
        <p>No conversations yet</p>
        <p>Ask a question and it will appear here.</p>
      </div>
    );
  }

  return (
    <>
      {group(sessions).map(([bucket, items]) => (
        <section key={bucket} className="session-group">
          <p className="session-group-title">{bucket}</p>
          <ul className="session-list" aria-label={bucket}>
            {items.map((session) => {
              const question = questions[session.id];
              const title = getConversationTitle(question);
              const isConfirming = confirming === session.id;

              return (
                <li
                  key={session.id}
                  className="session-row"
                  data-confirming={isConfirming}
                  data-active={session.id === activeId}
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') setConfirming(null);
                  }}
                >
                  {isConfirming ? (
                    <>
                      <span className="session-confirm-text">Delete this chat?</span>
                      <button
                        type="button"
                        className="session-confirm"
                        onClick={() => {
                          setConfirming(null);
                          onDelete(session.id);
                        }}
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        className="session-cancel"
                        onClick={() => setConfirming(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="session-item"
                        title={question || undefined}
                        aria-current={session.id === activeId ? 'true' : undefined}
                        onClick={() => onSelect(session.id)}
                      >
                        {title}
                      </button>
                      <button
                        type="button"
                        className="session-delete"
                        aria-label={`Delete conversation: ${title}`}
                        onClick={() => setConfirming(session.id)}
                      >
                        <IconTrash />
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </>
  );
}
