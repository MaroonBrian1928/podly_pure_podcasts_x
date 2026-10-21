import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { feedsApi, billingApi } from '../services/api';
import FeedList from '../components/FeedList';
import FeedDetail from '../components/FeedDetail';
import AddFeedForm from '../components/AddFeedForm';
import ModalShell from '../components/ModalShell';
import type { Feed } from '../types';
import {
  loadFeedListSortPreference,
  persistFeedListSortPreference,
} from '../utils/feedListSort';
import type { FeedSortOption } from '../utils/feedListSort';
import { toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { copyToClipboard } from '../utils/clipboard';
import { emitDiagnosticError } from '../utils/diagnostics';
import { getHttpErrorInfo } from '../utils/httpError';
import { useDelayedFlag } from '../hooks/useDelayedFlag';
import { LinkIcon, PlusIcon, RefreshIcon, SlidersIcon, CheckIcon, CloseIcon } from '../components/icons';

const MOBILE_FEED_DETAIL_ENTER_MS = 440;
const MOBILE_FEED_DETAIL_EXIT_MS = 440;
const HOME_ROUTE_QUERY_GC_TIME_MS = 5 * 60 * 1000;

type MobileFeedTransitionState = 'idle' | 'entering' | 'exiting';
type MobileFeedDetailPosition = 'onscreen' | 'offscreen';

interface MobileTransitionViewport {
  height: number;
  top: number;
}

function isMobileFeedViewport(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches;
}

function captureMobileTransitionViewport(
  container: HTMLDivElement | null
): MobileTransitionViewport | null {
  const mainElement = container?.closest('main');
  if (!(mainElement instanceof HTMLElement)) {
    return null;
  }

  return {
    top: mainElement.scrollTop,
    height: mainElement.clientHeight,
  };
}

function scrollMobileMainToTop(container: HTMLDivElement | null): void {
  const mainElement = container?.closest('main');
  if (mainElement instanceof HTMLElement) {
    mainElement.scrollTop = 0;
  }
}

export default function HomePage() {
  const navigate = useNavigate();
  const { feedId } = useParams();
  const location = useLocation();
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedFeed, setSelectedFeed] = useState<Feed | null>(null);
  const [mobileFeedTransitionState, setMobileFeedTransitionState] =
    useState<MobileFeedTransitionState>('idle');
  const [mobileTransitionFeed, setMobileTransitionFeed] = useState<Feed | null>(null);
  const [mobileTransitionViewport, setMobileTransitionViewport] =
    useState<MobileTransitionViewport | null>(null);
  const [mobileDetailPosition, setMobileDetailPosition] =
    useState<MobileFeedDetailPosition>('onscreen');
  const mobileDetailFrameRef = useRef<number | null>(null);
  const [showSortMenu, setShowSortMenu] = useState(false);
  const sortMenuRef = useRef<HTMLDivElement>(null);
  const [feedSortBy, setFeedSortBy] = useState<FeedSortOption>(() =>
    loadFeedListSortPreference()
  );
  const pageContainerRef = useRef<HTMLDivElement>(null);
  const previousSelectedFeedRef = useRef<Feed | null>(null);
  const mobileFeedTransitionTimeoutRef = useRef<number | null>(null);
  const { requireAuth, user } = useAuth();

  const { data: feeds, isLoading, error, refetch } = useQuery({
    queryKey: ['feeds'],
    queryFn: feedsApi.getFeeds,
    gcTime: HOME_ROUTE_QUERY_GC_TIME_MS,
  });
  const showSkeleton = useDelayedFlag(isLoading);

  const { data: billingSummary, refetch: refetchBilling } = useQuery({
    queryKey: ['billing', 'summary'],
    queryFn: billingApi.getSummary,
    enabled: requireAuth && !!user,
    gcTime: HOME_ROUTE_QUERY_GC_TIME_MS,
  });
  const canRefreshAll = !requireAuth || user?.role === 'admin';
  const refreshAllMutation = useMutation({
    mutationFn: () => feedsApi.refreshAllFeeds(),
    onSuccess: (data) => {
      toast.success(
        `Refreshed ${data.feeds_refreshed} feeds and enqueued ${data.jobs_enqueued} jobs`
      );
      refetch();
    },
    onError: (err) => {
      console.error('Failed to refresh all feeds', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to refresh all feeds',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
        },
      });
    },
  });

  useEffect(() => {
    if (!feeds || !feedId) {
      if (location.pathname === '/' && selectedFeed !== null) {
        setSelectedFeed(null);
      }
      return;
    }

    const parsedId = Number(feedId);
    if (!Number.isFinite(parsedId)) {
      if (selectedFeed !== null) {
        setSelectedFeed(null);
      }
      return;
    }

    const matchingFeed = feeds.find((feed) => feed.id === parsedId) || null;
    if (matchingFeed?.id !== selectedFeed?.id) {
      setSelectedFeed(matchingFeed);
    }
  }, [feeds, feedId, location.pathname, selectedFeed]);

  useLayoutEffect(() => {
    const previousSelectedFeed = previousSelectedFeedRef.current;
    const previousSelectedFeedId = previousSelectedFeed?.id ?? null;
    const nextSelectedFeedId = selectedFeed?.id ?? null;

    if (mobileFeedTransitionTimeoutRef.current !== null) {
      window.clearTimeout(mobileFeedTransitionTimeoutRef.current);
      mobileFeedTransitionTimeoutRef.current = null;
    }
    if (mobileDetailFrameRef.current !== null) {
      window.cancelAnimationFrame(mobileDetailFrameRef.current);
      mobileDetailFrameRef.current = null;
    }

    const beginEnter = () => {
      setMobileDetailPosition('offscreen');
      mobileDetailFrameRef.current = window.requestAnimationFrame(() => {
        mobileDetailFrameRef.current = window.requestAnimationFrame(() => {
          mobileDetailFrameRef.current = null;
          setMobileDetailPosition('onscreen');
        });
      });
    };

    if (!isMobileFeedViewport()) {
      setMobileDetailPosition('onscreen');
      setMobileFeedTransitionState('idle');
      setMobileTransitionFeed(null);
      setMobileTransitionViewport(null);
      previousSelectedFeedRef.current = selectedFeed;
      return;
    }

    if (previousSelectedFeedId === null && nextSelectedFeedId !== null && selectedFeed) {
      scrollMobileMainToTop(pageContainerRef.current);
      setMobileTransitionViewport(
        captureMobileTransitionViewport(pageContainerRef.current)
      );
      setMobileTransitionFeed(selectedFeed);
      setMobileFeedTransitionState('entering');
      beginEnter();
      mobileFeedTransitionTimeoutRef.current = window.setTimeout(() => {
        setMobileFeedTransitionState('idle');
        setMobileTransitionFeed(null);
        setMobileTransitionViewport(null);
        mobileFeedTransitionTimeoutRef.current = null;
      }, MOBILE_FEED_DETAIL_ENTER_MS);
    } else if (previousSelectedFeedId !== null && nextSelectedFeedId === null && previousSelectedFeed) {
      setMobileTransitionViewport(
        captureMobileTransitionViewport(pageContainerRef.current)
      );
      setMobileTransitionFeed(previousSelectedFeed);
      setMobileFeedTransitionState('exiting');
      setMobileDetailPosition('offscreen');
      mobileFeedTransitionTimeoutRef.current = window.setTimeout(() => {
        setMobileFeedTransitionState('idle');
        setMobileTransitionFeed(null);
        setMobileTransitionViewport(null);
        mobileFeedTransitionTimeoutRef.current = null;
      }, MOBILE_FEED_DETAIL_EXIT_MS);
    } else if (
      previousSelectedFeedId !== null &&
      nextSelectedFeedId !== null &&
      previousSelectedFeedId !== nextSelectedFeedId &&
      selectedFeed
    ) {
      scrollMobileMainToTop(pageContainerRef.current);
      setMobileTransitionViewport(
        captureMobileTransitionViewport(pageContainerRef.current)
      );
      setMobileTransitionFeed(selectedFeed);
      setMobileFeedTransitionState('entering');
      beginEnter();
      mobileFeedTransitionTimeoutRef.current = window.setTimeout(() => {
        setMobileFeedTransitionState('idle');
        setMobileTransitionFeed(null);
        setMobileTransitionViewport(null);
        mobileFeedTransitionTimeoutRef.current = null;
      }, MOBILE_FEED_DETAIL_ENTER_MS);
    } else {
      setMobileFeedTransitionState('idle');
      setMobileTransitionFeed(null);
      setMobileTransitionViewport(null);
    }

    previousSelectedFeedRef.current = selectedFeed;
  }, [selectedFeed]);

  useEffect(() => {
    return () => {
      if (mobileFeedTransitionTimeoutRef.current !== null) {
        window.clearTimeout(mobileFeedTransitionTimeoutRef.current);
      }
      if (mobileDetailFrameRef.current !== null) {
        window.cancelAnimationFrame(mobileDetailFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!showSortMenu) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!sortMenuRef.current?.contains(event.target as Node)) {
        setShowSortMenu(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [showSortMenu]);

  const planLimitReached =
    !!billingSummary &&
    billingSummary.feeds_in_use >= billingSummary.feed_allowance &&
    user?.role !== 'admin';

  const handleChangePlan = () => {
    navigate('/billing');
  };

  const parsedFeedId = feedId ? Number(feedId) : null;
  const feedIdIsValid = parsedFeedId !== null && Number.isFinite(parsedFeedId);
  const feedNotFound = feedIdIsValid && !selectedFeed;
  const detailFeed = selectedFeed ?? mobileTransitionFeed;
  const isMobileFeedTransitioning = mobileFeedTransitionState !== 'idle';
  const mobileFeedTransitionStyle =
    isMobileFeedTransitioning && mobileTransitionViewport
      ? {
          top: mobileTransitionViewport.top,
          height: mobileTransitionViewport.height,
        }
      : undefined;

  const handleCopyAggregateLink = async () => {
    try {
      const { url } = await feedsApi.getAggregateFeedLink();
      await copyToClipboard(url, 'Copy the Aggregate RSS URL:', 'Aggregate feed URL copied to clipboard!');
    } catch (err) {
      console.error('Failed to get aggregate link', err);
      toast.error('Failed to get aggregate feed link');
    }
  };

  const handleAddFeedClick = () => {
    if (planLimitReached) {
      navigate('/billing');
    } else {
      setShowAddForm((prev) => !prev);
    }
  };

  const handleFeedSortChange = (nextSort: FeedSortOption) => {
    setFeedSortBy(nextSort);
    persistFeedListSortPreference(nextSort);
    setShowSortMenu(false);
  };

  const feedSortOptions: { value: FeedSortOption; label: string }[] = [
    { value: 'newest', label: 'Newest Episode' },
    { value: 'oldest', label: 'Oldest Episode' },
    { value: 'title-asc', label: 'Title A–Z' },
    { value: 'title-desc', label: 'Title Z–A' },
    { value: 'feed-added-oldest', label: 'Feed Added (Oldest)' },
    { value: 'feed-added-newest', label: 'Feed Added (Newest)' },
  ];

  return (
    <div ref={pageContainerRef} className="relative h-full flex flex-col lg:flex-row gap-6">
      {/* Left Panel - Feed List (hidden on mobile when feed is selected) */}
      <div className={`flex-1 lg:max-w-md xl:max-w-lg flex flex-col ${
        selectedFeed && !isMobileFeedTransitioning ? 'hidden lg:flex' : 'flex'
      }`}>
        <div className="mb-6 flex flex-wrap items-center gap-x-3 gap-y-3">
          <h1 className="w-full text-2xl font-semibold text-gray-900 sm:w-auto sm:flex-1">
            Podcast Feeds
          </h1>
          <div className="flex items-center gap-2">
            <div ref={sortMenuRef} className="relative">
              <button
                type="button"
                onClick={() => setShowSortMenu((prev) => !prev)}
                title="Sort podcast feeds"
                aria-label="Sort feeds"
                aria-haspopup="menu"
                aria-expanded={showSortMenu}
                className="btn btn-secondary btn-icon"
              >
                <SlidersIcon className="w-4 h-4" />
              </button>
              {showSortMenu && (
                <div
                  role="menu"
                  className="absolute right-0 top-full mt-1 w-48 origin-top-right animate-pop-in rounded-md border border-gray-200 bg-surface py-1 shadow-lg z-20 max-w-[calc(100vw-2rem)]"
                >
                  {feedSortOptions.map((option) => {
                    const isActive = option.value === feedSortBy;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        role="menuitemradio"
                        aria-checked={isActive}
                        onClick={() => handleFeedSortChange(option.value)}
                        className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm leading-5 transition-colors ${
                          isActive
                            ? 'font-medium text-blue-700'
                            : 'text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        <span>{option.label}</span>
                        {isActive && <CheckIcon className="h-3.5 w-3.5 shrink-0 text-blue-700" />}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            {canRefreshAll && (
              <button
                type="button"
                onClick={() => refreshAllMutation.mutate()}
                disabled={refreshAllMutation.isPending}
                title="Refresh all feeds"
                aria-label="Refresh all feeds"
                className="btn btn-secondary btn-icon"
              >
                <RefreshIcon
                  className={`w-4 h-4 ${refreshAllMutation.isPending ? 'animate-spin' : ''}`}
                />
              </button>
            )}
            <button
              type="button"
              onClick={handleCopyAggregateLink}
              className="btn btn-secondary btn-icon"
              aria-label="Copy aggregate feed link"
              title="Copy your aggregate feed URL (last 3 episodes from each feed)"
            >
              <LinkIcon className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={handleAddFeedClick}
              className="btn btn-primary"
              title={planLimitReached ? 'Your plan is full. Click to upgrade.' : undefined}
            >
              <PlusIcon className="w-4 h-4" />
              {planLimitReached ? 'Plan full' : showAddForm ? 'Close' : 'Add Feed'}
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-hidden">
          {isLoading ? (
            showSkeleton && (
            <div className="space-y-2" aria-hidden="true">
              {Array.from({ length: 6 }, (_, index) => (
                <div
                  key={index}
                  className="flex items-start gap-3 rounded-lg border border-gray-200 bg-surface p-4"
                >
                  <div className="h-12 w-12 shrink-0 rounded-md bg-gray-200" />
                  <div className="flex-1 space-y-2 pt-1">
                    <div className="h-4 w-3/4 rounded bg-gray-200" />
                    <div className="h-3 w-1/2 rounded bg-gray-200" />
                  </div>
                </div>
              ))}
            </div>
            )
          ) : error ? (
            <div
              role="alert"
              className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4"
            >
              <p className="text-sm text-red-800">Error loading feeds.</p>
              <button
                type="button"
                onClick={() => refetch()}
                className="btn btn-ghost btn-sm"
              >
                Retry
              </button>
            </div>
          ) : (
            <FeedList 
            feeds={feeds || []} 
            onFeedDeleted={refetch}
            onFeedSelected={(feed) => {
              setSelectedFeed(feed);
              navigate(`/feeds/${feed.id}`);
            }}
            selectedFeedId={
              selectedFeed?.id ??
              (mobileFeedTransitionState === 'exiting' ? mobileTransitionFeed?.id : undefined)
            }
            sortBy={feedSortBy}
          />
          )}
        </div>
      </div>

      {/* Right Panel - Feed Detail */}
      {detailFeed && (
        <div
          data-state={mobileDetailPosition}
          className={`podly-mobile-feed-detail flex flex-1 flex-col bg-surface rounded-lg border border-gray-200 shadow-sm overflow-hidden lg:flex-[2] ${
            isMobileFeedTransitioning
              ? 'absolute left-0 right-0 z-10 lg:static lg:z-auto'
              : ''
          }`}
          style={mobileFeedTransitionStyle}
        >
          <FeedDetail 
            feed={detailFeed}
            onClose={() => {
              setSelectedFeed(null);
              navigate('/');
            }}
            onFeedDeleted={() => {
              setSelectedFeed(null);
              navigate('/');
              refetch();
            }}
          />
        </div>
      )}

      {/* Empty State for Desktop */}
      {!selectedFeed && !feedNotFound && feeds && (
        <div className="hidden lg:flex flex-[2] flex-col items-start gap-4 self-start rounded-lg border border-gray-200 bg-surface p-6 shadow-sm">
          {feeds.length === 0 ? (
            <>
              <h2 className="text-lg font-semibold text-gray-900">No podcasts yet</h2>
              <p className="text-sm text-gray-600">Add a feed to start removing ads from your shows.</p>
              <button type="button" onClick={handleAddFeedClick} className="btn btn-primary">
                <PlusIcon className="w-4 h-4" />
                Add Feed
              </button>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-gray-900">Select a podcast to see its episodes</h2>
              <p className="text-sm text-gray-600">
                <span className="tabular-nums">{feeds.length}</span>{' '}
                {feeds.length === 1 ? 'podcast' : 'podcasts'},{' '}
                <span className="tabular-nums">
                  {feeds.reduce((sum, feed) => sum + (feed.posts_count ?? 0), 0).toLocaleString()}
                </span>{' '}
                episodes in total
              </p>
              <button type="button" onClick={handleCopyAggregateLink} className="btn btn-secondary">
                <LinkIcon className="w-4 h-4" />
                Copy combined RSS link
              </button>
            </>
          )}
        </div>
      )}

      {feedNotFound && (
        <div className="hidden lg:flex flex-[2] flex-col items-start gap-1 self-start rounded-lg border border-gray-200 bg-surface p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Feed not found</h2>
          <p className="text-sm text-gray-600">Pick a feed from the list to continue.</p>
        </div>
      )}

      <ModalShell
        isOpen={showAddForm}
        onClose={() => setShowAddForm(false)}
        containerClassName="items-start p-4 sm:items-center sm:p-6"
        panelClassName="w-full max-w-3xl bg-surface rounded-lg shadow-2xl border border-gray-200 flex flex-col max-h-[90vh]"
      >
            <div className="flex items-center justify-between border-b border-gray-200 px-4 sm:px-6 py-4">
              <div>
                <h2 className="text-xl sm:text-2xl font-semibold text-gray-900">Add a Podcast Feed</h2>
                <p className="text-sm text-gray-500 mt-1">
                  Paste an RSS URL or search the catalog to find shows to follow.
                </p>
              </div>
              <button
                onClick={() => setShowAddForm(false)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
                aria-label="Close add feed modal"
              >
                <CloseIcon className="w-6 h-6" />
              </button>
            </div>

            <div className="overflow-y-auto px-4 sm:px-6 py-4">
              <AddFeedForm
                onSuccess={() => {
                  setShowAddForm(false);
                  refetch();
                  refetchBilling();
                }}
                onUpgradePlan={handleChangePlan}
                planLimitReached={planLimitReached}
              />
            </div>
      </ModalShell>
    </div>
  );
}
