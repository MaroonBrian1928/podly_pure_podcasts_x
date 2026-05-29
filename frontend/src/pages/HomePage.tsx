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

const MOBILE_FEED_DETAIL_TRANSITION_MS = 440;
const HOME_ROUTE_QUERY_GC_TIME_MS = 5 * 60 * 1000;

type MobileFeedTransitionState = 'idle' | 'entering' | 'exiting';

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

    if (!isMobileFeedViewport()) {
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
      mobileFeedTransitionTimeoutRef.current = window.setTimeout(() => {
        setMobileFeedTransitionState('idle');
        setMobileTransitionFeed(null);
        setMobileTransitionViewport(null);
        mobileFeedTransitionTimeoutRef.current = null;
      }, MOBILE_FEED_DETAIL_TRANSITION_MS);
    } else if (previousSelectedFeedId !== null && nextSelectedFeedId === null && previousSelectedFeed) {
      setMobileTransitionViewport(
        captureMobileTransitionViewport(pageContainerRef.current)
      );
      setMobileTransitionFeed(previousSelectedFeed);
      setMobileFeedTransitionState('exiting');
      mobileFeedTransitionTimeoutRef.current = window.setTimeout(() => {
        setMobileFeedTransitionState('idle');
        setMobileTransitionFeed(null);
        setMobileTransitionViewport(null);
        mobileFeedTransitionTimeoutRef.current = null;
      }, MOBILE_FEED_DETAIL_TRANSITION_MS);
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
      mobileFeedTransitionTimeoutRef.current = window.setTimeout(() => {
        setMobileFeedTransitionState('idle');
        setMobileTransitionFeed(null);
        setMobileTransitionViewport(null);
        mobileFeedTransitionTimeoutRef.current = null;
      }, MOBILE_FEED_DETAIL_TRANSITION_MS);
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
    };
  }, []);

  useEffect(() => {
    if (!showSortMenu) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (!sortMenuRef.current?.contains(event.target as Node)) {
        setShowSortMenu(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [showSortMenu]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-4">
        <p className="text-red-800">Error loading feeds. Please try again.</p>
      </div>
    );
  }

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
  const mobileFeedDetailAnimationClass =
    mobileFeedTransitionState === 'entering'
      ? 'podly-mobile-feed-detail-enter'
      : mobileFeedTransitionState === 'exiting'
        ? 'podly-mobile-feed-detail-exit'
        : '';
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
        <div className="mb-6 flex min-w-0 items-center gap-3">
          <h2 className="shrink-0 text-2xl font-bold text-gray-900">
            Podcast Feeds
          </h2>
          <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
            <div ref={sortMenuRef} className="relative shrink-0">
              <button
                type="button"
                onClick={() => setShowSortMenu((prev) => !prev)}
                title="Sort podcast feeds"
                aria-haspopup="menu"
                aria-expanded={showSortMenu}
                className="h-10 w-10 flex items-center justify-center rounded-md border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <svg
                  className="w-4 h-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M3 6h13" />
                  <path d="M3 12h9" />
                  <path d="M3 18h5" />
                  <path d="M17 8V4m0 0l-3 3m3-3l3 3" />
                  <path d="M17 16v4m0 0l-3-3m3 3l3-3" />
                </svg>
                <span className="sr-only">Sort feeds</span>
              </button>
              {showSortMenu && (
                <div
                  role="menu"
                  className="absolute right-0 top-full mt-1 w-48 rounded-md border border-gray-200 bg-white py-1 shadow-lg z-20 max-w-[calc(100vw-2rem)]"
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
                            ? 'font-medium text-blue-600'
                            : 'text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        <span>{option.label}</span>
                        {isActive && (
                          <svg
                            className="h-3.5 w-3.5 shrink-0 text-blue-600"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden="true"
                          >
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            {canRefreshAll && (
              <button
                onClick={() => refreshAllMutation.mutate()}
                disabled={refreshAllMutation.isPending}
                title="Refresh all feeds"
                className={`h-10 w-10 shrink-0 flex items-center justify-center rounded-md border transition-colors ${
                  refreshAllMutation.isPending
                    ? 'border-gray-200 text-gray-400 cursor-not-allowed'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-100'
                }`}
              >
                <svg
                  className={`w-4 h-4 ${refreshAllMutation.isPending ? 'animate-spin' : ''}`}
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M21 12a9 9 0 1 1-2.64-6.36" />
                  <path d="M21 3v6h-6" />
                </svg>
                <span className="sr-only">Refresh all</span>
              </button>
            )}
            <button
              onClick={handleCopyAggregateLink}
              className="h-10 w-10 shrink-0 flex items-center justify-center rounded-md border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors"
              title="Copy your aggregate feed URL (last 3 episodes from each feed)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </button>
            <button
              onClick={() => {
                if (planLimitReached) {
                  navigate('/billing');
                } else {
                  setShowAddForm((prev) => !prev);
                }
              }}
              className={`h-10 shrink-0 inline-flex items-center justify-center rounded-md px-4 font-medium transition-colors ${
                planLimitReached
                  ? 'bg-amber-600 hover:bg-amber-700 text-white'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
              title={planLimitReached ? 'Your plan is full. Click to upgrade.' : undefined}
            >
              {planLimitReached ? 'Plan full' : showAddForm ? 'Close' : 'Add Feed'}
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-hidden">
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
        </div>
      </div>

      {/* Right Panel - Feed Detail */}
      {detailFeed && (
        <div
          className={`${mobileFeedDetailAnimationClass} flex flex-1 flex-col bg-white rounded-lg shadow border overflow-hidden lg:flex-[2] ${
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
      {!selectedFeed && !feedNotFound && (
        <div className="hidden lg:flex flex-[2] items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <div className="text-center">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No podcast selected</h3>
            <p className="mt-1 text-sm text-gray-500">Select a podcast from the list to view details and episodes.</p>
          </div>
        </div>
      )}

      {feedNotFound && (
        <div className="hidden lg:flex flex-[2] items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <div className="text-center">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">Feed not found</h3>
            <p className="mt-1 text-sm text-gray-500">Pick a feed from the list to continue.</p>
          </div>
        </div>
      )}

      <ModalShell
        isOpen={showAddForm}
        onClose={() => setShowAddForm(false)}
        containerClassName="items-start p-4 sm:items-center sm:p-6"
        panelClassName="w-full max-w-3xl bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col max-h-[90vh]"
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
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
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
