'use client';

import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, FormEvent, KeyboardEvent, PointerEvent } from 'react';
import {
  displayIntensity, extractSelectedRegionSequence, getSequenceTooltip, residueCopyLabel,
} from '../lib/sequence-viewer-model.ts';
import type { ColorMode, SequenceResidue, SequenceViewerModel } from '../lib/sequence-viewer-model.ts';
import type { ViewerFocusRequest, ViewerRegionSelection } from '../lib/viewer-data.ts';
import {
  buildSequenceRows, navigateSequencePosition, parsePositionQuery, rowStartForPosition, SEQUENCE_RESIDUES_PER_ROW, writeCopyText,
} from '../lib/sequence-viewer-layout.ts';
import type { SequenceRow } from '../lib/sequence-viewer-layout.ts';

export interface SequencePerformanceSample {
  kind: 'initial_render' | 'hover' | 'selection' | 'color';
  durationMs: number;
}

export interface ProteinSequenceViewerProps {
  model: SequenceViewerModel;
  selectedResidue: number | null;
  selectedRegion: ViewerRegionSelection | null;
  focusRequest?: ViewerFocusRequest | null;
  active?: boolean;
  onResidueSelect: (position: number) => void;
  onRegionSelect: (region: ViewerRegionSelection) => void;
  onSelectionClear: () => void;
  onViewInFeature?: () => void;
  writeClipboard?: (text: string) => Promise<void>;
  onPerformance?: (sample: SequencePerformanceSample) => void;
}

const labels: Record<string, string> = {
  'lreca-attribution': 'LRECA attribution', 'lreca-kde': 'KDE contribution density',
  'lreca-critical': 'LRECA critical region', 'fuzdrop-propensity': 'FuzDrop propensity (pDP)',
  'fuzdrop-regions': 'FuzDrop region', 'seg-regions': 'LCR — SEG', 'dismeta-regions': 'IDR — DisMeta',
};
const colorStatusLabel: Record<SequenceViewerModel['colorModes'][number]['status'], string> = {
  success: 'Available', empty: 'No regions', not_provided: 'N/A', not_imported: 'Not imported',
  unavailable: 'Unavailable', pending: 'Pending', failed: 'Failed', not_selected: 'Not run',
  invalid: 'Invalid output',
};

function numeric(value: number): string {
  return value !== 0 && Math.abs(value) < 0.001 ? value.toExponential(3) : value.toFixed(3);
}

export function ProteinSequenceViewer(props: ProteinSequenceViewerProps) {
  if (!props.model.sequence || props.model.length < 1) return <section className="panel sequence-viewer" aria-label="Protein Sequence Viewer">
    <div className="panel-header"><div><p className="eyebrow">RESIDUE EXPLORATION</p><h2>Protein Sequence Viewer</h2></div><span className="badge">Awaiting analysis</span></div>
    <p className="muted">Run an analysis to inspect the submitted amino-acid sequence and its available residue evidence.</p>
    {props.model.issues.map((issue, index) => <p className="notice" key={index}>{issue.message}</p>)}
    <p className="muted small">DisMeta integration is currently unavailable.</p>
  </section>;
  return <SequenceViewerSession
    key={`${props.model.analysisId ?? 'unidentified'}:${props.model.length}:${props.model.defaultColorMode}`}
    {...props}
  />;
}

function SequenceViewerSession({ model, selectedResidue, selectedRegion, focusRequest, active = true,
  onResidueSelect, onRegionSelect, onSelectionClear, onViewInFeature, writeClipboard, onPerformance }: ProteinSequenceViewerProps) {
  const sequence = model.sequence!;
  const [colorMode, setColorMode] = useState<ColorMode>(model.defaultColorMode);
  const [hovered, setHovered] = useState<number | null>(null);
  const [keyboardPosition, setKeyboardPosition] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [queryError, setQueryError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [mountStarted] = useState(() => performance.now());
  const areaRef = useRef<HTMLDivElement | null>(null);
  const performanceCallback = useRef(onPerformance);
  const hoveredRef = useRef<number | null>(null);
  const measurements = useRef<{ kind: SequencePerformanceSample['kind']; started: number }[]>([]);
  const initialReported = useRef(false);
  const id = useId();
  const rows = useMemo(() => buildSequenceRows(sequence), [sequence]);
  const validSelectedResidue = selectedResidue !== null && Number.isSafeInteger(selectedResidue) && selectedResidue >= 1 && selectedResidue <= model.length ? selectedResidue : null;
  const selectedRegionSequence = useMemo(() => selectedRegion ? extractSelectedRegionSequence(model, selectedRegion) : null, [model, selectedRegion]);
  const region = useMemo(() => selectedRegionSequence !== null && selectedRegion ? model.regions.find((item) => selectedRegion.id ? item.id === selectedRegion.id
    : item.method === selectedRegion.method && item.start === selectedRegion.start && item.end === selectedRegion.end
      && (!selectedRegion.type || item.type === selectedRegion.type)) ?? null : null, [model.regions, selectedRegion, selectedRegionSequence]);
  const currentColor = model.colorModes.find((option) => option.id === colorMode && option.available);
  const resolvedColor = currentColor ? colorMode : 'none';
  const inspected = hovered ?? validSelectedResidue ?? region?.start ?? null;
  const tooltip = inspected === null ? null : getSequenceTooltip(model, inspected);
  const selectedLabel = validSelectedResidue === null ? null : residueCopyLabel(model, validSelectedResidue);
  const focusKey = focusRequest ? `${focusRequest.requestId}:${focusRequest.start}:${focusRequest.end}` : '';
  const selectionKey = validSelectedResidue !== null ? `residue:${validSelectedResidue}`
    : region ? `region:${region.id}:${region.start}:${region.end}` : '';
  const [observedSelection, setObservedSelection] = useState(selectionKey);

  if (selectionKey !== observedSelection) {
    setObservedSelection(selectionKey);
    setHovered(null);
    setKeyboardPosition(validSelectedResidue ?? region?.start ?? null);
  }

  useEffect(() => { performanceCallback.current = onPerformance; }, [onPerformance]);
  useEffect(() => { hoveredRef.current = null; }, [selectionKey]);
  const measure = useCallback((kind: SequencePerformanceSample['kind']) => {
    if (performanceCallback.current) measurements.current.push({ kind, started: performance.now() });
  }, []);
  useLayoutEffect(() => {
    if (!performanceCallback.current) return;
    if (!initialReported.current) {
      initialReported.current = true;
      performanceCallback.current({ kind: 'initial_render', durationMs: performance.now() - mountStarted });
    }
    for (const item of measurements.current.splice(0)) performanceCallback.current({ kind: item.kind, durationMs: performance.now() - item.started });
  });

  const scrollToPosition = useCallback((position: number) => {
    if (!active || !Number.isSafeInteger(position) || position < 1 || position > model.length) return;
    const rowStart = rowStartForPosition(position, model.length);
    areaRef.current?.querySelector<HTMLElement>(`[data-sequence-row-start="${rowStart}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [active, model.length]);
  useEffect(() => {
    if (!active) return;
    const position = validSelectedResidue ?? region?.start ?? focusRequest?.start;
    if (position !== undefined && position !== null) scrollToPosition(position);
  }, [active, focusKey, focusRequest?.start, validSelectedResidue, region?.start, scrollToPosition]);

  const hover = useCallback((position: number | null) => {
    if (position === hoveredRef.current) return;
    hoveredRef.current = position;
    if (position !== null) measure('hover');
    setHovered(position);
  }, [measure]);
  const selectResidue = useCallback((position: number) => {
    measure('selection'); hoveredRef.current = null; setKeyboardPosition(position); onResidueSelect(position);
  }, [measure, onResidueSelect]);
  const selectRegion = (regionId: string) => {
    const next = model.regions.find((item) => item.id === regionId);
    if (!next) return;
    measure('selection'); hoveredRef.current = null; setHovered(null); setKeyboardPosition(next.start); onRegionSelect(next); scrollToPosition(next.start);
  };

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    const current = validSelectedResidue ?? keyboardPosition ?? region?.start ?? 1;
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = navigateSequencePosition(current, event.key as Parameters<typeof navigateSequencePosition>[1], model.length);
      hoveredRef.current = null; setHovered(null); selectResidue(next); scrollToPosition(next);
    } else if (event.key === 'Enter') {
      event.preventDefault(); hoveredRef.current = null; setHovered(null); selectResidue(current);
    } else if (event.key === 'Escape') {
      event.preventDefault(); hoveredRef.current = null; setHovered(null); setKeyboardPosition(null); onSelectionClear();
    }
  }

  function goToPosition(event: FormEvent) {
    event.preventDefault();
    const parsed = parsePositionQuery(query, sequence);
    if (parsed.position === null) {
      setQueryError(parsed.error === 'residue_mismatch' ? 'The amino-acid letter does not match this sequence position.'
        : `Enter a position from 1 to ${model.length}, or a matching residue label such as Y243.`);
      return;
    }
    setQueryError(null); hoveredRef.current = null; setHovered(null); selectResidue(parsed.position); scrollToPosition(parsed.position); areaRef.current?.focus({ preventScroll: true });
  }

  async function copy(text: string | null, description: string) {
    if (text === null) return;
    const copied = await writeCopyText(text, writeClipboard ?? (async (value) => {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(value);
      }));
    setCopyStatus(copied ? `${description} copied.` : 'Copy failed. Clipboard access is unavailable or was denied.');
  }

  return <section className="panel sequence-viewer" aria-label="Protein Sequence Viewer" data-analysis-id={model.analysisId ?? ''}
    data-sequence-length={model.length} data-residues-per-row={SEQUENCE_RESIDUES_PER_ROW} data-row-count={rows.length}
    data-color-mode={resolvedColor} data-selected-residue={validSelectedResidue ?? ''} data-selected-region={region ? `${region.start}-${region.end}` : ''}>
    <div className="panel-header"><div><p className="eyebrow">RESIDUE EXPLORATION</p><h2>Protein Sequence Viewer</h2></div><span className="badge">{model.length.toLocaleString()} residues</span></div>
    <p className="muted small">Actual amino-acid letters · 1-based inclusive coordinates · 50 residues per row</p>
    {model.issues.length > 0 && <ul className="notice sequence-issues" aria-label="Sequence data validation issues">{model.issues.map((issue, index) => <li key={index}>{issue.message}</li>)}</ul>}
    <div className="sequence-toolbar" role="group" aria-label="Sequence viewer controls">
      <label htmlFor={`${id}-color`}>Color by<select id={`${id}-color`} className="input" value={resolvedColor} onChange={(event) => {
        const option = model.colorModes.find((item) => item.id === event.target.value && item.available);
        if (option) { measure('color'); setColorMode(option.id); }
      }}>{model.colorModes.map((option) => <option key={option.id} value={option.id} disabled={!option.available} title={option.unavailableReason ?? option.help}>
        {option.label}{option.available ? '' : ` — ${colorStatusLabel[option.status]}`}
      </option>)}</select></label>
      <form className="sequence-position-form" onSubmit={goToPosition} noValidate><label htmlFor={`${id}-find`}>Find position / residue</label>
        <input id={`${id}-find`} className="input" type="text" autoComplete="off" spellCheck={false} placeholder="243 or Y243" value={query} onChange={(event) => { setQuery(event.target.value); setQueryError(null); }} />
        <button className="button" type="submit">Go</button></form>
      <label htmlFor={`${id}-region`}>Jump to region<select id={`${id}-region`} className="input" value={region?.id ?? ''} disabled={!model.regions.length} onChange={(event) => selectRegion(event.target.value)}>
        <option value="">{model.regions.length ? 'Choose a native region' : 'No regions available'}</option>
        {model.regions.map((item) => <option key={item.id} value={item.id}>{item.method.toUpperCase()} · {item.isPrimary ? 'Primary hotspot' : item.label} {item.start}–{item.end}</option>)}
      </select></label>
    </div>
    {queryError && <p className="validation-message invalid" role="alert">{queryError}</p>}
    <SequenceLegend mode={resolvedColor} />
    <p className="muted small sequence-color-help">{currentColor?.help ?? 'No residue coloring.'}</p>
    <p className="sequence-keyboard-help muted small" id={`${id}-keys`}>Focus the sequence and use ← → for one residue, ↑ ↓ for 50, Home / End for the row, and Enter to select. Hover or click a letter to inspect it.</p>

    <div ref={areaRef} className="sequence-grid-scroll" role="group" tabIndex={0} aria-label={`Protein sequence viewer, ${model.length} residues`}
      aria-describedby={`${id}-keys ${id}-selection`} onKeyDown={handleKey} data-sequence-area="true">
      <SequenceGrid rows={rows} residues={model.residues} colorMode={resolvedColor} selectedResidue={validSelectedResidue}
        selectedStart={region?.start ?? null} selectedEnd={region?.end ?? null} onHover={hover} onSelect={selectResidue} />
    </div>

    <div className="sequence-actions">
      <button className="button" type="button" onClick={() => { void copy(sequence, 'Full sequence'); }}>Copy Full Sequence</button>
      <button className="button" type="button" disabled={selectedRegionSequence === null} onClick={() => { void copy(selectedRegionSequence, 'Selected region'); }}>Copy Selected Region</button>
      <button className="button" type="button" disabled={selectedLabel === null} onClick={() => { void copy(selectedLabel, 'Residue label'); }}>Copy Residue Label</button>
      <button className="text-button" type="button" disabled={validSelectedResidue === null && !region} onClick={() => { hoveredRef.current = null; setHovered(null); setKeyboardPosition(null); onSelectionClear(); }}>Clear selection</button>
    </div>
    <p className="sequence-copy-status small" role="status" aria-live="polite">{copyStatus ?? ''}</p>
    <p className="sequence-selection-status" id={`${id}-selection`} role="status" aria-live="polite">{selectedLabel ? `Selected residue: ${selectedLabel}.`
      : region ? `Selected ${region.method.toUpperCase()} region: ${region.start}–${region.end}, ${region.length} residues.` : 'No fixed selection.'}</p>

    <section className="sequence-inspector" aria-label="Residue details" data-inspected-position={tooltip?.position ?? ''}>
      <div className="sequence-inspector-heading"><div><p className="eyebrow">RESIDUE DETAILS</p><h3>{tooltip ? `${tooltip.aa}${tooltip.position}` : 'Inspect a residue'}</h3></div>
        {onViewInFeature && <button className="button" type="button" disabled={validSelectedResidue === null && !region} onClick={onViewInFeature}>View in Feature Viewer</button>}</div>
      {tooltip ? <dl className="sequence-detail-grid"><div><dt>Position</dt><dd>{tooltip.position}</dd></div><div><dt>Amino acid</dt><dd>{tooltip.aa}</dd></div>
        {tooltip.rows.map((row) => <div key={row.id} data-sequence-detail={row.id} data-value-status={row.status}><dt>{labels[row.id] ?? row.label}</dt>
          <dd title={row.value === null ? undefined : String(row.value)}>{row.value === null ? row.text ?? 'N/A' : numeric(row.value)}
            {row.regions.length > 0 && <span className="sequence-membership">{row.regions.map((item) => `${item.isPrimary ? 'Primary hotspot' : item.label} ${item.start}–${item.end}`).join('; ')}</span>}</dd></div>)}</dl>
        : <p className="muted">Hover a letter, click a residue, or use the position control to inspect its available evidence.</p>}
    </section>
    {region && <section className="sequence-region-details" aria-label="Selected region details"><div className="sequence-inspector-heading"><h3>{region.isPrimary ? 'Primary hotspot' : region.label}</h3>
      {onViewInFeature && <button className="button" type="button" onClick={onViewInFeature}>View in Feature Viewer</button>}</div>
      <dl className="sequence-detail-grid"><div><dt>Method</dt><dd>{region.method.toUpperCase()}</dd></div><div><dt>Region type</dt><dd>{region.label}</dd></div>
        <div><dt>Start</dt><dd>{region.start}</dd></div><div><dt>End</dt><dd>{region.end}</dd></div><div><dt>Length</dt><dd>{region.length} aa</dd></div></dl>
      <details className="sequence-region-text" open><summary>Selected region sequence · {region.length} aa</summary>
        <span className="sr-only">The selected sequence is shown visually and can be copied with Copy Selected Region.</span>
        <code aria-hidden="true">{selectedRegionSequence}</code></details>
    </section>}
    <p className="muted small">Attribution, contribution density, propensity and region membership remain distinct. DisMeta integration is currently unavailable; this does not mean the protein has no IDR.</p>
  </section>;
}

interface GridProps {
  rows: SequenceRow[]; residues: SequenceResidue[]; colorMode: ColorMode;
  selectedResidue: number | null; selectedStart: number | null; selectedEnd: number | null;
  onHover: (position: number | null) => void; onSelect: (position: number) => void;
}
const SequenceGrid = memo(function SequenceGrid({ rows, residues, colorMode, selectedResidue, selectedStart, selectedEnd, onHover, onSelect }: GridProps) {
  function eventPosition(target: EventTarget | null): number | null {
    if (!(target instanceof Element)) return null;
    const value = Number(target.closest<HTMLElement>('[data-residue-position]')?.dataset.residuePosition);
    return Number.isSafeInteger(value) && value >= 1 && value <= residues.length ? value : null;
  }
  function move(event: PointerEvent<HTMLDivElement>) { onHover(eventPosition(event.target)); }
  return <div className="sequence-grid" aria-hidden="true" onPointerMove={move} onPointerLeave={() => onHover(null)} onClick={(event) => {
    const position = eventPosition(event.target); if (position !== null) onSelect(position);
  }}>{rows.map((row) => <SequenceRowView key={row.start} row={row} residues={residues} colorMode={colorMode}
    selectedResidue={selectedResidue !== null && selectedResidue >= row.start && selectedResidue <= row.end ? selectedResidue : null}
    selectedStart={selectedStart !== null && selectedEnd !== null && selectedStart <= row.end && selectedEnd >= row.start ? Math.max(row.start, selectedStart) : null}
    selectedEnd={selectedStart !== null && selectedEnd !== null && selectedStart <= row.end && selectedEnd >= row.start ? Math.min(row.end, selectedEnd) : null} />)}</div>;
});

const SequenceRowView = memo(function SequenceRowView({ row, residues, colorMode, selectedResidue, selectedStart, selectedEnd }: {
  row: SequenceRow; residues: SequenceResidue[]; colorMode: ColorMode; selectedResidue: number | null; selectedStart: number | null; selectedEnd: number | null;
}) {
  return <div className="sequence-row" data-sequence-row-start={row.start} data-sequence-row-end={row.end}>
    <span className="sequence-row-start">{row.start}</span>
    <div className="sequence-row-content"><div className="sequence-row-ticks">{row.ticks.map((position) => <span key={position} style={{ gridColumn: position - row.start + 1 }}>{position}</span>)}</div>
      <div className="sequence-row-residues">{row.residues.map(({ position, aa }) => {
        const residue = residues[position - 1];
        const intensity = colorMode === 'lreca-attribution' ? displayIntensity(residue?.lrecaAttribution)
          : colorMode === 'fuzdrop-propensity' ? displayIntensity(residue?.fuzdropPropensity) : null;
        const membership = colorMode === 'lreca-critical' ? residue?.lrecaCriticalMembership
          : colorMode === 'fuzdrop-regions' ? residue?.fuzdropRegionMembership : colorMode === 'seg-regions' ? residue?.segMembership : undefined;
        return <span key={position} className="sequence-residue" data-residue-position={position} data-aa={aa} data-color-mode={colorMode}
          data-membership={membership} data-has-value={intensity !== null ? 'true' : undefined}
          data-selected={position === selectedResidue ? 'true' : undefined}
          data-in-selected-region={selectedStart !== null && selectedEnd !== null && position >= selectedStart && position <= selectedEnd ? 'true' : undefined}
          style={intensity !== null ? { '--sequence-intensity': intensity } as CSSProperties : undefined}>{aa}</span>;
      })}</div></div>
  </div>;
});

function SequenceLegend({ mode }: { mode: ColorMode }) {
  if (mode === 'none') return null;
  if (mode === 'lreca-attribution' || mode === 'fuzdrop-propensity') return <div className="sequence-legend" data-color-mode={mode} aria-label="Color legend">
    <span>{mode === 'lreca-attribution' ? 'Low attribution' : 'Low propensity'}</span><i className="sequence-gradient-key" aria-hidden="true" /><span>{mode === 'lreca-attribution' ? 'High attribution' : 'High propensity'}</span><span className="muted small">0–1 · original values</span>
  </div>;
  if (mode === 'lreca-critical') return <div className="sequence-legend" data-color-mode={mode} aria-label="Color legend"><span><i className="sequence-primary-key" aria-hidden="true" />Primary hotspot</span><span><i className="sequence-candidate-key" aria-hidden="true" />Candidate hotspot</span></div>;
  return <div className="sequence-legend" data-color-mode={mode} aria-label="Color legend"><i className="sequence-region-key" aria-hidden="true" /><span>{mode === 'seg-regions' ? 'Low-complexity region (LCR)' : 'Imported FuzDrop region'}</span></div>;
}
