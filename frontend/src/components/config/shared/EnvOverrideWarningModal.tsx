import type { EnvOverrideMap } from '../../../types';
import ModalShell from '../../ModalShell';
import { ENV_FIELD_LABELS } from './constants';

interface EnvOverrideWarningModalProps {
  paths: string[];
  overrides: EnvOverrideMap;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function EnvOverrideWarningModal({
  paths,
  overrides,
  onConfirm,
  onCancel,
}: EnvOverrideWarningModalProps) {
  if (!paths.length) {
    return null;
  }

  return (
    <ModalShell
      isOpen
      onClose={onCancel}
      panelClassName="w-full max-w-lg"
    >
      <div className="space-y-4 rounded-lg border border-gray-200 bg-surface p-5">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Environment-managed settings</h2>
          <p className="text-sm text-gray-600">
            These fields are controlled by environment variables. Update the referenced variables in your
            <code className="mx-1 font-mono text-xs">.env</code>
            (or deployment secrets) to make the change persistent. Your manual change will be saved, but will be overwritten if you modify your environment variables in the future.
          </p>
        </div>
        <ul className="space-y-3 text-sm">
          {paths.map((path) => {
            const meta = overrides[path];
            const label = ENV_FIELD_LABELS[path] ?? path;
            return (
              <li key={path} className="rounded border border-gray-200 bg-gray-50 p-3">
                <div className="font-medium text-gray-900">{label}</div>
                {meta?.env_var ? (
                  <p className="mt-1 text-xs text-gray-700">
                    Managed by <code className="font-mono">{meta.env_var}</code>
                    {meta?.value_preview && (
                      <span className="ml-1 text-gray-600">({meta.value_preview})</span>
                    )}
                    {!meta?.value_preview && meta?.value && (
                      <span className="ml-1 text-gray-600">({meta.value})</span>
                    )}
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-gray-700">Managed by deployment environment</p>
                )}
              </li>
            );
          })}
        </ul>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn btn-secondary">
            Go back
          </button>
          <button type="button" onClick={onConfirm} className="btn btn-primary">
            Save anyway
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
