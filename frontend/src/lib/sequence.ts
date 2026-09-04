/** Python str.isspace/splitlines parity; ASCII case conversion never expands residues. */
const SPACE = /[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u;
const LINES = /\r\n|[\n\r\v\f\u001c-\u001e\u0085\u2028\u2029]/u;
const STANDARD = new Set('ACDEFGHIKLMNPQRSTVWY');
export type InputType = 'raw' | 'fasta';
export interface SequenceError {
  name: 'SequenceValidationError'; code: string; message: string;
  position?: number; residue?: string;
}
export interface SequenceValidation {
  canonical: string; length: number; validResidues: number; inputType: InputType;
  headerName: string | null; valid: boolean; error: SequenceError | null;
}
export function trimPythonWhitespace(value: string): string {
  const points = [...value];
  let start = 0; let end = points.length;
  while (start < end && SPACE.test(points[start])) start += 1;
  while (end > start && SPACE.test(points[end - 1])) end -= 1;
  return points.slice(start, end).join('');
}
export function parseSequence(input: unknown): SequenceValidation {
  const result: SequenceValidation = { canonical: '', length: 0, validResidues: 0, inputType: 'raw', headerName: null, valid: false, error: null };
  const fail = (code: string, message: string, extra: Partial<SequenceError> = {}) => {
    result.error = { name: 'SequenceValidationError', code, message, ...extra };
    return result;
  };
  if (typeof input !== 'string') return fail('INVALID_SEQUENCE_TYPE', 'Sequence must be text.');
  let lines = input.split(LINES).map(trimPythonWhitespace).filter(Boolean);
  const headers = lines.flatMap((line, index) => line.startsWith('>') ? [index] : []);
  if (headers.length) result.inputType = 'fasta';
  if (headers.length > 1) return fail('MULTIPLE_FASTA_RECORDS', 'Enter exactly one protein sequence.');
  if (headers.length) {
    if (headers[0] !== 0) return fail('INVALID_FASTA', 'The FASTA header must precede the sequence.');
    result.headerName = trimPythonWhitespace(lines[0].slice(1)) || null;
    if (!result.headerName) return fail('INVALID_FASTA', 'The FASTA header needs a name.');
    lines = lines.slice(1);
  }
  result.canonical = [...lines.join('')].filter((point) => !SPACE.test(point)).join('')
    .replace(/[a-z]/g, (point) => point.toUpperCase());
  const residues = [...result.canonical];
  result.length = residues.length;
  result.validResidues = residues.filter((point) => STANDARD.has(point)).length;
  if (!residues.length) return fail('EMPTY_SEQUENCE', 'Enter a protein sequence.');
  const invalid = residues.findIndex((point) => !STANDARD.has(point));
  if (invalid !== -1) {
    const residue = residues[invalid];
    return fail('INVALID_AMINO_ACID', `Unsupported residue ${residue} at position ${invalid + 1}.`, { residue, position: invalid + 1 });
  }
  result.valid = true;
  return result;
}
export const validateSequence = parseSequence;
export function sequenceNameError(name: string): string | null {
  return [...name].length > 128 || /\p{C}/u.test(name)
    ? 'Sequence name must be text without control characters, at most 128 characters long.' : null;
}
export async function sequenceSha256(canonical: string): Promise<string> {
  const buffer = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return [...new Uint8Array(buffer)].map((value) => value.toString(16).padStart(2, '0')).join('');
}
