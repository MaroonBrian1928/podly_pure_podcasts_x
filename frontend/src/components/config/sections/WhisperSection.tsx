import { useMemo } from 'react';
import { toast } from 'react-hot-toast';
import { configApi } from '../../../services/api';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, ToggleField, SaveButton, TestButton } from '../shared';
import type { WhisperConfig } from '../../../types';

export default function WhisperSection() {
  const {
    pending,
    setField,
    getEnvHint,
    isFieldReadOnly,
    handleSave,
    isSaving,
    handleWhisperTypeChange,
    getWhisperApiKey,
    envOverrides,
  } = useConfigContext();

  const whisperTypeReadOnly = isFieldReadOnly('whisper.whisper_type');
  const whisperApiKeyReadOnly = isFieldReadOnly('whisper.api_key');
  const whisperModelReadOnly = isFieldReadOnly('whisper.model');
  const whisperBaseUrlReadOnly = isFieldReadOnly('whisper.base_url');
  const whisperTimeoutReadOnly = isFieldReadOnly('whisper.timeout_sec');
  const whisperChunksizeReadOnly = isFieldReadOnly('whisper.chunksize_mb');
  const whisperDiarizeReadOnly = isFieldReadOnly('whisper.diarize');
  const whisperSpeakerEmbeddingsReadOnly = isFieldReadOnly('whisper.speaker_embeddings');
  const whisperMaxRetriesReadOnly = isFieldReadOnly('whisper.max_retries');

  const whisperApiKeyPreview =
    pending?.whisper?.whisper_type === 'remote' || pending?.whisper?.whisper_type === 'groq'
      ? (pending.whisper as { api_key_preview?: string }).api_key_preview
      : undefined;

  const whisperApiKeyPlaceholder = useMemo(() => {
    if (pending?.whisper?.whisper_type === 'remote' || pending?.whisper?.whisper_type === 'groq') {
      if (whisperApiKeyPreview) {
        return whisperApiKeyPreview;
      }
      const override = envOverrides['whisper.api_key'];
      if (override) {
        return override.value_preview || override.value || '';
      }
    }
    return '';
  }, [whisperApiKeyPreview, pending?.whisper?.whisper_type, envOverrides]);

  if (!pending) return null;

  const handleTestWhisper = () => {
    toast.promise(configApi.testWhisper({ whisper: pending.whisper as WhisperConfig }), {
      loading: 'Testing Whisper…',
      success: (res: { ok: boolean; message?: string }) => res?.message || 'Whisper OK',
      error: (err: unknown) => {
        const e = err as {
          response?: { data?: { error?: string; message?: string } };
          message?: string;
        };
        return (
          e?.response?.data?.error ||
          e?.response?.data?.message ||
          e?.message ||
          'Whisper test failed'
        );
      },
    });
  };

  const whisperType = pending?.whisper?.whisper_type === 'groq' ? 'groq' : 'remote';
  const isRemote = pending?.whisper?.whisper_type === 'remote';
  const isGroq = pending?.whisper?.whisper_type === 'groq';
  const remoteWhisper = isRemote
    ? (pending.whisper as Extract<WhisperConfig, { whisper_type: 'remote' }>)
    : null;
  const diarizeEnabled = remoteWhisper?.diarize ?? false;

  return (
    <div className="space-y-6">
      <Section title="Transcription service">
        <Field label="Provider" envMeta={getEnvHint('whisper.whisper_type')}>
          <select
            className="input"
            value={whisperType}
            onChange={(e) => handleWhisperTypeChange(e.target.value as 'remote' | 'groq')}
            disabled={whisperTypeReadOnly}
          >
            <option value="remote">Remote (OpenAI-compatible)</option>
            <option value="groq">Groq</option>
          </select>
        </Field>

        <Field label="API key" envMeta={getEnvHint('whisper.api_key')}>
          <input
            className="input"
            type="text"
            placeholder={whisperApiKeyPlaceholder}
            value={getWhisperApiKey(pending?.whisper)}
            onChange={(e) => setField(['whisper', 'api_key'], e.target.value)}
            disabled={whisperApiKeyReadOnly}
          />
        </Field>

        <Field label="Model" envMeta={getEnvHint('whisper.model')}>
          <input
            className="input"
            type="text"
            value={
              (pending?.whisper as { model?: string })?.model ||
              (isGroq ? 'whisper-large-v3-turbo' : 'whisper-1')
            }
            onChange={(e) => setField(['whisper', 'model'], e.target.value)}
            disabled={whisperModelReadOnly}
          />
        </Field>

        {isRemote && (
          <Field label="Base URL" envMeta={getEnvHint('whisper.base_url')}>
            <input
              className="input"
              type="text"
              placeholder="https://api.openai.com/v1"
              value={(pending?.whisper as { base_url?: string })?.base_url || ''}
              onChange={(e) => setField(['whisper', 'base_url'], e.target.value)}
              disabled={whisperBaseUrlReadOnly}
            />
          </Field>
        )}

        <Field label="Language">
          <input
            className="input"
            type="text"
            value={(pending?.whisper as { language?: string })?.language || 'en'}
            onChange={(e) => setField(['whisper', 'language'], e.target.value)}
          />
        </Field>

        <TestButton onClick={handleTestWhisper} label="Test connection" />
      </Section>

      <Section title="Limits" collapsible>
        <div className="grid gap-5 sm:grid-cols-2">
          {isRemote && (
            <>
              <Field label="Timeout (seconds)" envMeta={getEnvHint('whisper.timeout_sec')}>
                <input
                  className="input"
                  type="number"
                  value={(pending?.whisper as { timeout_sec?: number })?.timeout_sec ?? 600}
                  onChange={(e) => setField(['whisper', 'timeout_sec'], Number(e.target.value))}
                  disabled={whisperTimeoutReadOnly}
                />
              </Field>
              <Field label="Chunk size (MB)" envMeta={getEnvHint('whisper.chunksize_mb')}>
                <input
                  className="input"
                  type="number"
                  value={(pending?.whisper as { chunksize_mb?: number })?.chunksize_mb ?? 24}
                  onChange={(e) => setField(['whisper', 'chunksize_mb'], Number(e.target.value))}
                  disabled={whisperChunksizeReadOnly}
                />
              </Field>
            </>
          )}
          {isGroq && (
            <Field label="Max retries" envMeta={getEnvHint('whisper.max_retries')}>
              <input
                className="input"
                type="number"
                value={(pending?.whisper as { max_retries?: number })?.max_retries ?? 3}
                onChange={(e) => setField(['whisper', 'max_retries'], Number(e.target.value))}
                disabled={whisperMaxRetriesReadOnly}
              />
            </Field>
          )}
        </div>
      </Section>

      {isRemote && (
        <Section title="Speaker detection">
          <div className="space-y-4">
            <ToggleField
              label="Detect speakers (diarization)"
              hint="Asks the remote service to label who is speaking in the transcript."
              envMeta={getEnvHint('whisper.diarize')}
              checked={diarizeEnabled}
              onChange={(checked) => {
                setField(['whisper', 'diarize'], checked);
                if (!checked) {
                  setField(['whisper', 'speaker_embeddings'], false);
                }
              }}
              disabled={whisperDiarizeReadOnly}
            />
            <ToggleField
              label="Return speaker embeddings"
              hint="Needs speaker detection. Includes voice embeddings alongside the diarization output."
              envMeta={getEnvHint('whisper.speaker_embeddings')}
              checked={remoteWhisper?.speaker_embeddings ?? false}
              onChange={(checked) => setField(['whisper', 'speaker_embeddings'], checked)}
              disabled={whisperSpeakerEmbeddingsReadOnly || !diarizeEnabled}
            />
          </div>
        </Section>
      )}

      <Section title="Word timestamps">
        <ToggleField
          label="Record word timestamps"
          hint="Asks the transcription service for per-word timing and keeps it with the episode. Word-level boundary refinement and profanity bleeping need it and request it even when this is off. Adds roughly 1 MB of stored data per hour of audio."
          checked={pending?.processing?.record_word_timestamps ?? true}
          onChange={(checked) =>
            setField(['processing', 'record_word_timestamps'], checked)
          }
        />
      </Section>

      <SaveButton onSave={handleSave} isPending={isSaving} />
    </div>
  );
}
