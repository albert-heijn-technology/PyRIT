import React from 'react';
import { diffJsonPaths, diffWords } from '../lib/diff';
import { AssistantFieldValue, NormalizedCase, Run } from '../lib/types';

const COLLAPSE_LIMIT = 200;

type FieldDefinition = {
  key: string;
  label: string;
};

export default function DetailView({
  baseline,
  compare,
  testId,
  fieldConfig,
}: {
  baseline: Run | null;
  compare: Run | null;
  testId: string | null;
  fieldConfig: FieldDefinition[];
}) {
  if (!baseline || !compare || !testId) {
    return (
      <section className="panel detail-panel">
        <div className="empty-state">Select a test case to view details.</div>
      </section>
    );
  }

  const caseA = baseline.cases.find((entry) => entry.testId === testId) ?? null;
  const caseB = compare.cases.find((entry) => entry.testId === testId) ?? null;

  if (!caseA && !caseB) {
    return (
      <section className="panel detail-panel">
        <div className="empty-state">Case not found in selected runs.</div>
      </section>
    );
  }

  const objective = caseA?.objective ?? caseB?.objective ?? '';
  const scoreDelta =
    caseA && caseB && caseA.finalScore !== null && caseB.finalScore !== null
      ? caseB.finalScore - caseA.finalScore
      : null;
  const latencyDelta =
    caseA && caseB && caseA.totalLatencyMs !== null && caseB.totalLatencyMs !== null
      ? caseB.totalLatencyMs - caseA.totalLatencyMs
      : null;

  const maxTurns = Math.max(caseA?.turns.length ?? 0, caseB?.turns.length ?? 0);
  const enabledFields = getEnabledFields(fieldConfig);

  return (
    <section className="panel detail-panel">
      <header className="detail-header">
        <div>
          <div className="detail-title">{objective}</div>
          <div className="detail-meta mono">{testId}</div>
        </div>
        <div className="detail-deltas">
          <span>Score Δ: {formatScore(scoreDelta)}</span>
          <span>Latency Δ: {formatLatency(latencyDelta)}</span>
        </div>
      </header>

      <div className="turns">
        {Array.from({ length: maxTurns }, (_, idx) => {
          const turnA = caseA?.turns[idx];
          const turnB = caseB?.turns[idx];
          const showTextDiff = enabledFields.has('text');
          const showDataDiffs = enabledFields.has('data');
          const showPillsDiffs = enabledFields.has('pills');
          const diff = showTextDiff
            ? diffWords(turnA?.assistantText ?? '', turnB?.assistantText ?? '')
            : [];
          const dataDiffs = showDataDiffs
            ? diffJsonPaths(turnA?.assistantData, turnB?.assistantData)
            : [];
          const pillsDiffs = showPillsDiffs
            ? diffJsonPaths(turnA?.assistantPills, turnB?.assistantPills)
            : [];
          const showDiffSummary =
            (showDataDiffs && dataDiffs.length > 0) || (showPillsDiffs && pillsDiffs.length > 0);
          const latencyDeltaTurn =
            turnA && turnB && turnA.latencyMs !== null && turnB.latencyMs !== null
              ? turnB.latencyMs - turnA.latencyMs
              : null;

          return (
            <details key={`turn-${idx}`} className="turn" open={idx === 0}>
              <summary>
                Turn {idx + 1} · latency Δ{' '}
                {formatLatency(latencyDeltaTurn)}
              </summary>
              <div className="turn-body">
                {showTextDiff && (
                  <div className="diff-block">
                    <div className="diff-label">Assistant text diff</div>
                    <div className="diff-text">
                      {diff.length === 0 ? (
                        <span className="diff-equal">No assistant text.</span>
                      ) : (
                        diff.map((chunk, cIdx) => (
                          <span key={`${chunk.type}-${cIdx}`} className={`diff-${chunk.type}`}>
                            {chunk.text}{' '}
                          </span>
                        ))
                      )}
                    </div>
                  </div>
                )}

                <div className="turn-columns">
                  <div className="turn-column">
                    <h4>{baseline.displayName}</h4>
                    <TurnContent turn={turnA} fieldConfig={fieldConfig} />
                  </div>
                  <div className="turn-column">
                    <h4>{compare.displayName}</h4>
                    <TurnContent turn={turnB} fieldConfig={fieldConfig} />
                  </div>
                </div>

                {showDiffSummary && (
                  <div className="diff-summary">
                    {showDataDiffs && (
                      <div>
                        <div className="diff-label">Data diff paths</div>
                        {dataDiffs.length === 0 ? (
                          <div className="diff-equal">No data changes.</div>
                        ) : (
                          <ul>
                            {dataDiffs.slice(0, 10).map((diffItem, dIdx) => (
                              <li key={`data-${dIdx}`}>[{diffItem.type}] {diffItem.path}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                    {showPillsDiffs && (
                      <div>
                        <div className="diff-label">Pills diff paths</div>
                        {pillsDiffs.length === 0 ? (
                          <div className="diff-equal">No pill changes.</div>
                        ) : (
                          <ul>
                            {pillsDiffs.slice(0, 10).map((diffItem, dIdx) => (
                              <li key={`pills-${dIdx}`}>[{diffItem.type}] {diffItem.path}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function TurnContent({
  turn,
  fieldConfig,
}: {
  turn: NormalizedCase['turns'][number] | undefined;
  fieldConfig: FieldDefinition[];
}) {
  if (!turn) {
    return <div className="empty-state">Missing turn data.</div>;
  }

  const fields = buildTurnFields(turn, fieldConfig);

  return (
    <div className="turn-content">
      {fields.map((field) => (
        <div key={field.key} className="field">
          <div className="field-label">{field.label}</div>
          {field.content}
        </div>
      ))}
    </div>
  );
}

function buildTurnFields(
  turn: NormalizedCase['turns'][number],
  fieldConfig: FieldDefinition[]
): Array<{ key: string; label: string; content: JSX.Element }> {
  const fields: Array<{ key: string; label: string; content: JSX.Element }> = [];

  for (const definition of fieldConfig) {
    const field = resolveTurnField(definition, turn);
    if (field) {
      fields.push(field);
    }
  }

  return fields;
}

function resolveTurnField(
  definition: FieldDefinition,
  turn: NormalizedCase['turns'][number]
): { key: string; label: string; content: JSX.Element } | null {
  const normalized = normalizeFieldKey(definition.key);
  switch (normalized) {
    case 'user':
      return {
        key: 'user',
        label: definition.label,
        content: renderFieldValue(turn.userText || '—'),
      };
    case 'text':
      return {
        key: 'text',
        label: definition.label,
        content: renderFieldValue(turn.assistantText || '—'),
      };
    case 'data':
      return {
        key: 'data',
        label: definition.label,
        content: renderJsonField(turn.assistantData, turn.assistantDataRaw),
      };
    case 'pills':
      return {
        key: 'pills',
        label: definition.label,
        content: renderJsonField(turn.assistantPills, turn.assistantPillsRaw),
      };
    case 'streamended':
      return {
        key: 'streamended',
        label: definition.label,
        content: renderFieldValue(formatStreamEnded(turn.streamEnded)),
      };
    case 'latency':
      return {
        key: 'latency',
        label: definition.label,
        content: renderFieldValue(formatLatency(turn.latencyMs)),
      };
    case 'weightedaverage':
    case 'weightedavg':
      return {
        key: 'weightedaverage',
        label: definition.label,
        content: renderFieldValue(formatScore(turn.weightedAverage)),
      };
    case 'scores':
    case 'scorers':
      return {
        key: 'scores',
        label: definition.label,
        content: renderScores(turn),
      };
    default:
      return resolveAssistantField(definition, turn, normalized);
  }
}

function resolveAssistantField(
  definition: FieldDefinition,
  turn: NormalizedCase['turns'][number],
  normalized: string
): { key: string; label: string; content: JSX.Element } | null {
  const entry = findAssistantField(turn, normalized);
  if (!entry) {
    return null;
  }
  return {
    key: normalized,
    label: definition.label,
    content: renderAssistantFieldValue(entry.value),
  };
}

function formatJson(parsed: unknown | null, raw: string | null): string {
  if (parsed !== null) {
    return JSON.stringify(parsed, null, 2);
  }
  return raw ?? '—';
}

function renderJsonField(parsed: unknown | null, raw: string | null): JSX.Element {
  if (parsed !== null && typeof parsed === 'object') {
    return (
      <div className="field-value field-json">
        <JsonTree value={parsed} />
      </div>
    );
  }
  return renderFieldValue(formatJson(parsed, raw));
}

function renderAssistantFieldValue(field: AssistantFieldValue): JSX.Element {
  const parsed = field.parsed;
  if (parsed !== null && typeof parsed === 'object') {
    return (
      <div className="field-value field-json">
        <JsonTree value={parsed} />
      </div>
    );
  }
  const display =
    field.raw ??
    (parsed === null || parsed === undefined ? '—' : String(parsed));
  return renderFieldValue(display);
}

function renderFieldValue(value: string): JSX.Element {
  if (value.length <= COLLAPSE_LIMIT) {
    return <pre className="field-value">{value}</pre>;
  }
  const summaryText = truncateValue(value, COLLAPSE_LIMIT);
  const hiddenCount = value.length - COLLAPSE_LIMIT;
  const tail = value.slice(COLLAPSE_LIMIT);
  const continuation = tail.startsWith('\n') ? tail : `...${tail}`;
  return (
    <details className="field-details">
      <summary className="field-value field-summary">
        <span className="field-summary-text">{summaryText}</span>
        <span className="field-summary-meta">
          <span className="field-summary-more">Show more (+{hiddenCount} chars)</span>
          <span className="field-summary-less">Show less</span>
        </span>
      </summary>
      <pre className="field-value field-full">{continuation}</pre>
    </details>
  );
}

function truncateValue(value: string, limit: number): string {
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit)}...`;
}

function formatScore(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return '—';
  }
  return value.toFixed(1);
}

function formatLatency(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return '—';
  }
  return `${value.toFixed(0)} ms`;
}

function formatStreamEnded(value: boolean | null): string {
  if (value === null) {
    return '—';
  }
  return value ? 'true' : 'false';
}

function renderScores(turn: NormalizedCase['turns'][number]): JSX.Element {
  if (turn.scores.length === 0) {
    return <div className="muted">No scores.</div>;
  }
  return (
    <ul className="score-list">
      {turn.scores.map((score, idx) => (
        <li key={`score-${idx}`}>
          <span>{formatScore(score.score)}</span>
          <span>threshold {formatScore(score.threshold)}</span>
          <span>{score.passed === null ? '—' : score.passed ? 'pass' : 'fail'}</span>
          <span>{score.required ? 'required' : 'optional'}</span>
          <span className="mono">{score.scorerConfigPath ?? '—'}</span>
          <span className="muted">{score.rationale ?? ''}</span>
        </li>
      ))}
    </ul>
  );
}

function JsonTree({ value }: { value: unknown }) {
  if (isRecord(value)) {
    const entries = Object.entries(value).sort(([a], [b]) => a.localeCompare(b));
    return (
      <div className="json-tree-children">
        {entries.map(([key, child]) => (
          <JsonNodeView key={key} nodeKey={key} value={child} depth={0} />
        ))}
      </div>
    );
  }
  if (Array.isArray(value)) {
    return (
      <div className="json-tree-children">
        {value.map((child, index) => (
          <JsonNodeView key={`root-${index}`} nodeKey={`[${index}]`} value={child} depth={0} />
        ))}
      </div>
    );
  }
  return <JsonNodeView nodeKey="value" value={value} depth={0} />;
}

function JsonNodeView({
  nodeKey,
  value,
  depth,
}: {
  nodeKey: string;
  value: unknown;
  depth: number;
}) {
  const isBranch = isRecord(value) || Array.isArray(value);
  const paddingStyle = { paddingLeft: `${depth * 14}px` };

  if (isBranch) {
    const entries = Array.isArray(value)
      ? value.map((entry, index) => [`[${index}]`, entry] as const)
      : Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b));
    return (
      <details className="json-tree-node" open={depth < 1}>
        <summary style={paddingStyle}>
          <span className="json-tree-key">{nodeKey}</span>
          <span className="json-tree-type">{formatBranchType(value)}</span>
        </summary>
        <div className="json-tree-children">
          {entries.map(([key, child]) => (
            <JsonNodeView key={`${nodeKey}-${key}`} nodeKey={String(key)} value={child} depth={depth + 1} />
          ))}
        </div>
      </details>
    );
  }

  return (
    <div className="json-tree-node json-tree-leaf" style={paddingStyle}>
      <span className="json-tree-key">{nodeKey}</span>
      <span className="json-tree-sep">:</span>
      <span className="json-tree-value">{formatJsonValue(value)}</span>
    </div>
  );
}

function formatBranchType(value: unknown): string {
  if (Array.isArray(value)) {
    return `Array(${value.length})`;
  }
  if (isRecord(value)) {
    return `Object(${Object.keys(value).length})`;
  }
  return '';
}

function formatJsonValue(value: unknown): string {
  if (value === null) {
    return 'null';
  }
  if (value === undefined) {
    return 'undefined';
  }
  if (typeof value === 'string') {
    const preview = value.length > COLLAPSE_LIMIT ? `${value.slice(0, COLLAPSE_LIMIT)}...` : value;
    return JSON.stringify(preview);
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function normalizeFieldKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

function findAssistantField(
  turn: NormalizedCase['turns'][number],
  normalizedKey: string
): { key: string; value: AssistantFieldValue } | null {
  for (const [key, value] of Object.entries(turn.assistantFields)) {
    if (normalizeFieldKey(key) === normalizedKey) {
      return { key, value };
    }
  }
  return null;
}

function getEnabledFields(fieldConfig: FieldDefinition[]): Set<string> {
  return new Set(fieldConfig.map((definition) => normalizeFieldKey(definition.key)));
}
