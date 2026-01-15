import React from 'react';

export type FieldOption = {
  key: string;
  label: string;
  source: 'core' | 'assistant';
};

type FieldConfigPanelProps = {
  options: FieldOption[];
  selected: string[];
  onToggle: (key: string) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
};

export default function FieldConfigPanel({
  options,
  selected,
  onToggle,
  onSelectAll,
  onClearAll,
}: FieldConfigPanelProps) {
  const selectedSet = new Set(selected);
  const coreOptions = options.filter((option) => option.source === 'core');
  const assistantOptions = options.filter((option) => option.source === 'assistant');

  return (
    <section className="panel config-panel">
      <div className="config-header">
        <div>
          <div className="config-title">Field config</div>
          <p className="config-help">
            Toggle which per-turn fields render. Assistant fields are inferred from the baseline run.
          </p>
        </div>
        <div className="config-actions">
          <button className="button subtle config-button" onClick={onSelectAll} type="button">
            Select all
          </button>
          <button className="button ghost config-button" onClick={onClearAll} type="button">
            Clear
          </button>
        </div>
      </div>
      <div className="config-section">
        <div className="config-section-title">Core fields</div>
        <div className="config-grid">
          {coreOptions.map((option) => (
            <label key={option.key} className="checkbox config-option">
              <input
                type="checkbox"
                checked={selectedSet.has(option.key)}
                onChange={() => onToggle(option.key)}
              />
              {option.label}
            </label>
          ))}
        </div>
      </div>
      <div className="config-section">
        <div className="config-section-title">Assistant fields</div>
        {assistantOptions.length === 0 ? (
          <div className="config-empty">Load a baseline run to discover assistant fields.</div>
        ) : (
          <div className="config-grid">
            {assistantOptions.map((option) => (
              <label key={option.key} className="checkbox config-option">
                <input
                  type="checkbox"
                  checked={selectedSet.has(option.key)}
                  onChange={() => onToggle(option.key)}
                />
                {option.label}
              </label>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
