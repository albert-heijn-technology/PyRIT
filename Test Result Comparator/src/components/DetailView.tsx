import React from 'react';
import { diffJsonPaths, diffWords } from '../lib/diff';
import { NormalizedCase, Run } from '../lib/types';

export default function DetailView({
  baseline,
  compare,
  testId,
}: {
  baseline: Run | null;
  compare: Run | null;
  testId: string | null;
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
          const diff = diffWords(turnA?.assistantText ?? '', turnB?.assistantText ?? '');
          const dataDiffs = diffJsonPaths(turnA?.assistantData, turnB?.assistantData);
          const pillsDiffs = diffJsonPaths(turnA?.assistantPills, turnB?.assistantPills);
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

                <div className="turn-columns">
                  <div className="turn-column">
                    <h4>{baseline.displayName}</h4>
                    <TurnContent turn={turnA} />
                  </div>
                  <div className="turn-column">
                    <h4>{compare.displayName}</h4>
                    <TurnContent turn={turnB} />
                  </div>
                </div>

                <div className="diff-summary">
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
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function TurnContent({ turn }: { turn: NormalizedCase['turns'][number] | undefined }) {
  if (!turn) {
    return <div className="empty-state">Missing turn data.</div>;
  }

  return (
    <div className="turn-content">
      <div className="field">
        <div className="field-label">User</div>
        <pre className="field-value">{turn.userText || '—'}</pre>
      </div>
      <div className="field">
        <div className="field-label">Assistant</div>
        <pre className="field-value">{turn.assistantText || '—'}</pre>
      </div>
      <div className="field">
        <div className="field-label">Data</div>
        <pre className="field-value">{formatJson(turn.assistantData, turn.assistantDataRaw)}</pre>
      </div>
      <div className="field">
        <div className="field-label">Pills</div>
        <pre className="field-value">{formatJson(turn.assistantPills, turn.assistantPillsRaw)}</pre>
      </div>
      <div className="field inline">
        <span>Latency: {formatLatency(turn.latencyMs)}</span>
        <span>Weighted avg: {formatScore(turn.weightedAverage)}</span>
      </div>
      <div className="field">
        <div className="field-label">Scorers</div>
        {turn.scores.length === 0 ? (
          <div className="muted">No scores.</div>
        ) : (
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
        )}
      </div>
    </div>
  );
}

function formatJson(parsed: unknown | null, raw: string | null): string {
  if (parsed !== null) {
    return JSON.stringify(parsed, null, 2);
  }
  return raw ?? '—';
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
