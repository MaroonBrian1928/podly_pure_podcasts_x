import { useState } from 'react';
import { formatTimelineLabel } from '../utils/processingTimeline';

interface TimelineSegment {
  startTime: number;
  endTime: number;
  kind?: 'range' | 'point';
  visualDurationSeconds?: number;
  tooltipTitle: string;
  tooltipRows: Array<{
    label: string;
    value: string;
  }>;
  ariaLabel?: string;
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
  timelineDurationSeconds?: number;
  minimumSegmentWidthPercent?: number;
  minimumSegmentWidthPx?: number;
  minimumPointWidthPx?: number;
  segments: TimelineSegment[];
  metricAccentClassName: string;
  percentageAccentClassName: string;
  tooltipAccentClassName?: string;
  segmentClassName: string;
  legendBaseLabel: string;
  legendSegmentLabel: string;
}

const timelineTrackClass = 'relative h-3 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-slate-800';
const timelineContentOverlayClass = 'absolute inset-0 bg-gradient-to-r from-slate-400/22 via-slate-300/16 to-slate-400/22 dark:from-slate-400/20 dark:via-slate-300/14 dark:to-slate-400/20';
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

export default function ProcessingTimelineSummaryCard({
  title,
  itemCount,
  itemLabel,
  totalTimeSeconds,
  totalTimeLabel,
  percentage,
  percentageLabel,
  durationSeconds,
  timelineDurationSeconds,
  minimumSegmentWidthPercent = 0,
  minimumSegmentWidthPx = 2,
  minimumPointWidthPx = 6,
  segments,
  metricAccentClassName,
  percentageAccentClassName,
  tooltipAccentClassName = '',
  segmentClassName,
  legendBaseLabel,
  legendSegmentLabel,
}: ProcessingTimelineSummaryCardProps) {
  const [activeSegmentIndex, setActiveSegmentIndex] = useState<number | null>(null);
  const effectiveTimelineDurationSeconds = Math.max(
    timelineDurationSeconds ?? durationSeconds,
    0
  );
  const activeSegment = activeSegmentIndex !== null ? segments[activeSegmentIndex] : null;
  const getIsPointSegment = (segment: TimelineSegment) => (
    segment.kind === 'point' || segment.endTime <= segment.startTime
  );
  const getRawWidthPercent = (segment: TimelineSegment) => {
    if (effectiveTimelineDurationSeconds <= 0) {
      return 0;
    }

    if (getIsPointSegment(segment)) {
      const visualDurationSeconds = Math.max(0, segment.visualDurationSeconds ?? 0);
      return (visualDurationSeconds / effectiveTimelineDurationSeconds) * 100;
    }

    return ((segment.endTime - segment.startTime) / effectiveTimelineDurationSeconds) * 100;
  };
  const getWidthPercent = (segment: TimelineSegment) => (
    Math.min(100, Math.max(minimumSegmentWidthPercent, getRawWidthPercent(segment)))
  );
  const getLeftPercent = (segment: TimelineSegment, widthPercent: number) => {
    if (effectiveTimelineDurationSeconds <= 0) {
      return 0;
    }

    const anchorPercent = (segment.startTime / effectiveTimelineDurationSeconds) * 100;
    if (getIsPointSegment(segment)) {
      return anchorPercent - (widthPercent / 2);
    }
    return anchorPercent;
  };

  const activeSegmentLeft = (() => {
    if (!activeSegment || effectiveTimelineDurationSeconds <= 0) {
      return 0;
    }

    const width = getWidthPercent(activeSegment);
    const left = getLeftPercent(activeSegment, width);
    return Math.min(Math.max(0, left), Math.max(0, 100 - width));
  })();
  const activeSegmentWidth = (() => {
    if (!activeSegment || effectiveTimelineDurationSeconds <= 0) {
      return 0;
    }

    return getWidthPercent(activeSegment);
  })();
  const activeSegmentCenter = Math.max(
    0,
    Math.min(100, activeSegmentLeft + (activeSegmentWidth / 2))
  );
  const activeSegmentRight = Math.max(
    0,
    Math.min(100, activeSegmentLeft + activeSegmentWidth)
  );

  const tooltipStyle = activeSegmentRight <= 72
    ? { left: `calc(${activeSegmentRight}% + 12px)`, transform: 'translateX(0)' }
    : activeSegmentLeft >= 28
      ? { left: `calc(${activeSegmentLeft}% - 12px)`, transform: 'translateX(-100%)' }
      : activeSegmentCenter < 15
        ? { left: '0%', transform: 'translateX(0)' }
        : activeSegmentCenter > 85
          ? { left: '100%', transform: 'translateX(-100%)' }
          : { left: `${activeSegmentCenter}%`, transform: 'translateX(-50%)' };

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-5 sm:p-6 dark:border-slate-700 dark:bg-slate-900/80">
      <h3 className="mb-5 text-left font-semibold text-gray-900 dark:text-slate-100">{title}</h3>
      <div className="grid grid-cols-1 gap-5 text-center md:grid-cols-3 md:gap-6">
        <div>
          <div className={`text-2xl font-bold ${metricAccentClassName}`}>{itemCount}</div>
          <div className="mt-1 text-sm text-gray-600 dark:text-slate-300">{itemLabel}</div>
        </div>
        <div>
          <div className={`text-2xl font-bold ${metricAccentClassName}`}>
            {formatDuration(totalTimeSeconds)}
          </div>
          <div className="mt-1 text-sm text-gray-600 dark:text-slate-300">{totalTimeLabel}</div>
        </div>
        <div>
          <div className={`text-2xl font-bold ${percentageAccentClassName}`}>
            {percentage.toFixed(1)}%
          </div>
          <div className="mt-1 text-sm text-gray-600 dark:text-slate-300">{percentageLabel}</div>
        </div>
      </div>

      <div className="mt-6 space-y-3">
        <div className="relative">
          {activeSegment && (
            <div
              className="pointer-events-none absolute bottom-full z-30 mb-3 w-full"
              aria-hidden="true"
            >
              <div
                className="absolute w-max min-w-[13rem] max-w-[calc(100vw-3rem)] rounded-xl border border-gray-200 bg-white p-3.5 text-left shadow-2xl ring-1 ring-black/5 dark:border-slate-700 dark:bg-slate-950 dark:ring-white/10"
                style={tooltipStyle}
              >
                <div className={`text-sm font-semibold text-gray-900 dark:text-slate-100 ${tooltipAccentClassName}`.trim()}>
                  {activeSegment.tooltipTitle}
                </div>
                <div className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
                  {activeSegment.tooltipRows.map((row) => (
                    <div key={`${row.label}-${row.value}`} className="contents">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500 dark:text-slate-400">
                        {row.label}
                      </div>
                      <div className="text-sm font-medium tabular-nums text-gray-900 dark:text-slate-100">
                        {row.value}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="relative">
            <div className={timelineTrackClass}>
              <div className={timelineContentOverlayClass} />
            </div>

            <div className="absolute inset-0">
              {effectiveTimelineDurationSeconds > 0 && segments.map((segment, index) => {
                const isPointSegment = getIsPointSegment(segment);
                const width = getWidthPercent(segment);
                const left = getLeftPercent(segment, width);
                const boundedLeft = Math.min(Math.max(0, left), Math.max(0, 100 - width));
                const isActive = activeSegmentIndex === index;

                return (
                  <button
                    key={`${segment.startTime}-${segment.endTime}-${index}`}
                    type="button"
                    aria-label={segment.ariaLabel ?? `${segment.tooltipTitle}: ${segment.tooltipRows.map((row) => `${row.label} ${row.value}`).join('. ')}`}
                    className={[
                      'absolute cursor-pointer transition-transform duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:focus-visible:ring-blue-300/70',
                      isPointSegment
                        ? '-top-1 h-5 rounded-full shadow-[0_0_0_2px_rgba(255,255,255,0.85)] dark:shadow-[0_0_0_2px_rgba(15,23,42,0.92)]'
                        : 'top-0 h-full rounded-full',
                      segmentClassName,
                      isActive ? 'scale-y-110' : '',
                    ].join(' ').trim()}
                    style={{
                      left: `${boundedLeft}%`,
                      width: isPointSegment
                        ? `max(${width}%, ${minimumPointWidthPx}px)`
                        : `max(${width}%, ${minimumSegmentWidthPx}px)`,
                      zIndex: isActive ? 20 : 10,
                    }}
                    onMouseEnter={() => setActiveSegmentIndex(index)}
                    onMouseLeave={() => setActiveSegmentIndex((currentIndex) => (
                      currentIndex === index ? null : currentIndex
                    ))}
                    onFocus={() => setActiveSegmentIndex(index)}
                    onBlur={() => setActiveSegmentIndex((currentIndex) => (
                      currentIndex === index ? null : currentIndex
                    ))}
                  />
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex justify-between pt-1 text-xs text-gray-500 dark:text-slate-400">
          {timelineTicks.map((tick) => (
            <span key={tick}>
              {formatTimelineLabel(effectiveTimelineDurationSeconds * tick)}
            </span>
          ))}
        </div>

        <div className="flex items-center gap-5 pt-1 text-xs text-gray-500 dark:text-slate-400">
          <span className="flex items-center gap-2">
            <span className={`${timelineLegendSwatchClass} bg-gray-200 dark:bg-slate-800`}>
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
