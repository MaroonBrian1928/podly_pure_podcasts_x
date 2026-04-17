/**
 * Format a duration given in seconds into a human-readable string.
 * E.g. 3661 → "1h 1m 1s"
 */
export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.round(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m ${secs}s`;
  }
  return `${minutes}m ${secs}s`;
}

/**
 * Format a processing time given in seconds (or null/undefined) into a
 * human-readable string.  Returns '—' when no value is available.
 */
export function formatProcessingTime(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return '—';
  const totalSecs = Math.round(seconds);
  const h = Math.floor(totalSecs / 3600);
  const m = Math.floor((totalSecs % 3600) / 60);
  const s = totalSecs % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
