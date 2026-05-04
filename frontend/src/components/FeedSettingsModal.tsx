import { useState, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import type { Feed, FeedSettingsUpdate } from '../types';

interface FeedSettingsModalProps {
  feed: Feed;
  isOpen: boolean;
  onClose: () => void;
  autoWhitelistGlobalDefault?: boolean;
  llmChapterFallbackGlobalDefault?: boolean;
  globalFeedTagLabel?: string;
  globalFeedTagPosition?: string;
  globalFeedTagOverride?: boolean;
  episodeDescriptionOverride?: 'source' | 'podly' | null;
  globalEpisodeDescriptionView?: 'source' | 'podly';
  onEpisodeDescriptionViewChange?: (view: 'source' | 'podly' | null) => void;
}

const DEFAULT_FILTER_STRINGS = 'sponsor,advertisement,ad break,promo,brought to you by';

const selectClass =
  'w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 ' +
  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 ' +
  'disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-500';

function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="relative group inline-flex items-center ml-1.5 cursor-help">
      <svg
        className="w-3.5 h-3.5 text-gray-400 group-hover:text-gray-500 transition-colors"
        fill="currentColor"
        viewBox="0 0 20 20"
      >
        <path
          fillRule="evenodd"
          d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
          clipRule="evenodd"
        />
      </svg>
      <span
        className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-60 px-2.5 py-1.5
          text-xs text-white bg-gray-800 rounded-lg shadow-lg leading-relaxed
          opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-20"
      >
        {text}
      </span>
    </span>
  );
}

function FieldLabel({
  children,
  tooltip,
  htmlFor,
}: {
  children: React.ReactNode;
  tooltip: string;
  htmlFor?: string;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="flex items-center text-sm font-medium text-gray-700 mb-2"
    >
      {children}
      <InfoTooltip text={tooltip} />
    </label>
  );
}

export default function FeedSettingsModal({
  feed,
  isOpen,
  onClose,
  autoWhitelistGlobalDefault,
  llmChapterFallbackGlobalDefault,
  globalFeedTagLabel = '',
  globalFeedTagPosition = 'suffix',
  globalFeedTagOverride = false,
  episodeDescriptionOverride = null,
  globalEpisodeDescriptionView = 'source',
  onEpisodeDescriptionViewChange,
}: FeedSettingsModalProps) {
  const queryClient = useQueryClient();

  const [strategy, setStrategy] = useState<'llm' | 'chapter' | 'chapter_insert'>(
    feed.ad_detection_strategy || 'llm'
  );
  const [filterStrings, setFilterStrings] = useState(
    feed.chapter_filter_strings || DEFAULT_FILTER_STRINGS
  );
  const [chapterFallbackOverride, setChapterFallbackOverride] = useState<'inherit' | 'on' | 'off'>(
    feed.enable_llm_chapter_fallback_tagging === true
      ? 'on'
      : feed.enable_llm_chapter_fallback_tagging === false
        ? 'off'
        : 'inherit'
  );
  const [autoWhitelistOverride, setAutoWhitelistOverride] = useState<'inherit' | 'on' | 'off'>(
    feed.auto_whitelist_new_episodes_override === true
      ? 'on'
      : feed.auto_whitelist_new_episodes_override === false
        ? 'off'
        : 'inherit'
  );
  const [feedTagLabel, setFeedTagLabel] = useState<string>(feed.feed_tag_label ?? '');
  const [feedTagPosition, setFeedTagPosition] = useState<string>(feed.feed_tag_position ?? '');
  // null = use global default
  const [descriptionViewOverride, setDescriptionViewOverride] = useState<
    'source' | 'podly' | null
  >(episodeDescriptionOverride);

  useEffect(() => {
    setStrategy(feed.ad_detection_strategy || 'llm');
    setFilterStrings(feed.chapter_filter_strings || DEFAULT_FILTER_STRINGS);
    setChapterFallbackOverride(
      feed.enable_llm_chapter_fallback_tagging === true
        ? 'on'
        : feed.enable_llm_chapter_fallback_tagging === false
          ? 'off'
          : 'inherit'
    );
    setAutoWhitelistOverride(
      feed.auto_whitelist_new_episodes_override === true
        ? 'on'
        : feed.auto_whitelist_new_episodes_override === false
          ? 'off'
          : 'inherit'
    );
    setFeedTagLabel(feed.feed_tag_label ?? '');
    setFeedTagPosition(feed.feed_tag_position ?? '');
    setDescriptionViewOverride(episodeDescriptionOverride);
  }, [feed, llmChapterFallbackGlobalDefault, episodeDescriptionOverride]);

  // Track the pending localStorage change so we can apply it only after a
  // successful API call (avoids an unrollback-able local state change on error).
  const pendingDescViewRef = useRef<{ value: 'source' | 'podly' | null; changed: boolean }>({
    value: null,
    changed: false,
  });

  const updateMutation = useMutation({
    mutationFn: (settings: FeedSettingsUpdate) =>
      feedsApi.updateFeedSettings(feed.id, settings),
    onSuccess: () => {
      // Apply the localStorage-only preference only once the API call succeeds.
      if (pendingDescViewRef.current.changed) {
        onEpisodeDescriptionViewChange?.(pendingDescViewRef.current.value);
      }
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      onClose();
    },
  });

  const currentStrategy = feed.ad_detection_strategy || 'llm';
  const currentFilterStrings = feed.chapter_filter_strings || DEFAULT_FILTER_STRINGS;
  const currentChapterFallbackOverride =
    feed.enable_llm_chapter_fallback_tagging === true
      ? 'on'
      : feed.enable_llm_chapter_fallback_tagging === false
        ? 'off'
        : 'inherit';
  const currentAutoWhitelistOverride =
    feed.auto_whitelist_new_episodes_override === true
      ? 'on'
      : feed.auto_whitelist_new_episodes_override === false
        ? 'off'
        : 'inherit';

  const handleSave = () => {
    const settings: FeedSettingsUpdate = {};

    if (strategy !== currentStrategy) {
      settings.ad_detection_strategy = strategy;
    }
    if (strategy === 'chapter' && filterStrings !== currentFilterStrings) {
      settings.chapter_filter_strings = filterStrings || null;
    }
    if (strategy !== 'chapter_insert' && chapterFallbackOverride !== currentChapterFallbackOverride) {
      settings.enable_llm_chapter_fallback_tagging =
        chapterFallbackOverride === 'inherit' ? null : chapterFallbackOverride === 'on';
    }
    if (autoWhitelistOverride !== currentAutoWhitelistOverride) {
      settings.auto_whitelist_new_episodes_override =
        autoWhitelistOverride === 'inherit' ? null : autoWhitelistOverride === 'on';
    }

    const normalizedLabel = feedTagLabel.trim();
    const currentLabel = feed.feed_tag_label ?? '';
    if (normalizedLabel !== currentLabel) {
      settings.feed_tag_label = normalizedLabel === '' ? null : normalizedLabel;
    }
    const normalizedPosition = feedTagPosition || '';
    const currentPosition = feed.feed_tag_position ?? '';
    if (normalizedPosition !== currentPosition) {
      settings.feed_tag_position = normalizedPosition === '' ? null : normalizedPosition;
    }

    const descChanged = descriptionViewOverride !== episodeDescriptionOverride;
    pendingDescViewRef.current = { value: descriptionViewOverride, changed: descChanged };

    if (Object.keys(settings).length === 0) {
      // No backend changes — apply the localStorage preference directly and close.
      if (descChanged) {
        onEpisodeDescriptionViewChange?.(descriptionViewOverride);
      }
      onClose();
      return;
    }
    updateMutation.mutate(settings);
  };

  const autoWhitelistDefaultLabel =
    autoWhitelistGlobalDefault === undefined ? 'Unknown'
    : autoWhitelistGlobalDefault ? 'On' : 'Off';
  const chapterFallbackGlobalDefaultLabel =
    llmChapterFallbackGlobalDefault === undefined ? 'Unknown'
    : llmChapterFallbackGlobalDefault ? 'On' : 'Off';
  const isChapterFallbackLocked = strategy === 'chapter_insert';
  const globalPositionLabel = globalFeedTagPosition === 'suffix' ? 'Feed Title [tag]' : '[tag] Feed Title';
  const globalDescLabel = globalEpisodeDescriptionView === 'podly' ? 'Podly' : 'Source';

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      <div className="relative w-full max-w-md bg-white rounded-xl border border-gray-200 shadow-lg flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-200 flex-shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Feed Settings</h2>
            <p className="text-sm text-gray-600 mt-1">Settings for "{feed.title}"</p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">

          {/* ── Feed tag ── */}
          {globalFeedTagOverride && (
            <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
              Global tag override is enabled — per-feed tag settings below are ignored. Disable "Override per-feed tag settings" in App Settings to use per-feed values.
            </div>
          )}
          <div>
            <FieldLabel
              htmlFor="fs-feed-tag-label"
              tooltip="Text shown inside brackets on feed titles in your podcast app. Leave empty to inherit the global default."
            >
              Feed tag label
            </FieldLabel>
            <input
              id="fs-feed-tag-label"
              type="text"
              maxLength={50}
              value={feedTagLabel}
              onChange={(e) => setFeedTagLabel(e.target.value)}
              placeholder={`Use global default (${globalFeedTagLabel || 'none'})`}
              disabled={globalFeedTagOverride}
              className={selectClass}
            />
          </div>

          <div>
            <FieldLabel tooltip="Where the bracketed tag appears relative to the feed title. Select 'Use global default' to inherit the app-wide setting.">
              Feed tag position
            </FieldLabel>
            <div className="flex flex-col gap-2">
              {[
                { value: '', label: `Use global default (${globalPositionLabel})` },
                { value: 'prefix', label: '[tag] Feed Title' },
                { value: 'suffix', label: 'Feed Title [tag]' },
              ].map((opt) => (
                <label key={opt.value} className={`flex items-center gap-2.5 ${globalFeedTagOverride ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                  <input
                    type="radio"
                    name={`feedTagPosition-${feed.id}`}
                    value={opt.value}
                    checked={feedTagPosition === opt.value}
                    onChange={() => setFeedTagPosition(opt.value)}
                    disabled={globalFeedTagOverride}
                    className="accent-blue-600"
                  />
                  <span className="text-sm text-gray-700">{opt.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="border-t border-gray-100" />

          {/* ── Ad detection strategy ── */}
          <div>
            <FieldLabel tooltip="Controls how ads are identified and handled during processing.">
              Ad detection strategy
            </FieldLabel>
            <div className="flex flex-col gap-3">
              {[
                {
                  value: 'llm',
                  label: 'LLM (AI-based)',
                  desc: 'Transcribes audio and uses AI to classify and remove ad segments.',
                },
                {
                  value: 'chapter',
                  label: 'Chapter-based',
                  desc: 'Removes chapters whose titles match filter strings. Requires chapter metadata; uses CBR encoding.',
                },
                {
                  value: 'chapter_insert',
                  label: 'Chapter insertion only',
                  desc: 'Keeps all audio intact and inserts chapter markers only — no ad removal.',
                },
              ].map((opt) => (
                <label key={opt.value} className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="radio"
                    name={`adStrategy-${feed.id}`}
                    value={opt.value}
                    checked={strategy === opt.value}
                    onChange={() => setStrategy(opt.value as typeof strategy)}
                    className="mt-0.5 accent-blue-600"
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{opt.label}</p>
                    <p className="text-xs text-gray-500 leading-snug">{opt.desc}</p>
                  </div>
                </label>
              ))}
            </div>

            {strategy === 'chapter' && (
              <div className="mt-3 ml-5 pl-3 border-l-2 border-gray-200">
                <div className="flex items-center text-xs text-gray-600 mb-1">
                  Filter strings
                  <InfoTooltip text="Comma-separated list. Any chapter whose title contains one of these strings (case-insensitive) will be removed." />
                </div>
                <textarea
                  value={filterStrings}
                  onChange={(e) => setFilterStrings(e.target.value)}
                  placeholder="sponsor,advertisement,ad break"
                  rows={3}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
              </div>
            )}
          </div>

          <div className="border-t border-gray-100" />

          {/* ── Behaviour overrides ── */}
          <div>
            <FieldLabel
              htmlFor="fs-auto-whitelist"
              tooltip="Whether new episodes are automatically queued for processing. Overrides the global setting for this feed only."
            >
              Auto-whitelist new episodes
            </FieldLabel>
            <select
              id="fs-auto-whitelist"
              value={autoWhitelistOverride}
              onChange={(e) => setAutoWhitelistOverride(e.target.value as 'inherit' | 'on' | 'off')}
              className={selectClass}
            >
              <option value="inherit">Use global setting ({autoWhitelistDefaultLabel})</option>
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
          </div>

          <div>
            <FieldLabel
              htmlFor="fs-chapter-fallback"
              tooltip="Preserves embedded chapters when available, falling back to description or transcript-derived chapters during LLM processing. Locked on when using chapter insertion mode."
            >
              LLM-based chapter tagging
            </FieldLabel>
            <select
              id="fs-chapter-fallback"
              value={isChapterFallbackLocked ? 'on' : chapterFallbackOverride}
              disabled={isChapterFallbackLocked}
              onChange={(e) => setChapterFallbackOverride(e.target.value as 'inherit' | 'on' | 'off')}
              className={selectClass}
            >
              <option value="inherit">Use global setting ({chapterFallbackGlobalDefaultLabel})</option>
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
            {isChapterFallbackLocked && (
              <p className="text-xs text-blue-600 mt-1">
                Locked on — required by chapter insertion mode.
              </p>
            )}
          </div>

          <div className="border-t border-gray-100" />

          {/* ── Episode description preview ── */}
          <div>
            <FieldLabel
              htmlFor="fs-desc-view"
              tooltip="Which episode description is shown in the Podly UI. This is a local preference saved in your browser — it does not affect the RSS feed delivered to your podcast app."
            >
              Episode description preview
            </FieldLabel>
            <select
              id="fs-desc-view"
              value={descriptionViewOverride ?? 'global'}
              onChange={(e) => {
                const v = e.target.value;
                setDescriptionViewOverride(v === 'global' ? null : (v as 'source' | 'podly'));
              }}
              className={selectClass}
            >
              <option value="global">Use global default ({globalDescLabel})</option>
              <option value="source">Source description</option>
              <option value="podly">Podly description preview</option>
            </select>
          </div>

          {updateMutation.isError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">Failed to save settings. Please try again.</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-5 py-4 border-t border-gray-200 bg-gray-50 flex-shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
