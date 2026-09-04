'use client';

import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, PointerEvent } from 'react';
import type { FeatureRegion, FeatureTrack, FeatureViewerModel } from '../lib/feature-viewer-model.ts';
import type { ViewerRegionSelection } from '../lib/viewer-data.ts';
import { brushDomain, domainLength, panDomain, positionToX, regionPixelBounds, xToPosition, zoomDomain } from '../lib/feature-coordinates.ts';
import type { ResidueDomain } from '../lib/feature-coordinates.ts';
import { drawFeatureCanvas, featureTrackRows, FEATURE_AXIS_HEIGHT, FEATURE_LABEL_WIDTH, hitTestRegion, scaleLabel } from '../lib/feature-plot-renderer.ts';

export interface FeaturePlotProps {
  model: FeatureViewerModel;
  tracks: readonly FeatureTrack[];
  domain: ResidueDomain;
  cursor: number | null;
  selectedResidue: number | null;
  selectedRegion: ViewerRegionSelection | null;
  interactionMode: 'pan' | 'select';
  onHover: (position: number | null) => void;
  onResidueSelect: (position: number) => void;
  onRegionSelect: (region: FeatureRegion) => void;
  onDomainChange: (domain: ResidueDomain) => void;
  compact?: boolean;
}

interface CanvasProps { tracks: readonly FeatureTrack[]; domain: ResidueDomain; width: number; height: number; pixelRatio: number }
const StaticCanvas = memo(function StaticCanvas({ tracks, domain, width, height, pixelRatio }: CanvasProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [themeRevision, setThemeRevision] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setThemeRevision((value) => value + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (canvas.current) drawFeatureCanvas(canvas.current, tracks, domain, width, pixelRatio);
  }, [tracks, domain.start, domain.end, width, pixelRatio, themeRevision, domain]);
  return <canvas ref={canvas} className="feature-static-canvas" data-renderer="canvas-2d" data-static-draw-count="0" aria-hidden="true" style={{ display: 'block', width: '100%', height }} />;
}, (before, after) => before.width === after.width && before.height === after.height && before.pixelRatio === after.pixelRatio
  && before.domain.start === after.domain.start && before.domain.end === after.domain.end
  && before.tracks.length === after.tracks.length && before.tracks.every((track, index) => track === after.tracks[index]));

const TrackLabels = memo(function TrackLabels({ tracks }: { tracks: readonly FeatureTrack[] }) {
  return <div className="feature-plot-labels" aria-label="Feature track labels">
    <div className="feature-track-label feature-axis-label" data-track-id="protein-coordinate" style={{ height: FEATURE_AXIS_HEIGHT }}><strong>Protein coordinate</strong><span>1-based, inclusive</span></div>
    {featureTrackRows(tracks).map((row) => <div className="feature-track-label" data-track-id={row.track.id} data-method={row.track.method} data-semantic-type={row.track.semanticType} key={row.track.id} style={{ height: row.height }}>
      <strong>{row.track.label}</strong><span>{row.track.kind === 'continuous' ? row.track.valueLabel : row.track.method === 'lreca' ? 'Derived hotspots' : row.track.method === 'fuzdrop' ? 'Imported regions' : 'Sequence annotation'}</span>
      {row.track.kind === 'continuous' && <small>{scaleLabel(row.track)}</small>}
    </div>)}
  </div>;
}, (before, after) => before.tracks.length === after.tracks.length && before.tracks.every((track, index) => track === after.tracks[index]));

interface Gesture {
  pointerId: number; startX: number; startY: number; currentX: number; width: number;
  initialDomain: ResidueDomain; mode: 'pan' | 'select'; dragged: boolean;
}
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
const sameDomain = (first: ResidueDomain, second: ResidueDomain) => first.start === second.start && first.end === second.end;

export function FeaturePlot({ model, tracks, domain, cursor, selectedResidue, selectedRegion, interactionMode, onHover, onResidueSelect, onRegionSelect, onDomainChange, compact = false }: FeaturePlotProps) {
  const stage = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const pendingFrame = useRef<number | null>(null);
  const pendingDomain = useRef<ResidueDomain | null>(null);
  const [brush, setBrush] = useState<{ first: number; last: number; context: string } | null>(null);
  const [size, setSize] = useState({ width: 0, pixelRatio: 1 });
  const rows = useMemo(() => featureTrackRows(tracks), [tracks]);
  const height = rows.length ? rows[rows.length - 1].top + rows[rows.length - 1].height : FEATURE_AXIS_HEIGHT;
  const trackIds = tracks.map((track) => track.id).join(' ');
  const gestureContext = `${model.analysisId}/${model.length}/${trackIds}/${size.width}/${compact}`;

  useEffect(() => {
    const target = stage.current;
    if (!target) return;
    let initialFrame: number | null = null;
    const measure = () => {
      const width = target.getBoundingClientRect().width;
      const pixelRatio = window.devicePixelRatio || 1;
      setSize((previous) => previous.width === width && previous.pixelRatio === pixelRatio ? previous : { width, pixelRatio });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(target);
    initialFrame = requestAnimationFrame(measure);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect(); window.removeEventListener('resize', measure);
      if (initialFrame !== null) cancelAnimationFrame(initialFrame);
    };
  }, []);

  useEffect(() => {
    const target = stage.current;
    return () => {
      if (pendingFrame.current !== null) cancelAnimationFrame(pendingFrame.current);
      pendingFrame.current = null; pendingDomain.current = null;
      const active = gesture.current;
      gesture.current = null;
      if (target && active && target.hasPointerCapture(active.pointerId)) target.releasePointerCapture(active.pointerId);
    };
  }, [model.analysisId, model.length, trackIds, size.width, compact]);

  function queueDomain(next: ResidueDomain) {
    pendingDomain.current = next;
    if (pendingFrame.current !== null) return;
    pendingFrame.current = requestAnimationFrame(() => {
      pendingFrame.current = null;
      const value = pendingDomain.current; pendingDomain.current = null;
      if (stage.current && value && !sameDomain(value, domain)) onDomainChange(value);
    });
  }

  function flushDomain(next?: ResidueDomain) {
    if (pendingFrame.current !== null) cancelAnimationFrame(pendingFrame.current);
    pendingFrame.current = null;
    const value = next ?? pendingDomain.current;
    pendingDomain.current = null;
    if (value && !sameDomain(value, domain)) onDomainChange(value);
  }

  // A non-passive native wheel listener can consume zoom without scrolling the page.
  useEffect(() => {
    const target = stage.current;
    if (!target || size.width <= 0 || model.length < 1 || compact) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      if (gesture.current) return;
      const rect = target.getBoundingClientRect();
      const x = clamp((event.clientX - rect.left) / rect.width * size.width, 0, size.width);
      const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1;
      const active = pendingDomain.current ?? domain;
      let next: ResidueDomain;
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) next = panDomain(active, model.length, event.deltaX * scale / size.width * domainLength(active));
      else {
        const delta = event.deltaY * scale;
        if (!delta) return;
        const anchor = active.start - 0.5 + x / size.width * domainLength(active);
        next = zoomDomain(active, model.length, Math.exp(clamp(delta * 0.002, -1, 1)), anchor);
      }
      pendingDomain.current = next;
      if (pendingFrame.current === null) pendingFrame.current = requestAnimationFrame(() => {
        pendingFrame.current = null;
        const value = pendingDomain.current; pendingDomain.current = null;
        if (stage.current && value && !sameDomain(value, domain)) onDomainChange(value);
      });
    };
    target.addEventListener('wheel', wheel, { passive: false });
    return () => target.removeEventListener('wheel', wheel);
  }, [domain, height, model.length, onDomainChange, size.width, compact]);

  function pointerCoordinates(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / rect.width * size.width, y: (event.clientY - rect.top) / rect.height * height };
  }

  function hoverAt(x: number, y: number) {
    if (size.width <= 0) return;
    const hit = hitTestRegion(rows, domain, size.width, x, y);
    const position = xToPosition(x, domain, size.width);
    // A minimum-width terminal bar still reports its original terminal residue.
    onHover(hit ? clamp(position, hit.start, hit.end) : position);
  }

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.button !== 0 || gesture.current || size.width <= 0) return;
    event.preventDefault();
    const initialDomain = pendingDomain.current ?? domain;
    flushDomain();
    const { x, y } = pointerCoordinates(event);
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { pointerId: event.pointerId, startX: x, startY: y, currentX: x, width: size.width, initialDomain, mode: interactionMode, dragged: false };
    hoverAt(x, y);
  }

  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    const { x, y } = pointerCoordinates(event);
    const active = gesture.current;
    if (!active) { hoverAt(x, y); return; }
    if (active.pointerId !== event.pointerId) return;
    event.preventDefault(); active.currentX = x;
    if (Math.hypot(x - active.startX, y - active.startY) >= 4) active.dragged = true;
    if (!active.dragged) return;
    if (compact) { hoverAt(x, y); return; }
    if (active.mode === 'select') {
      setBrush({ first: clamp(active.startX, 0, size.width), last: clamp(x, 0, size.width), context: gestureContext });
      onHover(xToPosition(x, active.initialDomain, active.width));
    } else {
      const next = panDomain(active.initialDomain, model.length, -(x - active.startX) / active.width * domainLength(active.initialDomain));
      queueDomain(next);
      onHover(xToPosition(x, next, active.width));
    }
  }

  function pointerUp(event: PointerEvent<HTMLDivElement>) {
    const active = gesture.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const { x, y } = pointerCoordinates(event);
    gesture.current = null; setBrush(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (active.dragged) {
      if (compact) return;
      flushDomain(active.mode === 'select' ? brushDomain(active.startX, x, active.initialDomain, active.width)
        : panDomain(active.initialDomain, model.length, -(x - active.startX) / active.width * domainLength(active.initialDomain)));
      return;
    }
    const region = hitTestRegion(rows, domain, size.width, x, y);
    if (region) onRegionSelect(region);
    else onResidueSelect(xToPosition(x, domain, size.width));
  }

  function cancelGesture(event?: PointerEvent<HTMLDivElement>) {
    const active = gesture.current;
    if (event && active && event.pointerId !== active.pointerId) return;
    gesture.current = null; setBrush(null);
    if (pendingFrame.current !== null) cancelAnimationFrame(pendingFrame.current);
    pendingFrame.current = null; pendingDomain.current = null;
    if (active && stage.current?.hasPointerCapture(active.pointerId)) stage.current.releasePointerCapture(active.pointerId);
  }

  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    let position: number;
    const current = cursor ?? selectedResidue ?? domain.start;
    if (event.key === 'ArrowLeft') position = Math.max(1, current - 1);
    else if (event.key === 'ArrowRight') position = Math.min(model.length, current + 1);
    else if (event.key === 'Home') position = domain.start;
    else if (event.key === 'End') position = domain.end;
    else if (event.key === 'Enter') { event.preventDefault(); onResidueSelect(current); return; }
    else if (event.key === 'Escape') { event.preventDefault(); cancelGesture(); onHover(null); return; }
    else return;
    event.preventDefault(); onHover(position);
    if (position < domain.start) onDomainChange(panDomain(domain, model.length, position - domain.start));
    else if (position > domain.end) onDomainChange(panDomain(domain, model.length, position - domain.end));
  }

  const marker = (position: number | null): CSSProperties | undefined => position !== null && position >= domain.start && position <= domain.end && size.width > 0
    ? { position: 'absolute', left: positionToX(position, domain, size.width), top: FEATURE_AXIS_HEIGHT - 7, bottom: 0, width: 0, pointerEvents: 'none' } : undefined;
  const cursorStyle = marker(cursor);
  const selectedStyle = marker(selectedResidue);
  const selectedRow = selectedRegion ? rows.find((row) => row.track.kind === 'region' && row.track.method === selectedRegion.method && row.track.semanticType === selectedRegion.semanticType) : undefined;
  const selectedPixels = selectedRegion && selectedRow ? regionPixelBounds(selectedRegion, domain, size.width) : null;

  return <div className={`feature-plot${compact ? ' is-compact' : ''}`} data-domain-start={domain.start} data-domain-end={domain.end} data-track-ids={trackIds}
    style={{ display: 'grid', gridTemplateColumns: `${FEATURE_LABEL_WIDTH}px minmax(0, 1fr)`, width: '100%' }}>
    <TrackLabels tracks={tracks} />
    <div ref={stage} className="feature-plot-stage" role="application" aria-roledescription="interactive protein feature plot" tabIndex={0}
      aria-label={`Protein feature plot, residues ${domain.start} to ${domain.end}. Use arrow keys to move the cursor and Enter to select.${compact ? '' : ` Drag to ${interactionMode === 'pan' ? 'pan' : 'select a zoom range'}.`}`}
      data-domain-start={domain.start} data-domain-end={domain.end} data-coordinate-system="one_based_inclusive" data-interaction-mode={compact ? 'inspect' : interactionMode}
      style={{ position: 'relative', minWidth: 0, height, padding: 0, border: 0, touchAction: compact ? 'pan-y' : 'none', userSelect: 'none', overflow: 'hidden' }}
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture}
      onLostPointerCapture={cancelGesture} onPointerLeave={() => { if (!gesture.current) onHover(null); }} onKeyDown={keyDown}>
      <StaticCanvas tracks={tracks} domain={domain} width={size.width} height={height} pixelRatio={size.pixelRatio} />
      <div className="feature-overlay" aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
        {selectedPixels && selectedRow && <div className="feature-region-selection" data-selected-region-start={selectedRegion?.start} data-selected-region-end={selectedRegion?.end} style={{ position: 'absolute', left: selectedPixels.left, width: selectedPixels.width, top: selectedRow.top + 4, height: selectedRow.height - 8, border: '2px solid var(--feature-selection)', background: 'transparent' }} />}
        {selectedStyle && <div className="feature-selected-line" data-selected-residue={selectedResidue} style={{ ...selectedStyle, borderLeft: '2px solid var(--feature-selection)' }} />}
        {cursorStyle && <div className="feature-cursor-line" data-cursor-position={cursor} style={{ ...cursorStyle, borderLeft: '1px dashed var(--feature-cursor)' }} />}
        {brush?.context === gestureContext && <div className="feature-brush-selection" style={{ position: 'absolute', left: Math.min(brush.first, brush.last), width: Math.abs(brush.last - brush.first), top: FEATURE_AXIS_HEIGHT - 7, bottom: 0, border: '1px solid var(--feature-selection)', background: 'var(--feature-selection)', opacity: 0.2 }} />}
      </div>
    </div>
  </div>;
}
