import React, { useEffect, useMemo, useState } from 'react';
import DetailView from './components/DetailView';
import FieldConfigPanel, { FieldOption } from './components/FieldConfigPanel';
import OverviewTable, { FilterState } from './components/OverviewTable';
import RunLoader from './components/RunLoader';
import Toast from './components/Toast';
import { buildComparisonRows } from './lib/compare';
import { buildRegressionCsv } from './lib/csv';
import { isJsonFile, parseReport } from './lib/parse';
import { ComparisonRow, ParseError, Run } from './lib/types';

const DEFAULT_FILTERS: FilterState = {
  search: '',
  trend: 'all',
  multiTurnOnly: false,
  outputChangedOnly: false,
  threshold: 1,
  thresholdMax: 1,
};

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [errors, setErrors] = useState<ParseError[]>([]);
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null);
  const [compareRunId, setCompareRunId] = useState<string | null>(null);
  const [isParsing, setIsParsing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [fieldSelection, setFieldSelection] = useState<string[]>([]);
  const fieldSelectionInitialized = React.useRef(false);
  const prevFieldKeys = React.useRef<string[]>([]);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }
    const timeout = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    const runIds = new Set(runs.map((run) => run.runId));
    setBaselineRunId((current) => (current && runIds.has(current) ? current : runs[0]?.runId ?? null));
    setCompareRunId((current) => {
      if (current && runIds.has(current)) {
        return current === baselineRunId ? findCompareRunId(runs, baselineRunId) : current;
      }
      return findCompareRunId(runs, baselineRunId);
    });
  }, [runs, baselineRunId]);

  const baselineRun = runs.find((run) => run.runId === baselineRunId) ?? null;
  const compareRun = runs.find((run) => run.runId === compareRunId) ?? null;

  const rows = useMemo(() => buildComparisonRows(baselineRun, compareRun), [baselineRun, compareRun]);
  const fieldOptions = useMemo(() => buildFieldOptions(baselineRun), [baselineRun]);
  const fieldOptionsKeys = useMemo(() => fieldOptions.map((option) => option.key), [fieldOptions]);

  const thresholdMax = useMemo(() => {
    const scores: number[] = [];
    for (const row of rows) {
      if (row.scoreA !== null) {
        scores.push(row.scoreA);
      }
      if (row.scoreB !== null) {
        scores.push(row.scoreB);
      }
    }
    const max = scores.length > 0 ? Math.max(...scores) : 1;
    return Math.max(1, Math.ceil(max * 100) / 100);
  }, [rows]);

  useEffect(() => {
    setFilters((prev) => {
      const shouldResetToMax = prev.threshold === prev.thresholdMax;
      const nextThreshold = shouldResetToMax
        ? thresholdMax
        : Math.min(prev.threshold, thresholdMax);
      return {
        ...prev,
        thresholdMax,
        threshold: nextThreshold,
      };
    });
  }, [thresholdMax]);

  const filteredRows = useMemo(() => filterRows(rows, filters), [rows, filters]);
  const selectedFields = useMemo(() => {
    const selectedSet = new Set(fieldSelection);
    return fieldOptions.filter((option) => selectedSet.has(option.key));
  }, [fieldOptions, fieldSelection]);

  useEffect(() => {
    if (fieldOptions.length === 0) {
      return;
    }
    const currentKeys = fieldOptionsKeys;
    const previousKeys = prevFieldKeys.current;
    setFieldSelection((prev) => {
      if (!fieldSelectionInitialized.current) {
        fieldSelectionInitialized.current = true;
        return currentKeys;
      }
      const currentSet = new Set(currentKeys);
      const prevSet = new Set(previousKeys);
      const next = prev.filter((key) => currentSet.has(key));
      for (const key of currentSet) {
        if (!prevSet.has(key) && !next.includes(key)) {
          next.push(key);
        }
      }
      return next;
    });
    prevFieldKeys.current = currentKeys;
  }, [fieldOptions, fieldOptionsKeys]);

  useEffect(() => {
    if (selectedTestId && !filteredRows.find((row) => row.testId === selectedTestId)) {
      setSelectedTestId(filteredRows[0]?.testId ?? null);
    }
  }, [filteredRows, selectedTestId]);

  const handleFilesSelected = async (files: File[]) => {
    if (files.length === 0) {
      return;
    }
    setIsParsing(true);
    const newRuns: Run[] = [];
    const newErrors: ParseError[] = [];

    for (const file of files) {
      if (!isJsonFile(file)) {
        newErrors.push({ fileName: file.name, message: 'Unsupported file type.' });
        continue;
      }
      try {
        const text = await file.text();
        const json = JSON.parse(text);
        const parsedRun = await parseReport(file.name, json);
        newRuns.push(parsedRun);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unknown parsing error.';
        newErrors.push({ fileName: file.name, message });
      }
    }

    setRuns((prev) => {
      const next = [...prev];
      for (const run of newRuns) {
        if (next.some((existing) => existing.runId === run.runId)) {
          setToast('Run already loaded');
        } else {
          next.push(run);
        }
      }
      return next;
    });

    if (newErrors.length > 0) {
      setErrors((prev) => [...newErrors, ...prev]);
    }

    setIsParsing(false);
  };

  const handleRemoveRun = (runId: string) => {
    setRuns((prev) => prev.filter((run) => run.runId !== runId));
  };

  const handleClearRuns = () => {
    setRuns([]);
    setErrors([]);
    setSelectedTestId(null);
  };

  const handleExport = () => {
    const csv = buildRegressionCsv(filteredRows);
    if (csv.split('\n').length <= 1) {
      setToast('No regressions to export');
      return;
    }
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'regressions.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="app">
      <Toast message={toast} />
      <header className="app-header">
        <div>
          <h1>PyROTOR</h1>
          <p>Compare JSON test runs, spot regressions, and drill into transcript diffs.</p>
        </div>
        <div className="header-stats">
          <div>
            <span className="stat-label">Runs</span>
            <span className="stat-value">{runs.length}</span>
          </div>
          <div>
            <span className="stat-label">Cases</span>
            <span className="stat-value">{filteredRows.length}</span>
          </div>
          <button className="button primary" onClick={handleExport} disabled={filteredRows.length === 0}>
            Export regressions CSV
          </button>
        </div>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <RunLoader
            runs={runs}
            errors={errors}
            baselineRunId={baselineRunId}
            compareRunId={compareRunId}
            isParsing={isParsing}
            onFilesSelected={handleFilesSelected}
            onRemoveRun={handleRemoveRun}
            onClearRuns={handleClearRuns}
            onSelectBaseline={setBaselineRunId}
            onSelectCompare={setCompareRunId}
          />
          <FieldConfigPanel
            options={fieldOptions}
            selected={fieldSelection}
            onToggle={(key) =>
              setFieldSelection((prev) =>
                prev.includes(key) ? prev.filter((entry) => entry !== key) : [...prev, key]
              )
            }
            onSelectAll={() => setFieldSelection(fieldOptionsKeys)}
            onClearAll={() => setFieldSelection([])}
          />
        </aside>
        <main className="main">
          <OverviewTable
            rows={filteredRows}
            selectedTestId={selectedTestId}
            onSelectTest={setSelectedTestId}
            filters={{ ...filters, thresholdMax }}
            onFiltersChange={(updates) => setFilters((prev) => ({ ...prev, ...updates }))}
          />
          <DetailView baseline={baselineRun} compare={compareRun} testId={selectedTestId} fieldConfig={selectedFields} />
        </main>
      </div>
    </div>
  );
}

function filterRows(rows: ComparisonRow[], filters: FilterState): ComparisonRow[] {
  const searchValue = filters.search.toLowerCase().trim();
  const filtered = rows.filter((row) => {
    if (searchValue) {
      const haystack = `${row.objective} ${row.testId}`.toLowerCase();
      if (!haystack.includes(searchValue)) {
        return false;
      }
    }

    if (filters.trend === 'regression' && !(row.deltaScore !== null && row.deltaScore < 0)) {
      return false;
    }

    if (filters.trend === 'improvement' && !(row.deltaScore !== null && row.deltaScore > 0)) {
      return false;
    }

    if (filters.multiTurnOnly) {
      const maxTurns = Math.max(row.turnsA ?? 0, row.turnsB ?? 0);
      if (maxTurns <= 1) {
        return false;
      }
    }

    if (filters.outputChangedOnly && !row.outputChanged) {
      return false;
    }

    const scoreValue = row.scoreA ?? row.scoreB;
    if (scoreValue !== null && scoreValue > filters.threshold) {
      return false;
    }

    return true;
  });

  return filtered.sort((a, b) => {
    const deltaA = a.deltaScore ?? Number.POSITIVE_INFINITY;
    const deltaB = b.deltaScore ?? Number.POSITIVE_INFINITY;
    if (deltaA !== deltaB) {
      return deltaA - deltaB;
    }
    return a.objective.localeCompare(b.objective);
  });
}

function findCompareRunId(runs: Run[], baselineRunId: string | null): string | null {
  return runs.find((run) => run.runId !== baselineRunId)?.runId ?? null;
}

function buildFieldOptions(run: Run | null): FieldOption[] {
  const core: FieldOption[] = [
    { key: 'user', label: 'User', source: 'core' },
    { key: 'text', label: 'Text', source: 'core' },
    { key: 'latency', label: 'Latency', source: 'core' },
    { key: 'weightedaverage', label: 'Weighted avg', source: 'core' },
    { key: 'scores', label: 'Scorers', source: 'core' },
  ];
  const coreKeys = new Set(core.map((option) => option.key));
  const assistantMap = new Map<string, string>();

  if (run) {
    for (const testCase of run.cases) {
      for (const turn of testCase.turns) {
        for (const key of Object.keys(turn.assistantFields)) {
          const normalized = normalizeFieldKey(key);
          if (!normalized || normalized === 'text' || coreKeys.has(normalized)) {
            continue;
          }
          if (!assistantMap.has(normalized)) {
            assistantMap.set(normalized, key);
          }
        }
      }
    }
  }

  const assistant = Array.from(assistantMap.entries())
    .map(([key, label]) => ({ key, label, source: 'assistant' as const }))
    .sort((a, b) => a.label.localeCompare(b.label));

  return [...core, ...assistant];
}

function normalizeFieldKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '');
}
