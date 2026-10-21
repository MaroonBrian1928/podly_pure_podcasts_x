import type { ReactNode } from 'react';
import type { EnvOverrideEntry } from '../../../types';
import EnvVarHint from './EnvVarHint';

interface FieldProps {
  label: string;
  children: ReactNode;
  envMeta?: EnvOverrideEntry;
  hint?: ReactNode;
}

/** A labelled text, number or select control. Use ToggleField for checkboxes. */
export default function Field({ label, children, envMeta, hint }: FieldProps) {
  return (
    <label className="block min-w-0">
      <span className="block text-sm font-medium text-gray-800">{label}</span>
      {hint ? <span className="mt-0.5 block text-xs text-gray-600">{hint}</span> : null}
      <div className="mt-1.5">{children}</div>
      <EnvVarHint meta={envMeta} />
    </label>
  );
}
