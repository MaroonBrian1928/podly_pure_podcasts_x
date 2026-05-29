// Shared between the JobsPage card and the episode-list
// EpisodeProcessingStatus indicator so the per-stage rail timestamps
// ("Queue 4s / Download 2s / ...") use identical logic in both places.

import { backendDateMs } from './datetime';
import type { JobStageEvent } from '../types';

// Subset of the `Job` shape that this helper actually reads. Keeping the
// interface narrow lets EpisodeProcessingStatus reuse it without forging
// the rest of the `Job` interface from `/api/posts/<guid>/status`.
export interface StageDurationJobLike {
  status: string;
  completed_at?: string | null;
}

// Compute how long stage `stageIndex` ran, using only server-recorded
// transitions in `history`. Returns NaN when we don't have enough info
// (e.g. the stage hasn't started, or the previous stage was never logged).
export function computeStageDurationMs(
  history: JobStageEvent[],
  stageIndex: number,
  job: StageDurationJobLike,
  now: number,
): number {
  if (history.length === 0) {
    return NaN;
  }
  // Use the latest entry for this step, in case a stage was re-entered.
  const entryIndex = (() => {
    for (let i = history.length - 1; i >= 0; i--) {
      if (history[i].step === stageIndex) return i;
    }
    return -1;
  })();
  if (entryIndex === -1) {
    return NaN;
  }
  const start = backendDateMs(history[entryIndex].started_at);
  if (!Number.isFinite(start)) {
    return NaN;
  }

  // Stage end = the next history entry's start, if there is one, else the
  // job's completed_at (for terminal jobs) or `now` (still running).
  let end: number;
  if (entryIndex < history.length - 1) {
    end = backendDateMs(history[entryIndex + 1].started_at);
  } else if (
    job.status === 'completed' ||
    job.status === 'skipped' ||
    job.status === 'failed' ||
    job.status === 'cancelled'
  ) {
    const completed = backendDateMs(job.completed_at);
    end = Number.isFinite(completed) ? completed : now;
  } else {
    end = now;
  }
  if (!Number.isFinite(end)) {
    return NaN;
  }
  return Math.max(0, end - start);
}
