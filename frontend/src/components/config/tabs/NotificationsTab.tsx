import { useState } from 'react';
import { toast } from 'react-hot-toast';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, SaveButton } from '../shared';
import { configApi } from '../../../services/api';

export default function NotificationsTab() {
  const { pending, setField, handleSave, isSaving } = useConfigContext();
  const [isTesting, setIsTesting] = useState(false);

  if (!pending) return null;

  const notifications = pending.notifications ?? {
    enabled: false,
    apprise_urls: [],
    notify_on_failure: true,
    include_llm_explanation: true,
  };

  const urls = notifications.apprise_urls ?? [];
  const enabled = !!notifications.enabled;

  const handleTest = async () => {
    const cleaned = urls.map((u) => u.trim()).filter(Boolean);
    if (cleaned.length === 0) {
      toast.error('Add at least one Apprise URL first');
      return;
    }
    setIsTesting(true);
    try {
      const res = await configApi.testNotification({
        notifications: { apprise_urls: cleaned },
      });
      if (res.ok) {
        toast.success(res.message || 'Test notification sent');
      } else {
        toast.error(res.error || 'Failed to send test notification');
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: string } }; message?: string };
      toast.error(
        e?.response?.data?.error || e?.message || 'Failed to send test notification'
      );
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div className="space-y-6">
      <Section title="Notifications">
        <p className="text-sm text-gray-600">
          Get pushed a message when an episode fails to process. Podly uses{' '}
          <a
            href="https://github.com/caronc/apprise/wiki"
            target="_blank"
            rel="noreferrer"
            className="text-indigo-600 hover:underline"
          >
            Apprise
          </a>
          , so you can deliver to Discord, Telegram, ntfy, Slack, email, Pushover, and
          100+ other services by pasting their notification URLs below (one per line).
        </p>

        <Field label="Enable notifications">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setField(['notifications', 'enabled'], e.target.checked)}
          />
        </Field>

        <Field label="Apprise URLs (one per line)">
          <textarea
            className="input font-mono text-xs"
            rows={4}
            placeholder={'discord://webhook_id/webhook_token\nntfy://ntfy.sh/my-topic'}
            value={urls.join('\n')}
            onChange={(e) =>
              setField(['notifications', 'apprise_urls'], e.target.value.split('\n'))
            }
          />
        </Field>

        <Field label="Notify when processing fails">
          <input
            type="checkbox"
            checked={!!notifications.notify_on_failure}
            onChange={(e) =>
              setField(['notifications', 'notify_on_failure'], e.target.checked)
            }
          />
        </Field>

        <Field
          label="Include AI root-cause analysis in failure alerts"
          hint="Runs the same LLM 'Troubleshoot' analysis and adds a plain-English cause to the alert. Costs one extra LLM call per failure."
        >
          <input
            type="checkbox"
            checked={!!notifications.include_llm_explanation}
            onChange={(e) =>
              setField(['notifications', 'include_llm_explanation'], e.target.checked)
            }
          />
        </Field>

        <div className="flex items-center justify-between gap-3">
          <button
            onClick={handleTest}
            className="px-3 py-2 text-sm rounded border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-60"
            disabled={isTesting}
          >
            {isTesting ? 'Sending...' : 'Send test notification'}
          </button>
          <SaveButton onSave={handleSave} isPending={isSaving} />
        </div>
      </Section>
    </div>
  );
}
