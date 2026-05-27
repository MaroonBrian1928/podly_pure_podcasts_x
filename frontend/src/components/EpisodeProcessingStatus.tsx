import { useMemo, useRef } from 'react';

import { useEpisodeStatus } from '../hooks/useEpisodeStatus';
import { buildProcessingProgressModel } from '../utils/processingProgress';
import { computeStageDurationMs } from '../utils/jobStageDurations';
import { JobProgressCaption, JobProgressIndicator } from './JobProgress';
import type { JobStageEvent } from '../types';

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

  // Cache `now` per render but only let it advance roughly every 3s so the
  // active-stage duration ticks without thrashing the whole tree on every
  // unrelated re-render (status polls every 3s anyway).
  const nowRef = useRef<number>(Date.now());
  const now = useMemo(() => {
    nowRef.current = Date.now();
    return nowRef.current;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

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
