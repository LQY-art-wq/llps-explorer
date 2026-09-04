import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

function source(path: string): string {
  return readFileSync(new URL(path, import.meta.url), 'utf8');
}

test('the proxy owns one high-entropy HttpOnly browser credential and streams authorized exports', () => {
  const route = source('../src/app/api/v1/[...path]/route.ts');
  const cookie = source('../src/lib/analysis-session-cookie.ts');
  assert.match(route, /randomBytes\(32\)\.toString\("base64url"\)/);
  assert.match(cookie, /httpOnly:\s*true/);
  assert.match(cookie, /sameSite:\s*'lax'/);
  assert.match(route, /request\.nextUrl\.protocol === "https:"/);
  assert.match(route, /"X-Analysis-Session": session/);
  assert.match(route, /new NextResponse\(upstream\.status === 204 \? null : upstream\.body/);
  assert.match(route, /request\.method === "POST" \|\| request\.method === "DELETE"/);
  const forward = route.slice(route.indexOf('async function forward'), route.indexOf('export const GET'));
  assert.doesNotMatch(forward, /return unavailable\(/);
  assert.doesNotMatch(route, /created/);
  assert.doesNotMatch(route, /localStorage|sessionStorage/);
});

test('workspace establishes the ownership cookie before concurrent startup reads and history Open uses detail GET', () => {
  const workspace = source('../src/lib/use-workspace.ts');
  const historyFirst = workspace.indexOf('await withAnalysisSessionLock(refreshHistory);');
  const secondary = workspace.indexOf('await Promise.all([refreshMethods(), refreshPublicConfig()]);');
  assert.ok(historyFirst >= 0 && secondary > historyFirst);
  assert.match(workspace, /withAnalysisSessionLock\(refreshHistory\)/);
  assert.match(workspace, /setSessionReady\(true\)/);
  assert.match(workspace, /await getAnalysis\(jobId, controller\.signal\)/);
  assert.match(workspace, /persistedInput\(persisted\)/);
  const viewJob = workspace.slice(workspace.indexOf('async function viewJob'), workspace.indexOf('async function deleteJob'));
  assert.ok(viewJob.indexOf('await persistedInput(persisted)') < viewJob.indexOf('analysisAbort.current?.abort()'));
  const run = workspace.slice(workspace.indexOf('async function run()'), workspace.indexOf('function retryPolling'));
  assert.match(run, /viewAbort\.current\?\.abort\(\)/);
  const retry = workspace.slice(workspace.indexOf('function retryPolling'), workspace.indexOf('async function viewJob'));
  assert.match(retry, /viewAbort\.current\?\.abort\(\)/);
  const deleteJob = workspace.slice(workspace.indexOf('async function deleteJob'), workspace.indexOf('async function downloadJob'));
  assert.match(deleteJob, /jobRef\.current\?\.job_id === jobId/);
  assert.match(deleteJob, /setError\(null\)/);
  assert.doesNotMatch(deleteJob, /job\?\.job_id === jobId/);
  assert.doesNotMatch(workspace, /retainHistory/);
});

test('history and results expose exact lifecycle language and backend export formats without local JSON reconstruction', () => {
  const history = source('../src/components/analysis-history.tsx');
  const results = source('../src/components/results.tsx');
  assert.match(history, /No saved analyses yet\./);
  assert.match(history, /This permanently deletes the stored sequence and analysis result\./);
  for (const kind of ['json', 'summary.csv', 'residues.csv', 'regions.csv', 'fasta']) {
    assert.ok(history.includes(`kind: '${kind}'`) || history.includes(`kind: \"${kind}\"`), kind);
    assert.ok(results.includes(`kind: '${kind}'`) || results.includes(`kind: \"${kind}\"`), kind);
  }
  assert.match(results, /Residue-level Data/);
  assert.match(results, /pageSize=\{50\}/);
  assert.doesNotMatch(results, /JSON\.stringify/);
});
