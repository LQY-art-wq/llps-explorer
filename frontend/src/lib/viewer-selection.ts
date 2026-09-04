/** Shared presentation selection for the two viewers and result tables. */
import type { ViewerFocusRequest, ViewerRegionSelection } from './viewer-data.ts';

export type ResultTab = 'overview' | 'features' | 'sequence' | 'lreca' | 'fuzdrop'
  | 'annotations' | 'tables' | 'download';
export type ViewerDestination = 'features' | 'sequence';

export interface ViewerSelectionState {
  activeTab: ResultTab;
  selectedResidue: number | null;
  selectedRegion: ViewerRegionSelection | null;
  featureFocusRequest: ViewerFocusRequest | null;
  sequenceFocusRequest: ViewerFocusRequest | null;
}

export type ViewerSelectionAction =
  | { type: 'set_tab'; tab: ResultTab }
  | { type: 'select_residue'; position: number }
  | { type: 'select_region'; region: ViewerRegionSelection }
  | { type: 'view_residue'; destination: ViewerDestination; position: number }
  | { type: 'view_region'; destination: ViewerDestination; region: ViewerRegionSelection }
  | { type: 'view_selected'; destination: ViewerDestination }
  | { type: 'clear' };

export function createViewerSelectionState(activeTab: ResultTab = 'overview'): ViewerSelectionState {
  return {
    activeTab, selectedResidue: null, selectedRegion: null,
    featureFocusRequest: null, sequenceFocusRequest: null,
  };
}

function validPosition(position: number): boolean {
  return Number.isSafeInteger(position) && position >= 1;
}

function validRegion(region: ViewerRegionSelection): boolean {
  return Number.isSafeInteger(region.start) && Number.isSafeInteger(region.end)
    && region.start >= 1 && region.end >= region.start;
}

function selectedFocus(state: ViewerSelectionState): Omit<ViewerFocusRequest, 'requestId'> | null {
  if (state.selectedResidue !== null) {
    return { start: state.selectedResidue, end: state.selectedResidue };
  }
  return state.selectedRegion
    ? { start: state.selectedRegion.start, end: state.selectedRegion.end } : null;
}

function withFocus(
  state: ViewerSelectionState,
  destination: ViewerDestination,
  focus: Omit<ViewerFocusRequest, 'requestId'>,
): ViewerSelectionState {
  const key = destination === 'features' ? 'featureFocusRequest' : 'sequenceFocusRequest';
  const previous = state[key];
  return {
    ...state, activeTab: destination,
    [key]: { ...focus, requestId: (previous?.requestId ?? 0) + 1 },
  };
}

export function reduceViewerSelection(
  state: ViewerSelectionState,
  action: ViewerSelectionAction,
): ViewerSelectionState {
  if (action.type === 'set_tab') return { ...state, activeTab: action.tab };
  if (action.type === 'clear') return createViewerSelectionState(state.activeTab);
  if (action.type === 'select_residue') {
    return validPosition(action.position)
      ? { ...state, selectedResidue: action.position, selectedRegion: null } : state;
  }
  if (action.type === 'select_region') {
    return validRegion(action.region)
      ? { ...state, selectedResidue: null, selectedRegion: { ...action.region } } : state;
  }
  if (action.type === 'view_residue') {
    if (!validPosition(action.position)) return state;
    const selected = { ...state, selectedResidue: action.position, selectedRegion: null };
    return withFocus(selected, action.destination, { start: action.position, end: action.position });
  }
  if (action.type === 'view_region') {
    if (!validRegion(action.region)) return state;
    const selected = { ...state, selectedResidue: null, selectedRegion: { ...action.region } };
    return withFocus(selected, action.destination, { start: action.region.start, end: action.region.end });
  }
  const focus = selectedFocus(state);
  return focus ? withFocus(state, action.destination, focus)
    : { ...state, activeTab: action.destination };
}
