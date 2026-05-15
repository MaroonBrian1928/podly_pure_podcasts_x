import { useEpisodeStatus } from '../hooks/useEpisodeStatus';
import { buildProcessingProgressModel } from '../utils/processingProgress';
import { JobProgressIndicator } from './JobProgress';

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

  const clamped = Math.max(0, Math.min(100, Math.round(model.progress)));

  return (
    <div className={`space-y-2 min-w-[200px] ${className}`}>
      <JobProgressIndicator
        model={model}
        status={status.status}
        size="compact"
      />

      <div className="text-xs text-center text-gray-600">
        {model.currentStageLabel} ({clamped}%)
      </div>

      {(status.error || status.status === 'failed' || status.status === 'error') && (
        <div className="text-xs text-red-600 text-center">
          {status.error || 'Processing failed'}
        </div>
      )}
    </div>
  );
}
