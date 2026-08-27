/**
 * Model selector.
 *
 * Every provider the backend knows about is listed, including ones that cannot
 * be used here. An unusable provider stays visible, disabled, with its reason
 * -- in production that is Ollama, which needs a local daemon the hosted API
 * does not have. Hiding it would leave the user wondering whether local models
 * exist at all; showing it disabled answers the question.
 *
 * A listbox rather than a <select>, so the options can carry a kind badge and
 * an explanation, and still keep arrow-key navigation.
 */

import { useEffect, useRef, useState } from 'react';

import type { ProviderStatus } from '../api/client';
import { PROVIDER_KIND_LABELS, type ProviderId } from '../constants';
import { IconCheck, IconChevronDown } from './icons';

interface ModelSelectorProps {
  providers: ProviderStatus[];
  selected: ProviderId | null;
  onSelect: (id: ProviderId) => void;
  /** Disables the control, e.g. while a response is generating. */
  busy?: boolean;
}

export function ModelSelector({
  providers,
  selected,
  onSelect,
  busy = false,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);

  const current = providers.find((p) => p.id === selected);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        trigger.current?.focus();
      }
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    // Land on the selected option so arrow keys start from the right place.
    list.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus();

    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  function move(delta: number) {
    const options = [
      ...(list.current?.querySelectorAll<HTMLButtonElement>(
        '[role="option"]:not(:disabled)',
      ) ?? []),
    ];
    if (options.length === 0) return;
    const index = options.indexOf(document.activeElement as HTMLButtonElement);
    const next = (index + delta + options.length) % options.length;
    options[next].focus();
  }

  return (
    <div className="model" ref={root}>
      <button
        type="button"
        ref={trigger}
        className="model-trigger"
        disabled={busy}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Model: ${current?.label ?? 'none available'}`}
        onClick={() => setOpen(!open)}
      >
        <span className="model-dot" data-kind={current?.kind} aria-hidden="true" />
        <span className="model-name">{current?.label ?? 'No model'}</span>
        <IconChevronDown className="model-caret" />
      </button>

      {open && (
        <div
          className="model-menu"
          role="listbox"
          ref={list}
          aria-label="Model"
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              move(1);
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              move(-1);
            }
          }}
        >
          {providers.map((provider) => {
            const unavailable = !provider.available;
            return (
              <button
                key={provider.id}
                type="button"
                role="option"
                className="model-item"
                disabled={unavailable}
                aria-selected={selected === provider.id}
                onClick={() => {
                  onSelect(provider.id);
                  setOpen(false);
                  trigger.current?.focus();
                }}
              >
                <span className="model-item-head">
                  <span className="model-dot" data-kind={provider.kind} aria-hidden="true" />
                  <span className="model-item-name">{provider.label}</span>
                  <span className="model-item-kind">
                    {PROVIDER_KIND_LABELS[provider.kind]}
                  </span>
                  {selected === provider.id && <IconCheck className="model-item-check" />}
                </span>
                <span className="model-item-model">{provider.model}</span>
                {unavailable && provider.reason && (
                  <span className="model-item-reason">{provider.reason}</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
