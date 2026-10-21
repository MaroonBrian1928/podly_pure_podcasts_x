---
name: Podly
description: Ad-block for podcasts. A calm operator UI for feeds, processing and ad-free RSS.
colors:
  signal-blue: "#2563eb"
  signal-blue-deep: "#1d4ed8"
  cut-red: "#dc2626"
  cut-red-deep: "#b91c1c"
  paper-canvas: "#f9fafb"
  paper-surface: "#ffffff"
  ink: "#111827"
  ink-muted: "#4b5563"
  hairline: "#e5e7eb"
  hairline-strong: "#d1d5db"
  midnight-canvas: "#040a18"
  midnight-surface: "#0f172a"
  midnight-ink: "#f8fafc"
  midnight-ink-muted: "#d6dfec"
  pause-amber-tint: "#fef3c7"
  pause-amber-ink: "#92400e"
  subscribe-black: "#000000"
typography:
  headline:
    fontFamily: "ui-sans-serif, system-ui, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji'"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: "2rem"
  title:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: "1.75rem"
  body:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.25rem"
  label:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: "1rem"
  data:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "1rem"
    fontFeature: "tnum"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.signal-blue}"
    textColor: "{colors.paper-surface}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.signal-blue-deep}"
  button-secondary:
    backgroundColor: "{colors.paper-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  button-secondary-hover:
    backgroundColor: "{colors.paper-canvas}"
  button-ghost:
    textColor: "#374151"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  button-dark:
    backgroundColor: "{colors.subscribe-black}"
    textColor: "{colors.paper-surface}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  button-danger:
    backgroundColor: "{colors.cut-red}"
    textColor: "{colors.paper-surface}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  button-danger-hover:
    backgroundColor: "{colors.cut-red-deep}"
  button-sm:
    padding: "0 10px"
    height: "30px"
    typography: "{typography.label}"
  input:
    backgroundColor: "{colors.paper-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
    typography: "{typography.body}"
  feed-card:
    backgroundColor: "{colors.paper-surface}"
    rounded: "{rounded.lg}"
    padding: "16px"
  chip-status:
    rounded: "{rounded.full}"
    padding: "2px 8px"
    typography: "{typography.label}"
  chip-paused:
    backgroundColor: "{colors.pause-amber-tint}"
    textColor: "{colors.pause-amber-ink}"
    rounded: "{rounded.full}"
  nav-item:
    textColor: "#374151"
    rounded: "{rounded.md}"
    padding: "6px 12px"
    typography: "{typography.body}"
---

# Design System: Podly

## Overview

**Creative North Star: "The Quiet Control Room"**

Podly is somewhere you check in, not somewhere you stay. Someone adds a feed, copies a link, sees that last night's episodes processed, and leaves. The interface is a calm room of neutral surfaces with a single blue accent. Color shows up only when something needs a decision or has gone wrong. Brand character lives in precise details: tabular numerals, a short press response on every control, and motion that settles instead of bouncing.

Density is moderate and leans compact. Controls are small (36px default, 30px compact), and body copy is 14px. A split view puts feeds next to episodes on desktop, and on a phone the episode view slides over the list. There are two themes with equal standing, light paper and Midnight Navy. Both come from one set of role variables, so any class means the same role in either theme.

**Key Characteristics:**
- Neutral-first surfaces, with one blue accent for primary action, focus and selection.
- Status hues (amber, red, green, sky) appear only as tinted chips and banners, never as decoration.
- System sans for everything, with monospace and tabular numerals for timings, counts and logs.
- Flat surfaces with hairline borders, plus a soft shadow on cards and floating layers.
- Quick, damped motion that always respects `prefers-reduced-motion`.

## Colors

A cool-gray neutral system with one confident blue, and status hues used as tints.

### Primary
- **Signal Blue** (`signal-blue`; hover `signal-blue-deep`): primary buttons, focus rings, the selected feed card's border and inner ring, and the input focus border. It stays fixed in both themes because white labels sit on it.

### Secondary
- **Cut Red** (`cut-red`; hover `cut-red-deep`): destructive actions only (delete, remove). It also stays fixed in both themes.

### Tertiary
- **Pause Amber** (`pause-amber-tint` / `pause-amber-ink`): paused or warning states such as a paused membership or a stale job. Green, sky and rose follow the same tint-plus-ink pattern for success, info and error.

### Neutral
- **Paper Canvas** (`paper-canvas`): the app background behind every panel in light mode.
- **Paper Surface** (`paper-surface`): cards, header, modals, inputs and secondary buttons.
- **Ink** (`ink`): headings and primary text. **Ink Muted** (`ink-muted`): secondary copy, metadata and inactive nav.
- **Hairline** (`hairline`) and **Hairline Strong** (`hairline-strong`): card borders and input/secondary-button borders.
- **Midnight Canvas** (`midnight-canvas`) and **Midnight Surface** (`midnight-surface`): the dark theme's background and panels, a deep navy rather than neutral black. **Midnight Ink** and **Midnight Ink Muted** keep text tiers bright so secondary copy keeps its contrast.
- **Subscribe Black** (`subscribe-black`): the near-black Subscribe button on a feed. It stays black in both themes.

### Named Rules
**The Role, Not Shade, Rule.** Gray and status classes resolve to CSS variables (`--gray-*`, `--amber-*`, …), generated in `tailwind.config.js` for `:root` and `html.dark`. Write `bg-gray-50` or `text-amber-800` and the role flips with the theme. Never add `dark:` overrides per class. Shades 400 and 500 are mid-tones and stay fixed.

**The One Accent Rule.** Blue means "act here" or "you are here". It appears on the primary action, the focused control and the selected item, and nowhere else.

## Typography

**Body Font:** the system UI sans stack (Tailwind `font-sans`).
**Data Font:** the system monospace stack (Tailwind `font-mono`).

**Character:** Platform-native and unbranded. Type is a tool here; hierarchy comes from weight and size, not from the typeface.

### Hierarchy
- **Headline** (600, 1.5rem/2rem): page titles such as Jobs, Billing and the feed name. On phones it drops to 1.25rem where space is tight.
- **Title** (600, 1.125rem/1.75rem): section and empty-state headings, and stat values.
- **Body** (400–500, 0.875rem/1.25rem): the default for almost everything. Medium (500) is the standard weight for labels, nav and buttons.
- **Label** (500, 0.75rem/1rem): metadata, chips and compact buttons. Status chips go down to 11px.
- **Data** (mono, 0.75rem, tabular numerals): timings, durations, segment timestamps and processing logs.

### Named Rules
**The Tabular Rule.** Any number that updates live or sits in a column uses `tabular-nums`, so digits never shift.

## Layout

The app shell fills the viewport (`100dvh`, document scroll disabled): a 48px header, then a content region that scrolls inside each pane. Horizontal page padding steps from 8px to 16px (`sm`) to 24px (`lg`). Main nav appears from `md` (768px); below that a menu button opens a 224px popover. From `lg` (1024px) the home view is a two-pane split, with the feed list beside feed detail. Below `lg`, feed detail is a full-width panel that slides in from the right over the list. The spacing rhythm is 4px-based: 8px gaps between cards, 12px inside compact groups, 16px card padding and 24px section spacing. Reading-width content (forms, modals) caps between `max-w-md` and `max-w-4xl`.

## Elevation & Depth

Mostly flat, with hairline borders separating surfaces. Shadows are small and do a structural job: they mark something that can be clicked or something floating above the page. Modals add a blurred navy backdrop instead of a heavier shadow.

### Shadow Vocabulary
- **Resting card** (`shadow-sm`): feed cards and stat tiles.
- **Hovered card** (`shadow-md`): a feed card under the pointer.
- **Floating layer** (`shadow-lg` to `shadow-2xl`): menus, popovers, the audio player and modal panels.

### Named Rules
**The Border-First Rule.** Separate surfaces with a hairline before reaching for a shadow. A shadow means "this lifts or floats".

## Shapes

Gently curved, never pill-shaped except for chips and avatars. Controls and inputs use 6px corners, cards and popovers 8px, and modal panels up to 12–16px. Artwork thumbnails use 6px corners. Status chips, toggles and skeleton pills are fully rounded.

## Components

### Buttons
Quiet, tactile, precise.
- **Shape:** gently curved (6px), 36px tall by default, 30px for `.btn-sm`, square for `.btn-icon`.
- **Primary:** Signal Blue fill with white 14px medium label.
- **Secondary:** surface fill, Hairline Strong border, ink label. Hover fills with canvas.
- **Ghost:** no fill, gray-700 label. Hover gets a gray-100 wash.
- **Dark:** near-black fill, used only for a feed's Subscribe action.
- **Danger:** Cut Red fill for destructive confirmations.
- **Press:** every button scales to 0.96 on `:active` over 80ms, then eases back over 360ms (`cubic-bezier(0.33, 1, 0.68, 1)`). This is turned off under reduced motion.
- **Focus:** 2px blue-500 ring with a 2px offset in the canvas color.
- **Disabled:** gray-200 fill and gray-600 label, with a not-allowed cursor.
- **Touch:** on coarse pointers every `.btn` (and any control marked `.touch-target`) gets an invisible hit area of at least 44 × 44px, centered on the drawn control. Drawn sizes stay 36/30px. Mark small custom controls (play button, chip toggles, text buttons) with `.touch-target` instead of enlarging them.

### Chips
- **Style:** fully rounded, 11–12px medium label, tint background with matching dark ink (for example amber-100 / amber-800). Bordered variants add the 200 shade of the hue.
- **Use:** membership state, processing state and detection tags. Never decorative.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** surface.
- **Shadow Strategy:** resting `shadow-sm`, `shadow-md` on hover (see Elevation & Depth).
- **Border:** hairline. When selected, a Signal Blue border plus a 1px inset blue ring.
- **Internal Padding:** 16px. Feed cards lead with 48px artwork.

### Inputs / Fields
- **Style:** surface fill, Hairline Strong border, 6px corners, 10px × 12px padding, 14px text.
- **Focus:** the border turns blue-500 with a soft 3px blue-500/20 halo. Border and shadow transition over 150ms.
- **Disabled:** gray-100 fill and gray-700 text at full opacity, so the value stays readable.

### Settings Forms
Built from `frontend/src/components/config/shared/`. Below `lg` (1024px), tabs run across the top and each Section is a card. From `lg`, the tabs and Advanced subtabs move into a sticky 12rem sidebar, and each Section becomes a hairline-separated row: heading in a 15rem column, fields beside it, capped at `max-w-5xl`. Dashboards and tables (Costs) pass `stacked` to keep full-width cards.
- **Field:** label above the control (14px medium), optional one-sentence hint between them (12px gray-600).
- **ToggleField:** label and hint on the left, checkbox on the right; the whole row is the tap target. Every on/off setting uses it.
- **Section:** a card with a 16px semibold title and an optional description. `collapsible` sections start closed and hold limits and tuning most people never touch. Never nest a card inside a Section.
- **Environment-locked fields:** disabled, with an amber "Set by `VAR` in your environment." line. The variable name appears only when it is actually set.
- **Copy:** sentence-case labels, units spelled out in parentheses, toggle labels that state the behaviour (no leading "Enable"), and "enabled episodes" rather than "whitelist".

### Navigation
- **Style:** 14px medium items, 6px × 12px padding, 6px corners.
- **States:** inactive is gray-700 with a gray-50 wash on hover. Active is a gray-100 fill with ink text. There is no accent color in navigation.
- **Mobile:** a menu button opens a right-aligned popover card with the same items, entering with `pop-in` (220ms scale from 0.97).

### Modal Shell
The panel rises 10px and fades in (320–380ms, `cubic-bezier(0.22, 1, 0.36, 1)`) over a navy backdrop that blurs to 4px. Under reduced motion it appears without moving.

### Stats Metric Tiles
The episode Stats pop-up's "Key metrics" row is a deliberate, owner-approved signature: one soft gradient tile per metric (`bg-gradient-to-br from-{hue}-50 to-{hue}-100`, bold `{hue}-600` number, `{hue}-800` label), with its own dark treatment (`dark:from-{hue}-950 dark:to-slate-900` and a tinted border). Hues: blue for transcript lines, green for content lines, red for ad lines removed, indigo for estimated cost, purple for chapters. It is the one place multiple accent hues and gradients are allowed. Keep it when polishing or auditing, and do not spread it to other surfaces.

### Live Timer Digits
Each digit that changes re-enters with `digit-tick`, a 350ms blur-and-rise with slight overshoot. This is the system's only deliberate flourish, and it's kept for live processing counters.

## Do's and Don'ts

### Do:
- **Do** use the `.btn`, `.btn-*` and `.input` component classes in `index.css` instead of rebuilding controls with ad-hoc utilities.
- **Do** write gray and status colors as role classes (`bg-gray-50`, `text-amber-800`) and let the variables handle dark mode.
- **Do** use `tabular-nums` (and `font-mono` for timings and logs) on any changing or columnar number.
- **Do** give every animation a `prefers-reduced-motion: reduce` fallback, as `index.css` does.
- **Do** keep layouts working at phone width first. The slide-over feed detail is the reference pattern.

### Don't:
- **Don't** add `dark:` overrides for themed hues or grays. Fix the role variable instead.
- **Don't** use Signal Blue for decoration, headings or navigation states.
- **Don't** add a second accent hue, or use status colors outside chips, banners and inline state. The Stats metric tiles are the one sanctioned exception.
- **Don't** use heavy shadows on resting surfaces. Save `shadow-lg` and above for layers that float.
- **Don't** use bouncy or overshooting easing outside the live-digit tick.
