import { normalizeText } from './normalize';
import { ComparisonRow, NormalizedCase, Run } from './types';

export function buildComparisonRows(runA: Run | null, runB: Run | null): ComparisonRow[] {
  const casesA = runA ? mapByTestId(runA.cases) : new Map<string, NormalizedCase>();
  const casesB = runB ? mapByTestId(runB.cases) : new Map<string, NormalizedCase>();
  const testIds = new Set([...casesA.keys(), ...casesB.keys()]);
  const rows: ComparisonRow[] = [];

  for (const testId of testIds) {
    const caseA = casesA.get(testId) ?? null;
    const caseB = casesB.get(testId) ?? null;
    const scoreA = caseA?.finalScore ?? null;
    const scoreB = caseB?.finalScore ?? null;
    const latencyA = caseA?.totalLatencyMs ?? null;
    const latencyB = caseB?.totalLatencyMs ?? null;

    rows.push({
      testId,
      objective: caseA?.objective ?? caseB?.objective ?? '',
      turnsA: caseA?.turnsCount ?? null,
      turnsB: caseB?.turnsCount ?? null,
      statusA: caseA?.passed ?? null,
      statusB: caseB?.passed ?? null,
      scoreA,
      scoreB,
      deltaScore: scoreA !== null && scoreB !== null ? scoreB - scoreA : null,
      latencyA,
      latencyB,
      deltaLatency: latencyA !== null && latencyB !== null ? latencyB - latencyA : null,
      outputChanged: isOutputChanged(caseA, caseB),
      caseA,
      caseB,
    });
  }

  return rows;
}

function mapByTestId(cases: NormalizedCase[]): Map<string, NormalizedCase> {
  const map = new Map<string, NormalizedCase>();
  for (const entry of cases) {
    map.set(entry.testId, entry);
  }
  return map;
}

function isOutputChanged(caseA: NormalizedCase | null, caseB: NormalizedCase | null): boolean {
  if (!caseA || !caseB) {
    return true;
  }
  const maxTurns = Math.max(caseA.turns.length, caseB.turns.length);
  for (let idx = 0; idx < maxTurns; idx += 1) {
    const turnA = caseA.turns[idx];
    const turnB = caseB.turns[idx];
    if (!turnA || !turnB) {
      return true;
    }
    if (normalizeText(turnA.assistantText) !== normalizeText(turnB.assistantText)) {
      return true;
    }
  }
  return false;
}
