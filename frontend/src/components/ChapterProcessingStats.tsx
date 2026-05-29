import { Fragment, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import ModalShell from './ModalShell';
import ProcessingTimelineSummaryCard from './ProcessingTimelineSummaryCard';
import ProcessingStageLogs from './ProcessingStageLogs';
import SpeakerTimeBreakdown from './SpeakerTimeBreakdown';
import { formatBackendDateTime } from '../utils/datetime';
import {
  formatTimelineRange,
} from '../utils/processingTimeline';

interface ChapterProcessingStatsProps {
  episodeGuid: string;
  hasProcessedAudio: boolean;
  className?: string;
}

type TabId = 'overview' | 'audio' | 'chapters' | 'speakers' | 'model-calls' | 'transcript' | 'logs';

export default function ChapterProcessingStats({
  episodeGuid,
  hasProcessedAudio,
  className = ''
}: ChapterProcessingStatsProps) {
  const [showModal, setShowModal] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [expandedModelCalls, setExpandedModelCalls] = useState<Set<number>>(new Set());

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['episode-stats', episodeGuid],
    queryFn: () => feedsApi.getPostStats(episodeGuid),
    enabled: showModal && hasProcessedAudio,
  });
  const isChapterInsert = stats?.ad_detection_strategy === 'chapter_insert';
  const showTranscriptTab = isChapterInsert;
  const showSpeakerTab = isChapterInsert
    && (stats?.processing_stats?.speaker_breakdown?.length || 0) > 0;
  const hasAudioSegments = (stats?.audio_segments?.length || 0) > 0;
  const modelEntries = Object.entries(stats?.processing_stats?.model_types || {});
  const estimatedCost = stats?.processing_stats?.estimated_cost;

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
      setActiveTab('overview');
    }
    if (!showSpeakerTab && activeTab === 'speakers') {
      setActiveTab('overview');
    }
    if (!hasAudioSegments && activeTab === 'audio') {
      setActiveTab('overview');
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

  const hasSpeakerLabels = (stats?.transcript_segments || []).some(
    (segment) => Boolean(segment.speaker_label)
  );
  const contentViewKey = isLoading
    ? 'loading'
    : error
      ? 'error'
      : stats
        ? activeTab
        : 'empty';
  const durationFallbackCandidates = [
    ...(stats?.transcript_segments || []).map((segment) => segment.end_time),
    ...((stats?.processing_stats?.bleep_windows || []).map((window) => window.end_time)),
  ];
  const fallbackDurationSeconds = durationFallbackCandidates.length
    ? Math.max(...durationFallbackCandidates)
    : 0;
  const bleepBlocks = (stats?.processing_stats?.bleep_windows || []).map((window) => ({
    startTime: window.start_time,
    endTime: window.end_time,
  }));
  const bleepTimeSeconds = stats?.processing_stats?.bleeped_time_seconds
    ?? bleepBlocks.reduce((sum, block) => sum + Math.max(0, block.endTime - block.startTime), 0);
  const originalDurationSeconds = stats?.processing_stats?.original_duration_seconds
    ?? (
      stats?.post?.duration != null
        ? stats.post.duration
        : fallbackDurationSeconds
    );
  const editedDurationSeconds = stats?.processing_stats?.edited_duration_seconds
    ?? originalDurationSeconds;
  const editedBleepPercent = editedDurationSeconds > 0
    ? (bleepTimeSeconds / editedDurationSeconds) * 100
    : 0;
  const bleepTimelineSegments = (stats?.processing_stats?.edited_bleep_windows || []).map((window) => ({
    startTime: (window.edited_start_time + window.edited_end_time) / 2,
    endTime: (window.edited_start_time + window.edited_end_time) / 2,
    kind: 'point' as const,
    visualDurationSeconds: Math.max(0, window.edited_end_time - window.edited_start_time),
    tooltipTitle: 'Bleeped Section',
    tooltipRows: [
      {
        label: 'Edited',
        value: formatTimelineRange(window.edited_start_time, window.edited_end_time),
      },
      {
        label: 'Source',
        value: formatTimelineRange(window.original_start_time, window.original_end_time),
      },
    ],
    ariaLabel: [
      'Bleeped section.',
      `Edited audio range ${formatTimelineRange(window.edited_start_time, window.edited_end_time)}.`,
      `Source audio range ${formatTimelineRange(window.original_start_time, window.original_end_time)}.`,
    ].join(' '),
  }));
  const hasBleepWindows = stats?.processing_stats?.edited_bleep_windows != null
    ? bleepTimelineSegments.length > 0
    : (stats?.processing_stats?.has_bleep_windows ?? bleepBlocks.length > 0);

  if (!hasProcessedAudio) {
    return null;
  }

  return (
    <>
      <button
        onClick={() => setShowModal(true)}
        className={`px-3 py-1 text-xs rounded font-medium transition-colors border bg-white text-gray-700 border-gray-300 hover:bg-gray-50 hover:border-gray-400 hover:text-gray-900 flex items-center gap-1 ${className}`}
      >
        Stats
      </button>

      <ModalShell
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        panelClassName="bg-white rounded-lg w-full max-w-7xl xl:max-w-[96rem] 2xl:max-w-[110rem] flex h-[85dvh] max-h-[85dvh] flex-col overflow-hidden sm:h-[82dvh] sm:max-h-[82dvh] lg:h-[min(88dvh,58rem)] lg:max-h-[min(88dvh,58rem)] xl:h-[min(90dvh,62rem)] xl:max-h-[min(90dvh,62rem)]"
      >
            <div className="flex items-center justify-between p-6 border-b">
              <h2 className="text-xl font-bold text-gray-900 text-left">Processing Statistics & Debug</h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="border-b overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
              <nav className="flex min-w-max space-x-8 px-6">
                {[
                  { id: 'overview', label: 'Overview' },
                  ...(hasAudioSegments ? [{ id: 'audio', label: 'Audio Segments' }] : []),
                  { id: 'chapters', label: 'Chapters' },
                  ...(showSpeakerTab ? [{ id: 'speakers', label: 'Speakers' }] : []),
                  { id: 'model-calls', label: 'Model Calls' },
                  { id: 'logs', label: 'Related Logs' },
                  ...(showTranscriptTab ? [{ id: 'transcript', label: 'Transcript' }] : []),
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id as TabId)}
                    className={`py-4 px-1 border-b-2 font-medium text-sm ${
                      activeTab === tab.id
                        ? 'border-blue-500 text-blue-600'
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
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-6">
              <div
                key={contentViewKey}
                className="podly-tab-panel-enter min-h-full"
              >
              {isLoading ? (
                <div className="flex min-h-full items-center justify-center py-12">
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
                    <div className="space-y-6">
                      <div className="bg-gray-50 rounded-lg p-4">
                        <h3 className="font-semibold text-gray-900 mb-2 text-left">Episode Information</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Title:</span>
                            <span className="ml-2 text-gray-600">{stats.post?.title || 'Unknown'}</span>
                          </div>
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Duration:</span>
                            <span className="ml-2 text-gray-600">
                              {stats.post?.duration ? formatDuration(stats.post.duration) : 'Unknown'}
                            </span>
                          </div>
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Detection Method:</span>
                            <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                              {isChapterInsert ? 'Chapter insertion only' : 'Chapter-based removal'}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">Key Metrics</h3>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                          <div className="rounded-lg border border-transparent bg-gradient-to-br from-purple-50 to-purple-100 p-4 text-center dark:border-purple-800/70 dark:from-purple-950 dark:to-slate-900">
                            <div className="text-2xl font-bold text-purple-600 dark:text-purple-200">
                              {stats.chapters?.total_chapters || 0}
                            </div>
                            <div className="text-sm text-purple-800 dark:text-purple-100">Total Chapters</div>
                          </div>

                          <div className="rounded-lg border border-transparent bg-gradient-to-br from-green-50 to-green-100 p-4 text-center dark:border-green-800/70 dark:from-green-950 dark:to-slate-900">
                            <div className="text-2xl font-bold text-green-600 dark:text-green-200">
                              {stats.chapters?.chapters_kept || 0}
                            </div>
                            <div className="text-sm text-green-800 dark:text-green-100">
                              {isChapterInsert ? 'Chapters Inserted' : 'Chapters Kept'}
                            </div>
                          </div>

                          <div className="rounded-lg border border-transparent bg-gradient-to-br from-red-50 to-red-100 p-4 text-center dark:border-red-800/70 dark:from-red-950 dark:to-slate-900">
                            <div className="text-2xl font-bold text-red-600 dark:text-red-200">
                              {stats.chapters?.chapters_removed || 0}
                            </div>
                            <div className="text-sm text-red-800 dark:text-red-100">
                              {isChapterInsert ? 'Chapters Removed (N/A)' : 'Chapters Removed'}
                            </div>
                          </div>
                          {estimatedCost != null && (
                            <div className="rounded-lg border border-transparent bg-gradient-to-br from-indigo-50 to-indigo-100 p-4 text-center dark:border-indigo-800/70 dark:from-indigo-950 dark:to-slate-900">
                              <div className="text-2xl font-bold text-indigo-600 dark:text-indigo-200">
                                ${estimatedCost.toFixed(4)}
                              </div>
                              <div className="text-sm text-indigo-800 dark:text-indigo-100">Estimated LLM Cost</div>
                            </div>
                          )}
                        </div>
                      </div>

                      {isChapterInsert && (
                        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
                          Chapter insertion mode preserves episode timing and only writes chapter metadata unless profanity bleeping was applied.
                        </div>
                      )}

                      {isChapterInsert && hasBleepWindows && (
                        <ProcessingTimelineSummaryCard
                          title="Bleeps Added"
                          itemCount={bleepTimelineSegments.length}
                          itemLabel="Bleeped Sections"
                          totalTimeSeconds={bleepTimeSeconds}
                          totalTimeLabel="Time Bleeped"
                          percentage={editedBleepPercent}
                          percentageLabel="Edited Audio Bleeped"
                          durationSeconds={editedDurationSeconds}
                          timelineDurationSeconds={originalDurationSeconds}
                          minimumSegmentWidthPx={2}
                          minimumPointWidthPx={6}
                          segments={bleepTimelineSegments}
                          metricAccentClassName="text-amber-600 dark:text-amber-200"
                          percentageAccentClassName="text-amber-700 dark:text-amber-300"
                          tooltipAccentClassName="text-amber-700 dark:text-amber-300"
                          segmentClassName="bg-amber-500 dark:bg-amber-400"
                          legendBaseLabel="Unbleeped audio"
                          legendSegmentLabel="Bleep markers"
                        />
                      )}

                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">AI Model Performance</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                          <div className="bg-white border rounded-lg p-4">
                            <h4 className="font-medium text-gray-900 mb-3 text-left">Processing Status</h4>
                            <div className="space-y-2">
                              {Object.entries(stats.processing_stats?.model_call_statuses || {}).map(([status, count]) => (
                                <div key={status} className="flex justify-between items-center">
                                  <span className="text-sm text-gray-600 capitalize">{status}</span>
                                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                                    status === 'success' ? 'bg-green-100 text-green-800' :
                                    status === 'failed' || status === 'failed_permanent' || status === 'failed_retries' ? 'bg-red-100 text-red-800' :
                                    status === 'cancelled' ? 'bg-gray-200 text-gray-700' :
                                    status === 'retrying' ? 'bg-orange-100 text-orange-800' :
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

                          <div className="bg-white border rounded-lg p-4">
                            <h4 className="font-medium text-gray-900 mb-3 text-left">
                              Models Used ({stats.processing_stats?.total_model_calls || 0} calls)
                            </h4>
                            <div className="space-y-2">
                              {modelEntries.map(([model, count]) => (
                                <div key={model} className="flex justify-between items-center gap-4">
                                  <span className="text-sm text-gray-600 break-all text-left">{model}</span>
                                  <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium shrink-0">
                                    {count} calls
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
                          <h3 className="font-semibold text-gray-900 mb-4 text-left">Filter Strings</h3>
                          <div className="bg-white border rounded-lg p-4">
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
                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                          <h3 className="font-semibold text-gray-900 mb-2 text-left">Debug Details</h3>
                          <p className="text-xs text-amber-700 mb-4 text-left">
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
                              <span className="font-medium text-gray-700">Processed Audio Path:</span>
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
                              <span className="font-medium text-gray-700">Unprocessed Audio Path:</span>
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
                              <span className="font-medium text-gray-700">Data Roots:</span>
                              <span className="ml-2 text-gray-600 font-mono break-all">
                                in: {stats.debug_info.processing_roots.in_root} | srv: {stats.debug_info.processing_roots.srv_root}
                              </span>
                            </div>
                            <div className="text-left">
                              <span className="font-medium text-gray-700">Record Counts:</span>
                              <span className="ml-2 text-gray-600">
                                segments {stats.debug_info.record_counts.transcript_segments}, calls {stats.debug_info.record_counts.model_calls}, ids {stats.debug_info.record_counts.identifications}
                              </span>
                            </div>
                          </div>

                          <div className="mt-4">
                            <h4 className="font-medium text-gray-900 mb-2 text-left">Processed Audio Path Candidates</h4>
                            {(stats.debug_info.processed_audio_path_candidates || []).length === 0 ? (
                              <p className="text-xs text-gray-500 text-left">No candidates derived.</p>
                            ) : (
                              <div className="space-y-2">
                                {(stats.debug_info.processed_audio_path_candidates || []).map((candidate, idx) => (
                                  <div key={`${candidate.path}-${idx}`} className="bg-white border border-amber-100 rounded p-2">
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
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">#</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Title</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Duration</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
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
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Model Calls ({stats.model_calls?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Range / Phase</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Tier</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider" title="prompt + cached prompt + completion = total tokens">Tokens</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Timestamp</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Retries</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
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
                                          call.status === 'retrying' ? 'bg-orange-100 text-orange-800' :
                                          'bg-yellow-100 text-yellow-800'
                                        }`}>
                                          {call.status}
                                        </span>
                                      </td>
                                      <td className="px-4 py-3 text-sm">
                                        {call.service_tier ? (
                                          <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                            call.service_tier === 'flex' ? 'bg-purple-100 text-purple-800' :
                                            call.service_tier === 'priority' ? 'bg-blue-100 text-blue-800' :
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
                                      <td className="px-4 py-3 text-sm text-gray-600">{formatTimestamp(call.timestamp)}</td>
                                      <td className="px-4 py-3 text-sm text-gray-600">{call.retry_count}</td>
                                      <td className="px-4 py-3">
                                        <button
                                          onClick={() => toggleModelCallDetails(call.id)}
                                          className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                                        >
                                          {expandedModelCalls.has(call.id) ? 'Hide' : 'Details'}
                                        </button>
                                      </td>
                                    </tr>
                                    {expandedModelCalls.has(call.id) && (
                                      <tr className="bg-gray-50">
                                        <td colSpan={9} className="px-4 py-4">
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
                                                <h5 className="font-medium text-red-900 mb-2 text-left">Error Message:</h5>
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
                        Audio Segments ({stats.audio_segments?.length || 0})
                      </h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Duration</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Label</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.audio_segments || []).map((segment) => (
                                <tr key={segment.id} className="hover:bg-gray-50">
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {segment.start_time}s - {segment.end_time}s
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {formatDuration(Math.max(0, segment.end_time - segment.start_time))}
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className="inline-flex px-2 py-1 text-xs font-medium rounded-full bg-slate-100 text-slate-700">
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
                        Related Logs ({stats.related_logs?.entries.length || 0})
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
                        Transcript Segments ({stats.transcript_segments?.length || 0})
                      </h3>
                      {(!stats.transcript_segments || stats.transcript_segments.length === 0) ? (
                        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                          No transcript segments were generated for this episode.
                        </div>
                      ) : (
                        <div className="bg-white border rounded-lg overflow-hidden">
                          <div className="overflow-x-auto">
                            <table className="min-w-full divide-y divide-gray-200">
                              <thead className="bg-gray-50">
                                <tr>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">#</th>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Start</th>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">End</th>
                                  {hasSpeakerLabels && (
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Speaker</th>
                                  )}
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Ad Confidence</th>
                                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Text</th>
                                </tr>
                              </thead>
                              <tbody className="bg-white divide-y divide-gray-200">
                                {(stats.transcript_segments || []).map((segment, idx) => {
                                  const adConfidence = getAdConfidence(segment);

                                  return (
                                    <tr key={segment.id ?? idx} className="hover:bg-gray-50">
                                      <td className="px-4 py-3 text-sm text-gray-900">{segment.sequence_num}</td>
                                      <td className="px-4 py-3 text-sm text-gray-600">{segment.start_time}s</td>
                                      <td className="px-4 py-3 text-sm text-gray-600">{segment.end_time}s</td>
                                      {hasSpeakerLabels && (
                                        <td className="px-4 py-3 text-sm text-gray-600">
                                          {segment.speaker_label ? (
                                            <span className="inline-flex items-center rounded-full bg-indigo-50 border border-indigo-200 px-2.5 py-1 text-xs font-medium text-indigo-700">
                                              {segment.speaker_label}
                                            </span>
                                          ) : (
                                            <span className="text-gray-400">-</span>
                                          )}
                                        </td>
                                      )}
                                      <td className="px-4 py-3 text-sm text-gray-600">
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
                    </div>
                  )}
                </>
              ) : null}
              </div>
            </div>
      </ModalShell>
    </>
  );
}
