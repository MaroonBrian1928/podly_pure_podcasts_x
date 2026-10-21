// Shared progress UI shared between the Jobs page card and the episode-list
// EpisodeProcessingStatus indicator. Single source of truth so styling can't
// drift between the two views — anywhere a job's progress is shown should
// be composed from these primitives.

import type { ProcessingProgressModel, ProcessingStageState } from '../utils/processingProgress';
import { formatDuration } from '../utils/datetime';
import { CheckIcon } from './icons';

type BarSize = 'compact' | 'full';

interface JobProgressBarProps {
  value: number;
  colorClass?: string;
  size?: BarSize;
  className?: string;
}

const BAR_HEIGHT: Record<BarSize, string> = {
  compact: 'h-1.5',
  full: 'h-2',
};

const BAR_RADIUS: Record<BarSize, string> = {
  compact: 'rounded-full',
  full: 'rounded',
};

export function JobProgressBar({
  value,
  colorClass = 'bg-blue-600',
  size = 'full',
  className = '',
}: JobProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  const height = BAR_HEIGHT[size];
  const radius = BAR_RADIUS[size];
  return (
    <div className={`relative w-full bg-gray-200 ${radius} ${height} overflow-hidden ${className}`}>
      <div
        className={`absolute inset-y-0 left-0 ${colorClass} ${radius} transition-[width] duration-300 ease-out`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

interface JobStageRailProps {
  stages: ProcessingStageState[];
  // Optional per-stage durations indexed by `stage.index`. Use `NaN` (or omit)
  // to suppress a row's duration cell. Stage durations only render under
  // cells that have actually been entered (completed / active / failed).
  stageDurationsMs?: ReadonlyArray<number>;
  className?: string;
}

export function JobStageRail({ stages, stageDurationsMs, className = '' }: JobStageRailProps) {
  // Tailwind needs literal class names; the LLM pipeline has 6 stages, the
  // chapter pipelines 5.
  const cols = stages.length === 6 ? 'grid-cols-6' : 'grid-cols-5';
  return (
    <div className={`grid ${cols} gap-1 text-[11px] text-gray-600 ${className}`}>
      {stages.map((stage) => {
        const ms = stageDurationsMs?.[stage.index];
        const hasDuration =
          ms !== undefined &&
          Number.isFinite(ms) &&
          ms >= 0 &&
          (stage.state === 'completed' || stage.state === 'active' || stage.state === 'failed');
        return (
          <div
            key={stage.index}
            title={stage.label}
            className={`flex flex-col items-center leading-tight ${
              stage.state === 'active'
                ? 'text-blue-700 font-medium'
                : stage.state === 'completed'
                  ? 'text-green-700'
                  : stage.state === 'failed'
                    ? 'text-red-700 font-medium'
                    : 'text-gray-500'
            }`}
          >
            <span className="flex h-3 items-center justify-center">
              {stage.state === 'completed' ? (
                <CheckIcon className="h-3 w-3" />
              ) : stage.state === 'active' ? (
                <span className="relative inline-flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75 animate-ping" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-600" />
                </span>
              ) : stage.state === 'failed' ? (
                <span>!</span>
              ) : (
                <span className="inline-block h-2 w-2 rounded-full border border-current" />
              )}
            </span>
            <span>{stage.shortLabel}</span>
            {hasDuration ? (
              <span className="font-mono tabular-nums text-[11px] text-gray-500">
                {formatDuration(ms)}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

interface JobProgressIndicatorProps {
  model: ProcessingProgressModel;
  status: string;
  size?: BarSize;
  stageDurationsMs?: ReadonlyArray<number>;
  className?: string;
}

// One-stop combination: bar + stage rail with the right palette for the
// job's status. Use this when the caller doesn't need extra chrome around
// the bar (e.g. EpisodeProcessingStatus). Callers that want surrounding
// labels (like the JobsPage "Progress 50%" header) can compose
// JobProgressBar + JobStageRail directly.
export function JobProgressIndicator({
  model,
  status,
  size = 'compact',
  stageDurationsMs,
  className = '',
}: JobProgressIndicatorProps) {
  const isFailure = status === 'failed' || status === 'cancelled' || status === 'error';
  const isTerminalSuccess = status === 'completed' || status === 'skipped';
  const colorClass = isFailure
    ? 'bg-red-600'
    : isTerminalSuccess
      ? 'bg-green-600'
      : 'bg-blue-600';
  return (
    <div className={`space-y-1 ${className}`}>
      <JobProgressBar
        value={model.progress}
        colorClass={colorClass}
        size={size}
      />
      <JobStageRail stages={model.stages} stageDurationsMs={stageDurationsMs} />
    </div>
  );
}

// Shared shape mirrors the backend `service_tier` summary in
// app/jobs_manager.py::_summarize_service_tier_for_post.
export interface ServiceTierSummary {
  label: string;
  latest: string;
  mixed: boolean;
  in_flight?: {
    status: 'pending' | 'retrying';
    attempt: number;
    max_retries?: number;
    // ISO UTC deadline of the current backoff sleep; present only while
    // status === 'retrying' and the worker persisted a deadline.
    backoff_until?: string;
    // Short label for what kind of LLM call is in flight (e.g. "chapter
    // topic plan"); present for chapter-phase calls so the caption makes
    // sense when they run inside the audio-processing stage.
    call_label?: string;
  };
}

export function ServiceTierChip({ tier }: { tier: ServiceTierSummary }) {
  const color =
    tier.label === 'flex'
      ? 'bg-sky-100 text-sky-800'
      : tier.label === 'priority'
        ? 'bg-blue-100 text-blue-800'
        : 'bg-gray-100 text-gray-800';
  const title = tier.mixed
    ? `LLM calls so far used mixed tiers; latest=${tier.latest}`
    : `LLM calls used the "${tier.label}" service tier`;
  return (
    <span className="inline-flex items-center gap-1">
      <span
        title={title}
        className={`inline-flex items-center px-1.5 py-0.5 text-[11px] font-medium rounded ${color}`}
      >
        {tier.label}
        {tier.mixed ? '*' : ''}
      </span>
      {tier.in_flight ? (
        <span className="text-[11px] text-gray-500 italic">
          {formatTierInFlight(tier.in_flight)}
        </span>
      ) : null}
    </span>
  );
}

// Centered "Stage Name (NN%) [tier chip] (attempt 1/5)" caption matching the
// layout EpisodeProcessingStatus uses below its bar. Extracted so the JobsPage
// card and the episode-list status indicator stay visually in sync.
//
// Callers that render the tier chip elsewhere (e.g. JobsPage shows it in the
// top-right badge row) can pass `hideChip` to suppress the inline chip while
// keeping the in-flight retry text, which still belongs inline with the
// stage label.
export function JobProgressCaption({
  stageLabel,
  percent,
  tier,
  hideChip = false,
  className = '',
}: {
  stageLabel: string;
  percent: number;
  tier?: ServiceTierSummary;
  hideChip?: boolean;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      className={`text-xs text-center text-gray-600 flex items-center justify-center gap-1.5 ${className}`}
    >
      <span>
        {stageLabel} ({clamped}%)
      </span>
      {tier && !hideChip ? <ServiceTierChip tier={tier} /> : null}
      {tier?.in_flight && hideChip ? (
        <span className="text-[11px] text-gray-500 italic">
          {formatTierInFlight(tier.in_flight)}
        </span>
      ) : null}
    </div>
  );
}

function formatTierInFlight(inFlight: {
  status: 'pending' | 'retrying';
  attempt: number;
  max_retries?: number;
  backoff_until?: string;
  call_label?: string;
}): string {
  const count =
    inFlight.max_retries && inFlight.max_retries > 0
      ? `${inFlight.attempt}/${inFlight.max_retries}`
      : `${inFlight.attempt}`;
  // Name the call when we know it (chapter-phase calls run inside the
  // audio-processing stage, where a bare "awaiting provider" reads oddly).
  const subject = inFlight.call_label ? `${inFlight.call_label}: ` : '';
  if (inFlight.status === 'retrying') {
    const remaining = backoffRemainingSeconds(inFlight.backoff_until);
    if (remaining !== null && remaining > 0) {
      return `(${subject}attempt ${count} — backoff, retrying in ${formatSeconds(remaining)})`;
    }
    return `(${subject}retrying ${count})`;
  }
  // pending = the request is out; we're waiting on the provider's response.
  return `(${subject}attempt ${count} — awaiting provider)`;
}

function backoffRemainingSeconds(backoffUntil?: string): number | null {
  if (!backoffUntil) return null;
  const deadline = Date.parse(backoffUntil);
  if (Number.isNaN(deadline)) return null;
  return Math.round((deadline - Date.now()) / 1000);
}

function formatSeconds(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}
