import type { ReactNode } from 'react';
import { ChevronDownIcon } from '../../icons';

interface SectionProps {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Starts collapsed; for settings most people never change. */
  collapsible?: boolean;
}

const frame = 'rounded-lg border border-gray-200 bg-surface p-4 shadow-sm sm:p-5';

export default function Section({
  title,
  description,
  children,
  className = '',
  collapsible = false,
}: SectionProps) {
  const heading = (
    <div className="min-w-0">
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {description ? <p className="mt-0.5 text-sm text-gray-600">{description}</p> : null}
    </div>
  );
  const body = <div className="space-y-5">{children}</div>;

  if (collapsible) {
    return (
      <details className={`group ${frame} ${className}`}>
        <summary className="flex cursor-pointer list-none items-start justify-between gap-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
          {heading}
          <ChevronDownIcon className="mt-0.5 h-5 w-5 shrink-0 text-gray-500 transition-transform duration-200 group-open:rotate-180" />
        </summary>
        <div className="mt-5">{body}</div>
      </details>
    );
  }

  return (
    <section className={`${frame} ${className}`}>
      <div className="mb-5">{heading}</div>
      {body}
    </section>
  );
}
