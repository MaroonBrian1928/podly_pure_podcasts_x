import { Fragment, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../../services/api';
import { useDelayedFlag } from '../../hooks/useDelayedFlag';
import { useStatsReveal } from '../../hooks/useStatsReveal';
import ProcessingTimelineSummaryCard from '../ProcessingTimelineSummaryCard';
import ProcessingStageLogs from '../ProcessingStageLogs';
import SpeakerTimeBreakdown from '../SpeakerTimeBreakdown';
import { formatBackendDateTime } from '../../utils/datetime';
import {
  formatTimelineLabel,
  formatTimelineRange,
} from '../../utils/processingTimeline';
import {
  StatsHeader,
  StatsTabBarPlaceholder,
  StatsTabBarShell,
} from './StatsLoadingFrame';
import ShowMoreRows, { ROW_PAGE_SIZE } from './ShowMoreRows';

interface ChapterStatsBodyProps {
  episodeGuid: string;
  onClose: () => void;
}

type TabId = 'overview' | 'audio' | 'chapters' | 'speakers' | 'model-calls' | 'transcript' | 'logs';

function getFallbackDurationSeconds(
  transcriptSegments: Array<{ end_time: number }> | undefined,
  bleepWindows: Array<{ end_time: number }> | undefined
) {
  const candidates = [
    ...(transcriptSegments || []).map((segment) => segment.end_time),
    ...(bleepWindows || []).map((window) => window.end_time),
  ];
  return candidates.length ? Math.max(...candidates) : 0;
}

export default function ChapterStatsBody({ episodeGuid, onClose }: ChapterStatsBodyProps) {
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [expandedModelCalls, setExpandedModelCalls] = useState<Set<number>>(new Set());
  const [visibleRows, setVisibleRows] = useState(ROW_PAGE_SIZE);
  const selectTab = (tab: TabId) => {
    setActiveTab(tab);
    setVisibleRows(ROW_PAGE_SIZE);
  };
  const showMoreRows = () => setVisibleRows((count) => count + ROW_PAGE_SIZE);

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['episode-stats', episodeGuid],
    queryFn: () => feedsApi.getPostStats(episodeGuid),
  });
  // Fast responses skip the spinner rather than flashing it.
  const showSpinner = useDelayedFlag(isLoading, 250);
  const overviewRef = useStatsReveal(true, Boolean(stats) && activeTab === 'overview');
  const isChapterInsert = stats?.ad_detection_strategy === 'chapter_insert';
  const showTranscriptTab = isChapterInsert;
  const showSpeakerTab = isChapterInsert
    && (stats?.processing_stats?.speaker_breakdown?.length || 0) > 0;
  const transcriptSegments = stats?.transcript_segments;
  const hasAudioSegments = (stats?.audio_segments?.length || 0) > 0;
  const modelEntries = useMemo(
    () => Object.entries(stats?.processing_stats?.model_types || {}),
    [stats?.processing_stats?.model_types]
  );
  const estimatedCost = stats?.processing_stats?.estimated_cost;
  // The backend only attaches per-call cost data for admins; use that as the
  // signal for whether to render the Cost column at all so non-admins don't
  // see a column full of em-dashes.
  const showCostColumn = estimatedCost != null;

  const formatTimestamp = (timestamp: string | null) => {
    if (!timestamp) return 'N/A';
    return formatBackendDateTime(timestamp);
  };

  const toggleModelCallDetails = (callId: number) => {
    const nextExpanded = new Set(expandedModelCalls);
    if (nextExpanded.has(callId)) {
      nextExpanded.delete(callId);
    } else {
      nextExpanded.add(callId);
    }
    setExpandedModelCalls(nextExpanded);
  };

  useEffect(() => {
    if (!showTranscriptTab && activeTab === 'transcript') {
      selectTab('overview');
    }
    if (!showSpeakerTab && activeTab === 'speakers') {
      selectTab('overview');
    }
    if (!hasAudioSegments && activeTab === 'audio') {
      selectTab('overview');
    }
  }, [activeTab, hasAudioSegments, showSpeakerTab, showTranscriptTab]);

  const formatDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.round(seconds % 60);

    if (hours > 0) {
      return `${hours}h ${minutes}m ${secs}s`;
    }
    return `${minutes}m ${secs}s`;
  };

  const formatBytes = (bytes: number | null) => {
    if (bytes === null || Number.isNaN(bytes)) return 'unknown';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getAdConfidence = (segment: {
    identifications?: Array<{ label: string; confidence: number | null }>;
  }) => {
    const adConfidences = (segment.identifications || [])
      .filter((identification) => identification.label === 'ad' && identification.confidence !== null)
      .map((identification) => identification.confidence as number);

    if (!adConfidences.length) {
      return null;
    }

    return Math.max(...adConfidences);
  };

  const hasSpeakerLabels = useMemo(
    () => (transcriptSegments || []).some((segment) => Boolean(segment.speaker_label)),
    [transcriptSegments]
  );
  const contentViewKey = isLoading
    ? 'loading'
    : error
      ? 'error'
      : stats
        ? activeTab
        : 'empty';
  const bleepBlocks = useMemo(
    () => (stats?.processing_stats?.bleep_windows || []).map((window) => ({
      startTime: window.start_time,
      endTime: window.end_time,
    })),
    [stats?.processing_stats?.bleep_windows]
  );
  const bleepTimeSeconds = stats?.processing_stats?.bleeped_time_seconds
    ?? bleepBlocks.reduce((sum, block) => sum + Math.max(0, block.endTime - block.startTime), 0);
  const originalDurationSeconds = stats?.processing_stats?.original_duration_seconds
    ?? (
      stats?.post?.duration != null
        ? stats.post.duration
        : getFallbackDurationSeconds(transcriptSegments, stats?.processing_stats?.bleep_windows)
    );
  const reportedOriginalSeconds = stats?.processing_stats?.original_duration_seconds;
  const hasOriginalDuration =
    reportedOriginalSeconds != null &&
    stats?.post?.duration != null &&
    Math.abs(reportedOriginalSeconds - stats.post.duration) > 1;
  const editedDurationSeconds = stats?.processing_stats?.edited_duration_seconds
    ?? originalDurationSeconds;
  const editedBleepPercent = editedDurationSeconds > 0
    ? (bleepTimeSeconds / editedDurationSeconds) * 100
    : 0;
  const bleepTimelineSegments = useMemo(() => (stats?.processing_stats?.edited_bleep_windows || []).map((window) => ({
    startTime: window.edited_start_time,
    endTime: window.edited_end_time,
    kind: 'range' as const,
    tooltipTitle: 'Bleeped section',
    tooltipRows: [
      {
        label: 'Edited at',
        value: formatTimelineRange(window.edited_start_time, window.edited_end_time),
      },
      {
        label: 'Original',
        value: formatTimelineRange(window.original_start_time, window.original_end_time),
      },
    ],
    ariaLabel: [
      'Bleeped section.',
      `Edited audio range ${formatTimelineRange(window.edited_start_time, window.edited_end_time)}.`,
      `Source audio range ${formatTimelineRange(window.original_start_time, window.original_end_time)}.`,
    ].join(' '),
  })), [stats?.processing_stats?.edited_bleep_windows]);
  const hasBleepWindows = stats?.processing_stats?.edited_bleep_windows != null
    ? bleepTimelineSegments.length > 0
    : (stats?.processing_stats?.has_bleep_windows ?? bleepBlocks.length > 0);

  return (
    <>
            <StatsHeader onClose={onClose} />

            <StatsTabBarShell>
              {/* Tabs and their counts depend on the stats, so placeholders hold the
                  bar's height until they land instead of tabs shifting in. */}
              {stats ? (
                <nav role="tablist" className="podly-tab-panel-enter flex min-w-max space-x-8 px-6">
                  {[
                    { id: 'overview', label: 'Overview' },
                    ...(hasAudioSegments ? [{ id: 'audio', label: 'Audio segments' }] : []),
                    { id: 'chapters', label: 'Chapters' },
                    ...(showSpeakerTab ? [{ id: 'speakers', label: 'Speakers' }] : []),
                    { id: 'model-calls', label: 'Model calls' },
                    { id: 'logs', label: 'Related logs' },
                    ...(showTranscriptTab ? [{ id: 'transcript', label: 'Transcript' }] : []),
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={activeTab === tab.id}
                      onClick={() => selectTab(tab.id as TabId)}
                      className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                        activeTab === tab.id
                          ? 'border-blue-600 text-blue-700'
                          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                      } shrink-0 whitespace-nowrap`}
                    >
                      {tab.label}
                      {stats && tab.id === 'audio' && ` (${stats.audio_segments?.length || 0})`}
                      {stats && tab.id === 'chapters' && stats.chapters && ` (${stats.chapters.chapters?.length || 0})`}
                      {stats && tab.id === 'speakers' && ` (${stats.processing_stats?.speaker_breakdown?.length || 0})`}
                      {stats && tab.id === 'model-calls' && stats.model_calls && ` (${stats.model_calls.length})`}
                      {stats && tab.id === 'logs' && ` (${stats.related_logs?.entries.length || 0})`}
                      {stats && tab.id === 'transcript' && ` (${stats.transcript_segments?.length || 0})`}
                    </button>
                  ))}
                </nav>
              ) : (
                <StatsTabBarPlaceholder />
              )}
            </StatsTabBarShell>

            <div className="flex-1 min-h-0 overflow-y-auto p-6">
              <div
                key={contentViewKey}
                className="podly-tab-panel-enter min-h-full"
              >
              {isLoading ? (
                showSpinner && <div className="flex min-h-full items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                  <span className="ml-3 text-gray-600">Loading stats...</span>
                </div>
              ) : error ? (
                <div className="flex min-h-full items-center justify-center text-center py-12">
                  <p className="text-red-600">Failed to load processing statistics</p>
                </div>
              ) : stats ? (
                <>
                  {activeTab === 'overview' && (
                    <div ref={overviewRef} className="space-y-6">
                      <div className="bg-gray-50 rounded-lg p-4">
                        <h3 className="font-semibold text-gray-900 mb-2 text-left">Episode information</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Title:</span>
                            <span className="ml-2 text-gray-600">{stats.post?.title || 'Unknown'}</span>
                          </div>
                          <div className="text-left">
                            <span className="font-medium text-gray-700">{hasOriginalDuration ? 'Length:' : 'Duration:'}</span>
                            <span className="ml-2 text-gray-600">
                              {stats.post?.duration
                                ? hasOriginalDuration
                                  ? `${formatDuration(stats.post.duration)} after cuts (original ${formatTimelineLabel(originalDurationSeconds)})`
                                  : formatDuration(stats.post.duration)
                                : 'Unknown'}
                            </span>
                          </div>
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Detection method:</span>
                            <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-sky-100 text-sky-800">
                              {isChapterInsert ? 'Chapter insertion only' : 'Chapter-based removal'}
                            </span>
                          </div>
                        </div>
                      </div>

                      {isChapterInsert && hasBleepWindows && (
                        <ProcessingTimelineSummaryCard
                          title="Bleeps added"
                          itemCount={bleepTimelineSegments.length}
                          itemLabel="Bleeped sections"
                          totalTimeSeconds={bleepTimeSeconds}
                          totalTimeLabel="Time bleeped"
                          percentage={editedBleepPercent}
                          percentageLabel="Of edited audio"
                          durationSeconds={editedDurationSeconds}
                          timelineDurationSeconds={editedDurationSeconds}
                          variant="density"
                          itemNoun={{ one: 'bleep', other: 'bleeps' }}
                          segments={bleepTimelineSegments}
                          segmentClassName="bg-amber-500"
                          legendSegmentLabel={`Bleeps · ${bleepTimelineSegments.length.toLocaleString()} total`}
                        />
                      )}

                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">Key metrics</h3>
                        <div className={`grid grid-cols-2 ${estimatedCost != null ? 'md:grid-cols-4' : 'md:grid-cols-3'} gap-4`}>
                          <div data-stats-tile className="rounded-lg border border-transparent bg-gradient-to-br from-purple-50 to-purple-100 p-4 text-center dark:border-purple-800/70 dark:from-purple-950 dark:to-slate-900">
                            <div className="text-2xl font-bold tabular-nums tracking-tight text-purple-600 dark:text-purple-200">
                              {(stats.chapters?.total_chapters || 0).toLocaleString()}
                            </div>
                            <div className="text-sm text-purple-800 dark:text-purple-100">Total chapters</div>
                          </div>

                          <div data-stats-tile className="rounded-lg border border-transparent bg-gradient-to-br from-green-50 to-green-100 p-4 text-center dark:border-[rgb(22_101_52/0.7)] dark:from-green-950 dark:to-slate-900">
                            <div className="text-2xl font-bold tabular-nums tracking-tight text-green-600">
                              {(stats.chapters?.chapters_kept || 0).toLocaleString()}
                            </div>
                            <div className="text-sm text-green-800">
                              {isChapterInsert ? 'Chapters inserted' : 'Chapters kept'}
                            </div>
                          </div>

                          <div data-stats-tile className="rounded-lg border border-transparent bg-gradient-to-br from-red-50 to-red-100 p-4 text-center dark:border-[rgb(153_27_27/0.7)] dark:from-red-950 dark:to-slate-900">
                            <div className="text-2xl font-bold tabular-nums tracking-tight text-red-600">
                              {(stats.chapters?.chapters_removed || 0).toLocaleString()}
                            </div>
                            <div className="text-sm text-red-800">
                              {isChapterInsert ? 'Chapters removed (N/A)' : 'Chapters removed'}
                            </div>
                          </div>
                          {estimatedCost != null && (
                            <div data-stats-tile className="rounded-lg border border-transparent bg-gradient-to-br from-indigo-50 to-indigo-100 p-4 text-center dark:border-indigo-800/70 dark:from-indigo-950 dark:to-slate-900">
                              <div className="text-2xl font-bold tabular-nums tracking-tight text-indigo-600 dark:text-indigo-200">
                                ${estimatedCost.toFixed(4)}
                              </div>
                              <div className="text-sm text-indigo-800 dark:text-indigo-100" title="Total compute cost = LLM (tokens × LiteLLM rate) + Whisper (hourly rate × episode duration) + INA (hourly rate × episode duration)">Estimated cost</div>
                            </div>
                          )}
                        </div>
                      </div>

                      {isChapterInsert && (
                        <div className="rounded-lg border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900">
                          Chapter insertion mode preserves episode timing and only writes chapter metadata unless profanity bleeping was applied.
                        </div>
                      )}

                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">LLM performance</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                          <div className="bg-surface border rounded-lg p-4">
                            <h4 className="font-medium text-gray-900 mb-3 text-left">Processing status</h4>
                            <div className="space-y-2">
                              {Object.entries(stats.processing_stats?.model_call_statuses || {}).map(([status, count]) => (
                                <div key={status} className="flex justify-between items-center">
                                  <span className="text-sm text-gray-600 capitalize">{status}</span>
                                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                                    status === 'success' ? 'bg-green-100 text-green-800' :
                                    status === 'failed' || status === 'failed_permanent' || status === 'failed_retries' ? 'bg-red-100 text-red-800' :
                                    status === 'cancelled' ? 'bg-gray-200 text-gray-700' :
                                    status === 'retrying' ? 'bg-amber-100 text-amber-800' :
                                    'bg-gray-100 text-gray-800'
                                  }`}>
                                    {count}
                                  </span>
                                </div>
                              ))}
                              {Object.keys(stats.processing_stats?.model_call_statuses || {}).length === 0 && (
                                <p className="text-sm text-gray-500 text-left">No model calls were recorded for this run.</p>
                              )}
                            </div>
                          </div>

                          <div className="bg-surface border rounded-lg p-4">
                            <h4 className="font-medium text-gray-900 mb-3 text-left">
                              Models used ({stats.processing_stats?.total_model_calls || 0} {stats.processing_stats?.total_model_calls === 1 ? 'call' : 'calls'})
                            </h4>
                            <div className="space-y-2">
                              {modelEntries.map(([model, count]) => (
                                <div key={model} className="flex justify-between items-center gap-4">
                                  <span className="text-sm text-gray-600 break-all text-left">{model}</span>
                                  <span className="px-2 py-1 bg-sky-100 text-sky-800 rounded-full text-xs font-medium shrink-0">
                                    {count} {count === 1 ? 'call' : 'calls'}
                                  </span>
                                </div>
                              ))}
                              {modelEntries.length === 0 && (
                                <p className="text-sm text-gray-500 text-left">No model calls were recorded for this run.</p>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>

                      {!isChapterInsert && (stats.chapters?.filter_strings ?? []).length > 0 && (
                        <div>
                          <h3 className="font-semibold text-gray-900 mb-4 text-left">Filter strings</h3>
                          <div className="bg-surface border rounded-lg p-4">
                            <div className="flex flex-wrap gap-2">
                              {(stats.chapters?.filter_strings ?? []).map((filter: string, idx: number) => (
                                <span key={idx} className="px-3 py-1 bg-gray-100 text-gray-700 rounded-full text-sm">
                                  {filter}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}

                      {stats.debug_info && (
                        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                          <h3 className="font-semibold text-gray-900 mb-2 text-left">Debug details</h3>
                          <p className="text-xs text-gray-600 mb-4 text-left">
                            Visible because <code>PODLY_STATS_DEBUG</code> is enabled.
                          </p>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                            <div className="text-left">
                              <span className="font-medium text-gray-700">GUID:</span>
                              <span className="ml-2 text-gray-600 font-mono break-all">{stats.debug_info.guid}</span>
                            </div>
                            <div className="text-left">
                              <span className="font-medium text-gray-700">Post ID / Feed ID:</span>
                              <span className="ml-2 text-gray-600">{stats.debug_info.post_id} / {stats.debug_info.feed_id}</span>
                            </div>
                            <div className="text-left md:col-span-2">
                              <span className="font-medium text-gray-700">Download URL:</span>
                              <span className="ml-2 text-gray-600 font-mono break-all">{stats.debug_info.download_url}</span>
                            </div>
                            <div className="text-left md:col-span-2">
                              <span className="font-medium text-gray-700">Processed audio path:</span>
                              <span className="ml-2 text-gray-600 font-mono break-all">
                                {stats.debug_info.processed_audio.path || 'missing'}
                              </span>
                              <div className="text-xs text-gray-500 mt-1">
                                {stats.debug_info.processed_audio.exists
                                  ? `exists (${formatBytes(stats.debug_info.processed_audio.size_bytes)})`
                                  : 'missing'}
                              </div>
                            </div>
                            <div className="text-left md:col-span-2">
                              <span className="font-medium text-gray-700">Unprocessed audio path:</span>
                              <span className="ml-2 text-gray-600 font-mono break-all">
                                {stats.debug_info.unprocessed_audio.path || 'missing'}
                              </span>
                              <div className="text-xs text-gray-500 mt-1">
                                {stats.debug_info.unprocessed_audio.exists
                                  ? `exists (${formatBytes(stats.debug_info.unprocessed_audio.size_bytes)})`
                                  : 'missing'}
                              </div>
                            </div>
                            <div className="text-left md:col-span-2">
                              <span className="font-medium text-gray-700">Data roots:</span>
                              <span className="ml-2 text-gray-600 font-mono break-all">
                                in: {stats.debug_info.processing_roots.in_root} | srv: {stats.debug_info.processing_roots.srv_root}
                              </span>
                            </div>
                            <div className="text-left">
                              <span className="font-medium text-gray-700">Record counts:</span>
                              <span className="ml-2 text-gray-600">
                                segments {stats.debug_info.record_counts.transcript_segments}, calls {stats.debug_info.record_counts.model_calls}, ids {stats.debug_info.record_counts.identifications}
                              </span>
                            </div>
                          </div>

                          <div className="mt-4">
                            <h4 className="font-medium text-gray-900 mb-2 text-left">Processed audio path candidates</h4>
                            {(stats.debug_info.processed_audio_path_candidates || []).length === 0 ? (
                              <p className="text-xs text-gray-500 text-left">No candidates derived.</p>
                            ) : (
                              <div className="space-y-2">
                                {(stats.debug_info.processed_audio_path_candidates || []).map((candidate, idx) => (
                                  <div key={`${candidate.path}-${idx}`} className="bg-surface rounded p-2">
                                    <div className="font-mono text-xs text-gray-700 break-all text-left">{candidate.path}</div>
                                    <div className="text-xs text-gray-500 mt-1 text-left">
                                      {candidate.exists ? `exists (${formatBytes(candidate.size_bytes)})` : 'missing'}
                                      {candidate.error ? ` - ${candidate.error}` : ''}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'chapters' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Chapters ({stats.chapters?.chapters?.length || 0})</h3>
                      <div className="bg-surface border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead>
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">#</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Title</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Time range</th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-600">Duration</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Status</th>
                              </tr>
                            </thead>
                            <tbody className="bg-surface divide-y divide-gray-200">
                              {(stats.chapters?.chapters || []).map((chapter: { title: string; start_time: number; end_time: number; label: string }, idx: number) => (
                                <tr key={idx} className={`hover:bg-gray-50 ${
                                  chapter.label === 'ad' && !isChapterInsert ? 'bg-red-50' : ''
                                }`}>
                                  <td className="px-4 py-3 text-sm text-gray-900">{idx + 1}</td>
                                  <td className="px-4 py-3 text-sm text-gray-900 font-medium">{chapter.title}</td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {chapter.start_time}s - {chapter.end_time}s
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {Math.round(chapter.end_time - chapter.start_time)}s
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                      chapter.label === 'ad'
                                        ? 'bg-red-100 text-red-800'
                                        : 'bg-green-100 text-green-800'
                                    }`}>
                                      {chapter.label === 'ad'
                                        ? (isChapterInsert ? 'Excluded' : 'Removed')
                                        : (isChapterInsert ? 'Included' : 'Kept')}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                      {stats.chapters?.note && (
                        <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                          Note: {stats.chapters.note}
                        </div>
                      )}
                      {(!stats.chapters?.chapters || stats.chapters.chapters.length === 0) && (
                        <div className="text-center py-8 text-gray-500">
                          No chapter data available.
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'model-calls' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Model calls ({stats.model_calls?.length || 0})</h3>
                      <div className="bg-surface border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead>
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Model</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Range / Phase</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Status</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Tier</th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-600" title="prompt + cached prompt + completion = total tokens">Tokens</th>
                                {showCostColumn && (
                                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-600" title="USD cost for this call (LLM = tokens × LiteLLM rate; Whisper/INA = hourly rate × episode duration, split across success rows of that type)">Cost</th>
                                )}
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Timestamp</th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-600">Retries</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Actions</th>
                              </tr>
                            </thead>
                            <tbody className="bg-surface divide-y divide-gray-200">
                              {(stats.model_calls || []).map((call) => {
                                const tokenTotal = call.prompt_tokens != null || call.cached_prompt_tokens != null || call.completion_tokens != null
                                  ? (call.prompt_tokens ?? 0) + (call.cached_prompt_tokens ?? 0) + (call.completion_tokens ?? 0)
                                  : call.total_tokens;

                                return (
                                  <Fragment key={call.id}>
                                    <tr className="hover:bg-gray-50">
                                      <td className="px-4 py-3 text-sm text-gray-900">{call.id}</td>
                                      <td className="px-4 py-3 text-sm text-gray-900 break-all">{call.model_name}</td>
                                      <td className="px-4 py-3 text-sm text-gray-600">{call.segment_range}</td>
                                      <td className="px-4 py-3">
                                        <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                          call.status === 'success' ? 'bg-green-100 text-green-800' :
                                          call.status === 'failed' || call.status === 'failed_permanent' || call.status === 'failed_retries' ? 'bg-red-100 text-red-800' :
                                          call.status === 'cancelled' ? 'bg-gray-200 text-gray-700' :
                                          call.status === 'retrying' ? 'bg-amber-100 text-amber-800' :
                                          'bg-amber-100 text-amber-800'
                                        }`}>
                                          {call.status}
                                        </span>
                                      </td>
                                      <td className="px-4 py-3 text-sm">
                                        {call.service_tier ? (
                                          <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                            call.service_tier === 'flex' ? 'bg-gray-200 text-gray-800' :
                                            call.service_tier === 'priority' ? 'bg-sky-100 text-sky-800' :
                                            'bg-gray-100 text-gray-700'
                                          }`}>
                                            {call.service_tier}
                                          </span>
                                        ) : (
                                          <span className="text-gray-400">—</span>
                                        )}
                                      </td>
                                      <td className="px-4 py-3 text-sm text-gray-600">
                                        {tokenTotal != null ? (
                                          <span title={`prompt ${call.prompt_tokens ?? '—'} + cached prompt ${call.cached_prompt_tokens ?? '—'} + completion ${call.completion_tokens ?? '—'}`}>
                                            {tokenTotal.toLocaleString()}
                                          </span>
                                        ) : (
                                          <span className="text-gray-400">—</span>
                                        )}
                                      </td>
                                      {showCostColumn && (
                                        <td className="px-4 py-3 text-right text-sm tabular-nums text-gray-600">
                                          {call.estimated_cost_usd != null ? (
                                            `$${call.estimated_cost_usd.toFixed(4)}`
                                          ) : (
                                            <span className="text-gray-400">—</span>
                                          )}
                                        </td>
                                      )}
                                      <td className="px-4 py-3 text-sm text-gray-600">{formatTimestamp(call.timestamp)}</td>
                                      <td className="px-4 py-3 text-right text-sm tabular-nums text-gray-600">{call.retry_count}</td>
                                      <td className="px-4 py-3">
                                        <button
                                          onClick={() => toggleModelCallDetails(call.id)}
                                          className="btn btn-secondary btn-sm"
                                        >
                                          {expandedModelCalls.has(call.id) ? 'Hide' : 'Details'}
                                        </button>
                                      </td>
                                    </tr>
                                    {expandedModelCalls.has(call.id) && (
                                      <tr className="bg-gray-50">
                                        <td colSpan={showCostColumn ? 10 : 9} className="px-4 py-4">
                                          <div className="space-y-4">
                                            {call.prompt && (
                                              <div>
                                                <h5 className="font-medium text-gray-900 mb-2 text-left">Prompt:</h5>
                                                <div className="bg-gray-100 p-3 rounded text-sm font-mono whitespace-pre-wrap max-h-40 overflow-y-auto text-left">
                                                  {call.prompt}
                                                </div>
                                              </div>
                                            )}
                                            {call.error_message && (
                                              <div>
                                                <h5 className="font-medium text-red-900 mb-2 text-left">Error message:</h5>
                                                <div className="bg-red-50 p-3 rounded text-sm font-mono whitespace-pre-wrap text-left">
                                                  {call.error_message}
                                                </div>
                                              </div>
                                            )}
                                            {call.response && (
                                              <div>
                                                <h5 className="font-medium text-gray-900 mb-2 text-left">Response:</h5>
                                                <div className="bg-gray-100 p-3 rounded text-sm font-mono whitespace-pre-wrap max-h-40 overflow-y-auto text-left">
                                                  {call.response}
                                                </div>
                                              </div>
                                            )}
                                          </div>
                                        </td>
                                      </tr>
                                    )}
                                  </Fragment>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === 'audio' && hasAudioSegments && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">
                        Audio segments ({stats.audio_segments?.length || 0})
                      </h3>
                      <div className="bg-surface border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead>
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Time range</th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-600">Duration</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Label</th>
                              </tr>
                            </thead>
                            <tbody className="bg-surface divide-y divide-gray-200">
                              {(stats.audio_segments || []).map((segment) => (
                                <tr key={segment.id} className="hover:bg-gray-50">
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {segment.start_time}s - {segment.end_time}s
                                  </td>
                                  <td className="px-4 py-3 text-right text-sm tabular-nums text-gray-600">
                                    {formatDuration(Math.max(0, segment.end_time - segment.start_time))}
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className="inline-flex px-2 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-700">
                                      {segment.label}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === 'logs' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">
                        Related logs ({stats.related_logs?.entries.length || 0})
                      </h3>
                      <ProcessingStageLogs relatedLogs={stats.related_logs} />
                    </div>
                  )}

                  {activeTab === 'speakers' && showSpeakerTab && (
                    <div>
                      <SpeakerTimeBreakdown
                        speakerBreakdown={stats.processing_stats?.speaker_breakdown}
                      />
                    </div>
                  )}

                  {activeTab === 'transcript' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">
                        Transcript segments ({stats.transcript_segments?.length || 0})
                      </h3>
                      {(!stats.transcript_segments || stats.transcript_segments.length === 0) ? (
                        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                          No transcript segments were generated for this episode.
                        </div>
                      ) : (
                        <div className="bg-surface border rounded-lg overflow-hidden">
                          <div className="overflow-x-auto">
                            <table className="min-w-full divide-y divide-gray-200">
                              <thead>
                                <tr>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">#</th>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Start</th>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">End</th>
                                  {hasSpeakerLabels && (
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Speaker</th>
                                  )}
                                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-600">Ad confidence</th>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Text</th>
                                </tr>
                              </thead>
                              <tbody className="bg-surface divide-y divide-gray-200">
                                {(stats.transcript_segments || []).slice(0, visibleRows).map((segment, idx) => {
                                  const adConfidence = getAdConfidence(segment);

                                  return (
                                    <tr key={segment.id ?? idx} className="hover:bg-gray-50">
                                      <td className="px-4 py-3 text-sm text-gray-900">{segment.sequence_num}</td>
                                      <td className="px-4 py-3 text-sm text-gray-600">{segment.start_time}s</td>
                                      <td className="px-4 py-3 text-sm text-gray-600">{segment.end_time}s</td>
                                      {hasSpeakerLabels && (
                                        <td className="px-4 py-3 text-sm text-gray-600">
                                          {segment.speaker_label ? (
                                            <span className="inline-flex items-center rounded-full bg-gray-100 border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700">
                                              {segment.speaker_label}
                                            </span>
                                          ) : (
                                            <span className="text-gray-400">-</span>
                                          )}
                                        </td>
                                      )}
                                      <td className="px-4 py-3 text-right text-sm tabular-nums text-gray-600">
                                        {adConfidence !== null ? adConfidence.toFixed(2) : '-'}
                                      </td>
                                      <td className="px-4 py-3 text-sm text-gray-700 min-w-[28rem] max-w-4xl">
                                        <div className="whitespace-pre-wrap break-words text-left leading-6">
                                          {segment.text}
                                        </div>
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                      {(stats.transcript_segments?.length || 0) > 0 && (
                        <ShowMoreRows shown={visibleRows} total={stats.transcript_segments?.length || 0} onShowMore={showMoreRows} />
                      )}
                    </div>
                  )}
                </>
              ) : null}
              </div>
            </div>
    </>
  );
}
