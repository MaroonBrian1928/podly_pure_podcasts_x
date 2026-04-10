import type { Feed, CombinedConfig } from '../types';

/**
 * Client-side mirror of Python's _apply_feed_tag().
 *
 * Returns the title as it will appear in the podcast app's RSS feed,
 * or null when no tag is applied (label is empty) so callers can
 * choose not to render anything in that case.
 */
export function computeTaggedTitle(
  feed: Feed,
  appCfg: CombinedConfig['app'] | undefined,
): string | null {
  const globalLabel = (appCfg?.feed_tag_label ?? '').trim();
  const globalPosition = appCfg?.feed_tag_position ?? 'suffix';
  const override = appCfg?.feed_tag_override ?? false;

  let label: string;
  let position: string;

  if (override) {
    label = globalLabel;
    position = globalPosition;
  } else {
    label = (feed.feed_tag_label != null ? feed.feed_tag_label : globalLabel).trim();
    position = feed.feed_tag_position ?? globalPosition;
  }

  if (!label) return null;
  const tag = `[${label}]`;
  return position === 'suffix' ? `${feed.title} ${tag}` : `${tag} ${feed.title}`;
}
