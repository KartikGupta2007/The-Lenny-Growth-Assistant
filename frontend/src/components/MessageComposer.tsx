import { useEffect, useRef, useState } from 'react';

import type { ProviderStatus } from '../api/client';
import { MAX_MESSAGE_LENGTH, type ProviderId } from '../constants';
import { IconArrowUp } from './icons';
import { ModelSelector } from './ModelSelector';

/** Grows with the text up to this, then scrolls. */
const MAX_HEIGHT = 200;

interface MessageComposerProps {
  onSend: (message: string) => void;
  disabled: boolean;
  sending: boolean;
  providers: ProviderStatus[];
  provider: ProviderId | null;
  onSelectProvider: (id: ProviderId) => void;
  autoFocus?: boolean;
  placeholder?: string;
}

export function MessageComposer({
  onSend,
  disabled,
  sending,
  providers,
  provider,
  onSelectProvider,
  autoFocus,
  placeholder = 'Ask about product, growth, retention…',
}: MessageComposerProps) {
  const [value, setValue] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (autoFocus) field.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    const element = field.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  const trimmed = value.trim();
  const tooLong = trimmed.length > MAX_MESSAGE_LENGTH;
  const canSend = trimmed.length > 0 && !tooLong && !disabled;
  const nearLimit = trimmed.length > MAX_MESSAGE_LENGTH * 0.8;

  function submit() {
    if (!canSend) return;
    onSend(trimmed);
    setValue('');
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="composer-box" data-invalid={tooLong}>
        <label className="visually-hidden" htmlFor="composer-input">
          Your question
        </label>
        <textarea
          id="composer-input"
          ref={field}
          className="composer-input"
          rows={1}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          aria-describedby={tooLong ? 'composer-error' : undefined}
          aria-invalid={tooLong}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends; Shift+Enter starts a new line.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />

        <div className="composer-actions">
          {providers.length > 0 && (
            <ModelSelector
              providers={providers}
              selected={provider}
              onSelect={onSelectProvider}
              busy={sending}
            />
          )}

          <div className="composer-right">
            {nearLimit && (
              <span className="composer-count" data-over={tooLong}>
                {trimmed.length.toLocaleString()}/
                {MAX_MESSAGE_LENGTH.toLocaleString()}
              </span>
            )}
            <button
              className="composer-send"
              type="submit"
              disabled={!canSend}
              aria-label={sending ? 'Sending' : 'Send message'}
            >
              {sending ? <span className="spinner" aria-hidden="true" /> : <IconArrowUp />}
            </button>
          </div>
        </div>
      </div>

      {tooLong ? (
        <p className="composer-error" id="composer-error" role="alert">
          That is {(trimmed.length - MAX_MESSAGE_LENGTH).toLocaleString()} characters
          over the limit.
        </p>
      ) : (
        <p className="composer-hint">Enter to send · Shift+Enter for a new line</p>
      )}
    </form>
  );
}
