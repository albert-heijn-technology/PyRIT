import React, { useRef, useState } from 'react';
import { ParseError, Run } from '../lib/types';

type RunLoaderProps = {
  runs: Run[];
  errors: ParseError[];
  baselineRunId: string | null;
  compareRunId: string | null;
  isParsing: boolean;
  onFilesSelected: (files: File[]) => void;
  onRemoveRun: (runId: string) => void;
  onClearRuns: () => void;
  onSelectBaseline: (runId: string) => void;
  onSelectCompare: (runId: string | null) => void;
};

export default function RunLoader({
  runs,
  errors,
  baselineRunId,
  compareRunId,
  isParsing,
  onFilesSelected,
  onRemoveRun,
  onClearRuns,
  onSelectBaseline,
  onSelectCompare,
}: RunLoaderProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) {
      onFilesSelected(files);
    }
  };

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!isDragOver) {
      setIsDragOver(true);
    }
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleClick = () => {
    inputRef.current?.click();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      inputRef.current?.click();
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files ? Array.from(event.target.files) : [];
    if (files.length > 0) {
      onFilesSelected(files);
    }
    event.target.value = '';
  };

  const dropZoneState = isParsing ? 'processing' : isDragOver ? 'drag-over' : 'idle';
  const compareOptions = runs.filter((run) => run.runId !== baselineRunId);

  return (
    <section className="panel loader-panel">
      <div
        className={`drop-zone ${dropZoneState}`}
        role="button"
        tabIndex={0}
        aria-label="Upload JSON reports"
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        {isParsing ? (
          <div className="drop-zone-content">
            <span className="spinner" aria-hidden="true" />
            <span>Parsing …</span>
          </div>
        ) : isDragOver ? (
          <div className="drop-zone-content">Release to add reports</div>
        ) : (
          <div className="drop-zone-content">Drop JSON reports here or click to upload</div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".json,application/json"
          multiple
          onChange={handleFileChange}
          hidden
        />
      </div>

      <div className="loader-actions">
        <button className="button subtle" onClick={onClearRuns} disabled={runs.length === 0}>
          Clear all runs
        </button>
      </div>

      <div className="run-list">
        {runs.map((run) => (
          <div key={run.runId} className="run-card">
            <div className="run-card-header">
              <div>
                <div className="run-title">{run.displayName}</div>
                <div className="run-meta">{run.generatedAt || 'Unknown timestamp'}</div>
              </div>
              <button className="button ghost" onClick={() => onRemoveRun(run.runId)}>
                Remove
              </button>
            </div>
            <div className="run-stats">
              <span>
                {run.passedCases ?? 0}/{run.totalCases ?? 0} passed
              </span>
              <span>{run.executionTimeSeconds ?? 0}s exec</span>
            </div>
            <div className="run-selectors">
              <label className="selector">
                <input
                  type="radio"
                  name="baseline"
                  checked={baselineRunId === run.runId}
                  onChange={() => onSelectBaseline(run.runId)}
                />
                Baseline
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="compare-select">
        <label>
          Compare run
          <select
            value={compareRunId ?? ''}
            onChange={(event) => onSelectCompare(event.target.value || null)}
            disabled={compareOptions.length === 0}
          >
            <option value="">Select run</option>
            {compareOptions.map((run) => (
              <option key={run.runId} value={run.runId}>
                {run.displayName}
              </option>
            ))}
          </select>
        </label>
      </div>

      {errors.length > 0 && (
        <div className="error-list">
          <div className="error-title">Parse errors</div>
          {errors.map((error, idx) => (
            <div key={`${error.fileName}-${idx}`} className="error-item">
              <span className="error-file">{error.fileName}</span>
              <span className="error-message">{error.message}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
