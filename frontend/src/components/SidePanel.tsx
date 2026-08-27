import type { Artifact, Source } from '../api/client';
import { episodeName } from '../episodeName';
import { IconClose, IconExternal } from './icons';
import { Markdown } from './Markdown';

/** What the panel is showing: a generated artifact, or one cited source. */
export type PanelContent =
  | { kind: 'artifact'; id: string }
  | { kind: 'source'; source: Source };

interface SidePanelProps {
  content: PanelContent | null;
  /** Loaded artifact, when `content` is an artifact. */
  artifact: Artifact | null;
  loading: boolean;
  onClose: () => void;
}

/**
 * HTML artifacts render inside a sandboxed iframe with no allow-scripts and no
 * allow-same-origin, so the frame has no JavaScript, no access to this page,
 * and no access to its storage or cookies. Content is also sanitised
 * server-side before it is stored.
 */
function HtmlArtifact({ content }: { content: string }) {
  const page = `<!doctype html><meta charset="utf-8"><style>
    :root { color-scheme: light dark }
    body { margin: 0; padding: 24px; font: 15px/1.6 ui-sans-serif, system-ui, sans-serif }
  </style>${content}`;

  return (
    <iframe
      className="artifact-frame"
      title="Rendered artifact"
      sandbox=""
      referrerPolicy="no-referrer"
      srcDoc={page}
    />
  );
}

function SourceDetail({ source }: { source: Source }) {
  return (
    <div className="source-detail">
      <h2>{episodeName(source.title)}</h2>
      {source.guest && <p className="source-detail-guest">{source.guest}</p>}
      <p className="source-detail-note">
        This episode supported the answer. It was cited as source {source.number}.
      </p>
      {source.source_url && (
        <a
          className="source-detail-link"
          href={source.source_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Watch the episode
          <IconExternal />
        </a>
      )}
    </div>
  );
}

export function SidePanel({ content, artifact, loading, onClose }: SidePanelProps) {
  const isSource = content?.kind === 'source';
  const kind = isSource
    ? 'Source'
    : artifact?.type === 'html'
      ? 'HTML'
      : artifact?.type === 'markdown'
        ? 'Markdown'
        : 'Artifact';
  const title = isSource
    ? episodeName(content.source.title)
    : (artifact?.title ?? 'Loading…');

  return (
    <aside className="panel" aria-label={isSource ? 'Source' : 'Artifact'}>
      <header className="panel-head">
        <div className="panel-title">
          <span className="panel-kind">{kind}</span>
          <p title={title}>{title}</p>
        </div>
        <button
          type="button"
          className="icon-button"
          onClick={onClose}
          aria-label="Close panel"
        >
          <IconClose />
        </button>
      </header>

      <div className="panel-body">
        {isSource && <SourceDetail source={content.source} />}

        {!isSource && loading && (
          <div className="skeleton-lines panel-skeleton" aria-label="Loading artifact">
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
        )}

        {!isSource && !loading && artifact?.type === 'html' && (
          <HtmlArtifact content={artifact.content} />
        )}

        {!isSource && !loading && artifact?.type === 'markdown' && (
          <Markdown
            content={artifact.content}
            className="markdown artifact-markdown"
            omitTitle={artifact.title}
          />
        )}
      </div>
    </aside>
  );
}
