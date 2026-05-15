interface SpeakerBreakdownEntry {
  speaker_label?: string | null;
  speaking_time_seconds: number;
  speaking_percentage: number;
  segment_count: number;
}

interface SpeakerTimeBreakdownProps {
  speakerBreakdown?: SpeakerBreakdownEntry[];
}

const formatSpeakingTime = (seconds: number) => {
  if (seconds < 60) {
    const roundedSeconds = seconds >= 10
      ? Math.round(seconds)
      : Math.round(seconds * 10) / 10;
    return Number.isInteger(roundedSeconds)
      ? `${roundedSeconds.toFixed(0)}s`
      : `${roundedSeconds.toFixed(1)}s`;
  }

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.round(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m ${secs}s`;
  }

  return `${minutes}m ${secs}s`;
};

export default function SpeakerTimeBreakdown({
  speakerBreakdown = [],
}: SpeakerTimeBreakdownProps) {
  if (speakerBreakdown.length === 0) {
    return null;
  }

  const totalSpeakingTimeSeconds = speakerBreakdown.reduce(
    (sum, speaker) => sum + speaker.speaking_time_seconds,
    0
  );

  return (
    <div>
      <div className="mb-4 flex flex-col gap-2 text-left sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">Speaker Speaking Time</h3>
          <p className="text-sm text-gray-500">
            Derived from transcript segment durations in the LLM transcription flow.
          </p>
        </div>
        <div className="text-sm text-gray-600">
          Total tracked: <span className="font-semibold text-gray-900">{formatSpeakingTime(totalSpeakingTimeSeconds)}</span>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Speaker</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Speaking Time</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Share</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Segments</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {speakerBreakdown.map((speaker) => {
                const label = speaker.speaker_label || 'Unlabeled speaker';

                return (
                  <tr key={speaker.speaker_label || 'unlabeled-speaker'} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">
                      <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${
                        speaker.speaker_label
                          ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                          : 'border-gray-200 bg-gray-100 text-gray-700'
                      }`}>
                        {label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">
                      {formatSpeakingTime(speaker.speaking_time_seconds)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {speaker.speaking_percentage.toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {speaker.segment_count}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
