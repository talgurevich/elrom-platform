# Klaser Design System (v1)

**Status:** live in Takanon (Landing / Documents / Search). Applies to every Klaser product surface — including Meetings.
**Source of truth:** the DS Figma file `5CHeyijqFSxWta5KHsTtDy` (`Klaser-DS`) + this document. When the two disagree, this document wins for code.
**Last updated:** 2026-08-08.

This is a spec, not a component library. Every product ships its own copy of the shared component file (see [Component library](#component-library)). No cross-repo npm dependency yet; that's a post-launch conversation.

---

## 1. Reference implementations

Live examples in the Takanon repo (`talgurevich/elrom-platform`) — pull these when you're unsure how a pattern is applied:

| Surface | File |
|---|---|
| Marketing homepage (header, hero, benefits, products, about, FAQ, contact, CTA, footer) | `frontend/src/pages/Landing.tsx` |
| Documents page (header, toolbar, cards, filter sidebar, upload dropzone, queue, drawer) | `frontend/src/pages/Upload.tsx` |
| Chat + answers (references, retrieved passages, feedback buttons, ThinkingProgress) | `frontend/src/pages/Search.tsx` |
| Tailwind tokens | `frontend/tailwind.config.js` |
| Font loading | `frontend/index.html` |

---

## 2. Foundations

### 2.1 Colors

All from the DS Figma. `accent` and `turquoise` resolve to the same value; both tokens exist for legacy compatibility.

| Token | Hex | Notes |
|---|---|---|
| `turquoise.DEFAULT` | `#19819A` | Teal Primary — main brand color |
| `turquoise.dark` | `#166B80` | Hover / pressed pair for turquoise |
| `accent.DEFAULT` | `#19819A` | Alias for turquoise (legacy — new code prefers `turquoise`) |
| `accent.dark` | `#166B80` | Alias for turquoise.dark |
| `warning.DEFAULT` | `#FF7C2A` | Orange 500 — "מוצר דגל" badge, uncertain confidence |
| `warning.dark` | `#C2410C` | AA-safe orange for small text on white |
| `success.DEFAULT` | `#20B86B` | Green — DS exact value; feedback + status |
| `success.soft` | `#DCFCE7` | Green fill background |
| `danger.DEFAULT` | `#FF4848` | Red — DS exact value; feedback + destructive |
| `danger.soft` | `#FEE2E2` | Red fill background |
| `ink` | `#171717` | Body text |
| `ink-soft` | `#525252` | Secondary text |
| `surface` | `#FAFAF9` | Warm off-white |
| `line` | `#E7E5E4` | Hairline border |
| `line-strong` | `#D6D3D1` | Emphasised border |

**Extra Klaser DS colors not yet in the Tailwind config** (from the DS palette panel — add if you need them):

| Name | Hex | Notes |
|---|---|---|
| Yellow | `#FFC000` | Not currently used in code |
| Bright teal | `#00ABC1` | Not currently used in code |
| Dark blue | `#0E3740` | Not currently used in code |
| Gradient teal end | `#009299` | Second stop in the brand gradient |

**Brand gradient** — used on the "מוכנים להתחיל?" CTA band on the landing:

```css
background: linear-gradient(267deg, #19819A 0.01%, #009299 99.77%);
```

Tailwind arbitrary-value form:

```
bg-[linear-gradient(267deg,#19819A_0.01%,#009299_99.77%)]
```

---

### 2.2 Typography

The full DS text ramp. **Rubik for display + small + caption; Heebo for body.** Both have solid Hebrew coverage.

| Token | Font | Weight | Size | LH | Tracking | Tailwind classes |
|---|---|---|---|---|---|---|
| **H1** | Rubik | Bold (700) | 72 | 72 | 0% | `font-rubik font-bold text-5xl md:text-[72px] md:leading-[72px]` |
| **H2** | Rubik | Bold (700) | 48 | 60 | 0% | `font-rubik font-bold text-4xl md:text-5xl md:leading-[60px]` |
| **H3** | Rubik | Bold (700) | 32 | Auto | 0% | `font-rubik font-bold text-[32px] leading-tight` |
| **H4** | Rubik | Bold (700) | 24 | Auto | 0% | `font-rubik font-bold text-2xl` |
| **H5** | Rubik | Bold (700) | 16 | Auto | 25% | `font-rubik font-bold text-base uppercase tracking-[0.25em]` |
| **Body** | Heebo | Regular (400) | 18 | Auto | 0% | `text-lg` (Heebo is the default sans stack) |
| **Body 2** | Heebo | Regular (400) | 20 | Auto | 0% | `text-xl` |
| **Body 2 bold** | Heebo | Bold (700) | 20 | Auto | 0% | `text-xl font-bold` |
| **Small 14** | Rubik | Regular (400) | 14 | Auto | 0% | `font-rubik text-sm` |
| **Caption** | Rubik | Regular (400) | 12 | Auto | 0% | `font-rubik text-xs` |

**Two conventions to remember:**

- **H5 = eyebrow style.** Always `uppercase` + tracked out. Use it above every H2. Example: "למה קלסר" over "מהיר יותר. מדויק יותר. עם מקור.".
- **Button labels** use **Rubik Bold 16** (same specs as H5 minus the tracking) OR **Small 14 Bold** for compact buttons. There is no dedicated `Button` token in the DS; if you need one, ask.

---

### 2.3 Spacing scale (4pt)

**Rule:** every Tailwind spacing utility (`p-*`, `px-*`, `py-*`, `m-*`, `gap-*`, `space-y-*`, `mt-*`, etc.) is a multiple of 4. Tailwind's default scale already gives you `p-4` (16px), `p-8` (32px), `p-12` (48px), `p-16` (64px), `p-20` (80px), `p-24` (96px), `p-32` (128px), etc.

**Do:**
- `gap-4` / `gap-6` / `gap-8` / `gap-12`
- `mt-4` / `mt-8` / `mt-12` / `mt-16`
- Section vertical padding: `py-20` or `py-24`

**Don't:**
- `p-5`, `p-7`, `p-9`, `p-11`, `p-13` (odd Tailwind units — Tailwind gives you these but they're off-scale for the DS)
- Arbitrary bracket values like `mt-[13px]` unless you're expressing an exact DS-spec measurement (like `md:gap-[104px]` on the final CTA)

---

### 2.4 Radius / shadow

**Radius:**
- `rounded-md` (4px) — buttons, inputs, chips, tags, badges — this is the DS button-corner-radius
- `rounded-lg` (6px) — cards
- `rounded-full` — pills, avatar circles, status number badges

The base Tailwind default is overridden in `tailwind.config.js` to 2px for tighter aesthetics on non-`md`/`lg` uses.

**Shadow:**
Cards use a two-layer soft shadow that reads as "lift, not blur":

```
shadow-[0px_2px_0_rgba(0,0,0,0.05),0px_4px_25px_0px_rgba(0,0,0,0.08)]
```

Or the lighter card variant:

```
shadow-[0px_1px_0_rgba(0,0,0,0.03),0px_4px_16px_-4px_rgba(0,0,0,0.06)]
```

Named shadows in the Tailwind config (`shadow-soft`, `shadow-lift`, `shadow-glow`) exist too, but the inline shadows are what current cards use.

---

### 2.5 RTL rules — the gotchas

The whole app runs `dir="rtl"` on `<html>`. Two things bite constantly:

1. **`justify-end` sends items to the LEFT in RTL** (end of the flex flow). If you want items on the right, use `justify-start` (which is start-of-flow = right in RTL) or omit `justify-*` entirely (default is `flex-start`).
2. **DOM order determines RTL visual order.** In `flex-row` under RTL:
   - First DOM child → visually **rightmost**
   - Last DOM child → visually **leftmost**
   So if you want the "פתח מקור" button on the visual **left** of a card row, it goes **last** in the DOM. Content div (with `flex-1`) goes first.
3. Text alignment: default RTL alignment is right. Set `text-right` explicitly on text nodes when the containing flex/grid changes context.
4. Border helpers still refer to physical sides: `border-r` = right edge regardless of dir. Convention we use: place a separator using `border-r pr-3` on the item whose right side is adjacent to the item it separates from.
5. Icon positioning inside buttons: for `<span>text</span><Icon />` (arrow on left of text in RTL), DOM order is text **first**, icon **second**.

---

### 2.6 Font loading

In `index.html` `<head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  href="https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700&family=Heebo:wght@400;500;700&family=Rubik:wght@400;700&display=swap"
  rel="stylesheet"
/>
```

Weights required: Rubik 400/700, Heebo 400/500/700. Assistant 400/600/700 is legacy but stays for now.

Root element:

```html
<html lang="he" dir="rtl">
```

---

### 2.7 Tailwind config additions

Merge into your `tailwind.config.js` `theme.extend`:

```js
fontFamily: {
  sans: ['"Heebo"', '"Assistant"', "system-ui", "sans-serif"],
  display: ['"Heebo"', '"Assistant"', "system-ui", "sans-serif"],
  // Klaser DS — Rubik for display/H*/Caption/Small; Heebo for Body/Body 2
  rubik: ['"Rubik"', '"Heebo"', "system-ui", "sans-serif"],
},
colors: {
  accent: {
    DEFAULT: "#19819A",
    dark: "#166b80",
    light: "#d96a52", // legacy — do not use in new code
  },
  ink: "#171717",
  "ink-soft": "#525252",
  surface: "#fafaf9",
  line: "#e7e5e4",
  "line-strong": "#d6d3d1",
  turquoise: {
    DEFAULT: "#19819a",
    dark: "#166b80",
  },
  warning: {
    DEFAULT: "#ff7c2a",
    dark: "#c2410c",
  },
  success: {
    DEFAULT: "#20B86B",
    soft: "#dcfce7",
  },
  danger: {
    DEFAULT: "#FF4848",
    soft: "#fee2e2",
  },
},
backgroundImage: {
  "brand-gradient": "linear-gradient(180deg, #19819A 0%, #166b80 100%)",
},
boxShadow: {
  soft: "0 1px 0 rgba(23, 23, 23, 0.04)",
  lift: "0 2px 0 rgba(23, 23, 23, 0.06)",
  glow: "0 0 0 3px rgba(25, 129, 154, 0.18)",
},
borderRadius: {
  DEFAULT: "0.125rem",
  sm: "0.125rem",
  md: "0.25rem",
  lg: "0.375rem",
  xl: "0.5rem",
  "2xl": "0.5rem",
},
keyframes: {
  "fade-up": {
    "0%": { opacity: "0", transform: "translateY(6px)" },
    "100%": { opacity: "1", transform: "translateY(0)" },
  },
},
animation: {
  "fade-up": "fade-up 0.35s ease-out",
},
```

---

## 3. Component library

Drop this file in verbatim as `src/components/klaser-ds.tsx` (or wherever your project keeps shared UI). Then `import { Chip, DsTag, StatusPill, ... } from "./klaser-ds"`.

```tsx
// klaser-ds.tsx — Klaser Design System shared components (v1)
// Copy-paste target: every Klaser product surface.
import type { ReactNode, MouseEvent } from "react";

/* ─── Chips / Tags / Pills ────────────────────────────────────────── */

/**
 * Grey / active / teal-outlined chip. Interactive button variant.
 * Use for: filter chips, classify chips, small action buttons.
 */
export function Chip({
  children,
  variant = "grey",
  onClick,
  disabled,
  title,
}: {
  children: ReactNode;
  variant?: "grey" | "active" | "teal-outline";
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
}) {
  const styles =
    variant === "active"
      ? "bg-turquoise/10 text-turquoise hover:bg-turquoise/15"
      : variant === "teal-outline"
      ? "bg-white border border-turquoise text-turquoise hover:bg-turquoise/5"
      : "bg-line text-ink-soft hover:bg-line-strong";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center px-3 py-1.5 rounded-md font-rubik font-medium text-xs transition disabled:opacity-50 disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  );
}

/**
 * Read-only rounded tag pill. Use for doc types, categories, section paths,
 * date labels — anything metadata-ish that shouldn't look clickable.
 */
export function DsTag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-line text-ink-soft font-rubik text-xs">
      {children}
    </span>
  );
}

/**
 * Colored status pill — green (success), orange (warning), red (danger),
 * grey (neutral), teal (info). Optional icon rendered as first child.
 */
export function StatusPill({
  variant,
  children,
}: {
  variant: "success" | "warning" | "danger" | "neutral" | "teal";
  children: ReactNode;
}) {
  const styles: Record<typeof variant, string> = {
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning-dark",
    danger: "bg-danger/10 text-danger",
    neutral: "bg-line text-ink-soft",
    teal: "bg-turquoise/10 text-turquoise",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md font-rubik font-medium text-xs ${styles[variant]}`}
    >
      {children}
    </span>
  );
}

/* ─── Form controls ───────────────────────────────────────────────── */

export function DsInput({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full px-3 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
    />
  );
}

export function DsSelect({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none px-3 py-2.5 pl-9 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right outline-none cursor-pointer focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
      >
        {children}
      </select>
      <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none text-ink-soft">
        <ChevronDownIcon />
      </span>
    </div>
  );
}

/** Custom teal-filled checkbox. Do not use native `<input type="checkbox">`. */
export function DsCheckbox({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: () => void;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={`w-5 h-5 rounded-md flex items-center justify-center transition shrink-0 ${
        checked
          ? "bg-turquoise text-white"
          : "bg-white border border-line-strong hover:border-turquoise"
      }`}
    >
      {checked && <CheckMarkIcon />}
    </button>
  );
}

/** Custom teal radio button. */
export function DsRadio({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: () => void;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={`w-5 h-5 rounded-full flex items-center justify-center transition shrink-0 ${
        checked
          ? "border-2 border-turquoise"
          : "border border-line-strong hover:border-turquoise"
      }`}
    >
      {checked && <span className="w-2.5 h-2.5 rounded-full bg-turquoise" />}
    </button>
  );
}

/* ─── Icons — inline SVG, currentColor for tinting ───────────────── */

export function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M10 11v6M14 11v6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.8" />
      <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function ChevronDownIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ExternalLinkIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14 4h6v6M20 4L10 14M20 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CheckMarkIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CloseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/** Circle-arrow-left — canonical primary-CTA icon, appears at the LEFT of button labels. */
export function ArrowCircleLeft() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.6" />
      <path d="M13 8l-4 4 4 4M9 12h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function UploadCloudIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true" className="text-turquoise">
      <path d="M16 20V8m0 0l-5 5m5-5l5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 20a2 2 0 002 2h12a2 2 0 002-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* ─── Composite: open-source link button ─────────────────────────── */

/**
 * Small teal-outlined button — DS pattern for "פתח מקור" links to a
 * document. Wraps an `<a target="_blank">` so it renders as a link but
 * looks like a button. `href` is opaque to the DS (product-specific).
 */
export function OpenSourceButton({
  href,
  onClick,
  label = "פתח מקור",
}: {
  href: string;
  onClick?: (e: MouseEvent) => void;
  label?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      onClick={onClick}
      title="פתח את קובץ המקור"
      className="shrink-0 inline-flex items-center gap-1.5 border border-turquoise text-turquoise bg-white px-3 py-1.5 rounded-md font-rubik font-semibold text-xs hover:bg-turquoise hover:text-white transition"
    >
      <ExternalLinkIcon />
      <span>{label}</span>
    </a>
  );
}
```

---

## 4. Patterns

### 4.1 Buttons

Three canonical button variants. **Icon on the LEFT of the label** — in RTL that means the icon element comes **last** in the DOM.

**Primary (filled turquoise)**

```tsx
<button
  onClick={onLogin}
  className="inline-flex items-center gap-2 bg-turquoise text-white h-12 px-8 rounded-md font-rubik font-bold text-base hover:bg-turquoise-dark transition"
>
  <span>כניסה למערכת</span>
  <ArrowCircleLeft />
</button>
```

**Secondary (outlined turquoise)**

```tsx
<button
  className="inline-flex items-center gap-2 bg-white border-2 border-turquoise text-turquoise h-12 px-8 rounded-md font-rubik font-bold text-base hover:bg-turquoise hover:text-white transition"
>
  <span>למה זה טוב לי?</span>
</button>
```

**Destructive (outlined danger)**

```tsx
<button
  className="inline-flex items-center gap-2 border border-danger text-danger bg-white px-3 py-1.5 rounded-md font-rubik font-medium text-xs hover:bg-danger hover:text-white transition"
>
  <TrashIcon />
  <span>מחק</span>
</button>
```

Header/compact variants use `h-10 px-4` and `text-sm`. Micro-buttons in tables use `Chip` from the library.

### 4.2 Cards

Standard card:

```tsx
<div className="p-5 bg-white rounded-lg border border-line hover:border-turquoise/40 shadow-[0px_1px_0_rgba(0,0,0,0.03),0px_4px_16px_-4px_rgba(0,0,0,0.06)] transition">
  {/* content */}
</div>
```

Flagship card (heavier shadow, teal outline):

```tsx
<div className="relative bg-white rounded-lg p-8 md:p-12 border border-turquoise/15">
  {/* content */}
</div>
```

**Card row anatomy** (see `DocumentRow` in `Upload.tsx`):
1. Top row: metadata tags on the right + destructive action on the left
2. Divider (`<div className="h-px bg-line my-4" />`)
3. Middle row: `DsTag` chips on the right + `OpenSourceButton` on the left
4. Divider
5. Bottom row: metadata footer on the right + `StatusPill` on the left

### 4.3 Section headers

Every top-level section uses the eyebrow + H2 pair:

```tsx
<div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4 text-right">
  למה קלסר
</div>
<h2 className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-[#191919] text-right">
  מהיר יותר. מדויק יותר. עם מקור.
</h2>
```

For in-page dividers (references section, queue, etc.) use the compact teal header:

```tsx
<div className="font-rubik font-bold text-base tracking-[0.15em] text-turquoise mb-3 flex items-center gap-3">
  <span>סימוכין</span>
  <span className="flex-1 h-px bg-line" />
</div>
```

### 4.4 Form field

```tsx
<Field label="סוג מסמך">
  <DsSelect value={value} onChange={setValue}>
    <option value="">—</option>
    <option value="a">A</option>
  </DsSelect>
</Field>

// Field helper — teal small label above the control.
function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="font-rubik font-medium text-xs text-turquoise mb-2 flex items-baseline gap-2 justify-start">
        <span>{label}</span>
        {hint && <span className="text-ink-soft font-normal">{hint}</span>}
      </div>
      {children}
    </label>
  );
}
```

### 4.5 Tab switcher

```tsx
<div className="flex gap-0 border-b border-line px-6 pt-4">
  <button
    onClick={() => setTab("details")}
    className={`flex-1 py-3 rounded-t-md font-rubik font-medium text-sm transition ${
      tab === "details"
        ? "bg-turquoise text-white"
        : "bg-line/50 text-ink-soft hover:text-ink hover:bg-line"
    }`}
  >
    פרטים
  </button>
  {/* ...more tabs */}
</div>
```

### 4.6 Modals / drawers

- Close icon on the **LEFT** of the header (not the right).
- Title on the **RIGHT**, breadcrumb / eyebrow in teal above it.
- Action row: save + cancel on the **LEFT** (use `flex-row-reverse` on the actions container so the save button ends up on the far left).

---

## 5. What NOT to do

Failures we actually shipped and had to undo — don't repeat them.

- ❌ **Don't use `justify-end` in RTL** when you want items on the right. `justify-end` sends items to the LEFT in RTL. Use `justify-start` or omit `justify-*`.
- ❌ **Don't use clay-red (`#B8412B`)** anywhere. That's the retired pre-rebrand accent color. Everything is teal now (`#19819A`).
- ❌ **Don't use `warning-dark` for button fills or backgrounds.** It's the AA-safe text color for orange text on white. Fills use `warning` (`#FF7C2A`).
- ❌ **Don't use native `<input type="checkbox">` or `<input type="radio">`.** They style inconsistently across browsers and don't match the DS. Use `DsCheckbox` / `DsRadio`.
- ❌ **Don't put button icons on the RIGHT of the label in RTL.** DOM-first = visually rightmost; put text first, icon second in the DOM so the icon renders on the visual left.
- ❌ **Don't use `text-base` for eyebrow/progress-tracker labels.** 16px is too shouty. Use `text-[11px]` with `tracking-[0.15em]` for these.
- ❌ **Don't hardcode arbitrary spacing (`p-5`, `p-7`, `mt-[13px]`, etc.)**. Stick to the 4pt scale.
- ❌ **Don't hand-roll icon SVGs.** Import from `klaser-ds.tsx`. If you need a new icon, add it there so both products share it.
- ❌ **Don't put binder-hole decoration behind sections that are colored/dark.** The right-edge dot column belongs on white sections only. See `BinderHoles` in `Landing.tsx` for the pattern.

---

## 6. Migration checklist — porting the DS to a new product

Execute in this order:

1. **Font loading** — merge the `<link>` from §2.6 into `index.html`. Root html: `lang="he" dir="rtl"`.
2. **Tailwind config** — merge the tokens from §2.7 into `tailwind.config.js`. Keep existing product colors alongside if the product isn't fully rebranded yet.
3. **Component library** — drop `src/components/klaser-ds.tsx` (source in §3) into the repo.
4. **Header** — swap to turquoise bg + white text; login button on the left, brand on the right. See `Landing.tsx` for the pattern.
5. **Global text conventions** — audit every page and swap:
   - Section titles → H2 (`font-rubik font-bold text-4xl md:text-5xl md:leading-[60px]`)
   - Section eyebrows → H5 (`font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise`)
   - Body → Heebo default (`text-lg` = 18px, `text-xl` = 20px for Body 2)
   - Small labels / form-field labels → `font-rubik text-xs text-turquoise` (via `Field` helper)
6. **Buttons** — audit every button, swap to one of the three canonical variants (§4.1). Icon on the LEFT (DOM-last).
7. **Chips / tags / pills** — replace every ad-hoc badge with `Chip`, `DsTag`, or `StatusPill`.
8. **Forms** — replace every `<input>` and `<select>` with `DsInput` / `DsSelect`. Every `<input type="checkbox">` → `DsCheckbox`. Every `<input type="radio">` → `DsRadio`.
9. **Cards** — apply the standard card shell (§4.2). Border + soft shadow, no heavy shadows.
10. **Feedback semantics** — success = `#20B86B`, danger = `#FF4848`, warning = `#FF7C2A`. Use `StatusPill` for status badges.
11. **RTL audit** — grep for `justify-end` and replace with `justify-start` (or omit). Grep for `text-left` in text nodes and replace with `text-right` or nothing.
12. **Spacing audit** — grep for `p-5|p-7|p-9|p-11|p-13|m-5|m-7|gap-5|gap-7` and replace with 4pt-scale values.
13. **Verify with `tsc --noEmit`** after each area. Screenshot before/after to catch regressions.

---

## 7. Kickoff prompt for the Meetings agent

Copy-paste this into the Meetings repo's Claude Code session:

> We're porting the Klaser Design System (v1) to Meetings.
>
> **Read the spec first:** fetch `https://raw.githubusercontent.com/talgurevich/elrom-platform/main/docs/klaser-ds.md`. It has the full token list, type ramp, RTL rules, component library source, and migration checklist.
>
> **What to do:**
> 1. Follow the migration checklist in §6 of the spec, in order.
> 2. Start with the highest-traffic pages (dashboard / meeting detail / protocol editor) before edge screens.
> 3. Look at the reference implementations in §1 (Landing.tsx, Upload.tsx, Search.tsx in `talgurevich/elrom-platform`) whenever you're unsure how a pattern is applied. Fetch those files raw from GitHub.
> 4. Read §5 (What NOT to do) before you make styling calls — those mistakes were expensive.
>
> **Constraints:**
> - Hebrew RTL only. `lang="he" dir="rtl"` on `<html>`.
> - 4pt spacing scale — no `p-5`/`p-7`, no arbitrary bracket values unless matching a DS-spec measurement.
> - Icons come from `klaser-ds.tsx` — don't hand-roll new SVGs unless you're adding to that file.
> - Every color must map to a DS token. If you need a color that isn't in the token list, stop and ask.
> - `justify-end` sends items LEFT in RTL. Use `justify-start` or nothing.
> - Ship one section at a time. Typecheck (`tsc --noEmit`) after each. Screenshot before/after.
>
> **Report format:** after each section, drop a one-line summary + before/after screenshot pair.

---

## 8. Change log

- **2026-08-08** — v1 published. Consolidates the DS work landed in Takanon during the go-live sprint (Landing + Documents + Search + drawer + filter sidebar). Includes RTL gotchas and the full shared component source. Baseline for the Meetings port.
