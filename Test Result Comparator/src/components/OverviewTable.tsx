import React from 'react';
import { ComparisonRow } from '../lib/types';

export type FilterState = {
  search: string;
  trend: 'all' | 'regression' | 'improvement';
  multiTurnOnly: boolean;
  outputChangedOnly: boolean;
  threshold: number;
  thresholdMax: number;
};

type OverviewTableProps = {
  rows: ComparisonRow[];
  selectedTestId: string | null;
  onSelectTest: (testId: string) => void;
  filters: FilterState;
  onFiltersChange: (updates: Partial<FilterState>) => void;
};

export default function OverviewTable({
  rows,
  selectedTestId,
  onSelectTest,
  filters,
  onFiltersChange,
}: OverviewTableProps) {
  const thresholdLabel = Number.isFinite(filters.threshold) ? filters.threshold.toFixed(1) : '0.0';

  return (
    <section className="panel overview-panel">
      <div className="filters">
        <input
          className="input"
          type="search"
          placeholder="Search objectives or keys"
          value={filters.search}
          onChange={(event) => onFiltersChange({ search: event.target.value })}
        />
        <div className="filter-group">
          <button
            className={`button toggle ${filters.trend === 'all' ? 'active' : ''}`}
            onClick={() => onFiltersChange({ trend: 'all' })}
          >
            All
          </button>
          <button
            className={`button toggle ${filters.trend === 'regression' ? 'active' : ''}`}
            onClick={() => onFiltersChange({ trend: 'regression' })}
          >
            Regressions
          </button>
          <button
            className={`button toggle ${filters.trend === 'improvement' ? 'active' : ''}`}
            onClick={() => onFiltersChange({ trend: 'improvement' })}
          >
            Improvements
          </button>
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={filters.multiTurnOnly}
            onChange={(event) => onFiltersChange({ multiTurnOnly: event.target.checked })}
          />
          Multi-turn only
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={filters.outputChangedOnly}
            onChange={(event) => onFiltersChange({ outputChangedOnly: event.target.checked })}
          />
          Output changed
        </label>
        <label className="range">
          Score ≤ {thresholdLabel}
          <input
            type="range"
            min={0}
            max={filters.thresholdMax}
            step={0.01}
            value={filters.threshold}
            onChange={(event) => onFiltersChange({ threshold: Number(event.target.value) })}
          />
        </label>
      </div>

      <div className="table-wrap">
        <table className="overview-table">
          <thead>
            <tr>
              <th>Objective</th>
              <th>Objective key</th>
              <th>Turns</th>
              <th>Status A/B</th>
              <th>Score A/B/Δ</th>
              <th>Output Changed</th>
              <th>Latency A/B/Δ</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.testId}
                className={selectedTestId === row.testId ? 'selected' : ''}
                onClick={() => onSelectTest(row.testId)}
              >
                <td>{row.objective}</td>
                <td className="mono" title={row.testId}>
                  {row.testId}
                </td>
                <td>{formatTurns(row.turnsA, row.turnsB)}</td>
                <td className={row.statusA !== row.statusB ? 'cell-diff' : ''}>
                  {formatStatus(row.statusA, row.statusB)}
                </td>
                <td className={getDeltaClass(row.deltaScore, false)}>
                  {renderDelta(row.scoreA, row.scoreB, row.deltaScore, '', 1)}
                </td>
                <td className={row.outputChanged ? 'cell-diff' : ''}>
                  <span className={`chip ${row.outputChanged ? 'chip-warn' : 'chip-muted'}`}>
                    {row.outputChanged ? 'Yes' : 'No'}
                  </span>
                </td>
                <td className={getDeltaClass(row.deltaLatency, true)}>
                  {renderDelta(row.latencyA, row.latencyB, row.deltaLatency, 'ms', 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatTurns(a: number | null, b: number | null): string {
  const aValue = a ?? 0;
  const bValue = b ?? 0;
  return `${aValue}/${bValue}`;
}

function formatStatus(a: boolean | null, b: boolean | null): JSX.Element {
  return (
    <div className="status-pair">
      <span className={`status ${a === null ? 'status-missing' : a ? 'status-pass' : 'status-fail'}`}>
        {formatStatusValue(a)}
      </span>
      <span className="slash">/</span>
      <span className={`status ${b === null ? 'status-missing' : b ? 'status-pass' : 'status-fail'}`}>
        {formatStatusValue(b)}
      </span>
    </div>
  );
}

function formatStatusValue(value: boolean | null): string {
  if (value === null) {
    return '—';
  }
  return value ? 'Pass' : 'Fail';
}

function renderDelta(
  a: number | null,
  b: number | null,
  delta: number | null,
  suffix = '',
  decimals = 1
): JSX.Element {
  const aValue = a === null ? '—' : a.toFixed(decimals);
  const bValue = b === null ? '—' : b.toFixed(decimals);
  const deltaValue = delta === null ? '—' : delta.toFixed(decimals);
  const units = suffix ? ` ${suffix}` : '';
  return (
    <div className="delta-pair">
      <span>{aValue}</span>
      <span className="slash">/</span>
      <span>{bValue}</span>
      <span className="slash">/</span>
      <span className="delta">{deltaValue}</span>
      {units && <span className="units">{units}</span>}
    </div>
  );
}

function getDeltaClass(delta: number | null, lowerIsBetter: boolean): string {
  if (delta === null || Number.isNaN(delta)) {
    return '';
  }
  if (delta === 0) {
    return 'cell-neutral';
  }
  if (lowerIsBetter) {
    return delta < 0 ? 'cell-positive' : 'cell-negative';
  }
  return delta > 0 ? 'cell-positive' : 'cell-negative';
}
