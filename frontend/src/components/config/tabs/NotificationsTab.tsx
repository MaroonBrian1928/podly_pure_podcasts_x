import { useState } from 'react';
import { toast } from 'react-hot-toast';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, ToggleField, SaveButton } from '../shared';
import { configApi } from '../../../services/api';

export default function NotificationsTab() {
  const { pending, setField, handleSave, isSaving } = useConfigContext();
  const [isTesting, setIsTesting] = useState(false);

  if (!pending) return null;

  const notifications = pending.notifications ?? {
    enabled: false,
    apprise_urls: [],
    notify_on_failure: true,
    notify_on_success: false,
    notify_on_rust_fallback: false,
    include_llm_explanation: true,
  };

  const urls = notifications.apprise_urls ?? [];

  const handleTest = async () => {
    const cleaned = urls.map((u) => u.trim()).filter(Boolean);
    if (cleaned.length === 0) {
      toast.error('Add at least one Apprise URL, then send the test again.');
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
        toast.error(
          res.error || 'Could not send the test notification. Check your Apprise URLs.'
        );
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: string } }; message?: string };
      toast.error(
        e?.response?.data?.error ||
          e?.message ||
          'Could not send the test notification. Check your Apprise URLs.'
      );
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div className="space-y-6">
      <Section title="Delivery">
        <ToggleField
          label="Send notifications"
          hint="Push a message to your Apprise services when episodes need attention."
          checked={!!notifications.enabled}
          onChange={(checked) => setField(['notifications', 'enabled'], checked)}
        />

        <Field
          label="Apprise URLs (one per line)"
          hint={
            <>
              Example: <code>ntfy://ntfy.sh/my-topic</code>. See the{' '}
              <a
                href="https://github.com/caronc/apprise/wiki"
                target="_blank"
                rel="noreferrer"
                className="text-blue-700 underline hover:text-blue-800"
              >
                Apprise docs
              </a>{' '}
              for Discord, Telegram, Slack, email and 100+ other services.
            </>
          }
        >
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

        <div>
          <button
            type="button"
            onClick={handleTest}
            className="btn btn-secondary"
            disabled={isTesting}
          >
            {isTesting ? 'Sending…' : 'Send test notification'}
          </button>
        </div>
      </Section>

      <Section title="Events">
        <div className="space-y-4">
          <ToggleField
            label="Episode fails to process"
            hint="Includes the episode or feed, the failing step and the error."
            checked={!!notifications.notify_on_failure}
            onChange={(checked) => setField(['notifications', 'notify_on_failure'], checked)}
          />
          {notifications.notify_on_failure && (
            <div className="pl-6">
              <ToggleField
                label="Add LLM root-cause analysis to failures"
                hint="Runs the LLM troubleshoot analysis; costs one extra LLM call per failure."
                checked={!!notifications.include_llm_explanation}
                onChange={(checked) =>
                  setField(['notifications', 'include_llm_explanation'], checked)
                }
              />
            </div>
          )}
          <ToggleField
            label="Episode finishes processing"
            hint="One alert per completed episode, so expect higher volume."
            checked={!!notifications.notify_on_success}
            onChange={(checked) => setField(['notifications', 'notify_on_success'], checked)}
          />
          <ToggleField
            label="Rust sidecar falls back to Python"
            hint="Processing still works; alerts are throttled per operation."
            checked={!!notifications.notify_on_rust_fallback}
            onChange={(checked) =>
              setField(['notifications', 'notify_on_rust_fallback'], checked)
            }
          />
        </div>
      </Section>

      <SaveButton onSave={handleSave} isPending={isSaving} />
    </div>
  );
}
