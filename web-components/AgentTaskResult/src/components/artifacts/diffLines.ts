export type DiffLineType = 'unchanged' | 'added' | 'removed';

export interface DiffLine {
  type: DiffLineType;
  content: string;
  oldLineNumber?: number;
  newLineNumber?: number;
}

/**
 * Line-level Myers diff (O(ND)) between two texts, split on `\n`.
 *
 * Returns a minimal edit script as unchanged/removed/added line records with
 * 1-based line numbers on whichever side(s) each record belongs to. Ties in
 * the shortest-edit-script search are broken deterministically (favoring the
 * "insertion" diagonal), so output is stable across calls for the same input
 * but is not guaranteed to match every other Myers implementation's tie
 * choice on ambiguous inputs.
 */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.length > 0 ? oldText.split('\n') : [];
  const newLines = newText.length > 0 ? newText.split('\n') : [];
  return diffLineArrays(oldLines, newLines);
}

export function diffLineArrays(oldLines: string[], newLines: string[]): DiffLine[] {
  const n = oldLines.length;
  const m = newLines.length;
  const max = n + m;
  if (max === 0) return [];

  const size = 2 * max + 1;
  const offset = max;
  const trace: number[][] = [];
  let v = new Array<number>(size).fill(0);

  search:
  for (let d = 0; d <= max; d++) {
    const nextV = v.slice();
    for (let k = -d; k <= d; k += 2) {
      let x: number;
      if (k === -d) {
        x = v[offset + k + 1];
      } else if (k === d) {
        x = v[offset + k - 1] + 1;
      } else if (v[offset + k - 1] < v[offset + k + 1]) {
        x = v[offset + k + 1];
      } else {
        x = v[offset + k - 1] + 1;
      }
      let y = x - k;
      while (x < n && y < m && oldLines[x] === newLines[y]) {
        x += 1;
        y += 1;
      }
      nextV[offset + k] = x;
      if (x >= n && y >= m) {
        trace.push(nextV.slice());
        v = nextV;
        break search;
      }
    }
    trace.push(nextV.slice());
    v = nextV;
  }

  const result: DiffLine[] = [];
  let x = n;
  let y = m;
  for (let d = trace.length - 1; d >= 0; d--) {
    const vRow = trace[d];
    void vRow;
    const prevRow = d > 0 ? trace[d - 1] : new Array<number>(size).fill(0);
    const k = x - y;
    let prevK: number;
    if (k === -d) {
      prevK = k + 1;
    } else if (k === d) {
      prevK = k - 1;
    } else if (prevRow[offset + k - 1] < prevRow[offset + k + 1]) {
      prevK = k + 1;
    } else {
      prevK = k - 1;
    }
    const prevX = d === 0 ? 0 : prevRow[offset + prevK];
    const prevY = prevX - prevK;

    while (x > prevX && y > prevY) {
      result.unshift({ type: 'unchanged', content: oldLines[x - 1] });
      x -= 1;
      y -= 1;
    }
    if (d > 0) {
      if (x === prevX) {
        result.unshift({ type: 'added', content: newLines[y - 1] });
        y -= 1;
      } else {
        result.unshift({ type: 'removed', content: oldLines[x - 1] });
        x -= 1;
      }
    }
  }

  let oldLineNumber = 1;
  let newLineNumber = 1;
  return result.map(entry => {
    if (entry.type === 'unchanged') {
      const withNumbers: DiffLine = { ...entry, oldLineNumber, newLineNumber };
      oldLineNumber += 1;
      newLineNumber += 1;
      return withNumbers;
    }
    if (entry.type === 'removed') {
      const withNumbers: DiffLine = { ...entry, oldLineNumber };
      oldLineNumber += 1;
      return withNumbers;
    }
    const withNumbers: DiffLine = { ...entry, newLineNumber };
    newLineNumber += 1;
    return withNumbers;
  });
}
