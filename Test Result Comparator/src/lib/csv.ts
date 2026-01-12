import { ComparisonRow } from './types';

export function buildRegressionCsv(rows: ComparisonRow[]): string {
  const header = [
    'objective',
    'testId',
    'statusA',
    'statusB',
    'scoreA',
    'scoreB',
    'deltaScore',
    'latencyA',
    'latencyB',
    'deltaLatency',
    'outputChanged',
  ];
  const lines = [header.join(',')];

  for (const row of rows) {
    if (row.deltaScore === null || row.deltaScore >= 0) {
      continue;
    }
    lines.push(
      [
        row.objective,
        row.testId,
        formatStatus(row.statusA),
        formatStatus(row.statusB),
        formatNumber(row.scoreA),
        formatNumber(row.scoreB),
        formatNumber(row.deltaScore),
        formatNumber(row.latencyA),
        formatNumber(row.latencyB),
        formatNumber(row.deltaLatency),
        row.outputChanged ? 'true' : 'false',
      ]
        .map(escapeCsv)
        .join(',')
    );
  }

  return lines.join('\n');
}

function formatStatus(value: boolean | null): string {
  if (value === null) {
    return 'missing';
  }
  return value ? 'passed' : 'failed';
}

function formatNumber(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return '';
  }
  return value.toFixed(3);
}

function escapeCsv(value: string): string {
  if (value.includes(',') || value.includes('\n') || value.includes('"')) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}
