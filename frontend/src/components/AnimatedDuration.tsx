import { formatDuration } from '../utils/datetime';

interface AnimatedDurationProps {
  ms: number;
  className?: string;
}

// Render a duration (e.g. "2m 14s") one character at a time so each cell can
// animate independently when it changes. The trick: keying each span by
// `index-character` makes React remount the span whenever the character at
// that position changes, retriggering the CSS animation. Unchanged positions
// keep their key and stay static, so only the digits that actually moved get
// the entrance animation — the colon/space separators never re-animate.
//
// `tabular-nums` + a fixed `inline-block` per cell keep the row from
// horizontally jittering as digits shift width.
export default function AnimatedDuration({ ms, className = '' }: AnimatedDurationProps) {
  if (!Number.isFinite(ms) || ms < 0) {
    return <span className={className}>—</span>;
  }
  const text = formatDuration(ms);
  return (
    <span
      className={`inline-flex tabular-nums ${className}`}
      style={{ fontVariantNumeric: 'tabular-nums' }}
      aria-label={text}
    >
      {Array.from(text).map((ch, idx) => {
        const isAnimatable = /[0-9]/.test(ch);
        return (
          <span
            key={`${idx}-${ch}`}
            className={`inline-block ${
              isAnimatable ? 'animate-digit-tick' : ''
            }`}
            // Whitespace inside an inline-flex collapses; preserve it.
            style={ch === ' ' ? { width: '0.35em' } : undefined}
            aria-hidden="true"
          >
            {ch === ' ' ? ' ' : ch}
          </span>
        );
      })}
    </span>
  );
}
