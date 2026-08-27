import type { ArtifactSummary, ChatMessage, Source } from '../api/client';
import { IconDocument, IconSparkle } from './icons';
import { Markdown } from './Markdown';
import { SourceList } from './SourceList';

interface MessageBubbleProps {
  message: ChatMessage;
  /** The artifact this turn produced, if any. */
  artifact?: ArtifactSummary;
  onOpenArtifact: (id: string) => void;
  onOpenSource: (source: Source) => void;
}

export function MessageBubble({
  message,
  artifact,
  onOpenArtifact,
  onOpenSource,
}: MessageBubbleProps) {
  if (message.role === 'user') {
    return (
      <article className="message message-user" aria-label="Your question">
        <p className="user-bubble">{message.content}</p>
      </article>
    );
  }

  // grounded === false is the backend saying the corpus could not support an
  // answer. The frontend never decides this.
  const declined = message.grounded === false;

  return (
    <article className="message message-assistant" aria-label="Assistant answer">
      <span className="assistant-mark" aria-hidden="true">
        <IconSparkle />
      </span>

      <div className="assistant-body">
        {declined ? (
          <div className="decline">
            <span className="decline-label">No supporting evidence</span>
            <p>{message.content}</p>
          </div>
        ) : (
          <Markdown
            content={message.content}
            sources={message.sources}
            onCite={onOpenSource}
          />
        )}

        {artifact && (
          <button
            type="button"
            className="artifact-open"
            onClick={() => onOpenArtifact(artifact.id)}
          >
            <IconDocument />
            <span className="artifact-open-title">{artifact.title}</span>
            <span className="artifact-open-hint">Open</span>
          </button>
        )}

        <SourceList sources={message.sources} onOpen={onOpenSource} />
      </div>
    </article>
  );
}
