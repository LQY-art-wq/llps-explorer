import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSequence, sequenceNameError, sequenceSha256 } from '../src/lib/sequence.ts';
import { EXAMPLE_NAME, EXAMPLE_SEQUENCE } from '../src/lib/examples.ts';

test('raw input preserves order and normalizes ASCII case and whitespace', () => {
  assert.deepEqual(parseSequence('  ac d\nE\tfg  '), {
    canonical: 'ACDEFG', length: 6, validResidues: 6, inputType: 'raw', headerName: null, valid: true, error: null,
  });
});
test('one FASTA extracts a separate name, including description', () => {
  const parsed = parseSequence('\r\n > My protein \r\n acd \r\nef\r\n');
  assert.equal(parsed.headerName, 'My protein'); assert.equal(parsed.inputType, 'fasta');
  assert.equal(parsed.canonical, 'ACDEF'); assert.equal(parsed.valid, true);
});
for (const [input, code] of [
  ['', 'EMPTY_SEQUENCE'], [' \n\t', 'EMPTY_SEQUENCE'], ['>name\n', 'EMPTY_SEQUENCE'],
  ['> \nACD', 'INVALID_FASTA'], ['ACD\n>name\nEFG', 'INVALID_FASTA'],
  ['>a\nACD\n>b\nEFG', 'MULTIPLE_FASTA_RECORDS'],
  [null, 'INVALID_SEQUENCE_TYPE'], [42, 'INVALID_SEQUENCE_TYPE'],
] as const) test(`invalid input produces ${code}: ${String(input)}`, () => {
  const parsed = parseSequence(input); assert.equal(parsed.valid, false); assert.equal(parsed.error?.code, code);
});
for (const residue of ['B', 'J', 'O', 'U', 'X', 'Z', '*', '-', 'ß', 'ı', 'ſ', 'Ａ', '😀', '\ufeff']) {
  test(`unsupported residue ${JSON.stringify(residue)} is never silently changed`, () => {
    const parsed = parseSequence(`a c${residue} d`);
    assert.equal(parsed.error?.code, 'INVALID_AMINO_ACID'); assert.equal(parsed.error?.position, 3);
    assert.equal(parsed.error?.residue, residue); assert.equal(parsed.canonical, `AC${residue}D`);
    assert.equal(parsed.length, 4); assert.equal(parsed.validResidues, 3);
  });
}
test('all Python whitespace characters are removed; BOM is not whitespace', () => {
  const spaces = '\t\n\v\f\r\u001c\u001d\u001e\u001f \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000';
  assert.equal(parseSequence(`a${spaces}c`).canonical, 'AC');
  assert.equal(parseSequence(`a${spaces}c`).valid, true);
  assert.equal(parseSequence('\ufeffAC').error?.position, 1);
});
test('positions use Unicode code points, not UTF-16 or raw FASTA offsets', () => {
  const parsed = parseSequence('>protein\n ac\n😀X');
  assert.equal(parsed.error?.position, 3); assert.equal(parsed.length, 4);
});
test('sequence name validation matches length and category-C restrictions', () => {
  assert.equal(sequenceNameError('α protein'), null);
  assert.equal(sequenceNameError('😀'.repeat(128)), null);
  assert.notEqual(sequenceNameError('😀'.repeat(129)), null);
  for (const value of ['a\nb', 'a\u200db', '\ud800', '\ue000']) assert.notEqual(sequenceNameError(value), null);
});
test('example is the frozen real 248-aa sequence, with verified identity and no predictions', async () => {
  assert.equal(EXAMPLE_NAME, 'human_positive_line_1'); assert.equal(EXAMPLE_SEQUENCE.length, 248);
  assert.equal(parseSequence(EXAMPLE_SEQUENCE).valid, true);
  assert.equal(await sequenceSha256(EXAMPLE_SEQUENCE), '75078f3a53de34edd93133af165bd3d5246d26dddb31ce2037c8b11ac97791bf');
});
