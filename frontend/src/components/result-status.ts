import type { AnalysisJob } from '../lib/contracts.ts';
import { statusPresentation } from '../lib/viewer-data.ts';

/** Presentation-only status for the combined prediction card. */
export function combinedPredictionStatus(job: Pick<AnalysisJob, 'status' | 'ensemble'>): string {
  if (job.ensemble?.status === 'success') return 'Available';
  if (job.status === 'queued' || job.status === 'running') return statusPresentation(job.status).label;
  return 'Unavailable';
}
