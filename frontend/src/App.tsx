import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Link, NavLink, Navigate, useLocation } from 'react-router-dom';
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
import { billingApi } from './services/api';
import { DiagnosticsProvider, useDiagnostics } from './contexts/DiagnosticsContext';
import DiagnosticsModal from './components/DiagnosticsModal';
import ThemeToggle from './components/ThemeToggle';
import PageTransitionFrame from './components/PageTransitionFrame';
import { ThemeProvider } from './contexts/ThemeContext';
import { CloseIcon, MenuIcon } from './components/icons';

const navItemBase = 'rounded-md px-3 py-1.5 text-sm font-medium';
const navItemInactive = 'text-gray-700 hover:text-gray-900 hover:bg-gray-50';
const navItemActive = 'bg-gray-100 text-gray-900';

function navItemClass({ isActive }: { isActive: boolean }) {
  return `${navItemBase} ${isActive ? navItemActive : navItemInactive}`;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 0,
      refetchOnMount: 'always',
      refetchOnWindowFocus: 'always',
      refetchOnReconnect: 'always',
    },
  },
});

function isHomeRoute(pathname: string): boolean {
  return pathname === '/' || pathname.startsWith('/feeds/');
}

function AppShell() {
  const {
    status,
    requireAuth,
    isAuthenticated,
    user,
    logout,
    landingPageEnabled,
    showReportIssueButton,
  } = useAuth();
  const { open: openDiagnostics } = useDiagnostics();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const mobileMenuRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const previousPathnameRef = useRef<string | null>(null);
  const { data: billingSummary } = useQuery({
    queryKey: ['billing', 'summary'],
    queryFn: billingApi.getSummary,
    enabled: !!user && requireAuth && isAuthenticated,
    retry: false,
  });

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    previousPathnameRef.current = location.pathname;
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
      <div className="h-dvh flex items-center justify-center bg-gray-50">
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
  const previousPathname = previousPathnameRef.current;
  const locationState = location.state as { fromPath?: string } | null;
  const homeNavigationState = { fromPath: location.pathname };
  const homeTransitionSources = ['/login', '/jobs', '/config', '/billing'];
  const homeTransitionSource = locationState?.fromPath ?? previousPathname;
  const shouldAnimateHomePage =
    isHomeRoute(location.pathname) &&
    Boolean(homeTransitionSource && homeTransitionSources.includes(homeTransitionSource));
  const homeTransitionKey = shouldAnimateHomePage
    ? `home-enter-${homeTransitionSource ?? 'unknown'}`
    : 'home';
  const homeRouteElement = (
    <PageTransitionFrame
      transitionKey={homeTransitionKey}
      animateOnMount={shouldAnimateHomePage}
    >
      <HomePage />
    </PageTransitionFrame>
  );

  return (
    <div className="h-dvh bg-gray-50 flex flex-col overflow-hidden">
      <header className="bg-surface border-b flex-shrink-0">
        <div className="px-2 sm:px-4 lg:px-6">
          <div className="flex items-center justify-between h-12">
            <div className="flex items-center">
              <Link to="/" state={homeNavigationState} className="flex items-center">
                <img
                  src="/images/logos/logo.webp"
                  alt="Podly"
                  className="h-6 w-auto"
                />
                <span className="ml-2 text-lg font-semibold text-gray-900">
                  Podly
                </span>
              </Link>
            </div>

            {/* Desktop Navigation */}
            <nav className="hidden md:flex items-center space-x-2">
              <NavLink
                to="/"
                state={homeNavigationState}
                className={`${navItemBase} ${isHomeRoute(location.pathname) ? navItemActive : navItemInactive}`}
                aria-current={isHomeRoute(location.pathname) ? 'page' : undefined}
              >
                Home
              </NavLink>
              {showBillingLink && (
                <NavLink to="/billing" className={navItemClass}>
                  Billing
                </NavLink>
              )}
              {showJobsLink && (
                <NavLink to="/jobs" className={navItemClass}>
                  Jobs
                </NavLink>
              )}
              {showConfigLink && (
                <NavLink to="/config" className={navItemClass}>
                  Config
                </NavLink>
              )}
              {showReportIssueButton && (
                <button
                  type="button"
                  onClick={() => openDiagnostics()}
                  className={`${navItemBase} ${navItemInactive}`}
                >
                  Report issue
                </button>
              )}
              <ThemeToggle className="ml-2" />
              {requireAuth && user && (
                <div className="flex items-center gap-3 ml-2 text-sm text-gray-600 flex-shrink-0">
                  {billingSummary && !isAdmin && (
                    <>
                      <div
                        className="px-2 py-1 rounded-md border border-blue-200 text-blue-700 bg-blue-50 text-xs whitespace-nowrap"
                        title="Feeds included in your plan"
                      >
                        Feeds {billingSummary.feeds_in_use}/{billingSummary.feed_allowance}
                      </div>
                      <Link to="/billing" className="btn btn-secondary whitespace-nowrap">
                        Change plan
                      </Link>
                    </>
                  )}
                  <span className="hidden sm:inline whitespace-nowrap">{user.username}</span>
                  <button onClick={logout} className="btn btn-secondary whitespace-nowrap">
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
                  <Link to="/billing" className="btn btn-secondary btn-sm whitespace-nowrap">
                    Change plan
                  </Link>
                </>
              )}

              <ThemeToggle />

              <div className="relative" ref={mobileMenuRef}>
                <button
                  type="button"
                  onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                  className="p-2 rounded-md text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors"
                  aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
                  aria-expanded={mobileMenuOpen}
                >
                  {mobileMenuOpen ? <CloseIcon className="h-6 w-6" /> : <MenuIcon className="h-6 w-6" />}
                </button>

                {mobileMenuOpen && (
                  <div className="animate-pop-in origin-top-right absolute right-0 top-full mt-2 w-56 bg-surface rounded-lg shadow-lg border border-gray-200 p-2 z-50">
                    <NavLink
                      to="/"
                      state={homeNavigationState}
                      className={`block ${navItemBase} ${isHomeRoute(location.pathname) ? navItemActive : navItemInactive}`}
                      aria-current={isHomeRoute(location.pathname) ? 'page' : undefined}
                    >
                      Home
                    </NavLink>
                    {showBillingLink && (
                      <NavLink to="/billing" className={({ isActive }) => `block ${navItemClass({ isActive })}`}>
                        Billing
                      </NavLink>
                    )}
                    {showJobsLink && (
                      <NavLink to="/jobs" className={({ isActive }) => `block ${navItemClass({ isActive })}`}>
                        Jobs
                      </NavLink>
                    )}
                    {showConfigLink && (
                      <NavLink to="/config" className={({ isActive }) => `block ${navItemClass({ isActive })}`}>
                        Config
                      </NavLink>
                    )}
                    {showReportIssueButton && (
                      <button
                        type="button"
                        onClick={() => {
                          openDiagnostics();
                          setMobileMenuOpen(false);
                        }}
                        className={`block w-full text-left ${navItemBase} ${navItemInactive}`}
                      >
                        Report issue
                      </button>
                    )}
                    {requireAuth && user && (
                      <>
                        <div className="border-t border-gray-100 my-2" />
                        <div className="px-3 py-1.5 text-sm text-gray-600">
                          {user.username}
                        </div>
                        <button
                          onClick={() => {
                            logout();
                            setMobileMenuOpen(false);
                          }}
                          className="btn btn-secondary btn-sm w-full mt-1"
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
          <Route path="/" element={homeRouteElement} />
          <Route path="/feeds/:feedId" element={homeRouteElement} />
          {showBillingLink && (
            <Route
              path="/billing"
              element={
                <PageTransitionFrame key="billing" transitionKey="billing">
                  <BillingPage />
                </PageTransitionFrame>
              }
            />
          )}
          {showJobsLink && (
            <Route
              path="/jobs"
              element={
                <PageTransitionFrame key="jobs" transitionKey="jobs">
                  <JobsPage />
                </PageTransitionFrame>
              }
            />
          )}
          {showConfigLink && (
            <Route
              path="/config"
              element={
                <PageTransitionFrame key="config" transitionKey="config">
                  <ConfigPage />
                </PageTransitionFrame>
              }
            />
          )}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <AudioPlayer />
      <DiagnosticsModal />
      <Toaster
        position="top-center"
        toastOptions={{
          duration: 3000,
          style: {
            background: 'rgb(var(--surface))',
            color: 'rgb(var(--gray-900))',
            border: '1px solid rgb(var(--gray-200))',
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
