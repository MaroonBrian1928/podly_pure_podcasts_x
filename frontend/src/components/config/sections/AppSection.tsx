import { useState, useEffect } from 'react';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, SaveButton } from '../shared';

const EPISODE_DESCRIPTION_VIEW_GLOBAL_KEY = 'podly:episode-description-view:global';

function loadGlobalDescView(): 'source' | 'podly' {
  if (typeof window === 'undefined') return 'source';
  return window.localStorage.getItem(EPISODE_DESCRIPTION_VIEW_GLOBAL_KEY) === 'podly'
    ? 'podly'
    : 'source';
}

export default function AppSection() {
  const { pending, setField, handleSave, isSaving } = useConfigContext();
  const [globalDescView, setGlobalDescView] = useState<'source' | 'podly'>(loadGlobalDescView);

  useEffect(() => {
    window.localStorage.setItem(EPISODE_DESCRIPTION_VIEW_GLOBAL_KEY, globalDescView);
  }, [globalDescView]);

  if (!pending) return null;

  return (
    <div className="space-y-6">
      <Section title="App">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Feed Refresh Background Interval (min)">
            <input
              className="input"
              type="number"
              value={pending?.app?.background_update_interval_minute ?? ''}
              onChange={(e) =>
                setField(
                  ['app', 'background_update_interval_minute'],
                  e.target.value === '' ? null : Number(e.target.value)
                )
              }
            />
          </Field>
          <Field label="Cleanup Retention (days)">
            <input
              className="input"
              type="number"
              min={0}
              value={pending?.app?.post_cleanup_retention_days ?? ''}
              onChange={(e) =>
                setField(
                  ['app', 'post_cleanup_retention_days'],
                  e.target.value === '' ? null : Number(e.target.value)
                )
              }
            />
          </Field>
          <Field label="Auto-whitelist new episodes">
            <input
              type="checkbox"
              checked={!!pending?.app?.automatically_whitelist_new_episodes}
              onChange={(e) =>
                setField(['app', 'automatically_whitelist_new_episodes'], e.target.checked)
              }
            />
          </Field>
          <Field label="List all episodes in RSS and queue processing on download attempt if not previously whitelisted">
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={!!pending?.app?.autoprocess_on_download}
                onChange={(e) => setField(['app', 'autoprocess_on_download'], e.target.checked)}
              />
            </label>
          </Field>
          <Field label="Number of episodes to whitelist from new feed archive">
            <input
              className="input"
              type="number"
              value={pending?.app?.number_of_episodes_to_whitelist_from_archive_of_new_feed ?? 1}
              onChange={(e) =>
                setField(
                  ['app', 'number_of_episodes_to_whitelist_from_archive_of_new_feed'],
                  Number(e.target.value)
                )
              }
            />
          </Field>
          <Field label="Cost Rate Per Hour ($)">
            <input
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={pending?.app?.cost_rate_per_hour ?? 0.04}
              onChange={(e) =>
                setField(
                  ['app', 'cost_rate_per_hour'],
                  Number(e.target.value)
                )
              }
            />
          </Field>
          <div className="col-span-1 md:col-span-2 flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-700 font-medium">
              <input
                type="checkbox"
                checked={!!pending?.app?.enable_public_landing_page}
                onChange={(e) => setField(['app', 'enable_public_landing_page'], e.target.checked)}
              />
              Enable the public landing page
            </label>
          </div>
          <Field label="Apprise API Server URL">
            <input
              className="input"
              type="text"
              placeholder="http://apprise:8000"
              value={pending?.app?.notification_apprise_url ?? ''}
              onChange={(e) => setField(['app', 'notification_apprise_url'], e.target.value)}
            />
          </Field>
          <Field label="Apprise Config Key">
            <input
              className="input"
              type="text"
              placeholder="podly"
              value={pending?.app?.notification_apprise_key ?? ''}
              onChange={(e) => setField(['app', 'notification_apprise_key'], e.target.value)}
            />
          </Field>
          <Field label="Feed Tag Label">
            <input
              className="input"
              type="text"
              placeholder="podly"
              value={pending?.app?.feed_tag_label ?? 'podly'}
              onChange={(e) => setField(['app', 'feed_tag_label'], e.target.value)}
            />
            <p className="text-xs text-gray-500 mt-1">Text shown inside brackets on feed titles. Leave empty to omit the tag entirely.</p>
          </Field>
          <Field label="Feed Tag Position">
            <select
              className="input"
              value={pending?.app?.feed_tag_position ?? 'prefix'}
              onChange={(e) => setField(['app', 'feed_tag_position'], e.target.value)}
            >
              <option value="prefix">[tag] Feed Title</option>
              <option value="suffix">Feed Title [tag]</option>
            </select>
          </Field>
          <div className="col-span-1 md:col-span-2 flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-700 font-medium">
              <input
                type="checkbox"
                checked={!!pending?.app?.feed_tag_override}
                onChange={(e) => setField(['app', 'feed_tag_override'], e.target.checked)}
              />
              Override per-feed tag settings with global defaults
            </label>
            <p className="text-xs text-gray-500">When enabled, the global tag label and position above apply to all feeds, ignoring any per-feed tag customizations.</p>
          </div>
          <Field label="Default episode description view">
            <select
              className="input"
              value={globalDescView}
              onChange={(e) => setGlobalDescView(e.target.value as 'source' | 'podly')}
            >
              <option value="source">Source description</option>
              <option value="podly">Podly description preview</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">
              Default for all feeds. Can be overridden per feed in Feed Settings. Stored in your browser only.
            </p>
          </Field>
        </div>
      </Section>

      <SaveButton onSave={handleSave} isPending={isSaving} />

      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </div>
  );
}
