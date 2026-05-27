import { useEffect, useState } from 'react';

import { useEpisodeStatus } from '../hooks/useEpisodeStatus';
import { buildProcessingProgressModel } from '../utils/processingProgress';
import { computeStageDurationMs } from '../utils/jobStageDurations';
import { JobProgressCaption, JobProgressIndicator } from './JobProgress';
import type { JobStageEvent } from '../types';

const ACTIVE_STATUSES = new Set([
  'pending',
  'running',
  'starting',
  'processing',
]);

interface EpisodeProcessingStatusProps {
  episodeGuid: string;
  isWhitelisted: boolean;
  hasProcessedAudio: boolean;
  feedId?: number;
  className?: string;
}

export default function EpisodeProcessingStatus({
  episodeGuid,
  isWhitelisted,
  hasProcessedAudio,
  feedId,
  className = ''
}: EpisodeProcessingStatusProps) {
  const { data: status } = useEpisodeStatus(episodeGuid, isWhitelisted, hasProcessedAudio, feedId);

  // Tick `now` once per second so the active-stage duration in the rail
  // updates smoothly rather than waiting on the 3s status poll. Stops as
  // soon as the post is no longer in an active state so we're not running
  // an interval for nothing once processing finishes.
  const [now, setNow] = useState<number>(() => Date.now());
  const statusValue = status?.status;
  useEffect(() => {
    if (!statusValue || !ACTIVE_STATUSES.has(statusValue)) {
      return undefined;
    }
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [statusValue]);

  if (!status) return null;

  // Don't show anything if completed (DownloadButton handles this) or not started
  if (status.status === 'completed' || status.status === 'not_started') {
    return null;
  }

  const model = buildProcessingProgressModel({
    status: status.status,
    step: status.step,
    totalSteps: status.total_steps,
    stepName: status.step_name,
    progressPercentage: status.progress_percentage,
  });

  const stageHistory: JobStageEvent[] = status.stage_history ?? [];
  // Mirror the JobsPage card: compute a per-stage duration so the stage rail
  // shows "Queue 4s / Download 2s / ..." alongside the active stage's spinner.
  const jobLike = {
    status: status.status,
    started_at: status.started_at,
    completed_at: status.completed_at,
  };
  const stageDurationsMs = model.stages.map((stage) =>
    computeStageDurationMs(stageHistory, stage.index, jobLike, now)
  );

  return (
    <div className={`space-y-2 min-w-[200px] ${className}`}>
      <JobProgressIndicator
        model={model}
        status={status.status}
        size="compact"
        stageDurationsMs={stageDurationsMs}
      />

      <JobProgressCaption
        stageLabel={model.currentStageLabel}
        percent={model.progress}
        tier={status.service_tier}
      />

      {(status.error || status.status === 'failed' || status.status === 'error') && (
        <div className="text-xs text-red-600 text-center">
          {status.error || 'Processing failed'}
        </div>
      )}
    </div>
  );
}
