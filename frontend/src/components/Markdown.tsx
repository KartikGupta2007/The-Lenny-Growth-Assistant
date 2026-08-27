/**
 * Renders the light Markdown the models emit: headings, bold, italic, inline
 * code, fenced code, blockquotes and lists.
 *
 * Everything becomes React elements -- no HTML is parsed or injected, so there
 * is nothing to sanitise. Markdown links are deliberately not rendered: a URL
 * in model text is unverified, and every real link in this app comes from the
 * backend's own source metadata.
 */

import type { ReactNode } from 'react';

import type { Source } from '../api/client';

type Block =
  | { kind: 'p' | 'quote' | 'code'; text: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] };

const FENCE = /^\s*```/;
const HEADING = /^\s*(#{1,4})\s+(.*)$/;
const QUOTE = /^\s*>\s?/;
const BULLET = /^\s*[-*+]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;
/** Any line that starts a block of its own, so a paragraph stops before it. */
const BLOCK_START = /^\s*(```|#{1,4}\s|>|[-*+]\s|\d+[.)]\s)/;

function parse(input: string): Block[] {
  const lines = input.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (FENCE.test(line)) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i])) body.push(lines[i++]);
      i += 1; // closing fence, or the end of the text
      blocks.push({ kind: 'code', text: body.join('\n') });
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] });
      i += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        body.push(lines[i++].replace(QUOTE, ''));
      }
      blocks.push({ kind: 'quote', text: body.join(' ') });
      continue;
    }

    if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line);
      const marker = ordered ? NUMBERED : BULLET;
      const items: string[] = [];
      while (i < lines.length && marker.test(lines[i])) {
        items.push(lines[i++].replace(marker, ''));
      }
      blocks.push({ kind: 'list', ordered, items });
      continue;
    }

    const body: string[] = [];
    while (i < lines.length && lines[i].trim() && !BLOCK_START.test(lines[i])) {
      body.push(lines[i++].trim());
    }
    blocks.push({ kind: 'p', text: body.join(' ') });
  }

  return blocks;
}

// A marker swallows the punctuation that follows it, so the two never end up
// on different lines.
const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[\d{1,2}\](?!\()[.,;:!?]?)/g;

interface InlineContext {
  sources?: Source[];
  onCite?: (source: Source) => void;
}

function inline(text: string, key: string, ctx: InlineContext): ReactNode[] {
  // Models write "... value" [4]." -- close the gap so the marker sits against
  // the word it cites, the way a footnote does.
  const tightened = text.replace(/[ \t]+(\[\d{1,2}\])/g, '$1');

  return tightened.split(INLINE).map((part, index) => {
    if (!part) return null;
    const id = `${key}-${index}`;

    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={id}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={id}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={id}>{part.slice(1, -1)}</code>;
    }

    const cite = part.match(/^\[(\d{1,2})\]([.,;:!?]?)$/);
    if (cite) {
      const number = Number(cite[1]);
      const trailing = cite[2];
      const source = ctx.sources?.find((s) => s.number === number);
      // A number the backend did not supply stays plain text: the model can
      // never turn an invented index into something clickable.
      if (!source || !ctx.onCite) return <span key={id}>{part}</span>;
      return (
        <span key={id} className="cite-group">
          <button
            type="button"
            className="citation"
            onClick={() => ctx.onCite?.(source)}
            title={source.title}
            aria-label={`Source ${number}: ${source.title}`}
          >
            {number}
          </button>
          {trailing}
        </span>
      );
    }

    return <span key={id}>{part}</span>;
  });
}

interface MarkdownProps {
  content: string;
  className?: string;
  /** Supplied for assistant answers, so `[n]` becomes a citation control. */
  sources?: Source[];
  onCite?: (source: Source) => void;
  /** Drops a leading heading equal to this, so a title is not shown twice. */
  omitTitle?: string;
}

export function Markdown({
  content,
  className = 'markdown',
  sources,
  onCite,
  omitTitle,
}: MarkdownProps) {
  let blocks = parse(content.trim());

  const first = blocks[0];
  if (omitTitle && first?.kind === 'heading' && first.text.trim() === omitTitle.trim()) {
    blocks = blocks.slice(1);
  }

  const ctx = { sources, onCite };

  return (
    <div className={className}>
      {blocks.map((block, index) => {
        const key = `b${index}`;

        switch (block.kind) {
          case 'heading': {
            // Answers sit under the page h1, so their headings start at h2.
            const Tag = (['h2', 'h2', 'h3', 'h4'] as const)[block.level - 1] ?? 'h4';
            return <Tag key={key}>{inline(block.text, key, ctx)}</Tag>;
          }
          case 'code':
            return (
              <pre key={key}>
                <code>{block.text}</code>
              </pre>
            );
          case 'quote':
            return <blockquote key={key}>{inline(block.text, key, ctx)}</blockquote>;
          case 'list': {
            const items = block.items.map((item, n) => (
              <li key={`${key}-${n}`}>{inline(item, `${key}-${n}`, ctx)}</li>
            ));
            return block.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>;
          }
          default:
            return <p key={key}>{inline(block.text, key, ctx)}</p>;
        }
      })}
    </div>
  );
}
