import type { ReactNode } from 'react';

import { SUGGESTED_QUESTIONS } from '../constants';

/** The first screen: greeting, a live composer (passed in), and starters. */
export function Landing({
  onPick,
  children,
}: {
  onPick: (question: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="landing">
      <div className="landing-inner">
        <h1 className="landing-title">What would you like to know?</h1>
        <p className="landing-sub">
          Ask about product and growth. Every answer is grounded in Lenny&apos;s
          Podcast transcripts and cites the episodes it came from.
        </p>

        {children}

        <ul className="suggestions">
          {SUGGESTED_QUESTIONS.map((question) => (
            <li key={question}>
              <button
                type="button"
                className="suggestion"
                onClick={() => onPick(question)}
              >
                {question}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
