/** One shared 1-based, inclusive residue domain. Pixel cells never change native coordinates. */
export interface ResidueDomain { start: number; end: number }
export interface PixelBounds { left: number; right: number; width: number }

function validLength(length: number): number {
  if (!Number.isSafeInteger(length) || length < 1) throw new RangeError('A positive integer sequence length is required.');
  return length;
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

export function fullDomain(length: number): ResidueDomain {
  return { start: 1, end: validLength(length) };
}

export function normalizeDomain(domain: ResidueDomain, length: number): ResidueDomain {
  validLength(length);
  if (!Number.isFinite(domain.start) || !Number.isFinite(domain.end)) return fullDomain(length);
  return {
    start: clamp(Math.round(Math.min(domain.start, domain.end)), 1, length),
    end: clamp(Math.round(Math.max(domain.start, domain.end)), 1, length),
  };
}

export function domainLength(domain: ResidueDomain): number {
  return domain.end - domain.start + 1;
}

function fitWindow(start: number, size: number, length: number): ResidueDomain {
  const span = clamp(Math.round(size), 1, length);
  const first = clamp(Math.round(start), 1, length - span + 1);
  return { start: first, end: first + span - 1 };
}

/** factor < 1 zooms in; anchor is a residue coordinate, not an array index. */
export function zoomDomain(domain: ResidueDomain, length: number, factor: number, anchor?: number): ResidueDomain {
  const current = normalizeDomain(domain, length);
  if (!Number.isFinite(factor) || factor <= 0) return current;
  const size = domainLength(current);
  const focus = Number.isFinite(anchor) ? clamp(anchor!, current.start - 0.5, current.end + 0.5) : (current.start + current.end) / 2;
  const ratio = (focus - current.start + 0.5) / size;
  let nextSize = clamp(Math.round(size * factor), 1, length);
  // One-residue progress keeps gentle trackpad gestures usable near maximum zoom.
  if (nextSize === size && factor !== 1) nextSize = clamp(size + (factor < 1 ? -1 : 1), 1, length);
  return fitWindow(focus + 0.5 - ratio * nextSize, nextSize, length);
}

/** Pan retains the visible span when either sequence boundary is reached. */
export function panDomain(domain: ResidueDomain, length: number, deltaResidues: number): ResidueDomain {
  const current = normalizeDomain(domain, length);
  if (!Number.isFinite(deltaResidues)) return current;
  return fitWindow(current.start + deltaResidues, domainLength(current), length);
}

export function focusResidueDomain(position: number, length: number, windowSize = 51): ResidueDomain {
  validLength(length);
  if (!Number.isFinite(position)) return fullDomain(length);
  const center = clamp(Math.round(position), 1, length);
  const size = Number.isFinite(windowSize) ? clamp(Math.round(windowSize), 1, length) : Math.min(51, length);
  return fitWindow(center - (size - 1) / 2, size, length);
}

export function focusRegionDomain(region: ResidueDomain, length: number, margin = 20): ResidueDomain {
  const native = normalizeDomain(region, length);
  const padding = Number.isFinite(margin) ? Math.max(0, Math.round(margin)) : 20;
  return normalizeDomain({ start: native.start - padding, end: native.end + padding }, length);
}

/** Cell centers leave half a residue cell visible at both ends, including N=1. */
export function positionToX(position: number, domain: ResidueDomain, width: number): number {
  if (!Number.isFinite(width) || width <= 0 || domainLength(domain) <= 0) return 0;
  return ((position - domain.start + 0.5) / domainLength(domain)) * width;
}

/** Pointer coordinates at either plot boundary resolve to the visible end residue. */
export function xToPosition(x: number, domain: ResidueDomain, width: number): number {
  if (!Number.isFinite(x) || !Number.isFinite(width) || width <= 0) return domain.start;
  const continuous = domain.start - 0.5 + (clamp(x, 0, width) / width) * domainLength(domain);
  return clamp(Math.round(continuous), domain.start, domain.end);
}

/** Inclusive native regions occupy complete residue cells; no new region is inferred. */
export function regionPixelBounds(region: ResidueDomain, domain: ResidueDomain, width: number, minWidth = 3): PixelBounds | null {
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(region.start) || !Number.isFinite(region.end)
    || !Number.isFinite(domain.start) || !Number.isFinite(domain.end) || domainLength(domain) < 1
    || region.end < domain.start || region.start > domain.end || region.end < region.start) return null;
  const span = domainLength(domain);
  const nativeLeft = clamp((region.start - domain.start) / span * width, 0, width);
  const nativeRight = clamp((region.end - domain.start + 1) / span * width, 0, width);
  const minimum = Number.isFinite(minWidth) ? clamp(minWidth, 0, width) : 3;
  const visibleWidth = Math.min(width, Math.max(nativeRight - nativeLeft, minimum));
  const left = clamp((nativeLeft + nativeRight - visibleWidth) / 2, 0, width - visibleWidth);
  return { left, right: left + visibleWidth, width: visibleWidth };
}

/** A brush uses the same cell mapping as cursor, click, line and region rendering. */
export function brushDomain(firstX: number, lastX: number, domain: ResidueDomain, width: number): ResidueDomain {
  const first = xToPosition(firstX, domain, width);
  const last = xToPosition(lastX, domain, width);
  return { start: Math.min(first, last), end: Math.max(first, last) };
}

export function coordinateTicks(domain: ResidueDomain, width: number): number[] {
  const size = domainLength(domain);
  if (size === 1) return [domain.start];
  const count = Math.max(2, Math.floor(width / 85));
  const rough = (size - 1) / Math.max(1, count - 1);
  const power = 10 ** Math.floor(Math.log10(Math.max(1, rough)));
  const step = [1, 2, 5, 10].map((value) => value * power).find((value) => value >= rough) ?? power * 10;
  const ticks = [domain.start];
  for (let value = Math.ceil(domain.start / step) * step; value < domain.end; value += step) {
    if (value > domain.start && positionToX(value, domain, width) - positionToX(ticks[ticks.length - 1], domain, width) >= 38
      && positionToX(domain.end, domain, width) - positionToX(value, domain, width) >= 38) ticks.push(value);
  }
  ticks.push(domain.end);
  return ticks;
}
