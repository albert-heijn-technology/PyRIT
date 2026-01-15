export type ScoreSummary = {
  score: number;
  threshold: number | null;
  weight: number | null;
  passed: boolean | null;
  expectedOutput: string | null;
  rationale: string | null;
  scorerConfigPath: string | null;
  required: boolean | null;
};

export type AssistantFieldValue = {
  raw: string | null;
  parsed: unknown | null;
};

export type NormalizedTurn = {
  index: number;
  userText: string;
  assistantText: string;
  assistantData: unknown | null;
  assistantPills: unknown | null;
  assistantDataRaw: string | null;
  assistantPillsRaw: string | null;
  streamEnded: boolean | null;
  assistantFields: Record<string, AssistantFieldValue>;
  latencyMs: number | null;
  latencyFirstTokenMs: number | null;
  latencyEventsMs: Record<string, number> | null;
  weightedAverage: number | null;
  scores: ScoreSummary[];
};

export type NormalizedCase = {
  testId: string;
  objective: string;
  turnsCount: number;
  passed: boolean | null;
  finalScore: number | null;
  totalLatencyMs: number | null;
  turns: NormalizedTurn[];
};

export type Run = {
  runId: string;
  displayName: string;
  fileName: string;
  generatedAt: string;
  executionTimeSeconds: number | null;
  totalCases: number | null;
  passedCases: number | null;
  failedCases: number | null;
  threshold: number | null;
  cases: NormalizedCase[];
};

export type ParseError = {
  fileName: string;
  message: string;
};

export type ComparisonRow = {
  testId: string;
  objective: string;
  turnsA: number | null;
  turnsB: number | null;
  statusA: boolean | null;
  statusB: boolean | null;
  scoreA: number | null;
  scoreB: number | null;
  deltaScore: number | null;
  latencyA: number | null;
  latencyB: number | null;
  deltaLatency: number | null;
  outputChanged: boolean;
  caseA: NormalizedCase | null;
  caseB: NormalizedCase | null;
};
