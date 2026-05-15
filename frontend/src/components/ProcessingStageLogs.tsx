interface ProcessingLogEntry {
  timestamp: string;
  level: string;
  stage: string;
  message: string;
  job_id: string | null;
  step_name: string | null;
}

interface ProcessingStageLogsProps {
  relatedLogs?: {
    latest_job_id: string | null;
    entries: ProcessingLogEntry[];
  } | null;
}

const STAGE_ORDER = ['download', 'transcription', 'classification', 'chapters', 'audio', 'job', 'general'];

const STAGE_META: Record<string, { label: string; badgeClass: string }> = {
  download: {
    label: 'Download',
    badgeClass: 'bg-sky-100 text-sky-800 border-sky-200',
  },
  transcription: {
    label: 'Transcription',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200',
  },
  classification: {
    label: 'Classification',
    badgeClass: 'bg-violet-100 text-violet-800 border-violet-200',
  },
  chapters: {
    label: 'Chapters',
    badgeClass: 'bg-fuchsia-100 text-fuchsia-800 border-fuchsia-200',
  },
  audio: {
    label: 'Audio',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
  job: {
    label: 'Job Status',
    badgeClass: 'bg-amber-100 text-amber-800 border-amber-200',
  },
  general: {
    label: 'General',
    badgeClass: 'bg-gray-100 text-gray-800 border-gray-200',
  },
};

const LEVEL_BADGE_CLASS: Record<string, string> = {
  DEBUG: 'bg-slate-100 text-slate-700',
  INFO: 'bg-blue-50 text-blue-700',
  WARNING: 'bg-amber-50 text-amber-700',
  ERROR: 'bg-red-50 text-red-700',
  CRITICAL: 'bg-rose-100 text-rose-800',
};

export default function ProcessingStageLogs({ relatedLogs }: ProcessingStageLogsProps) {
  const entries = relatedLogs?.entries || [];
  const entriesByStage: Record<string, ProcessingLogEntry[]> = {};

  for (const entry of entries) {
    if (!entriesByStage[entry.stage]) {
      entriesByStage[entry.stage] = [];
    }
    entriesByStage[entry.stage].push(entry);
  }

  const orderedStages = [
    ...STAGE_ORDER.filter((stage) => entriesByStage[stage]?.length),
    ...Object.keys(entriesByStage).filter((stage) => !STAGE_ORDER.includes(stage)),
  ];

  if (!entries.length) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
        No related log lines were found for this episode in the current log window.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div className="flex flex-wrap items-center gap-3 text-sm text-gray-700">
          <span className="font-medium text-gray-900">
            {entries.length} related log {entries.length === 1 ? 'entry' : 'entries'}
          </span>
          {relatedLogs?.latest_job_id && (
            <span className="inline-flex items-center rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600">
              latest job {relatedLogs.latest_job_id}
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-gray-500 text-left">
          Entries are filtered from the recent <code>app.log</code> tail using the current post and recent processing job IDs.
        </p>
      </div>

      {orderedStages.map((stage) => {
        const stageEntries = entriesByStage[stage] || [];
        const stageMeta = STAGE_META[stage] || STAGE_META.general;

        return (
          <section key={stage} className="rounded-lg border border-gray-200 bg-white overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-gray-50 px-4 py-3">
              <div className="flex items-center gap-3">
                <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${stageMeta.badgeClass}`}>
                  {stageMeta.label}
                </span>
                <span className="text-sm text-gray-500">{stageEntries.length} entries</span>
              </div>
            </div>

            <div className="divide-y divide-gray-100">
              {stageEntries.map((entry, index) => (
                <div key={`${entry.timestamp}-${index}-${entry.message.slice(0, 24)}`} className="px-4 py-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-mono text-gray-500">{entry.timestamp}</span>
                    <span className={`inline-flex items-center rounded-full px-2 py-1 font-medium ${LEVEL_BADGE_CLASS[entry.level] || LEVEL_BADGE_CLASS.INFO}`}>
                      {entry.level}
                    </span>
                    {entry.step_name && (
                      <span className="inline-flex items-center rounded-full bg-white border border-gray-200 px-2 py-1 text-gray-600">
                        {entry.step_name}
                      </span>
                    )}
                    {entry.job_id && (
                      <span className="inline-flex items-center rounded-full bg-white border border-gray-200 px-2 py-1 font-mono text-gray-500">
                        {entry.job_id}
                      </span>
                    )}
                  </div>
                  <div className="mt-3 whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3 text-sm leading-6 text-gray-800 text-left">
                    {entry.message}
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
