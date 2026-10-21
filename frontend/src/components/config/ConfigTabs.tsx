import { useMemo, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import useConfigState from '../../hooks/useConfigState';
import {
  ADVANCED_SUBTABS,
  ConfigContext,
  type ConfigTabId,
  type AdvancedSubtab,
} from './ConfigContext';
import { EnvOverrideWarningModal } from './shared';
import DefaultTab from './tabs/DefaultTab';
import AdvancedTab from './tabs/AdvancedTab';
import UserManagementTab from './tabs/UserManagementTab';
import DiscordTab from './tabs/DiscordTab';
import CostsTab from './tabs/CostsTab';
import NotificationsTab from './tabs/NotificationsTab';

const TABS: { id: ConfigTabId; label: string; adminOnly?: boolean }[] = [
  { id: 'default', label: 'Basics' },
  { id: 'advanced', label: 'Advanced' },
  { id: 'users', label: 'Users', adminOnly: true },
  { id: 'discord', label: 'Discord', adminOnly: true },
  { id: 'costs', label: 'Costs', adminOnly: true },
  { id: 'notifications', label: 'Notifications', adminOnly: true },
];

const sidebarItem = 'block w-full rounded-md px-3 py-1.5 text-left text-sm font-medium transition-colors';
const sidebarActive = 'bg-gray-100 text-gray-900';
const sidebarInactive = 'text-gray-600 hover:bg-gray-50 hover:text-gray-900';

export default function ConfigTabs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user, requireAuth, showDiscordIntegration } = useAuth();
  const configState = useConfigState();

  const showSecurityControls = requireAuth && !!user;
  const isAdmin = !requireAuth || (showSecurityControls && user?.role === 'admin');

  // Get tab from URL or default
  const activeTab = useMemo<ConfigTabId>(() => {
    const urlTab = searchParams.get('tab') as ConfigTabId | null;
    if (urlTab && TABS.some((t) => t.id === urlTab)) {
      // Check admin-only tabs
      const tab = TABS.find((t) => t.id === urlTab);
      if (tab?.adminOnly && !isAdmin) {
        return 'default';
      }
      if (urlTab === 'discord' && !showDiscordIntegration) {
        return 'default';
      }
      if (urlTab === 'users' && !requireAuth) {
        return 'default';
      }
      return urlTab;
    }
    return 'default';
  }, [searchParams, isAdmin, requireAuth, showDiscordIntegration]);

  const activeSubtab = useMemo<AdvancedSubtab>(() => {
    const urlSubtab = searchParams.get('section') as AdvancedSubtab | null;
    if (urlSubtab && ['llm', 'whisper', 'processing', 'output', 'app'].includes(urlSubtab)) {
      return urlSubtab;
    }
    return 'llm';
  }, [searchParams]);

  const setActiveTab = useCallback((tab: ConfigTabId) => {
    setSearchParams((prev) => {
      const newParams = new URLSearchParams(prev);
      newParams.set('tab', tab);
      if (tab !== 'advanced') {
        newParams.delete('section');
      }
      return newParams;
    }, { replace: true });
  }, [setSearchParams]);

  const setActiveSubtab = useCallback((subtab: AdvancedSubtab) => {
    setSearchParams((prev) => {
      const newParams = new URLSearchParams(prev);
      newParams.set('section', subtab);
      return newParams;
    }, { replace: true });
  }, [setSearchParams]);

  // Redirect if on admin-only tab without permission
  useEffect(() => {
    const tab = TABS.find((t) => t.id === activeTab);
    if (tab?.adminOnly && !isAdmin) {
      setActiveTab('default');
    }
  }, [isAdmin, activeTab, setActiveTab]);

  const contextValue = useMemo(
    () => ({
      ...configState,
      activeTab,
      setActiveTab,
      activeSubtab,
      setActiveSubtab,
      isAdmin,
      showSecurityControls,
    }),
    [configState, activeTab, setActiveTab, activeSubtab, setActiveSubtab, isAdmin, showSecurityControls]
  );

  const visibleTabs = TABS.filter((tab) => {
    if (tab.id === 'users' && !requireAuth) return false;
    if (tab.id === 'discord' && !showDiscordIntegration) return false;
    return !tab.adminOnly || isAdmin;
  });

  if (configState.isLoading || !configState.pending) {
    return <div className="text-sm text-gray-700">Loading settings…</div>;
  }

  return (
    <ConfigContext.Provider value={contextValue}>
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-gray-900">Settings</h1>

        {/* Below `lg`: tabs across the top. */}
        <div className="overflow-x-auto border-b border-gray-200 lg:hidden">
          <nav className="flex min-w-max space-x-8" role="tablist" aria-label="Settings">
            {visibleTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-3 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
                  activeTab === tab.id
                    ? 'border-blue-600 text-gray-900'
                    : 'border-transparent text-gray-600 hover:text-gray-900'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="lg:grid lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-12">
          {/* From `lg`: a sticky sidebar with the Advanced subtabs nested under Advanced. */}
          <nav className="hidden lg:block" aria-label="Settings">
            <ul className="sticky top-6 space-y-0.5">
              {visibleTabs.map((tab) => {
                const tabActive = activeTab === tab.id;
                return (
                  <li key={tab.id}>
                    <button
                      type="button"
                      aria-current={tabActive && tab.id !== 'advanced' ? 'page' : undefined}
                      onClick={() => setActiveTab(tab.id)}
                      className={`${sidebarItem} ${
                        tabActive && tab.id !== 'advanced' ? sidebarActive : sidebarInactive
                      } ${tabActive && tab.id === 'advanced' ? 'text-gray-900' : ''}`}
                    >
                      {tab.label}
                    </button>
                    {tab.id === 'advanced' && tabActive && (
                      <ul className="mb-1 ml-3 mt-0.5 space-y-0.5 border-l border-gray-200 pl-2">
                        {ADVANCED_SUBTABS.map((subtab) => {
                          const subActive = activeSubtab === subtab.id;
                          return (
                            <li key={subtab.id}>
                              <button
                                type="button"
                                aria-current={subActive ? 'page' : undefined}
                                onClick={() => setActiveSubtab(subtab.id)}
                                className={`${sidebarItem} ${subActive ? sidebarActive : sidebarInactive}`}
                              >
                                {subtab.label}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </nav>

          {/* Forms stay at a readable width; Costs keeps the full width for its tables. */}
          <div className={`min-w-0 ${activeTab === 'costs' ? '' : 'max-w-5xl'}`}>
            {activeTab === 'default' && <DefaultTab />}
            {activeTab === 'advanced' && <AdvancedTab />}
            {activeTab === 'users' && isAdmin && <UserManagementTab />}
            {activeTab === 'discord' && isAdmin && showDiscordIntegration && <DiscordTab />}
            {activeTab === 'costs' && isAdmin && <CostsTab />}
            {activeTab === 'notifications' && isAdmin && <NotificationsTab />}
          </div>
        </div>

        {/* Env Warning Modal */}
        {configState.showEnvWarning && configState.envWarningPaths.length > 0 && (
          <EnvOverrideWarningModal
            paths={configState.envWarningPaths}
            overrides={configState.envOverrides}
            onCancel={configState.handleDismissEnvWarning}
            onConfirm={configState.handleConfirmEnvWarning}
          />
        )}

        {/* Keeps the last settings clear of the audio player overlay. */}
        <div className="h-24"></div>
      </div>
    </ConfigContext.Provider>
  );
}
