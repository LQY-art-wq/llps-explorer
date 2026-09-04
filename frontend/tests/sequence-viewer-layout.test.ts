import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildSequenceRows, copyPayload, extractRegionSequence, navigateSequencePosition,
  parsePositionQuery, residueLabel, rowStartForPosition, SEQUENCE_RESIDUES_PER_ROW, writeCopyText,
} from '../src/lib/sequence-viewer-layout.ts';

test('fixed 50-residue rows preserve 1-based positions and terminal residues', () => {
  const sequence = 'A'.repeat(49) + 'Y' + 'C'.repeat(50) + 'W';
  const rows = buildSequenceRows(sequence);
  assert.equal(SEQUENCE_RESIDUES_PER_ROW, 50);
  assert.deepEqual(rows.map(({ start, end }) => [start, end]), [[1, 50], [51, 100], [101, 101]]);
  assert.deepEqual(rows[0].ticks, [10, 20, 30, 40, 50]);
  assert.equal(rows[0].residues[0].position, 1);
  assert.deepEqual(rows[0].residues[49], { position: 50, aa: 'Y' });
  assert.deepEqual(rows[2].residues[0], { position: 101, aa: 'W' });
  assert.equal(buildSequenceRows('').length, 0);
});

for (const [length, expectedRows] of [[100, 2], [500, 10], [1000, 20], [2000, 40], [5000, 100]] as const) {
  test(`${length} residues produce ${expectedRows} lightweight rows`, () => {
    const rows = buildSequenceRows('A'.repeat(length));
    assert.equal(rows.length, expectedRows);
    assert.equal(rows.flatMap((row) => row.residues).length, length);
    assert.equal(rows.at(-1)?.end, length);
  });
}

test('row lookup is stable at 1, wrap boundaries and N', () => {
  assert.equal(rowStartForPosition(1, 5000), 1);
  assert.equal(rowStartForPosition(50, 5000), 1);
  assert.equal(rowStartForPosition(51, 5000), 51);
  assert.equal(rowStartForPosition(243, 5000), 201);
  assert.equal(rowStartForPosition(5000, 5000), 4951);
  assert.throws(() => rowStartForPosition(0, 100), RangeError);
});

test('position queries accept a number or matching amino-acid label only', () => {
  const sequence = `${'A'.repeat(242)}Y${'C'.repeat(10)}`;
  assert.deepEqual(parsePositionQuery('243', sequence), { position: 243, error: null });
  assert.deepEqual(parsePositionQuery('Y243', sequence), { position: 243, error: null });
  assert.deepEqual(parsePositionQuery('y243', sequence), { position: 243, error: null });
  assert.equal(parsePositionQuery('F243', sequence).error, 'residue_mismatch');
  assert.equal(parsePositionQuery('0', sequence).error, 'invalid_format');
  assert.equal(parsePositionQuery('254', sequence).error, 'out_of_range');
  assert.equal(parsePositionQuery('243Y', sequence).error, 'invalid_format');
  assert.equal(parsePositionQuery('24.3', sequence).error, 'invalid_format');
  assert.equal(parsePositionQuery('', sequence).error, 'empty');
});

test('keyboard navigation clamps to the protein and uses fixed row boundaries', () => {
  assert.equal(navigateSequencePosition(1, 'ArrowLeft', 101), 1);
  assert.equal(navigateSequencePosition(101, 'ArrowRight', 101), 101);
  assert.equal(navigateSequencePosition(51, 'ArrowUp', 101), 1);
  assert.equal(navigateSequencePosition(60, 'ArrowDown', 101), 101);
  assert.equal(navigateSequencePosition(57, 'Home', 101), 51);
  assert.equal(navigateSequencePosition(57, 'End', 101), 100);
  assert.equal(navigateSequencePosition(101, 'End', 101), 101);
});

test('copy helpers convert 1-based inclusive regions exactly once', () => {
  const sequence = 'MASNDYT';
  assert.equal(extractRegionSequence(sequence, 1, 1), 'M');
  assert.equal(extractRegionSequence(sequence, 7, 7), 'T');
  assert.equal(extractRegionSequence(sequence, 1, 7), sequence);
  assert.equal(extractRegionSequence(sequence, 3, 6), 'SNDY');
  assert.equal(copyPayload(sequence, { kind: 'full' }), sequence);
  assert.equal(copyPayload(sequence, { kind: 'region', start: 3, end: 6 }), 'SNDY');
  assert.equal(copyPayload(sequence, { kind: 'residue', position: 6 }), 'Y6');
  assert.equal(residueLabel(sequence, 1), 'M1');
  assert.throws(() => extractRegionSequence(sequence, 0, 1), RangeError);
  assert.throws(() => extractRegionSequence(sequence, 2, 8), RangeError);
});

test('clipboard wrapper reports injected browser success and denial without exposing sequence data', async () => {
  const written: string[] = [];
  assert.equal(await writeCopyText('Y243', async (value) => { written.push(value); }), true);
  assert.deepEqual(written, ['Y243']);
  assert.equal(await writeCopyText('PRIVATE', async () => { throw new Error('denied'); }), false);
});
