/** Presentation state only; never writes into an analysis result. */
import { fullDomain, normalizeDomain } from './feature-coordinates.ts';
import type { ResidueDomain } from './feature-coordinates.ts';
import type { FeatureTrackId } from './feature-viewer-model.ts';

export interface FeatureViewState {
  analysisId: string | null;
  domain: ResidueDomain;
  hiddenTrackIds: FeatureTrackId[];
  interactionMode: 'pan' | 'select';
}
export type FeatureViewAction =
  | { type: 'domain'; domain: ResidueDomain }
  | { type: 'toggle'; id: FeatureTrackId }
  | { type: 'mode'; mode: 'pan' | 'select' }
  | { type: 'reset' }
  | { type: 'analysis'; analysisId: string | null };

export function createFeatureViewState(analysisId: string | null, length: number): FeatureViewState {
  return { analysisId, domain: fullDomain(length), hiddenTrackIds: [], interactionMode: 'pan' };
}
export function updateFeatureView(state: FeatureViewState, action: FeatureViewAction, length: number): FeatureViewState {
  if (action.type === 'analysis') return action.analysisId === state.analysisId ? state : createFeatureViewState(action.analysisId, length);
  if (action.type === 'domain') return { ...state, domain: normalizeDomain(action.domain, length) };
  if (action.type === 'reset') return { ...state, domain: fullDomain(length) };
  if (action.type === 'mode') return { ...state, interactionMode: action.mode };
  return { ...state, hiddenTrackIds: state.hiddenTrackIds.includes(action.id)
    ? state.hiddenTrackIds.filter((id) => id !== action.id) : [...state.hiddenTrackIds, action.id] };
}
