interface TimelineSegment {
  startTime: number;
  endTime: number;
}

interface ProcessingTimelineSummaryCardProps {
  title: string;
  itemCount: number;
  itemLabel: string;
  totalTimeSeconds: number;
  totalTimeLabel: string;
  percentage: number;
  percentageLabel: string;
  durationSeconds: number;
  segments: TimelineSegment[];
  metricAccentClassName: string;
  percentageAccentClassName: string;
  segmentClassName: string;
  summaryBaseLabel: string;
  summarySegmentLabel: string;
  legendBaseLabel: string;
  legendSegmentLabel: string;
}

const timelineTrackClass = 'relative h-3 w-full overflow-hidden rounded-full bg-gray-200';
const timelineContentOverlayClass = 'absolute inset-0 bg-gradient-to-r from-blue-500/20 via-blue-400/15 to-blue-500/20';
const timelineLegendSwatchClass = 'relative h-2.5 w-5 shrink-0 overflow-hidden rounded-full';
const timelineTicks = [0, 0.25, 0.5, 0.75, 1];

const formatDuration = (seconds: number) => {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.round(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m ${secs}s`;
  }
  return `${minutes}m ${secs}s`;
};

const formatTimelineLabel = (seconds: number) => {
  const totalSeconds = Math.max(0, Math.round(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
};

export default function ProcessingTimelineSummaryCard({
  title,
  itemCount,
  itemLabel,
  totalTimeSeconds,
  totalTimeLabel,
  percentage,
  percentageLabel,
  durationSeconds,
  segments,
  metricAccentClassName,
  percentageAccentClassName,
  segmentClassName,
  summaryBaseLabel,
  summarySegmentLabel,
  legendBaseLabel,
  legendSegmentLabel,
}: ProcessingTimelineSummaryCardProps) {
  const remainingSeconds = Math.max(0, durationSeconds - totalTimeSeconds);

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
      <h3 className="mb-4 text-left font-semibold text-gray-900">{title}</h3>
      <div className="grid grid-cols-1 gap-4 text-center md:grid-cols-3">
        <div>
          <div className={`text-2xl font-bold ${metricAccentClassName}`}>{itemCount}</div>
          <div className="text-sm text-gray-600">{itemLabel}</div>
        </div>
        <div>
          <div className={`text-2xl font-bold ${metricAccentClassName}`}>
            {formatDuration(totalTimeSeconds)}
          </div>
          <div className="text-sm text-gray-600">{totalTimeLabel}</div>
        </div>
        <div>
          <div className={`text-2xl font-bold ${percentageAccentClassName}`}>
            {percentage.toFixed(1)}%
          </div>
          <div className="text-sm text-gray-600">{percentageLabel}</div>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-gray-600">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-500">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </span>
            Episode Timeline
          </div>
          <div className="text-gray-600">
            {formatDuration(remainingSeconds)} {summaryBaseLabel}
            <span className={`ml-2 ${percentageAccentClassName}`}>
              {formatDuration(totalTimeSeconds)} {summarySegmentLabel} ({percentage.toFixed(1)}%)
            </span>
          </div>
        </div>

        <div className={timelineTrackClass}>
          <div className={timelineContentOverlayClass} />
          {durationSeconds > 0 && segments.map((segment, index) => {
            const left = Math.max(0, (segment.startTime / durationSeconds) * 100);
            const width = Math.max(0.5, ((segment.endTime - segment.startTime) / durationSeconds) * 100);
            return (
              <div
                key={`${segment.startTime}-${segment.endTime}-${index}`}
                className={`absolute top-0 h-full rounded-full ${segmentClassName}`}
                style={{ left: `${left}%`, width: `${width}%` }}
              />
            );
          })}
        </div>

        <div className="flex justify-between text-xs text-gray-500">
          {timelineTicks.map((tick) => (
            <span key={tick}>{formatTimelineLabel(durationSeconds * tick)}</span>
          ))}
        </div>

        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="flex items-center gap-2">
            <span className={`${timelineLegendSwatchClass} bg-gray-200`}>
              <span className={timelineContentOverlayClass} />
            </span>
            {legendBaseLabel}
          </span>
          <span className="flex items-center gap-2">
            <span className={`${timelineLegendSwatchClass} ${segmentClassName}`} />
            {legendSegmentLabel}
          </span>
        </div>
      </div>
    </div>
  );
}
