import { useConfigContext, type AdvancedSubtab } from '../ConfigContext';
import {
  LLMSection,
  WhisperSection,
  ProcessingSection,
  OutputSection,
  AppSection,
} from '../sections';

const SUBTABS: { id: AdvancedSubtab; label: string }[] = [
  { id: 'llm', label: 'LLM' },
  { id: 'whisper', label: 'Transcription' },
  { id: 'processing', label: 'Processing' },
  { id: 'output', label: 'Audio output' },
  { id: 'app', label: 'General' },
];

export default function AdvancedTab() {
  const { activeSubtab, setActiveSubtab } = useConfigContext();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Advanced settings">
        {SUBTABS.map((subtab) => {
          const selected = activeSubtab === subtab.id;
          return (
            <button
              key={subtab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setActiveSubtab(subtab.id)}
              className={`btn btn-sm ${
                selected ? 'bg-gray-100 text-gray-900' : 'btn-ghost text-gray-600'
              }`}
            >
              {subtab.label}
            </button>
          );
        })}
      </div>

      <div role="tabpanel">
        {activeSubtab === 'llm' && <LLMSection />}
        {activeSubtab === 'whisper' && <WhisperSection />}
        {activeSubtab === 'processing' && <ProcessingSection />}
        {activeSubtab === 'output' && <OutputSection />}
        {activeSubtab === 'app' && <AppSection />}
      </div>
    </div>
  );
}
