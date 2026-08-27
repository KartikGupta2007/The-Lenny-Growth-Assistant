/**
 * Citations under an assistant answer.
 *
 * Collapsed by default so a 600-word answer stays the thing you read. Several
 * retrieved chunks often come from one episode, so they are grouped: eight
 * chunks usually mean four or five real episodes.
 *
 * Every field comes from the backend, built from the retrieval result. Nothing
 * is parsed out of the model's text, so an invented URL can never become a link.
 */

import { useState } from 'react';

import type { Source } from '../api/client';
import { episodeName } from '../episodeName';
import { IconChevronDown, IconExternal } from './icons';

interface Episode {
  source: Source;
  numbers: number[];
}

function groupByEpisode(sources: Source[]): Episode[] {
  const episodes = new Map<string, Episode>();
  for (const source of sources) {
    const key = source.source_url || source.title;
    const found = episodes.get(key);
    if (found) found.numbers.push(source.number);
    else episodes.set(key, { source, numbers: [source.number] });
  }
  return [...episodes.values()].sort((a, b) => a.numbers[0] - b.numbers[0]);
}

/** "Todd Jackson, Sean Ellis +3" -- a readable hint at what is behind the row. */
function preview(episodes: Episode[]): string {
  const names = episodes
    .map((episode) => episode.source.guest)
    .filter((guest): guest is string => Boolean(guest));
  if (names.length === 0) return '';
  const shown = names.slice(0, 2).join(', ');
  const rest = names.length - 2;
  return rest > 0 ? `${shown} +${rest}` : shown;
}

export function SourceList({
  sources,
  onOpen,
}: {
  sources: Source[];
  onOpen: (source: Source) => void;
}) {
  const [open, setOpen] = useState(false);
  if (sources.length === 0) return null;

  const episodes = groupByEpisode(sources);
  const label = `${episodes.length} ${episodes.length === 1 ? 'source' : 'sources'}`;

  return (
    <section className="sources" data-open={open}>
      <button
        type="button"
        className="sources-toggle"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <IconChevronDown className="sources-caret" />
        <span className="sources-label">{label}</span>
        {!open && <span className="sources-preview">{preview(episodes)}</span>}
      </button>

      {open && (
        <ol className="source-items">
          {episodes.map(({ source, numbers }) => (
            <li key={source.chunk_id}>
              <button
                type="button"
                className="source-row"
                title={source.title}
                onClick={() => onOpen(source)}
              >
                <span className="source-number" aria-hidden="true">
                  {numbers.join(', ')}
                </span>
                <span className="source-body">
                  <span className="source-episode">{episodeName(source.title)}</span>
                  {source.guest && (
                    <span className="source-guest">{source.guest}</span>
                  )}
                </span>
              </button>
              {source.source_url && (
                <a
                  className="source-link"
                  href={source.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Watch the episode: ${source.title}`}
                >
                  <IconExternal />
                </a>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
