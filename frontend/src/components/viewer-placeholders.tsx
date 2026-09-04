'use client';

import type { ViewerData, ViewerFocusRequest, ViewerRegionSelection, ViewerTrack } from '../lib/viewer-data.ts';

export interface ProteinFeatureViewerProps extends ViewerData {
  selectedResidue?: number | null;
  selectedRegion?: ViewerRegionSelection | null;
  focusRequest?: ViewerFocusRequest | null;
  onResidueSelect?: (position: number) => void;
  onRegionSelect?: (region: ViewerRegionSelection) => void;
  onFocusChange?: (focus: ViewerFocusRequest | null) => void;
}

export interface ProteinSequenceViewerProps {
  sequence: string | null;
  selectedResidue: number | null;
  selectedRegion: ViewerRegionSelection | null;
  tracks: ViewerTrack[];
  annotations: Pick<ViewerData, 'lrecaCriticalRegions' | 'fuzdropRegions' | 'segRegions'>;
  focusRequest: ViewerFocusRequest | null;
  onResidueSelect: (position: number) => void;
  onRegionSelect: (region: ViewerRegionSelection) => void;
  onFocusChange?: (focus: ViewerFocusRequest | null) => void;
}

export function ProteinFeatureViewerPlaceholder(props: ProteinFeatureViewerProps) {
  const available = props.tracks.filter((track) => track.available);
  return (
    <section className="panel viewer-placeholder" aria-label="Protein Feature Viewer">
      <div className="panel-header">
        <div><p className="eyebrow">SEQUENCE FEATURES</p><h2>Protein Feature Viewer</h2></div>
        <span className="badge" data-tone="neutral">Preview</span>
      </div>
      <p className="muted">Interactive tracks will be available in a later release.</p>
      <p>{available.length ? `${available.length} data tracks are available in this result. Explore their values in the method tabs and tables.` : 'Run an analysis to make feature data available here.'}</p>
      <ul className="viewer-track-list">
        {props.tracks.map((track) => (
          <li key={track.id}>
            <span className="track-label" data-tone={track.available ? track.method : 'neutral'}>{track.label}</span>
            <span className="muted">{track.available ? `${track.count} ${track.kind === 'region' ? 'regions' : 'values'}` : 'Not available'}</span>
          </li>
        ))}
      </ul>
      <p className="muted small">Residue attribution, residue propensity, KDE density, and region annotations remain separate.</p>
    </section>
  );
}

export function ProteinSequenceViewerPlaceholder(props: ProteinSequenceViewerProps) {
  return (
    <section className="panel viewer-placeholder" aria-label="Protein Sequence Viewer">
      <div className="panel-header">
        <div><p className="eyebrow">RESIDUE DETAIL</p><h2>Protein Sequence Viewer</h2></div>
        <span className="badge" data-tone="neutral">Preview</span>
      </div>
      <p className="muted">Interactive tracks will be available in a later release.</p>
      {props.sequence ? (
        <>
          <p>The submitted sequence is available: <strong>{props.sequence.length.toLocaleString()} residues</strong>.</p>
          <p className="sequence-preview" aria-label="Beginning of the submitted sequence">{props.sequence.slice(0, 80)}{props.sequence.length > 80 ? '…' : ''}</p>
          <p className="muted small">Positions use 1-based inclusive coordinates.</p>
        </>
      ) : <p>Submit a sequence to prepare the sequence view.</p>}
      {props.selectedResidue !== null && <p className="notice" role="status">Selected residue: {props.selectedResidue}</p>}
      {props.selectedRegion && <p className="notice" role="status">Selected {props.selectedRegion.method.toUpperCase()} region: {props.selectedRegion.start}–{props.selectedRegion.end}</p>}
    </section>
  );
}
