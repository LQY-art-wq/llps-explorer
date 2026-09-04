/** Canvas-only presentation helpers. No scientific values or native regions are changed. */
import type { ContinuousFeatureTrack, FeatureRegion, FeatureTrack, RegionFeatureTrack } from './feature-viewer-model.ts';
import { coordinateTicks, domainLength, positionToX, regionPixelBounds } from './feature-coordinates.ts';
import type { PixelBounds, ResidueDomain } from './feature-coordinates.ts';

export const FEATURE_LABEL_WIDTH = 176;
export const FEATURE_AXIS_HEIGHT = 38;
export const FEATURE_CONTINUOUS_HEIGHT = 96;
export const FEATURE_REGION_HEIGHT = 50;

export interface FeatureTrackRow { track: FeatureTrack; top: number; height: number }
export interface PaintedRegion extends PixelBounds { region: FeatureRegion; top: number; height: number }

export function featureTrackRows(tracks: readonly FeatureTrack[]): FeatureTrackRow[] {
  let top = FEATURE_AXIS_HEIGHT;
  return tracks.map((track) => {
    const height = track.kind === 'continuous' ? FEATURE_CONTINUOUS_HEIGHT : FEATURE_REGION_HEIGHT;
    const row = { track, top, height };
    top += height;
    return row;
  });
}

/** A visual y-axis scale only; values remain untouched, including signed KDE values. */
export function continuousScale(track: ContinuousFeatureTrack): readonly [number, number] {
  if (track.valueDomain) return track.valueDomain;
  let low = 0;
  let high = 0;
  for (const value of track.values) {
    if (value !== null && Number.isFinite(value)) { low = Math.min(low, value); high = Math.max(high, value); }
  }
  return low === high ? [low, low + 1] : [low, high];
}

/** Compact lanes preserve each source region and duplicate; crowded lanes may overlap. */
export function paintedRegions(track: RegionFeatureTrack, domain: ResidueDomain, width: number, top: number): PaintedRegion[] {
  const laneEnds = [-Infinity, -Infinity, -Infinity];
  const rows: PaintedRegion[] = [];
  track.regions.forEach((region, index) => {
    const pixels = regionPixelBounds(region, domain, width);
    if (!pixels) return;
    const free = laneEnds.findIndex((end) => end < region.start);
    const lane = free === -1 ? index % laneEnds.length : free;
    laneEnds[lane] = Math.max(laneEnds[lane], region.end);
    rows.push({ ...pixels, region, top: top + 9 + lane * 11, height: 8 });
  });
  // Primary is a backend flag. Paint its existing region last for a clear outline.
  return [...rows.filter((row) => !row.region.isPrimary), ...rows.filter((row) => row.region.isPrimary)];
}

export function hitTestRegion(rows: readonly FeatureTrackRow[], domain: ResidueDomain, width: number, x: number, y: number): FeatureRegion | null {
  const row = rows.find((item) => item.track.kind === 'region' && y >= item.top && y <= item.top + item.height);
  if (!row || row.track.kind !== 'region') return null;
  const regions = paintedRegions(row.track, domain, width, row.top);
  for (let index = regions.length - 1; index >= 0; index--) {
    const region = regions[index];
    if (x >= region.left && x <= region.right && y >= region.top - 2 && y <= region.top + region.height + 2) return region.region;
  }
  return null;
}

function valueLabel(value: number): string {
  return Number(value.toPrecision(3)).toString();
}

export function scaleLabel(track: ContinuousFeatureTrack): string {
  const [low, high] = continuousScale(track);
  return `${valueLabel(low)} – ${valueLabel(high)}`;
}

interface Palette { background: string; subtle: string; border: string; text: string; muted: string; lreca: string; kde: string; fuzdrop: string; seg: string; fontFamily: string }

function palette(canvas: HTMLCanvasElement): Palette {
  const styles = getComputedStyle(canvas);
  const color = (name: string, fallback = '--text') => styles.getPropertyValue(name).trim() || styles.getPropertyValue(fallback).trim() || styles.color;
  return {
    background: color('--surface'), subtle: color('--surface-subtle'), border: color('--border'),
    text: color('--text'), muted: color('--muted'), lreca: color('--feature-lreca', '--blue'),
    kde: color('--feature-kde', '--blue'), fuzdrop: color('--feature-fuzdrop', '--color-fuzdrop'),
    seg: color('--feature-seg', '--color-seg'), fontFamily: styles.fontFamily,
  };
}

function drawContinuous(context: CanvasRenderingContext2D, track: ContinuousFeatureTrack, row: FeatureTrackRow, domain: ResidueDomain, width: number, color: string, colors: Palette) {
  const [low, high] = continuousScale(track);
  const plotTop = row.top + 12;
  const plotBottom = row.top + row.height - 13;
  const y = (value: number) => plotBottom - (value - low) / (high - low || 1) * (plotBottom - plotTop);
  context.save();
  context.beginPath(); context.rect(0, row.top + 1, width, row.height - 2); context.clip();
  context.strokeStyle = colors.border;
  context.lineWidth = 0.7;
  for (const fraction of [0, 0.5, 1]) {
    const horizontal = plotTop + fraction * (plotBottom - plotTop);
    context.beginPath(); context.moveTo(0, horizontal); context.lineTo(width, horizontal); context.stroke();
  }
  const firstIndex = Math.max(0, domain.start - 2);
  const lastIndex = Math.min(track.values.length - 1, domain.end);
  const baseline = y(Math.min(high, Math.max(low, 0)));
  let segment: { x: number; y: number }[] = [];
  const flush = () => {
    if (!segment.length) return;
    context.fillStyle = color; context.strokeStyle = color;
    if (segment.length > 1) {
      context.globalAlpha = 0.14;
      context.beginPath(); context.moveTo(segment[0].x, baseline);
      for (const point of segment) context.lineTo(point.x, point.y);
      context.lineTo(segment[segment.length - 1].x, baseline); context.closePath(); context.fill();
      context.globalAlpha = 1;
      context.beginPath(); context.moveTo(segment[0].x, segment[0].y);
      for (let index = 1; index < segment.length; index++) context.lineTo(segment[index].x, segment[index].y);
      context.lineWidth = 1.5; context.stroke();
    }
    if (segment.length === 1 || domainLength(domain) <= 60) {
      context.globalAlpha = 1;
      for (const point of segment) { context.beginPath(); context.arc(point.x, point.y, 2, 0, Math.PI * 2); context.fill(); }
    }
    segment = [];
  };
  for (let index = firstIndex; index <= lastIndex; index++) {
    const value = track.values[index];
    if (value === null || !Number.isFinite(value)) { flush(); continue; }
    segment.push({ x: positionToX(index + 1, domain, width), y: y(value) });
  }
  flush(); context.restore();
}

/** One canvas for axis and every track; hover/selection are deliberately absent. */
export function drawFeatureCanvas(canvas: HTMLCanvasElement, tracks: readonly FeatureTrack[], domain: ResidueDomain, width: number, pixelRatio: number): void {
  if (width <= 0) return;
  // Synchronous canvas work only: excludes scheduling delays and later presentation.
  const drawStartedAt = performance.now();
  const rows = featureTrackRows(tracks);
  const height = rows.length ? rows[rows.length - 1].top + rows[rows.length - 1].height : FEATURE_AXIS_HEIGHT;
  const ratio = Math.max(1, pixelRatio || 1);
  canvas.width = Math.max(1, Math.round(width * ratio)); canvas.height = Math.max(1, Math.round(height * ratio));
  const context = canvas.getContext('2d');
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  const colors = palette(canvas);
  context.fillStyle = colors.background; context.fillRect(0, 0, width, height);
  context.font = `11px ${colors.fontFamily}`;
  context.textBaseline = 'middle';
  const ticks = coordinateTicks(domain, width);
  for (const row of rows) {
    if (row.track.kind === 'region') { context.fillStyle = colors.subtle; context.fillRect(0, row.top, width, row.height); }
    context.strokeStyle = colors.border; context.lineWidth = 1;
    context.beginPath(); context.moveTo(0, row.top); context.lineTo(width, row.top); context.stroke();
  }
  context.strokeStyle = colors.border; context.lineWidth = 0.65;
  for (const position of ticks) {
    const x = positionToX(position, domain, width);
    context.beginPath(); context.moveTo(x, FEATURE_AXIS_HEIGHT - 7); context.lineTo(x, height); context.stroke();
    context.fillStyle = colors.muted;
    context.textAlign = position === domain.start ? 'left' : position === domain.end ? 'right' : 'center';
    const textX = position === domain.start ? 2 : position === domain.end ? width - 2 : x;
    context.fillText(String(position), textX, 16);
  }
  for (const row of rows) {
    const color = row.track.id === 'lreca-kde' ? colors.kde : colors[row.track.method];
    if (row.track.kind === 'continuous') drawContinuous(context, row.track, row, domain, width, color, colors);
    else {
      const regions = paintedRegions(row.track, domain, width, row.top);
      context.fillStyle = color; context.strokeStyle = color;
      for (const region of regions) {
        context.globalAlpha = region.region.isPrimary ? 0.7 : 0.25;
        context.fillRect(region.left, region.top, region.width, region.height);
        context.globalAlpha = 1; context.lineWidth = region.region.isPrimary ? 1.8 : 0.8;
        context.strokeRect(region.left + 0.5, region.top + 0.5, Math.max(0, region.width - 1), region.height - 1);
      }
      if (!row.track.regions.length) {
        context.globalAlpha = 1; context.fillStyle = colors.muted; context.textAlign = 'left';
        context.fillText('No regions returned', 9, row.top + row.height / 2);
      }
    }
  }
  context.globalAlpha = 1;
  const drawMs = performance.now() - drawStartedAt;
  const recordedMax = Number(canvas.dataset.staticDrawMaxMs ?? 0);
  canvas.dataset.staticDrawMs = String(drawMs);
  canvas.dataset.staticLastDrawMs = String(drawMs);
  canvas.dataset.staticFirstDrawMs ??= String(drawMs);
  canvas.dataset.staticDrawMaxMs = String(Math.max(Number.isFinite(recordedMax) ? recordedMax : 0, drawMs));
  canvas.dataset.staticDrawCount = String(Number(canvas.dataset.staticDrawCount ?? 0) + 1);
}
