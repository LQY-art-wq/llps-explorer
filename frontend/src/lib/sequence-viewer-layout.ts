/** Presentation-only helpers for the 1-based, fixed-width protein sequence grid. */
export const SEQUENCE_RESIDUES_PER_ROW = 50;

export interface SequenceRow {
  start: number;
  end: number;
  residues: ReadonlyArray<{ position: number; aa: string }>;
  ticks: ReadonlyArray<number>;
}

export interface PositionQueryResult {
  position: number | null;
  error: 'empty' | 'invalid_format' | 'out_of_range' | 'residue_mismatch' | null;
}

export type CopyTarget =
  | { kind: 'full' }
  | { kind: 'residue'; position: number }
  | { kind: 'region'; start: number; end: number };

function validLength(length: number): void {
  if (!Number.isSafeInteger(length) || length < 1) throw new RangeError('Sequence length must be a positive safe integer.');
}

export function buildSequenceRows(sequence: string, residuesPerRow = SEQUENCE_RESIDUES_PER_ROW): SequenceRow[] {
  if (!Number.isSafeInteger(residuesPerRow) || residuesPerRow < 1) throw new RangeError('Residues per row must be a positive safe integer.');
  if (!sequence.length) return [];
  const rows: SequenceRow[] = [];
  for (let offset = 0; offset < sequence.length; offset += residuesPerRow) {
    const endOffset = Math.min(sequence.length, offset + residuesPerRow);
    const residues = Array.from(sequence.slice(offset, endOffset), (aa, index) => ({ position: offset + index + 1, aa }));
    const ticks = residues.filter(({ position }) => position % 10 === 0).map(({ position }) => position);
    rows.push({ start: offset + 1, end: endOffset, residues, ticks });
  }
  return rows;
}

export function rowStartForPosition(position: number, length: number, residuesPerRow = SEQUENCE_RESIDUES_PER_ROW): number {
  validLength(length);
  if (!Number.isSafeInteger(position) || position < 1 || position > length) throw new RangeError('Residue position is outside the sequence.');
  if (!Number.isSafeInteger(residuesPerRow) || residuesPerRow < 1) throw new RangeError('Residues per row must be a positive safe integer.');
  return Math.floor((position - 1) / residuesPerRow) * residuesPerRow + 1;
}

export function parsePositionQuery(query: string, sequence: string): PositionQueryResult {
  const value = query.trim();
  if (!value) return { position: null, error: 'empty' };
  const match = /^([A-Za-z])?([1-9]\d*)$/.exec(value);
  if (!match) return { position: null, error: 'invalid_format' };
  const position = Number(match[2]);
  if (!Number.isSafeInteger(position) || position > sequence.length) return { position: null, error: 'out_of_range' };
  if (match[1] && sequence[position - 1]?.toUpperCase() !== match[1].toUpperCase()) {
    return { position: null, error: 'residue_mismatch' };
  }
  return { position, error: null };
}

export function navigateSequencePosition(
  position: number, key: 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown' | 'Home' | 'End',
  length: number, residuesPerRow = SEQUENCE_RESIDUES_PER_ROW,
): number {
  validLength(length);
  const current = Math.min(length, Math.max(1, Number.isSafeInteger(position) ? position : 1));
  if (!Number.isSafeInteger(residuesPerRow) || residuesPerRow < 1) throw new RangeError('Residues per row must be a positive safe integer.');
  if (key === 'ArrowLeft') return Math.max(1, current - 1);
  if (key === 'ArrowRight') return Math.min(length, current + 1);
  if (key === 'ArrowUp') return Math.max(1, current - residuesPerRow);
  if (key === 'ArrowDown') return Math.min(length, current + residuesPerRow);
  const rowStart = Math.floor((current - 1) / residuesPerRow) * residuesPerRow + 1;
  return key === 'Home' ? rowStart : Math.min(length, rowStart + residuesPerRow - 1);
}

export function extractRegionSequence(sequence: string, start: number, end: number): string {
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start || end > sequence.length) {
    throw new RangeError('Region must use valid 1-based inclusive coordinates.');
  }
  return sequence.slice(start - 1, end);
}

export function residueLabel(sequence: string, position: number): string {
  if (!Number.isSafeInteger(position) || position < 1 || position > sequence.length) throw new RangeError('Residue position is outside the sequence.');
  return `${sequence[position - 1]}${position}`;
}

export function copyPayload(sequence: string, target: CopyTarget): string {
  if (target.kind === 'full') return sequence;
  if (target.kind === 'residue') return residueLabel(sequence, target.position);
  return extractRegionSequence(sequence, target.start, target.end);
}

/** Keeps clipboard success/failure handling testable without replacing the browser API in production. */
export async function writeCopyText(text: string, writer: (value: string) => Promise<void>): Promise<boolean> {
  try {
    await writer(text);
    return true;
  } catch {
    return false;
  }
}
