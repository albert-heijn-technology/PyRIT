export type DiffChunk = {
  type: 'equal' | 'insert' | 'delete';
  text: string;
};

export function diffWords(a: string, b: string): DiffChunk[] {
  const tokensA = tokenize(a);
  const tokensB = tokenize(b);
  const dp = buildLcsTable(tokensA, tokensB);
  const chunks: DiffChunk[] = [];

  let i = tokensA.length;
  let j = tokensB.length;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && tokensA[i - 1] === tokensB[j - 1]) {
      pushChunk(chunks, 'equal', tokensA[i - 1]);
      i -= 1;
      j -= 1;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      pushChunk(chunks, 'insert', tokensB[j - 1]);
      j -= 1;
    } else if (i > 0) {
      pushChunk(chunks, 'delete', tokensA[i - 1]);
      i -= 1;
    }
  }

  return chunks.reverse();
}

export type JsonDiff = {
  path: string;
  type: 'added' | 'removed' | 'changed';
};

export function diffJsonPaths(a: unknown, b: unknown, path = '$'): JsonDiff[] {
  if (a === undefined && b === undefined) {
    return [];
  }
  if (a === undefined) {
    return [{ path, type: 'added' }];
  }
  if (b === undefined) {
    return [{ path, type: 'removed' }];
  }
  if (isPrimitive(a) || isPrimitive(b)) {
    return Object.is(a, b) ? [] : [{ path, type: 'changed' }];
  }
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b)) {
      return [{ path, type: 'changed' }];
    }
    const diffs: JsonDiff[] = [];
    const max = Math.max(a.length, b.length);
    for (let idx = 0; idx < max; idx += 1) {
      diffs.push(...diffJsonPaths(a[idx], b[idx], `${path}[${idx}]`));
    }
    return diffs;
  }

  const objA = a as Record<string, unknown>;
  const objB = b as Record<string, unknown>;
  const keys = new Set([...Object.keys(objA), ...Object.keys(objB)]);
  const diffs: JsonDiff[] = [];
  for (const key of Array.from(keys).sort()) {
    diffs.push(...diffJsonPaths(objA[key], objB[key], `${path}.${key}`));
  }
  return diffs;
}

function tokenize(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) {
    return [];
  }
  return trimmed.split(/\s+/g);
}

function buildLcsTable(a: string[], b: string[]): number[][] {
  const table = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));
  for (let i = 1; i <= a.length; i += 1) {
    for (let j = 1; j <= b.length; j += 1) {
      if (a[i - 1] === b[j - 1]) {
        table[i][j] = table[i - 1][j - 1] + 1;
      } else {
        table[i][j] = Math.max(table[i - 1][j], table[i][j - 1]);
      }
    }
  }
  return table;
}

function pushChunk(chunks: DiffChunk[], type: DiffChunk['type'], token: string): void {
  const last = chunks[chunks.length - 1];
  if (last && last.type === type) {
    last.text = `${token} ${last.text}`;
  } else {
    chunks.push({ type, text: token });
  }
}

function isPrimitive(value: unknown): boolean {
  return value === null || typeof value !== 'object';
}
