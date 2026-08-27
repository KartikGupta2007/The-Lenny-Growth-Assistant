import { useEffect, useRef } from 'react';

import type { ArtifactSummary, ChatMessage, Source } from '../api/client';
import { IconSparkle } from './icons';
import { MessageBubble } from './MessageBubble';

interface MessageListProps {
  messages: ChatMessage[];
  artifacts: ArtifactSummary[];
  sending: boolean;
  onOpenArtifact: (id: string) => void;
  onOpenSource: (source: Source) => void;
}

export function MessageList({
  messages,
  artifacts,
  sending,
  onOpenArtifact,
  onOpenSource,
}: MessageListProps) {
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, sending]);

  return (
    <div className="messages">
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          artifact={artifacts.find((a) => a.message_id === message.id)}
          onOpenArtifact={onOpenArtifact}
          onOpenSource={onOpenSource}
        />
      ))}

      {sending && (
        <article className="message message-assistant">
          <span className="assistant-mark" aria-hidden="true">
            <IconSparkle />
          </span>
          <div className="assistant-body">
            {/* One honest label -- the backend reports no progress to stage. */}
            <p className="thinking" role="status">
              Searching the transcripts and writing an answer
            </p>
            <div className="skeleton-lines" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          </div>
        </article>
      )}

      <div ref={end} />
    </div>
  );
}
