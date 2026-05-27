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

      <div className="text-xs text-center text-gray-600 flex items-center justify-center gap-1.5">
        <span>{model.currentStageLabel} ({clamped}%)</span>
        {status.service_tier ? <ServiceTierChip tier={status.service_tier} /> : null}
      </div>

      {(status.error || status.status === 'failed' || status.status === 'error') && (
        <div className="text-xs text-red-600 text-center">
          {status.error || 'Processing failed'}
        </div>
      )}
    </div>
  );
}

function ServiceTierChip({
  tier,
}: {
  tier: { label: string; latest: string; mixed: boolean };
}) {
  const color =
    tier.label === 'flex'
      ? 'bg-purple-100 text-purple-800'
      : tier.label === 'priority'
        ? 'bg-blue-100 text-blue-800'
        : 'bg-gray-100 text-gray-700';
  const title = tier.mixed
    ? `LLM calls so far used mixed tiers; latest=${tier.latest}`
    : `LLM calls used the "${tier.label}" service tier`;
  return (
    <span
      title={title}
      className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded ${color}`}
    >
      {tier.label}
      {tier.mixed ? '*' : ''}
    </span>
  );
}
