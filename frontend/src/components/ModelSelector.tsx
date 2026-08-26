/**
 * Model selector.
 *
 * Every provider the backend knows about is rendered, including the ones that
 * cannot be used here. An unusable provider is shown disabled with the reason
 * beside it -- in production that is Ollama, which needs a local daemon the
 * hosted API does not have. Hiding it instead would leave the user wondering
 * whether local models exist at all; showing it disabled answers the question.
 *
 * Implemented as a radio group so that keyboard users get native arrow-key
 * navigation and disabled options are announced as disabled.
 */

import type { ProviderStatus } from '../api/client';
import {
  COPY,
  MODEL_RADIO_GROUP_NAME,
  PROVIDER_KIND_LABELS,
  PROVIDER_REASON_ID_PREFIX,
  type ProviderId,
} from '../constants';

interface ModelSelectorProps {
  providers: ProviderStatus[];
  selected: ProviderId | null;
  onSelect: (id: ProviderId) => void;
  /** Disables the whole group, e.g. while a response is generating. */
  busy?: boolean;
}

export function ModelSelector({
  providers,
  selected,
  onSelect,
  busy = false,
}: ModelSelectorProps) {
  return (
    <fieldset className="model-selector" disabled={busy}>
      <legend className="model-selector-legend">{COPY.modelLegend}</legend>

      <div className="model-options">
        {providers.map((provider) => {
          const disabled = !provider.available;
          const reasonId = `${PROVIDER_REASON_ID_PREFIX}-${provider.id}`;

          return (
            <label
              key={provider.id}
              className="model-option"
              data-disabled={disabled}
              data-selected={selected === provider.id}
            >
              <input
                type="radio"
                name={MODEL_RADIO_GROUP_NAME}
                value={provider.id}
                checked={selected === provider.id}
                disabled={disabled}
                aria-describedby={disabled ? reasonId : undefined}
                onChange={() => onSelect(provider.id)}
              />

              <span className="model-option-body">
                <span className="model-option-title">
                  {provider.label}
                  <span className="model-option-kind">
                    {PROVIDER_KIND_LABELS[provider.kind]}
                  </span>
                </span>

                <span className="model-option-model">{provider.model}</span>

                {disabled && provider.reason && (
                  <span className="model-option-reason" id={reasonId}>
                    {provider.reason}
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
