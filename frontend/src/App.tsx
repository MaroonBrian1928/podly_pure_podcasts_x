import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useQuery } from '@tanstack/react-query';
import { useState, useEffect, useRef } from 'react';
import HomePage from './pages/HomePage';
import JobsPage from './pages/JobsPage';
import ConfigPage from './pages/ConfigPage';
import LoginPage from './pages/LoginPage';
import LandingPage from './pages/LandingPage';
import BillingPage from './pages/BillingPage';
import AudioPlayer from './components/AudioPlayer';
import { billingApi, jobsApi } from './services/api';
import type { JobManagerStatus } from './types';
import { DiagnosticsProvider, useDiagnostics } from './contexts/DiagnosticsContext';
import DiagnosticsModal from './components/DiagnosticsModal';
import ThemeToggle from './components/ThemeToggle';
import { ThemeProvider, useTheme } from './contexts/ThemeContext';
import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      // Keep inactive query cache alive for 5 s so in-flight fetches can
      // settle before GC.  gcTime: 0 caused cancelled-query rejections to
      // leak as unhandled promise rejections when a component unmounted
      // while a background refetch was in progress.  30 s was overly long
      // and caused stale data to flash on remount; 5 s is a safe middle
      // ground.
      gcTime: 5_000,
      refetchOnMount: 'always',
      refetchOnWindowFocus: 'always',
      refetchOnReconnect: 'always',
      // Never throw errors into React error boundaries — keep them in the
      // query's own `error` state so the UI can handle them gracefully.
      throwOnError: false,
      // Retry once on transient network failures; avoids hammering the
      // server on persistent errors while still recovering from brief blips.
      // retryDelay: 0 makes the retry immediate — no artificial 1 s pause
      // before the UI shows an error or recovers.
      retry: 1,
      retryDelay: () => 0,
    },
  },
});

function AppShell() {
  const { status, requireAuth, isAuthenticated, user, logout, landingPageEnabled } = useAuth();
  const { open: openDiagnostics } = useDiagnostics();
  const { isDark } = useTheme();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const mobileMenuRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const { data: billingSummary } = useQuery({
    queryKey: ['billing', 'summary'],
    queryFn: billingApi.getSummary,
    enabled: !!user && requireAuth && isAuthenticated,
    retry: false,
  });

  const { data: jobManagerStatus } = useQuery({
    queryKey: ['job-manager', 'status', 'nav'],
    queryFn: jobsApi.getJobManagerStatus,
    enabled: !requireAuth || user?.role === 'admin',
    refetchInterval: (query) => {
      const run = (query.state.data as JobManagerStatus | undefined)?.run;
      const active = (run?.running_jobs ?? 0) + (run?.queued_jobs ?? 0);
      return active > 0 ? 15_000 : 60_000;
    },
    retry: false,
  });
  const activeJobsCount = (jobManagerStatus?.run?.running_jobs ?? 0) + (jobManagerStatus?.run?.queued_jobs ?? 0);
  const activeJobsLabel = activeJobsCount > 99 ? '99+' : String(activeJobsCount);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  // Close mobile menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (mobileMenuRef.current && !mobileMenuRef.current.contains(event.target as Node)) {
        setMobileMenuOpen(false);
      }
    }
    if (mobileMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [mobileMenuOpen]);

  if (status === 'loading') {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
          <p className="text-sm text-gray-600">Loading authentication…</p>
        </div>
      </div>
    );
  }

  // Show landing page for unauthenticated users when auth is required
  // But allow access to /login route
  if (requireAuth && !isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {landingPageEnabled ? (
          <Route path="*" element={<LandingPage />} />
        ) : (
          <>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </>
        )}
      </Routes>
    );
  }

  const isAdmin = !requireAuth || user?.role === 'admin';
  const showConfigLink = !requireAuth || isAdmin;
  const showJobsLink = !requireAuth || isAdmin;
  const showBillingLink = requireAuth && !isAdmin;

  return (
    <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
      <header className="bg-white shadow-sm border-b flex-shrink-0">
        <div className="px-2 sm:px-4 lg:px-6">
          <div className="flex items-center justify-between h-12">
            <div className="flex items-center">
              <Link to="/" className="flex items-center">
                <img 
                  src="/images/logos/logo.webp" 
                  alt="Podly" 
                  className="h-6 w-auto"
                />
                <h1 className="ml-2 text-lg font-semibold text-gray-900">
                  Podly
                </h1>
              </Link>
            </div>

            {/* Desktop Navigation */}
            <nav className="hidden md:flex items-center space-x-4">
              <Link to="/" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                Home
              </Link>
              {showBillingLink && (
                <Link to="/billing" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                  Billing
                </Link>
              )}
              {showJobsLink && (
                <Link to="/jobs" className="flex items-center gap-1.5 text-sm font-medium text-gray-700 hover:text-gray-900">
                  Jobs
                  {activeJobsCount > 0 && (
                    <span className="flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 dark:bg-red-600 text-white text-[10px] font-bold leading-none">
                      {activeJobsLabel}
                    </span>
                  )}
                </Link>
              )}
              {showConfigLink && (
                <Link to="/config" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                  Config
                </Link>
              )}
              <button
                type="button"
                onClick={() => openDiagnostics()}
                className="text-sm font-medium text-gray-700 hover:text-gray-900"
              >
                Report issue
              </button>
              <ThemeToggle />
              {requireAuth && user && (
                <div className="flex items-center gap-3 text-sm text-gray-600 flex-shrink-0">
                  {billingSummary && !isAdmin && (
                    <>
                      <div
                        className="px-2 py-1 rounded-md border border-blue-200 text-blue-700 bg-blue-50 text-xs whitespace-nowrap"
                        title="Feeds included in your plan"
                      >
                        Feeds {billingSummary.feeds_in_use}/{billingSummary.feed_allowance}
                      </div>
                      <Link
                        to="/billing"
                        className="px-2 py-1 rounded-md border border-blue-200 text-blue-700 bg-white hover:bg-blue-50 text-xs whitespace-nowrap transition-colors"
                      >
                        Change plan
                      </Link>
                    </>
                  )}
                  <span className="hidden sm:inline whitespace-nowrap">{user.username}</span>
                  <button
                    onClick={logout}
                    className="px-3 py-1 border border-gray-200 rounded-md hover:bg-gray-100 transition-colors whitespace-nowrap"
                  >
                    Logout
                  </button>
                </div>
              )}
            </nav>

            {/* Mobile: Credits + Hamburger */}
            <div className="md:hidden flex items-center gap-2">
              {requireAuth && user && billingSummary && !isAdmin && (
                <>
                  <div
                    className="px-2 py-1 rounded-md border border-blue-200 text-blue-700 bg-blue-50 text-xs whitespace-nowrap"
                    title="Feeds included in your plan"
                  >
                    Feeds {billingSummary.feeds_in_use}/{billingSummary.feed_allowance}
                  </div>
                  <Link
                    to="/billing"
                    className="px-2 py-1 rounded-md border border-blue-200 text-blue-700 bg-white text-xs whitespace-nowrap"
                  >
                    Change plan
                  </Link>
                </>
              )}

              <ThemeToggle />

              {showJobsLink && activeJobsCount > 0 && (
                <Link
                  to="/jobs"
                  aria-label={`${activeJobsCount} active jobs`}
                  className="flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-red-500 dark:bg-red-600 text-white text-[11px] font-bold leading-none"
                >
                  {activeJobsLabel}
                </Link>
              )}

              {/* Hamburger Button */}
              <div className="relative" ref={mobileMenuRef}>
                <button
                  onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                  className="p-2 rounded-md text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors"
                  aria-label="Toggle menu"
                >
                  {mobileMenuOpen ? (
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  ) : (
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                  )}
                </button>

                {/* Mobile Menu Dropdown */}
                {mobileMenuOpen && (
                  <div className="absolute right-0 top-full mt-2 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-2 z-50">
                    <Link
                      to="/"
                      className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                    >
                      Home
                    </Link>
                    {showBillingLink && (
                      <Link
                        to="/billing"
                        className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                      >
                        Billing
                      </Link>
                    )}
                    {showJobsLink && (
                      <Link
                        to="/jobs"
                        className="flex items-center justify-between px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                      >
                        Jobs
                        {activeJobsCount > 0 && (
                          <span className="flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 dark:bg-red-600 text-white text-[10px] font-bold leading-none">
                            {activeJobsLabel}
                          </span>
                        )}
                      </Link>
                    )}
                    {showConfigLink && (
                      <Link
                        to="/config"
                        className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                      >
                        Config
                      </Link>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        openDiagnostics();
                        setMobileMenuOpen(false);
                      }}
                      className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                    >
                      Report issue
                    </button>
                    {requireAuth && user && (
                      <>
                        <div className="border-t border-gray-100 my-2" />
                        <div className="px-4 py-2 text-sm text-gray-500">
                          {user.username}
                        </div>
                        <button
                          onClick={() => {
                            logout();
                            setMobileMenuOpen(false);
                          }}
                          className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                        >
                          Logout
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 px-2 sm:px-4 lg:px-6 py-4 overflow-auto">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/feeds/:feedId" element={<HomePage />} />
          {showBillingLink && <Route path="/billing" element={<BillingPage />} />}
          {showJobsLink && <Route path="/jobs" element={<JobsPage />} />}
          {showConfigLink && <Route path="/config" element={<ConfigPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <AudioPlayer />
      <DiagnosticsModal />
      <Toaster
        position="top-center"
        toastOptions={{
          duration: 3000,
          style: isDark
            ? {
                background: '#0f172a',
                color: '#e2e8f0',
                border: '1px solid #334155',
              }
            : {
                background: '#ffffff',
                color: '#111827',
                border: '1px solid #e5e7eb',
              },
        }}
      />
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <AudioPlayerProvider>
            <DiagnosticsProvider>
              <Router>
                <AppShell />
              </Router>
            </DiagnosticsProvider>
          </AudioPlayerProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
