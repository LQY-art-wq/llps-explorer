import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

function source(path: string): string {
  return readFileSync(new URL(path, import.meta.url), 'utf8');
}

test('the production image uses the Next standalone server and browser API stays same-origin', () => {
  const config = source('../next.config.ts');
  const api = source('../src/lib/api.ts');
  assert.match(config, /output:\s*["']standalone["']/);
  assert.match(api, /\/api\/v1/);
  assert.doesNotMatch(api, /backend:8000|lreca:8001|redis:6379|postgres:5432/);
});

test('About and Documentation state the actual method and privacy boundaries', () => {
  const workspace = source('../src/components/workspace.tsx');
  for (const statement of [
    'LRECA uses a human-specific model.',
    'FuzDrop uses official results you import.',
    'SEG identifies low-complexity regions.',
    'DisMeta is currently unavailable.',
    'Complete sequences are not written to application logs.',
    'This site never contacts FuzDrop automatically',
    'can be deleted from History',
  ]) assert.ok(workspace.includes(statement), statement);
  assert.match(workspace, /currently \{workspace\.retentionDays\} days by default/);
});

test('the scientific disclaimer remains concise and does not invent validation', () => {
  const workspace = source('../src/components/workspace.tsx');
  assert.match(workspace, /Prediction results are computational estimates and should be interpreted alongside experimental evidence\./);
  assert.doesNotMatch(workspace, /clinically validated|experimentally validated|medical advice/i);
});
