import { useState } from 'react';

import { feedsApi } from '../services/api';
import { getHttpErrorInfo } from '../utils/httpError';

interface ErrorTroubleshooterProps {
  episodeGuid: string;
  jobId?: string;
  className?: string;
}

/**
 * Self-contained "Explain this error" control shown on the failure state.
 *
 * Deliberately independent of the processing-stats modal, which only renders
 * for successfully processed episodes. On failure that modal (and the Related
 * Logs panel inside it) never appears, so this is the only path a user has to
 * a plain-English explanation of what went wrong.
 */
export default function ErrorTroubleshooter({
  episodeGuid,
  jobId,
  className = '',
}: ErrorTroubleshooterProps) {
  const [loading, setLoading] = useState(false);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setLoading(true);
    setError(null);
    setInfo(null);
    setExplanation(null);
    try {
      const result = await feedsApi.troubleshootPost(episodeGuid, jobId);
      if (result.ok && result.explanation) {
        setExplanation(result.explanation);
      } else if (result.ok) {
        setInfo(result.message || 'No error details were found for this episode.');
      } else {
        setError(result.error || 'Could not generate an explanation.');
      }
    } catch (err) {
      setError(getHttpErrorInfo(err).message || 'Could not generate an explanation.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`mt-2 text-left ${className}`}>
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className="inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading ? 'Analyzing logs…' : 'Explain this error'}
      </button>

      {explanation && (
        <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs leading-5 text-gray-800 whitespace-pre-wrap break-words">
          {explanation}
        </div>
      )}
      {info && (
        <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs leading-5 text-gray-600">
          {info}
        </div>
      )}
      {error && (
        <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}
