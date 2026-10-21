import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, useEffect, useRef, useMemo } from 'react';
import { toast } from 'react-hot-toast';
import type { Feed, Episode, PagedResult, ConfigResponse } from '../types';
import { feedsApi, configApi } from '../services/api';
import DownloadButton from './DownloadButton';
import PlayButton from './PlayButton';
import ProcessingStatsButton from './ProcessingStatsButton';
import EpisodeProcessingStatus from './EpisodeProcessingStatus';
import FeedSettingsModal from './FeedSettingsModal';
import FeedSubscribersModal from './FeedSubscribersModal';
import ModalShell from './ModalShell';
import { useAuth } from '../contexts/AuthContext';
import { copyToClipboard } from '../utils/clipboard';
import { emitDiagnosticError } from '../utils/diagnostics';
import { getHttpErrorInfo } from '../utils/httpError';
import { useDelayedFlag } from '../hooks/useDelayedFlag';
import {
  BlockedIcon,
  CheckIcon,
  CloseIcon,
  DotsVerticalIcon,
  GearIcon,
  InfoIcon,
  LogoutIcon,
  MusicIcon,
  PlusIcon,
  RefreshIcon,
  TrashIcon,
  WarningIcon,
} from './icons';

interface FeedDetailProps {
  feed: Feed;
  onClose?: () => void;
  onFeedDeleted?: () => void;
}

type SortOption = 'newest' | 'oldest' | 'title';
type EpisodeDescriptionView = 'source' | 'podly';

const EPISODE_DESCRIPTION_VIEW_STORAGE_KEY_PREFIX = 'podly:episode-description-view:feed:';

function getEpisodeDescriptionViewStorageKey(feedId: number): string {
  return `${EPISODE_DESCRIPTION_VIEW_STORAGE_KEY_PREFIX}${feedId}`;
}

function loadEpisodeDescriptionView(feedId: number): EpisodeDescriptionView {
  if (typeof window === 'undefined') {
    return 'source';
  }
  const rawValue = window.localStorage.getItem(
    getEpisodeDescriptionViewStorageKey(feedId)
  );
  return rawValue === 'podly' ? 'podly' : 'source';
}

function persistEpisodeDescriptionView(
  feedId: number,
  view: EpisodeDescriptionView
): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(
    getEpisodeDescriptionViewStorageKey(feedId),
    view
  );
}

interface ProcessingEstimate {
  post_guid: string;
  estimated_minutes: number;
  can_process: boolean;
  reason: string | null;
}

const EPISODES_PAGE_SIZE = 25;

const htmlToPlainText = (html: string) => new DOMParser().parseFromString(html, 'text/html').body.textContent?.trim() ?? '';

export default function FeedDetail({ feed, onClose, onFeedDeleted }: FeedDetailProps) {
  const { requireAuth, isAuthenticated, user } = useAuth();
  const [sortBy, setSortBy] = useState<SortOption>('newest');
  const [showStickyHeader, setShowStickyHeader] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const queryClient = useQueryClient();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const feedHeaderRef = useRef<HTMLDivElement>(null);
  const [currentFeed, setCurrentFeed] = useState(feed);
  const [expandedDescriptions, setExpandedDescriptions] = useState<Set<string>>(new Set());
  const [pendingEpisode, setPendingEpisode] = useState<Episode | null>(null);
  const [showProcessingModal, setShowProcessingModal] = useState(false);
  const [processingEstimate, setProcessingEstimate] = useState<ProcessingEstimate | null>(null);
  const [isEstimating, setIsEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [isFeedTransitionActive, setIsFeedTransitionActive] = useState(false);
  const [episodeDescriptionView, setEpisodeDescriptionView] =
    useState<EpisodeDescriptionView>(() => loadEpisodeDescriptionView(feed.id));
  const handleEpisodeDescriptionViewChange = (view: EpisodeDescriptionView) => {
    setEpisodeDescriptionView(view);
    persistEpisodeDescriptionView(currentFeed.id, view);
  };
  const [showSubscribersModal, setShowSubscribersModal] = useState(false);

  const isAdmin = !requireAuth || user?.role === 'admin';
  const whitelistedOnly = requireAuth && !isAdmin;

  type DescriptionToken =
    | { type: 'text'; value: string }
    | { type: 'link'; href: string; text: string }
    | { type: 'newline' };

  const tokenizeDescription = (rawDescription: string): DescriptionToken[] => {
    if (typeof document === 'undefined') {
      return [{ type: 'text', value: rawDescription }];
    }

    const parser = new DOMParser();
    const doc = parser.parseFromString(rawDescription, 'text/html');
    const tokens: DescriptionToken[] = [];
    const blockTags = new Set(['p', 'div', 'li', 'ul', 'ol']);

    const pushText = (text: string) => {
      if (!text) {
        return;
      }
      const parts = text.split(/\r?\n/);
      parts.forEach((part, index) => {
        if (part) {
          tokens.push({ type: 'text', value: part });
        }
        if (index < parts.length - 1) {
          tokens.push({ type: 'newline' });
        }
      });
    };

    const visitNode = (node: Node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        pushText(node.textContent ?? '');
        return;
      }

      if (node.nodeType !== Node.ELEMENT_NODE) {
        return;
      }

      const element = node as HTMLElement;
      const tag = element.tagName.toLowerCase();

      if (tag === 'br') {
        tokens.push({ type: 'newline' });
        return;
      }

      if (tag === 'a') {
        const href = element.getAttribute('href');
        const text = element.textContent ?? '';
        if (href) {
          tokens.push({ type: 'link', href, text: text || href });
        } else {
          pushText(text);
        }
        return;
      }

      if (blockTags.has(tag)) {
        tokens.push({ type: 'newline' });
        element.childNodes.forEach(visitNode);
        tokens.push({ type: 'newline' });
        return;
      }

      element.childNodes.forEach(visitNode);
    };

    doc.body.childNodes.forEach(visitNode);

    const normalized: DescriptionToken[] = [];
    for (const token of tokens) {
      const last = normalized[normalized.length - 1];
      if (token.type === 'text') {
        const cleaned = token.value.replace(/[ \t]+/g, ' ');
        if (!cleaned) {
          continue;
        }
        if (last?.type === 'text') {
          last.value += cleaned;
        } else {
          normalized.push({ type: 'text', value: cleaned });
        }
        continue;
      }

      if (token.type === 'newline') {
        if (last?.type !== 'newline') {
          normalized.push(token);
        }
        continue;
      }

      normalized.push(token);
    }

    while (normalized[0]?.type === 'newline') {
      normalized.shift();
    }
    while (normalized[normalized.length - 1]?.type === 'newline') {
      normalized.pop();
    }

    return normalized;
  };

  const renderDescriptionTokens = (tokens: DescriptionToken[]) =>
    tokens.map((token, index) => {
      if (token.type === 'newline') {
        return (
          <span key={`newline-${index}`}>
            {'\n'}
          </span>
        );
      }

      if (token.type === 'link') {
        return (
          <a
            key={`link-${index}`}
            href={token.href}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline"
          >
            {token.text}
          </a>
        );
      }

      return (
        <span key={`text-${index}`}>
          {token.value}
        </span>
      );
    });

  const tokensToPlainText = (tokens: DescriptionToken[]) =>
    tokens
      .map((token) => {
        if (token.type === 'text') {
          return token.value;
        }
        if (token.type === 'link') {
          return token.text;
        }
        return ' • ';
      })
      .join('')
      .replace(/\s+/g, ' ')
      .trim();

  const { data: configResponse } = useQuery<ConfigResponse>({
    queryKey: ['config'],
    queryFn: configApi.getConfig,
    enabled: isAdmin,
  });

  const {
    data: episodesPage,
    isLoading,
    isFetching,
    error,
  } = useQuery<PagedResult<Episode>, Error, PagedResult<Episode>, [string, number, number, boolean]>({
    queryKey: ['episodes', currentFeed.id, page, whitelistedOnly],
    queryFn: () =>
      feedsApi.getFeedPosts(currentFeed.id, {
        page,
        pageSize: EPISODES_PAGE_SIZE,
        whitelistedOnly,
      }),
    placeholderData: (previousData, previousQuery) => {
      const previousFeedId =
        Array.isArray(previousQuery?.queryKey) &&
        typeof previousQuery.queryKey[1] === 'number'
          ? previousQuery.queryKey[1]
          : null;
      return previousFeedId === currentFeed.id ? previousData : undefined;
    },
  });
  const showSkeleton = useDelayedFlag(isLoading);

  const whitelistMutation = useMutation({
    mutationFn: ({ guid, whitelisted, triggerProcessing }: { guid: string; whitelisted: boolean; triggerProcessing?: boolean }) =>
      feedsApi.togglePostWhitelist(guid, whitelisted, triggerProcessing),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes', currentFeed.id] });
    },
    onError: (err) => {
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to update whitelist status',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
        },
      });
    },
  });

  const bulkWhitelistMutation = useMutation({
    mutationFn: () => feedsApi.toggleAllPostsWhitelist(currentFeed.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes', currentFeed.id] });
    },
  });

  const refreshFeedMutation = useMutation({
    mutationFn: () => feedsApi.refreshFeed(currentFeed.id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      queryClient.invalidateQueries({ queryKey: ['episodes', currentFeed.id] });
      toast.success(data?.message ?? 'Feed refreshed');
    },
    onError: (err) => {
      console.error('Failed to refresh feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to refresh feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  const deleteFeedMutation = useMutation({
    mutationFn: () => feedsApi.deleteFeed(currentFeed.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      if (onFeedDeleted) {
        onFeedDeleted();
      }
    },
    onError: (err) => {
      console.error('Failed to delete feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to delete feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  const joinFeedMutation = useMutation({
    mutationFn: () => feedsApi.joinFeed(currentFeed.id),
    onSuccess: (data) => {
      toast.success('Joined feed');
      setCurrentFeed(data);
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
    },
    onError: (err) => {
      console.error('Failed to join feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to join feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  const leaveFeedMutation = useMutation({
    mutationFn: () => feedsApi.leaveFeed(currentFeed.id),
    onSuccess: () => {
      toast.success('Removed from your feeds');
      setCurrentFeed((prev) => (prev ? { ...prev, is_member: false, is_active_subscription: false } : prev));
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      if (onFeedDeleted && !isAdmin) {
        onFeedDeleted();
      }
    },
    onError: (err) => {
      console.error('Failed to leave feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to remove feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  useEffect(() => {
    if (feed.id !== currentFeed.id) {
      setIsFeedTransitionActive(true);
    }
    setCurrentFeed(feed);
  }, [feed, currentFeed.id]);

  useEffect(() => {
    if (!isFeedTransitionActive) {
      return;
    }

    if (isLoading || isFetching) {
      return;
    }

    setIsFeedTransitionActive(false);
  }, [isFeedTransitionActive, isFetching, isLoading]);

  useEffect(() => {
    setEpisodeDescriptionView(loadEpisodeDescriptionView(currentFeed.id));
  }, [currentFeed.id]);

  useEffect(() => {
    setExpandedDescriptions(new Set());
  }, [feed.id, episodeDescriptionView]);

  useEffect(() => {
    setPage(1);
  }, [feed.id, whitelistedOnly]);

  useEffect(() => {
    scrollContainerRef.current?.scrollTo({ top: 0 });
  }, [feed.id]);

  // Show/hide sticky header
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    const feedHeader = feedHeaderRef.current;

    if (!scrollContainer || !feedHeader) return;

    // Show the sticky header once the feed header is within 100px of leaving the container.
    const observer = new IntersectionObserver(
      ([entry]) => setShowStickyHeader(!entry.isIntersecting),
      { root: scrollContainer, rootMargin: '-100px 0px 0px 0px' }
    );
    observer.observe(feedHeader);
    return () => observer.disconnect();
  }, []);

  // Handle click outside to close menu
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (showMenu && !(event.target as Element).closest('.menu-container')) {
        setShowMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showMenu]);

  const handleWhitelistToggle = (episode: Episode) => {
    if (!episode.whitelisted) {
      setPendingEpisode(episode);
      setShowProcessingModal(true);
      setProcessingEstimate(null);
      setEstimateError(null);
      setIsEstimating(true);
      feedsApi
        .getProcessingEstimate(episode.guid)
        .then((estimate) => {
          setProcessingEstimate(estimate);
        })
        .catch((err) => {
          console.error('Failed to load processing estimate', err);
          const { status, data, message } = getHttpErrorInfo(err);
          emitDiagnosticError({
            title: 'Failed to load processing estimate',
            message,
            kind: status ? 'http' : 'network',
            details: {
              status,
              response: data,
              postGuid: episode.guid,
            },
          });
          setEstimateError(message ?? 'Unable to estimate processing time');
        })
        .finally(() => setIsEstimating(false));
      return;
    }

    whitelistMutation.mutate({
      guid: episode.guid,
      whitelisted: false,
    });
  };

  const handleConfirmProcessing = () => {
    if (!pendingEpisode) return;
    whitelistMutation.mutate(
      {
        guid: pendingEpisode.guid,
        whitelisted: true,
        triggerProcessing: true,
      },
      {
        onSuccess: () => {
          setShowProcessingModal(false);
          setPendingEpisode(null);
          setProcessingEstimate(null);
        },
      }
    );
  };

  const handleCancelProcessing = () => {
    setShowProcessingModal(false);
    setPendingEpisode(null);
    setProcessingEstimate(null);
    setEstimateError(null);
  };

  const isMember = Boolean(currentFeed.is_member);
  const isActiveSubscription = currentFeed.is_active_subscription !== false;

  // Admins can manage everything; regular users are read-only.
  const canDeleteFeed = isAdmin; // only admins can delete feeds
  const canModifyEpisodes = !requireAuth ? true : Boolean(isAdmin);
  const canBulkModifyEpisodes = !requireAuth ? true : Boolean(isAdmin);
  const canSubscribe = !requireAuth || isMember;
  const showPodlyRssButton = !(requireAuth && isAdmin && !isMember);
  const showWhitelistUi = canModifyEpisodes && isAdmin;
  const appAutoWhitelistDefault =
    configResponse?.config?.app?.automatically_whitelist_new_episodes;

  const episodes = episodesPage?.items ?? [];
  const totalCount = episodesPage?.total ?? 0;
  const whitelistedCount =
    episodesPage?.whitelisted_total ?? episodes.filter((ep: Episode) => ep.whitelisted).length;
  const totalPages = Math.max(
    1,
    episodesPage?.total_pages ?? Math.ceil(totalCount / EPISODES_PAGE_SIZE)
  );
  const hasEpisodes = totalCount > 0;
  const visibleStart = hasEpisodes ? (page - 1) * EPISODES_PAGE_SIZE + 1 : 0;
  const visibleEnd = hasEpisodes ? Math.min(totalCount, page * EPISODES_PAGE_SIZE) : 0;

  useEffect(() => {
    if (page > totalPages && totalPages > 0) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const handleBulkWhitelistToggle = () => {
    if (requireAuth && !isAdmin) {
      toast.error('Only admins can bulk toggle whitelist status.');
      return;
    }
    bulkWhitelistMutation.mutate();
  };

  const handleDeleteFeed = () => {
    if (confirm(`Are you sure you want to delete "${currentFeed.title}"? This action cannot be undone.`)) {
      deleteFeedMutation.mutate();
    }
  };

  const episodesToShow = useMemo(() => episodes, [episodes]);

  const sortedEpisodes = useMemo(() => {
    const list = [...episodesToShow];
    return list.sort((a, b) => {
      switch (sortBy) {
        case 'newest':
          return new Date(b.release_date || 0).getTime() - new Date(a.release_date || 0).getTime();
        case 'oldest':
          return new Date(a.release_date || 0).getTime() - new Date(b.release_date || 0).getTime();
        case 'title':
          return a.title.localeCompare(b.title);
        default:
          return 0;
      }
    });
  }, [episodesToShow, sortBy]);

  // Calculate whitelist status for bulk button
  const allWhitelisted = totalCount > 0 && whitelistedCount === totalCount;

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'Unknown date';
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    return `${minutes}m`;
  };

  const handleCopyRssToClipboard = async () => {
    if (requireAuth && !isAuthenticated) {
      toast.error('Please sign in to copy a protected RSS URL.');
      return;
    }

    try {
      let rssUrl: string;
      if (requireAuth) {
        const response = await feedsApi.createProtectedFeedShareLink(currentFeed.id);
        rssUrl = response.url;
      } else {
        rssUrl = new URL(`/feed/${currentFeed.id}`, window.location.origin).toString();
      }

      await copyToClipboard(rssUrl, 'Copy the Feed RSS URL:', 'Feed URL copied to clipboard!');
    } catch (err) {
      console.error('Failed to copy feed URL', err);
      toast.error('Failed to copy feed URL');
    }
  };

  const handleCopyOriginalRssToClipboard = async () => {
    try {
      const rssUrl = currentFeed.rss_url || '';
      if (!rssUrl) throw new Error('No RSS URL');

      await copyToClipboard(rssUrl, 'Copy the Original RSS URL:', 'Original RSS URL copied to clipboard');
    } catch (err) {
      console.error('Failed to copy original RSS URL', err);
      toast.error('Failed to copy original RSS URL');
    }
  };

  const transitionSkeletonClass =
    'rounded-full bg-gray-200';
  const transitionSkeletonSoftClass =
    'rounded-full bg-gray-100';

  return (
    <div
      className="h-full flex flex-col bg-surface relative"
      aria-busy={isFeedTransitionActive}
    >
      <div
        className={`flex h-full flex-col transition-opacity duration-150 ${
          isFeedTransitionActive ? 'pointer-events-none opacity-0' : 'opacity-100'
        }`}
      >
        {/* Mobile Header */}
        <div className="flex items-center justify-between p-4 border-b lg:hidden">
          <h2 className="text-lg font-semibold text-gray-900">Podcast Details</h2>
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Close"
              className="btn btn-ghost btn-icon"
            >
              <CloseIcon className="h-5 w-5" />
            </button>
          )}
        </div>

        {/* Sticky Header - appears when scrolling */}
        <div inert={!showStickyHeader} className={`absolute top-16 lg:top-0 left-0 right-0 z-10 bg-surface border-b transition-[opacity,transform] duration-300 ease-out ${
          showStickyHeader ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-full pointer-events-none'
        }`}>
          <div className="p-4">
            <div className="flex items-center gap-3">
              {currentFeed.image_url && (
                <img
                  src={currentFeed.image_url}
                  alt=""
                  className="w-10 h-10 rounded-lg object-cover"
                />
              )}
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-gray-900 truncate">{currentFeed.title}</p>
                {currentFeed.author && (
                  <p className="text-sm text-gray-600 truncate">by {currentFeed.author}</p>
                )}
              </div>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortOption)}
                aria-label="Sort episodes"
                className="input w-auto py-1.5 pl-3 pr-8"
              >
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
                <option value="title">Title A-Z</option>
              </select>

              {/* do not add addtional controls to sticky headers */}
            </div>
          </div>
        </div>

        {/* Scrollable Content */}
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
        {/* Feed Info Header */}
        <div ref={feedHeaderRef} className="p-6 border-b">
          <div className="flex flex-col gap-6">
            {/* Top Section: Image and Title */}
            <div className="flex items-end gap-6">
              {/* Podcast Image */}
              <div className="flex-shrink-0">
                {currentFeed.image_url ? (
                  <img
                    src={currentFeed.image_url}
                    alt=""
                    className="w-32 h-32 sm:w-40 sm:h-40 rounded-lg object-cover"
                  />
                ) : (
                  <div className="w-32 h-32 sm:w-40 sm:h-40 rounded-lg bg-gray-200 flex items-center justify-center">
                    <MusicIcon className="h-16 w-16 text-gray-400" />
                  </div>
                )}
              </div>

              {/* Title aligned to bottom-left of image */}
              <div className="flex-1 min-w-0 pb-2">
                <h2 className="text-2xl font-bold text-gray-900 mb-1">{currentFeed.title}</h2>
                {currentFeed.author && (
                  <p className="text-lg text-gray-600">by {currentFeed.author}</p>
                )}
                <div className="mt-2 text-sm text-gray-500">
                  <span>{totalCount} episodes visible</span>
                </div>
                {requireAuth && isAdmin && (
                  <div className="mt-2 flex items-center gap-2 flex-wrap text-sm">
                    <button
                      onClick={() => setShowSubscribersModal(true)}
                      className="px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                      title="View subscribers"
                    >
                      {currentFeed.member_count ?? 0} subscriber{(currentFeed.member_count ?? 0) !== 1 ? 's' : ''}
                    </button>
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-medium border ${
                        isMember
                          ? 'bg-green-50 text-green-700 border-green-200'
                          : 'bg-gray-100 text-gray-600 border-gray-200'
                      }`}
                    >
                      {isMember ? 'Joined' : 'Not joined'}
                    </span>
                    {isMember && !isActiveSubscription && (
                      <span className="px-2 py-1 rounded-full text-xs font-medium border bg-amber-50 text-amber-700 border-amber-200">
                        Paused
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* RSS Button and Menu */}
            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              {/* Podly RSS Subscribe Button */}
              {showPodlyRssButton && (
                <button
                  onClick={handleCopyRssToClipboard}
                  title="Copy Podly RSS feed URL"
                  className="btn btn-dark w-full sm:w-auto h-auto min-h-9 whitespace-normal py-2 text-center"
                  disabled={!canSubscribe}
                >
                  <img
                    src="/rss-round-color-icon.svg"
                    alt="Podly RSS"
                    className="h-5 w-5 shrink-0"
                    aria-hidden="true"
                  />
                  <span>
                    {canSubscribe ? 'Subscribe to Podly RSS' : 'Join feed to subscribe'}
                  </span>
                </button>
              )}

              <div className="flex w-full items-center gap-3 sm:w-auto sm:flex-1 flex-wrap">
                {requireAuth && isAdmin && !isMember && (
                  <button
                    onClick={() => joinFeedMutation.mutate()}
                    disabled={joinFeedMutation.isPending}
                    className="btn btn-secondary flex-1 sm:flex-none"
                  >
                    <PlusIcon className="h-4 w-4 shrink-0" />
                    <span>Join feed</span>
                  </button>
                )}

                {canModifyEpisodes && (
                  <button
                    onClick={() => refreshFeedMutation.mutate()}
                    disabled={refreshFeedMutation.isPending}
                    title="Refresh feed from source"
                    className="btn btn-secondary flex-1 sm:flex-none"
                  >
                    <RefreshIcon className={`h-4 w-4 shrink-0 ${refreshFeedMutation.isPending ? 'animate-spin' : ''}`} />
                    <span>Refresh Feed</span>
                  </button>
                )}

                {/* Settings Button (cog) */}
                {isAdmin && (
                  <button
                    onClick={() => setShowSettingsModal(true)}
                    title="Feed settings"
                    aria-label="Feed settings"
                    className="btn btn-secondary btn-icon shrink-0"
                  >
                    <GearIcon className="h-5 w-5" />
                  </button>
                )}

                {/* Ellipsis Menu */}
                <div className="relative menu-container shrink-0">
                  <button
                    onClick={() => setShowMenu(!showMenu)}
                    aria-label="More actions"
                    aria-expanded={showMenu}
                    className="btn btn-secondary btn-icon"
                  >
                    <DotsVerticalIcon className="h-5 w-5" />
                  </button>

                  {/* Dropdown Menu */}
                  {showMenu && (
                    <div className="absolute top-full right-0 mt-1 w-56 animate-pop-in origin-top-right bg-surface rounded-lg shadow-lg border border-gray-200 py-1 z-20 max-w-[calc(100vw-2rem)]">
                      {canBulkModifyEpisodes && (
                        <>
                          <button
                            onClick={() => {
                              if (!allWhitelisted) {
                                handleBulkWhitelistToggle();
                            }
                            setShowMenu(false);
                          }}
                          disabled={bulkWhitelistMutation.isPending || totalCount === 0 || allWhitelisted}
                          className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <CheckIcon className="h-4 w-4 text-green-600" />
                          Enable all episodes
                        </button>

                        <button
                          onClick={() => {
                            if (allWhitelisted) {
                              handleBulkWhitelistToggle();
                            }
                            setShowMenu(false);
                          }}
                          disabled={bulkWhitelistMutation.isPending || totalCount === 0 || !allWhitelisted}
                          className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <BlockedIcon className="h-4 w-4 text-red-600" />
                          Disable all episodes
                        </button>
                      </>
                      )}

                      {isAdmin && (
                        <button
                          onClick={() => {
                            setShowHelp(!showHelp);
                            setShowMenu(false);
                          }}
                          className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                        >
                          <InfoIcon className="h-4 w-4 text-blue-600" />
                          Explain whitelist
                        </button>
                      )}

                    <button
                      onClick={() => {
                        handleCopyOriginalRssToClipboard();
                        setShowMenu(false);
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                    >
                      <img src="/rss-round-color-icon.svg" alt="Original RSS" className="w-4 h-4" />
                      Original RSS feed
                    </button>

                    {requireAuth && isAdmin && isMember && (
                      <>
                        <div className="border-t border-gray-100 my-1"></div>
                        <button
                          onClick={() => {
                            leaveFeedMutation.mutate();
                            setShowMenu(false);
                          }}
                          disabled={leaveFeedMutation.isPending}
                          className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <LogoutIcon className="h-4 w-4" />
                          Leave feed
                        </button>
                      </>
                    )}

                    {canDeleteFeed && (
                      <>
                        <div className="border-t border-gray-100 my-1"></div>

                        <button
                          onClick={() => {
                            handleDeleteFeed();
                            setShowMenu(false);
                          }}
                          disabled={deleteFeedMutation.isPending}
                          className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <TrashIcon className="h-4 w-4" />
                          Delete feed
                        </button>
                      </>
                    )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Feed Description */}
            {currentFeed.description && (
              <div className="text-gray-700 leading-relaxed">
                <p>{htmlToPlainText(currentFeed.description)}</p>
              </div>
            )}
          </div>
        </div>

        {/* Inactive Subscription Warning */}
        {currentFeed.is_member && currentFeed.is_active_subscription === false && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-start gap-3">
            <WarningIcon className="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" />
            <div>
              <h3 className="text-sm font-medium text-amber-800">Processing Paused</h3>
              <p className="text-sm text-amber-700 mt-1">
                This feed exceeds your plan's allowance. New episodes will not be processed automatically until you upgrade your plan or leave other feeds.
              </p>
            </div>
          </div>
        )}

        {/* Episodes Header with Sort Only */}
        <div className="p-4 border-b bg-gray-50">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-900">Episodes</h3>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortOption)}
              aria-label="Sort episodes"
              className="input w-auto py-1.5 pl-3 pr-8"
            >
              <option value="newest">Newest First</option>
              <option value="oldest">Oldest First</option>
              <option value="title">Title A-Z</option>
            </select>
          </div>
        </div>

            {/* Help Explainer (admins only) */}
            {showHelp && isAdmin && (
          <div className="bg-blue-50 border-b border-blue-200 p-4">
            <div className="max-w-2xl">
              <h4 className="font-semibold text-blue-900 mb-2">About Enabling & Disabling Ad Removal</h4>
              <div className="text-sm text-blue-800 space-y-2 text-left">
                <p>
                  <strong>Enabled episodes</strong> are processed by Podly to automatically detect and remove advertisements,
                  giving you a clean, ad-free listening experience.
                </p>
                <p>
                  <strong>Disabled episodes</strong> are not processed and won't be available for download through Podly.
                  This is useful for episodes you don't want to listen to.
                </p>
                <p>
                  <strong>Why whitelist episodes?</strong> Processing takes time and computational resources.
                  Enable only the episodes you want to hear to keep your feed focused. This is useful when adding a new feed with a large back catalog.
                </p>
              </div>
              <button
                onClick={() => setShowHelp(false)}
                className="mt-3 text-xs text-blue-600 hover:text-blue-800 font-medium"
              >
                Got it, hide this explanation
              </button>
            </div>
          </div>
        )}

        {/* Episodes List */}
        <div className="min-h-[32rem]">
          {isLoading ? (
            showSkeleton && (
            <div className="p-6">
              <div className="animate-pulse space-y-4">
                {[...Array(5)].map((_, i) => (
                  <div
                    key={i}
                    className="h-28 rounded-lg border border-gray-200 bg-gray-100"
                  ></div>
                ))}
              </div>
            </div>
            )
          ) : error ? (
            <div className="p-6">
              <p className="text-red-600">Failed to load episodes</p>
            </div>
          ) : sortedEpisodes.length === 0 ? (
            <div className="p-6 text-center">
              <p className="text-gray-500">No episodes found</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200">
              {sortedEpisodes.map((episode) => (
                <div key={episode.id} className="p-4 hover:bg-gray-50">
                  <div className={`flex flex-col ${episode.whitelisted ? 'gap-3' : 'gap-2'}`}>
                    {/* Top Section: Thumbnail and Title */}
                    <div className="flex items-start gap-3">
                      {/* Episode/Podcast Thumbnail */}
                      <div className="flex-shrink-0">
                        {(episode.image_url || currentFeed.image_url) ? (
                          <img
                            src={episode.image_url || currentFeed.image_url}
                            alt=""
                            loading="lazy"
                            className="w-16 h-16 rounded-lg object-cover"
                          />
                        ) : (
                          <div className="w-16 h-16 rounded-lg bg-gray-200 flex items-center justify-center">
                            <MusicIcon className="h-8 w-8 text-gray-400" />
                          </div>
                        )}
                      </div>

                      {/* Title and Feed Name */}
                      <div className="flex-1 min-w-0 text-left">
                        <h4 className="font-medium text-gray-900 mb-1 line-clamp-2 text-left">
                          {episode.title}
                        </h4>
                        <p className="text-sm text-gray-600 text-left">
                          {currentFeed.title}
                        </p>
                      </div>
                    </div>

                    {/* Episode Description */}
                    {(
                      episodeDescriptionView === 'podly'
                        ? (episode.podly_description_html || episode.description)
                        : episode.description
                    ) && (
                      <div className="text-left">
                        {(() => {
                          const descriptionHtml =
                            episodeDescriptionView === 'podly'
                              ? (episode.podly_description_html || episode.description)
                              : episode.description;
                          const descriptionTokens = tokenizeDescription(descriptionHtml);
                          const descriptionLength = descriptionTokens.reduce((total, token) => {
                            if (token.type === 'text') {
                              return total + token.value.length;
                            }
                            if (token.type === 'link') {
                              return total + token.text.length;
                            }
                            return total + 1;
                          }, 0);
                          const isExpanded = expandedDescriptions.has(episode.guid);
                          const shouldTruncate = descriptionLength > 300;
                          const isTruncated = !isExpanded && shouldTruncate;
                          const plainText = tokensToPlainText(descriptionTokens);
                          const truncatedText = isTruncated
                            ? `${plainText.slice(0, 300)}…`
                            : plainText;
                          return (
                            <>
                              {isExpanded ? (
                                <p className="text-sm text-gray-500 whitespace-pre-line">
                                  {renderDescriptionTokens(descriptionTokens)}
                                </p>
                              ) : (
                                <p className="text-sm text-gray-500 line-clamp-3">
                                  {truncatedText}
                                </p>
                              )}
                              {shouldTruncate && (
                                <button
                                  type="button"
                                  aria-expanded={isExpanded}
                                  onClick={() => {
                                    setExpandedDescriptions((prev) => {
                                      const next = new Set(prev);
                                      if (isExpanded) {
                                        next.delete(episode.guid);
                                      } else {
                                        next.add(episode.guid);
                                      }
                                      return next;
                                    });
                                  }}
                                  className="touch-target mt-2 inline-flex items-center text-xs font-medium text-gray-500 underline-offset-2 transition hover:text-gray-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-300/60"
                                >
                                  {isExpanded ? 'Show less' : 'Show more'}
                                </button>
                              )}
                            </>
                          );
                        })()}
                      </div>
                    )}

                    {/* Metadata: Status, Date and Duration */}
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500">
                      {showWhitelistUi && (
                        <>
                          <button
                            onClick={() => handleWhitelistToggle(episode)}
                            disabled={whitelistMutation.isPending}
                            role="switch"
                            aria-checked={episode.whitelisted}
                            className={`touch-target px-2 py-1 text-xs font-medium rounded-full transition-colors flex items-center justify-center gap-1 ${
                              episode.whitelisted
                                ? 'bg-green-100 text-green-800 hover:bg-green-200'
                                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                            } ${whitelistMutation.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
                          >
                            <span className="sr-only">Process episode: </span>
                            {whitelistMutation.isPending ? (
                              <>
                                <RefreshIcon className="h-3 w-3 animate-spin" />
                                <span>...</span>
                              </>
                            ) : episode.whitelisted ? (
                              <>
                                <CheckIcon className="h-3 w-3" />
                                <span>Enabled</span>
                              </>
                            ) : (
                              <>
                                <BlockedIcon className="h-3 w-3" />
                                <span>Disabled</span>
                              </>
                            )}
                          </button>
                        </>
                      )}
                      {/* Each separator leads its item so a wrapped line never ends on a bullet. */}
                      <span className="whitespace-nowrap">
                        {showWhitelistUi && <span aria-hidden="true" className="mr-2">•</span>}
                        {formatDate(episode.release_date)}
                      </span>
                      {episode.duration && (
                        <span className="whitespace-nowrap">
                          <span aria-hidden="true" className="mr-2">•</span>
                          {formatDuration(episode.duration)}
                        </span>
                      )}
                      <span className="whitespace-nowrap">
                        <span aria-hidden="true" className="mr-2">•</span>
                        {episode.download_count ? episode.download_count : 0} {episode.download_count === 1 ? 'download' : 'downloads'}
                      </span>
                    </div>

                    {/* Bottom Controls - only show if episode is whitelisted */}
                    {episode.whitelisted && (
                      <div className="flex items-center gap-2">
                        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                          <DownloadButton
                            episodeGuid={episode.guid}
                            isWhitelisted={episode.whitelisted}
                            hasProcessedAudio={episode.has_processed_audio}
                            feedId={currentFeed.id}
                            canModifyEpisodes={canModifyEpisodes}
                            className="min-w-[100px] shrink-0"
                          />

                          <EpisodeProcessingStatus
                            episodeGuid={episode.guid}
                            isWhitelisted={episode.whitelisted}
                            hasProcessedAudio={episode.has_processed_audio}
                            feedId={currentFeed.id}
                          />

                          <ProcessingStatsButton
                            episodeGuid={episode.guid}
                            hasProcessedAudio={episode.has_processed_audio}
                            adDetectionStrategy={currentFeed.ad_detection_strategy}
                          />
                        </div>

                        {episode.has_processed_audio && (
                          <PlayButton
                            episode={episode}
                            className="ml-auto shrink-0"
                          />
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {totalCount > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t bg-surface">
            <div className="text-sm text-gray-600">
              Showing {visibleStart}-{visibleEnd} of {totalCount} episodes
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                disabled={page === 1 || isLoading || isFetching}
                className="btn btn-secondary btn-sm"
              >
                Previous
              </button>
              <span className="text-sm text-gray-700">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                disabled={page >= totalPages || isLoading || isFetching}
                className="btn btn-secondary btn-sm"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
      </div>

      <div
        className={`absolute inset-0 z-20 transition-opacity duration-200 ${
          isFeedTransitionActive
            ? 'opacity-100'
            : 'pointer-events-none opacity-0'
        }`}
        aria-hidden={!isFeedTransitionActive}
      >
        <div className="absolute inset-0 bg-surface/95 backdrop-blur-[3px]" />
        <div className="absolute inset-0 overflow-hidden">
          <div className="flex h-full flex-col animate-pulse">
            <div className="flex items-center justify-between border-b p-4 lg:hidden">
              <div className={`h-7 w-40 ${transitionSkeletonClass}`} />
              <div className="h-10 w-10 rounded-lg bg-gray-200" />
            </div>

            <div className="flex-1 overflow-y-auto">
              <div className="border-b p-6">
                <div className="flex flex-col gap-6">
                  <div className="flex items-end gap-6">
                    <div className="h-32 w-32 rounded-lg bg-gray-200 sm:h-40 sm:w-40" />
                    <div className="min-w-0 flex-1 pb-2">
                      <div className={`mb-2 h-8 w-2/3 max-w-xl ${transitionSkeletonClass}`} />
                      <div className={`mb-3 h-6 w-1/4 min-w-[8rem] ${transitionSkeletonClass}`} />
                      <div className={`h-5 w-32 ${transitionSkeletonSoftClass}`} />
                      {requireAuth && isAdmin && (
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <div className="h-7 w-24 rounded-full bg-gray-200" />
                          <div className="h-7 w-16 rounded-full bg-gray-200" />
                          {isMember && !isActiveSubscription && (
                            <div className="h-7 w-16 rounded-full bg-gray-200" />
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                    {showPodlyRssButton && (
                      <div className="h-11 w-full rounded-lg bg-gray-200 sm:w-72" />
                    )}

                    <div className="flex w-full items-center gap-3 sm:w-auto sm:flex-1 sm:flex-wrap">
                      {requireAuth && isAdmin && !isMember && (
                        <div className="h-11 flex-1 rounded-lg bg-gray-200 sm:w-32 sm:flex-none" />
                      )}
                      {canModifyEpisodes && (
                        <div className="h-11 flex-1 rounded-lg bg-gray-200 sm:w-40 sm:flex-none" />
                      )}
                      {isAdmin && (
                        <div className="h-11 w-11 rounded-lg bg-gray-200" />
                      )}
                      <div className="h-11 w-11 rounded-lg bg-gray-200" />
                    </div>
                  </div>

                  {currentFeed.description && (
                    <div className="space-y-3">
                      <div className={`h-4 w-full ${transitionSkeletonSoftClass}`} />
                      <div className={`h-4 w-11/12 ${transitionSkeletonSoftClass}`} />
                      <div className={`h-4 w-3/4 ${transitionSkeletonSoftClass}`} />
                    </div>
                  )}
                </div>
              </div>

              {currentFeed.is_member && currentFeed.is_active_subscription === false && (
                <div className="border-b px-6 py-4">
                  <div className="flex items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4">
                    <div className="mt-0.5 h-5 w-5 rounded-full bg-gray-200" />
                    <div className="flex-1 space-y-2">
                      <div className={`h-4 w-40 ${transitionSkeletonClass}`} />
                      <div className={`h-4 w-full ${transitionSkeletonSoftClass}`} />
                      <div className={`h-4 w-10/12 ${transitionSkeletonSoftClass}`} />
                    </div>
                  </div>
                </div>
              )}

              <div className="border-b bg-gray-50 p-4">
                <div className="flex items-center justify-between">
                  <div className={`h-7 w-24 ${transitionSkeletonClass}`} />
                  <div className="h-9 w-32 rounded-md bg-gray-200" />
                </div>
              </div>

              {showHelp && isAdmin && (
                <div className="border-b px-4 py-4">
                  <div className="space-y-3">
                    <div className={`h-4 w-64 ${transitionSkeletonClass}`} />
                    <div className={`h-4 w-full ${transitionSkeletonSoftClass}`} />
                    <div className={`h-4 w-11/12 ${transitionSkeletonSoftClass}`} />
                    <div className={`h-4 w-10/12 ${transitionSkeletonSoftClass}`} />
                  </div>
                </div>
              )}

              <div className="min-h-[32rem] divide-y divide-gray-200">
                {[0, 1, 2].map((item) => (
                  <div key={item} className="p-4">
                    <div className="flex flex-col gap-3">
                      <div className="flex items-start gap-3">
                        <div className="h-16 w-16 rounded-lg bg-gray-200" />
                        <div className="min-w-0 flex-1">
                          <div className={`mb-2 h-5 w-3/5 ${transitionSkeletonClass}`} />
                          <div className={`h-4 w-1/4 min-w-[8rem] ${transitionSkeletonClass}`} />
                        </div>
                      </div>
                      <div className="space-y-3">
                        <div className={`h-4 w-full ${transitionSkeletonSoftClass}`} />
                        <div className={`h-4 w-5/6 ${transitionSkeletonSoftClass}`} />
                        <div className={`h-4 w-16 ${transitionSkeletonSoftClass}`} />
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-8 w-24 rounded-full bg-gray-200" />
                        <div className={`h-4 w-32 ${transitionSkeletonSoftClass}`} />
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-8 w-24 rounded-md bg-gray-200" />
                        <div className="h-8 w-24 rounded-md bg-gray-200" />
                        <div className="h-8 w-16 rounded-md bg-gray-200" />
                        <div className="ml-auto h-10 w-10 rounded-full bg-gray-200" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex items-center justify-between border-t bg-surface px-4 py-3">
                <div className={`h-4 w-40 ${transitionSkeletonSoftClass}`} />
                <div className="flex items-center gap-2">
                  <div className="h-8 w-20 rounded-md bg-gray-200" />
                  <div className={`h-4 w-20 ${transitionSkeletonSoftClass}`} />
                  <div className="h-8 w-16 rounded-md bg-gray-200" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <ModalShell
        isOpen={showProcessingModal && pendingEpisode !== null}
        onClose={handleCancelProcessing}
        panelClassName="bg-surface rounded-lg shadow-2xl max-w-lg w-full p-6 space-y-4"
      >
        {pendingEpisode && (
          <>
            <h3 className="text-lg font-semibold text-gray-900">Enable episode</h3>
            <p className="text-sm text-gray-600">{pendingEpisode.title}</p>
            {isEstimating && (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <div className="w-4 h-4 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
                Estimating processing time…
              </div>
            )}
            {!isEstimating && estimateError && (
              <p className="text-sm text-red-600">{estimateError}</p>
            )}
            {!isEstimating && processingEstimate && (
              <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 space-y-1">
                <p><strong>Estimated minutes:</strong> {processingEstimate.estimated_minutes.toFixed(2)}</p>
                {!processingEstimate.can_process && (
                  <p className="text-red-600 font-medium">Processing not available for this episode.</p>
                )}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={handleCancelProcessing}
                className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmProcessing}
                disabled={
                  whitelistMutation.isPending ||
                  isEstimating ||
                  !processingEstimate?.can_process
                }
                className="btn btn-primary"
              >
                {whitelistMutation.isPending ? 'Starting…' : 'Confirm & process'}
              </button>
            </div>
          </>
        )}
      </ModalShell>

      <FeedSettingsModal
        feed={currentFeed}
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
        autoWhitelistGlobalDefault={appAutoWhitelistDefault}
        llmChapterFallbackGlobalDefault={
          configResponse?.config?.llm?.enable_llm_chapter_fallback_tagging
        }
        chapterFullBlockTextGlobalDefault={
          configResponse?.config?.llm?.chapter_full_block_text
        }
        whisperType={configResponse?.config?.whisper?.whisper_type}
        episodeDescriptionView={episodeDescriptionView}
        onEpisodeDescriptionViewChange={handleEpisodeDescriptionViewChange}
      />

      <FeedSubscribersModal
        feedId={currentFeed.id}
        feedTitle={currentFeed.title}
        isOpen={showSubscribersModal}
        onClose={() => setShowSubscribersModal(false)}
      />
    </div>
  );
}
