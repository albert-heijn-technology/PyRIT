import { normalizeText } from './normalize';
import { AssistantFieldValue, NormalizedCase, NormalizedTurn, Run, ScoreSummary } from './types';

const JSON_MIME = 'application/json';

export function isJsonFile(file: File): boolean {
  const lowerName = file.name.toLowerCase();
  const isJsonExt = lowerName.endsWith('.json');
  if (file.type === JSON_MIME) {
    return true;
  }
  if (isJsonExt) {
    return true;
  }
  return file.type === '' && isJsonExt;
}

export async function parseReport(fileName: string, json: unknown): Promise<Run> {
  if (!json || typeof json !== 'object') {
    throw new Error('Invalid JSON root. Expected an object.');
  }

  const root = json as Record<string, unknown>;
  const generatedAt = asString(root.generated_at) ?? '';
  const runId = `${fileName}|${generatedAt}`;
  const displayName = fileName.replace(/\.[^.]+$/, '');
  const casesRaw = Array.isArray(root.cases) ? root.cases : [];

  const cases: NormalizedCase[] = [];
  for (const caseObj of casesRaw) {
    cases.push(await parseCase(caseObj));
  }

  return {
    runId,
    displayName,
    fileName,
    generatedAt,
    executionTimeSeconds: asNumber(root.execution_time_seconds),
    totalCases: asNumber(root.total_cases),
    passedCases: asNumber(root.passed_cases),
    failedCases: asNumber(root.failed_cases),
    threshold: asNumber(root.threshold),
    cases,
  };
}

export async function parseCase(caseObj: unknown): Promise<NormalizedCase> {
  const obj = (caseObj ?? {}) as Record<string, unknown>;
  const objective = asString(obj.objective) ?? '';
  const transcript = Array.isArray(obj.transcript) ? obj.transcript : [];
  const testId = normalizeText(objective);

  const turns: NormalizedTurn[] = [];
  let totalLatencyMs = 0;
  let totalLatencyCount = 0;

  for (let idx = 0; idx < transcript.length; idx += 1) {
    const turnObj = transcript[idx] as Record<string, unknown>;
    const { turn, assistantLatencySum, assistantLatencyCount } = parseTurn(turnObj, idx);
    turns.push(turn);
    totalLatencyMs += assistantLatencySum;
    totalLatencyCount += assistantLatencyCount;
  }

  return {
    testId,
    objective,
    turnsCount: asNumber(obj.turns) ?? turns.length,
    passed: asBoolean(obj.passed),
    finalScore: asNumber(obj.final_score),
    totalLatencyMs: totalLatencyCount > 0 ? totalLatencyMs : null,
    turns,
  };
}

export function parseAssistantEnvelope(originalValue: string): {
  text: string;
  dataJson: unknown | null;
  dataRaw: string | null;
  pillsJson: unknown | null;
  pillsRaw: string | null;
  streamEnded: boolean | null;
  fields: Record<string, AssistantFieldValue>;
} {
  const text = extractStringValue(originalValue, 'Text') ?? '';
  const dataRaw = extractStringValue(originalValue, 'Data');
  const pillsRaw = extractStringValue(originalValue, 'Pills');
  const streamLiteral = extractLiteralValue(originalValue, 'StreamEnded');
  const fields = parseAssistantFields(originalValue);

  const { parsed: dataJson, raw: normalizedDataRaw } = parseJsonString(dataRaw);
  const { parsed: pillsJson, raw: normalizedPillsRaw } = parseJsonString(pillsRaw);

  let streamEnded: boolean | null = null;
  if (streamLiteral !== null) {
    streamEnded = parseBooleanLiteral(streamLiteral);
  }

  return {
    text,
    dataJson,
    dataRaw: normalizedDataRaw,
    pillsJson,
    pillsRaw: normalizedPillsRaw,
    streamEnded,
    fields,
  };
}

function parseTurn(
  turnObj: Record<string, unknown>,
  idx: number
): { turn: NormalizedTurn; assistantLatencySum: number; assistantLatencyCount: number } {
  const turnIndex = asNumber(turnObj.turn_index) ?? idx + 1;
  const pieces = Array.isArray(turnObj.pieces) ? turnObj.pieces : [];
  const userPieces = pieces.filter((piece) => asString((piece as Record<string, unknown>).role) === 'user');
  const assistantPieces = pieces.filter(
    (piece) => asString((piece as Record<string, unknown>).role) === 'assistant'
  );

  const userText = userPieces
    .map((piece) => asString((piece as Record<string, unknown>).original_value) ?? '')
    .join('\n')
    .trim();

  let assistantText = '';
  let assistantData: unknown | null = null;
  let assistantPills: unknown | null = null;
  let assistantDataRaw: string | null = null;
  let assistantPillsRaw: string | null = null;
  let streamEnded: boolean | null = null;
  let latencyMs: number | null = null;
  let latencyFirstTokenMs: number | null = null;
  let latencyEventsMs: Record<string, number> | null = null;
  let weightedAverage: number | null = null;
  let scores: ScoreSummary[] = [];
  let assistantFields: Record<string, AssistantFieldValue> = {};

  if (assistantPieces.length > 0) {
    const texts: string[] = [];
    for (const assistantPiece of assistantPieces) {
      const pieceObj = assistantPiece as Record<string, unknown>;
      const originalValue = asString(pieceObj.original_value) ?? '';
      const envelope = parseAssistantEnvelope(originalValue);
      if (envelope.text) {
        texts.push(envelope.text);
      }
    }
    assistantText = texts.join('\n\n');

    const primaryPiece = assistantPieces[0] as Record<string, unknown>;
    const envelope = parseAssistantEnvelope(asString(primaryPiece.original_value) ?? '');
    assistantData = envelope.dataJson;
    assistantPills = envelope.pillsJson;
    assistantDataRaw = envelope.dataRaw;
    assistantPillsRaw = envelope.pillsRaw;
    streamEnded = envelope.streamEnded;
    assistantFields = envelope.fields;
    latencyMs = asNumber(primaryPiece.latency_ms);
    latencyFirstTokenMs = asNumber(primaryPiece.latency_first_token_ms);
    latencyEventsMs = asRecordNumber(primaryPiece.latency_events_ms);
    weightedAverage = asNumber(primaryPiece.weighted_average);

    const rawScores = Array.isArray(primaryPiece.scores) ? primaryPiece.scores : [];
    scores = rawScores.map((score) => parseScore(score));
  }

  const assistantLatencySum = assistantPieces.reduce((sum, piece) => {
    const latency = asNumber((piece as Record<string, unknown>).latency_ms);
    return sum + (latency ?? 0);
  }, 0);
  const assistantLatencyCount = assistantPieces.reduce((count, piece) => {
    const latency = asNumber((piece as Record<string, unknown>).latency_ms);
    return latency === null ? count : count + 1;
  }, 0);

  return {
    turn: {
      index: turnIndex,
      userText,
      assistantText,
      assistantData,
      assistantPills,
      assistantDataRaw,
      assistantPillsRaw,
      streamEnded,
      assistantFields,
      latencyMs,
      latencyFirstTokenMs,
      latencyEventsMs,
      weightedAverage,
      scores,
    },
    assistantLatencySum,
    assistantLatencyCount,
  };
}

function parseScore(scoreObj: unknown): ScoreSummary {
  const obj = (scoreObj ?? {}) as Record<string, unknown>;
  const scorerIdentifier = obj.scorer_identifier as Record<string, unknown> | undefined;
  return {
    score: asNumber(obj.score) ?? 0,
    threshold: asNumber(obj.threshold),
    weight: asNumber(obj.weight),
    passed: asBoolean(obj.passed),
    expectedOutput: asString(obj.expected_output),
    rationale: asString(obj.rationale),
    scorerConfigPath: asString(scorerIdentifier?.config_path),
    required: asBoolean(obj.required),
  };
}

function parseJsonString(raw: string | null): { parsed: unknown | null; raw: string | null } {
  if (raw === null) {
    return { parsed: null, raw: null };
  }
  try {
    return { parsed: JSON.parse(raw), raw };
  } catch {
    return { parsed: null, raw };
  }
}

type EnvelopeEntry = {
  key: string;
  raw: string | null;
  isLiteral: boolean;
};

function parseAssistantFields(originalValue: string): Record<string, AssistantFieldValue> {
  const fields: Record<string, AssistantFieldValue> = {};
  const entries = extractEnvelopeEntries(originalValue);
  for (const entry of entries) {
    if (!entry.key) {
      continue;
    }
    fields[entry.key] = {
      raw: entry.raw,
      parsed: parseFieldValue(entry.raw, entry.isLiteral),
    };
  }
  return fields;
}

function extractEnvelopeEntries(source: string): EnvelopeEntry[] {
  const entries: EnvelopeEntry[] = [];
  let idx = 0;
  while (idx < source.length) {
    const char = source[idx];
    if (char !== '\'' && char !== '"') {
      idx += 1;
      continue;
    }
    const parsedKey = parseQuotedString(source, idx);
    if (!parsedKey) {
      idx += 1;
      continue;
    }
    let cursor = skipWhitespace(source, parsedKey.endIndex);
    if (source[cursor] !== ':') {
      idx = parsedKey.endIndex;
      continue;
    }
    cursor = skipWhitespace(source, cursor + 1);
    if (cursor >= source.length) {
      entries.push({ key: parsedKey.value, raw: null, isLiteral: true });
      idx = cursor;
      continue;
    }
    const valueChar = source[cursor];
    if (valueChar === '\'' || valueChar === '"') {
      const parsedValue = parseQuotedString(source, cursor);
      if (parsedValue) {
        entries.push({ key: parsedKey.value, raw: parsedValue.value, isLiteral: false });
        idx = parsedValue.endIndex;
        continue;
      }
    }
    let end = cursor;
    while (end < source.length && source[end] !== ',' && source[end] !== '}') {
      end += 1;
    }
    const literal = source.slice(cursor, end).trim();
    entries.push({ key: parsedKey.value, raw: literal || null, isLiteral: true });
    idx = end;
  }
  return entries;
}

function parseFieldValue(raw: string | null, isLiteral: boolean): unknown | null {
  if (raw === null) {
    return null;
  }
  if (isLiteral) {
    const normalized = raw.trim().toLowerCase();
    if (normalized === 'none' || normalized === 'null') {
      return null;
    }
  }
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function extractStringValue(source: string, key: string): string | null {
  const match = findKeyMatch(source, key);
  if (!match) {
    return null;
  }
  let idx = match.index + match.length;
  idx = skipWhitespace(source, idx);
  const quote = source[idx];
  if (quote !== '\'' && quote !== '"') {
    return null;
  }
  const parsed = parseQuotedString(source, idx);
  return parsed ? parsed.value : null;
}

function extractLiteralValue(source: string, key: string): string | null {
  const match = findKeyMatch(source, key);
  if (!match) {
    return null;
  }
  let idx = match.index + match.length;
  idx = skipWhitespace(source, idx);
  const quote = source[idx];
  if (quote === '\'' || quote === '"') {
    const parsed = parseQuotedString(source, idx);
    return parsed ? parsed.value : null;
  }
  let end = idx;
  while (end < source.length && source[end] !== ',' && source[end] !== '}') {
    end += 1;
  }
  return source.slice(idx, end).trim();
}

function findKeyMatch(source: string, key: string): { index: number; length: number } | null {
  const pattern = new RegExp(`['"]${escapeRegExp(key)}['"]\\s*:`);
  const match = source.match(pattern);
  if (!match || match.index === undefined) {
    return null;
  }
  return { index: match.index, length: match[0].length };
}

function parseQuotedString(source: string, startIndex: number): { value: string; endIndex: number } | null {
  const quote = source[startIndex];
  let value = '';
  let i = startIndex + 1;
  while (i < source.length) {
    const char = source[i];
    if (char === '\\') {
      const next = source[i + 1];
      if (next !== undefined) {
        value += next;
        i += 2;
        continue;
      }
    }
    if (char === quote) {
      return { value, endIndex: i + 1 };
    }
    value += char;
    i += 1;
  }
  return null;
}

function skipWhitespace(source: string, index: number): number {
  let idx = index;
  while (idx < source.length && /\s/.test(source[idx])) {
    idx += 1;
  }
  return idx;
}

function parseBooleanLiteral(value: string): boolean | null {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'true') {
    return true;
  }
  if (normalized === 'false') {
    return false;
  }
  if (normalized === 'none' || normalized === 'null') {
    return null;
  }
  return null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asBoolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function asRecordNumber(value: unknown): Record<string, number> | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record: Record<string, number> = {};
  let hasValue = false;
  for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
    if (typeof val === 'number' && Number.isFinite(val)) {
      record[key] = val;
      hasValue = true;
    }
  }
  return hasValue ? record : null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
