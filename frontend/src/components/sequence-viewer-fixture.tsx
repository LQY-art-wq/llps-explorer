'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ProteinSequenceViewer } from './protein-sequence-viewer';
import type { SequencePerformanceSample } from './protein-sequence-viewer';
import { buildFeatureViewerModel } from '../lib/feature-viewer-model';
import {
  createFeatureTestFixture, FEATURE_TEST_LENGTHS, FEATURE_TEST_NOTICE,
} from '../lib/feature-test-fixtures';
import type { FeatureTestFixture, FeatureTestScenario } from '../lib/feature-test-fixtures';
import { buildSequenceViewerModel } from '../lib/sequence-viewer-model';
import type { ViewerRegionSelection } from '../lib/viewer-data';

const PERFORMANCE_KINDS: SequencePerformanceSample['kind'][] = [
  'initial_render', 'hover', 'selection', 'color',
];

function summarize(samples: readonly SequencePerformanceSample[]) {
  return PERFORMANCE_KINDS.map((kind) => {
    const values = samples.filter((sample) => sample.kind === kind
      && Number.isFinite(sample.durationMs) && sample.durationMs >= 0)
      .map((sample) => sample.durationMs).sort((a, b) => a - b);
    const count = values.length;
    return {
      kind,
      count,
      medianMs: count ? (values[Math.floor((count - 1) / 2)] + values[Math.floor(count / 2)]) / 2 : null,
      p95Ms: count ? values[Math.ceil(count * 0.95) - 1] : null,
      maxMs: count ? values[count - 1] : null,
    };
  });
}

function FixtureSession({ fixture }: { fixture: FeatureTestFixture }) {
  const featureModel = useMemo(() => buildFeatureViewerModel(fixture.job, fixture.input), [fixture]);
  const model = useMemo(() => buildSequenceViewerModel(featureModel), [featureModel]);
  const [selectedResidue, setSelectedResidue] = useState<number | null>(null);
  const [selectedRegion, setSelectedRegion] = useState<ViewerRegionSelection | null>(null);
  const [samples, setSamples] = useState<SequencePerformanceSample[]>([]);
  const onPerformance = useCallback((sample: SequencePerformanceSample) => {
    if (!Number.isFinite(sample.durationMs) || sample.durationMs < 0) return;
    setSamples((current) => [...current.slice(-199), { ...sample }]);
  }, []);
  const onResidueSelect = useCallback((position: number) => {
    setSelectedResidue(position);
    setSelectedRegion(null);
  }, []);
  const onRegionSelect = useCallback((region: ViewerRegionSelection) => {
    setSelectedRegion(region);
    setSelectedResidue(null);
  }, []);
  const onSelectionClear = useCallback(() => {
    setSelectedResidue(null);
    setSelectedRegion(null);
  }, []);
  const statistics = summarize(samples);
  const latest = samples[samples.length - 1];
  const display = (value: number | null) => value === null ? 'Not measured' : `${value.toFixed(2)} ms`;

  return <div data-fixture-kind="synthetic_render_fixture" data-fixture-analysis-id={fixture.job.job_id}
    data-fixture-scenario={fixture.scenario}>
    <ProteinSequenceViewer model={model} selectedResidue={selectedResidue} selectedRegion={selectedRegion}
      onResidueSelect={onResidueSelect} onRegionSelect={onRegionSelect} onSelectionClear={onSelectionClear}
      onPerformance={onPerformance} />
    <section className="panel" aria-labelledby="sequence-fixture-measurements" style={{ marginTop: 16 }}>
      <div className="panel-header"><h2 id="sequence-fixture-measurements">Observed sequence interaction timings</h2><span className="badge">Synthetic test data</span></div>
      <p className="muted">The production component records handler-to-commit application timings in this browser. Values are rendering evidence only; they are not inference, scientific validation, or screen-paint timings.</p>
      <p role="status" aria-live="polite" data-profile-latest data-profile-latest-kind={latest?.kind}
        data-profile-latest-ms={latest?.durationMs}>{latest ? `Latest ${latest.kind}: ${latest.durationMs.toFixed(2)} ms` : 'Waiting for an application update.'}</p>
      <div className="table-wrap"><table className="data-table" aria-label="Actual sequence viewer application timings">
        <thead><tr><th scope="col">Event</th><th scope="col">Samples</th><th scope="col">Median</th><th scope="col">p95</th><th scope="col">Maximum</th></tr></thead>
        <tbody>{statistics.map((row) => <tr key={row.kind} data-profile-kind={row.kind} data-profile-count={row.count}
          data-profile-median-ms={row.medianMs ?? undefined} data-profile-p95-ms={row.p95Ms ?? undefined}
          data-profile-max-ms={row.maxMs ?? undefined}><th scope="row">{row.kind}</th><td>{row.count}</td>
          <td>{display(row.medianMs)}</td><td>{display(row.p95Ms)}</td><td>{display(row.maxMs)}</td></tr>)}</tbody>
      </table></div>
      <p className="muted" data-fixture-selection>Selected residue: {selectedResidue ?? 'none'} · Region: {selectedRegion
        ? `${selectedRegion.method} ${selectedRegion.start}–${selectedRegion.end}` : 'none'}</p>
    </section>
  </div>;
}

export function SequenceViewerFixture() {
  const [request, setRequest] = useState<{ length: number; revision: number; scenario: FeatureTestScenario }>({
    length: 5000, revision: 1, scenario: 'mixed',
  });
  const [fixture, setFixture] = useState<FeatureTestFixture | null>(null);
  const [failure, setFailure] = useState(false);
  useEffect(() => {
    let current = true;
    void createFeatureTestFixture(request.length, request.revision, request.scenario).then((result) => {
      if (current) { setFixture(result); setFailure(false); }
    }).catch(() => { if (current) setFailure(true); });
    return () => { current = false; };
  }, [request]);
  const ready = fixture?.length === request.length && fixture?.revision === request.revision
    && fixture?.scenario === request.scenario;

  return <main className="workspace-main" style={{ maxWidth: 1600, margin: '0 auto', padding: 24 }}>
    <header className="panel" style={{ marginBottom: 20 }}>
      <p className="eyebrow">Module 8 · Explicit test environment</p>
      <h1>Synthetic test data — Sequence Viewer harness</h1>
      <p className="notice">{FEATURE_TEST_NOTICE}</p>
      <p className="muted">This page is unavailable unless the server explicitly enables FEATURE_VIEWER_TEST_MODE=1. It uses the production mappers and ProteinSequenceViewer.</p>
      <div className="button-row">
        <label className="field" htmlFor="sequence-fixture-length">Sequence length</label>
        <select id="sequence-fixture-length" className="input" value={request.length} onChange={(event) => setRequest((current) => ({
          ...current, length: Number(event.target.value), revision: current.revision + 1,
        }))}>{FEATURE_TEST_LENGTHS.map((length) => <option key={length} value={length}>{length} aa · synthetic</option>)}</select>
        <label className="field" htmlFor="sequence-fixture-scenario">Test scenario</label>
        <select id="sequence-fixture-scenario" className="input" value={request.scenario} onChange={(event) => setRequest((current) => ({
          ...current, scenario: event.target.value as FeatureTestScenario, revision: current.revision + 1,
        }))}><option value="mixed">Mixed · native presentation shapes</option>
          <option value="malformed_fuzdrop_residue">Malformed FuzDrop pDP · isolation test</option></select>
        <button className="button" type="button" onClick={() => setRequest((current) => ({ ...current, revision: current.revision + 1 }))}>New analysis / reset state</button>
      </div>
    </header>
    {failure ? <p role="alert" className="notice error">The synthetic test fixture could not be prepared.</p>
      : ready && fixture ? <FixtureSession key={fixture.job.job_id} fixture={fixture} />
        : <p role="status">Preparing synthetic test data…</p>}
  </main>;
}
