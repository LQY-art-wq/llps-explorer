"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ProteinFeatureViewer } from "./protein-feature-viewer";
import { buildFeatureViewerModel } from "../lib/feature-viewer-model";
import {
  createFeatureTestFixture, FEATURE_TEST_LENGTHS, FEATURE_TEST_NOTICE,
  summarizeFeaturePerformance,
} from "../lib/feature-test-fixtures";
import type {
  FeaturePerformanceSample, FeatureTestFixture, FeatureTestScenario,
} from "../lib/feature-test-fixtures";
import type { ViewerRegionSelection } from "../lib/viewer-data";

function FixtureSession({ fixture }: { fixture: FeatureTestFixture }) {
  const model = useMemo(() => buildFeatureViewerModel(fixture.job, fixture.input), [fixture]);
  const [selectedResidue, setSelectedResidue] = useState<number | null>(null);
  const [selectedRegion, setSelectedRegion] = useState<ViewerRegionSelection | null>(null);
  const [samples, setSamples] = useState<FeaturePerformanceSample[]>([]);
  const onPerformance = useCallback((sample: FeaturePerformanceSample) => {
    if (!Number.isFinite(sample.durationMs) || sample.durationMs < 0) return;
    setSamples((current) => [...current.slice(-199), { ...sample }]);
  }, []);
  const onResidueSelect = useCallback((position: number) => {
    setSelectedResidue(position); setSelectedRegion(null);
  }, []);
  const onRegionSelect = useCallback((region: ViewerRegionSelection) => {
    setSelectedRegion(region); setSelectedResidue(null);
  }, []);
  const onSelectionClear = useCallback(() => {
    setSelectedResidue(null); setSelectedRegion(null);
  }, []);
  const statistics = summarizeFeaturePerformance(samples);
  const latest = samples[samples.length - 1];
  const display = (value: number | null) => value === null ? "Not measured" : `${value.toFixed(2)} ms`;

  return (
    <div data-fixture-kind="synthetic_render_fixture" data-fixture-analysis-id={fixture.job.job_id}
      data-fixture-scenario={fixture.scenario}>
      <section className="panel" aria-label="Synthetic fixture identity" style={{ marginBottom: 16 }}>
        <h2>Synthetic test data · {fixture.length} residues</h2>
        <p className="muted">{fixture.job.job_id}</p>
        <p className="muted">
          One shared production mapper and viewer. The mixed fixture supplies six data tracks, intentional
          nullable pDP values, overlapping regions, duplicates, and first/last residue boundaries.
          DisMeta has no synthetic data or track.
        </p>
        {fixture.scenario === "malformed_fuzdrop_residue" && <p className="notice" role="status">
          Synthetic malformed-data scenario: one FuzDrop pDP row intentionally has position 0.
          The production mapper should flag that residue track as invalid while preserving the
          other five tracks, including FuzDrop regions. This is an in-memory test fixture,
          never an official result or backend import.
        </p>}
      </section>
      <ProteinFeatureViewer
        model={model}
        variant="full"
        selectedResidue={selectedResidue}
        selectedRegion={selectedRegion}
        onResidueSelect={onResidueSelect}
        onRegionSelect={onRegionSelect}
        onSelectionClear={onSelectionClear}
        onPerformance={onPerformance}
      />
      <section className="panel" aria-labelledby="fixture-measurements" style={{ marginTop: 16 }}>
        <div className="panel-header">
          <h2 id="fixture-measurements">Observed interaction timings</h2>
          <span className="badge">Synthetic test data</span>
        </div>
        <p className="muted">
          Measured by the production viewer with the browser Performance API: initial component mount
          or interaction handler to React commit. Canvas execution is recorded separately on the canvas.
          These are application update timings, not screen paint, scientific inference, or total page-load
          times. Statistics retain the latest 200 samples for this analysis.
        </p>
        <p role="status" aria-live="polite" data-profile-latest
          data-profile-latest-kind={latest?.kind} data-profile-latest-ms={latest?.durationMs}>
          {latest ? `Latest ${latest.kind}: ${latest.durationMs.toFixed(2)} ms` : "Waiting for an application update."}
        </p>
        <div className="table-wrap">
          <table className="data-table" aria-label="Actual feature viewer application timings">
            <thead><tr><th scope="col">Event</th><th scope="col">Samples</th><th scope="col">Median</th><th scope="col">p95</th><th scope="col">Maximum</th></tr></thead>
            <tbody>{statistics.map((row) => (
              <tr key={row.kind} data-profile-kind={row.kind} data-profile-count={row.count}
                data-profile-median-ms={row.medianMs ?? undefined} data-profile-p95-ms={row.p95Ms ?? undefined}
                data-profile-max-ms={row.maxMs ?? undefined}>
                <th scope="row">{row.kind}</th><td>{row.count}</td><td>{display(row.medianMs)}</td>
                <td>{display(row.p95Ms)}</td><td>{display(row.maxMs)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <p className="muted" data-fixture-selection>
          Selected residue: {selectedResidue ?? "none"} · Region: {selectedRegion
            ? `${selectedRegion.method} ${selectedRegion.start}–${selectedRegion.end}` : "none"}
        </p>
      </section>
    </div>
  );
}

export function FeatureViewerFixture() {
  const [request, setRequest] = useState<{ length: number; revision: number; scenario: FeatureTestScenario }>({
    length: 5000, revision: 1, scenario: "mixed",
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

  return (
    <main className="workspace-main" style={{ maxWidth: 1600, margin: "0 auto", padding: 24 }}>
      <header className="panel" style={{ marginBottom: 20 }}>
        <p className="eyebrow">Module 7 · Explicit test environment</p>
        <h1>Synthetic test data — Feature Viewer harness</h1>
        <p className="notice">{FEATURE_TEST_NOTICE}</p>
        <p className="muted">This page is unavailable unless the server explicitly enables FEATURE_VIEWER_TEST_MODE=1.</p>
        <div className="button-row">
          <label className="field" htmlFor="feature-fixture-length">Sequence length</label>
          <select id="feature-fixture-length" className="input" value={request.length}
            onChange={(event) => setRequest((current) => ({ ...current, length: Number(event.target.value), revision: current.revision + 1 }))}>
            {FEATURE_TEST_LENGTHS.map((length) => <option key={length} value={length}>{length} aa · synthetic</option>)}
          </select>
          <label className="field" htmlFor="feature-fixture-scenario">Test scenario</label>
          <select id="feature-fixture-scenario" className="input" value={request.scenario}
            onChange={(event) => setRequest((current) => ({ ...current,
              scenario: event.target.value as FeatureTestScenario, revision: current.revision + 1 }))}>
            <option value="mixed">Mixed · six synthetic tracks</option>
            <option value="malformed_fuzdrop_residue">Malformed FuzDrop pDP · isolation test</option>
          </select>
          <button className="button" type="button" onClick={() =>
            setRequest((current) => ({ ...current, revision: current.revision + 1 }))}>
            New analysis / reset state
          </button>
        </div>
      </header>
      {failure ? <p role="alert" className="notice error">The synthetic test fixture could not be prepared.</p>
        : ready && fixture ? <FixtureSession key={fixture.job.job_id} fixture={fixture} />
          : <p role="status">Preparing synthetic test data…</p>}
    </main>
  );
}
