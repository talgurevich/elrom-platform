// Klaser Design System — shared components (v1)
// Spec: /docs/klaser-ds.md
//
// Every new Klaser product surface imports from this file. Legacy pages
// (Upload.tsx, Landing.tsx, Search.tsx) still have their own inline copies
// as of the go-live sprint; they'll get refactored to import from here
// post-launch. Keep this file identical across product frontends.

import type { ReactNode, MouseEvent } from "react";

/* ─── Chips / Tags / Pills ────────────────────────────────────────── */

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

export function DsTag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-line text-ink-soft font-rubik text-xs">
      {children}
    </span>
  );
}

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

/* ─── Icons ───────────────────────────────────────────────────────── */

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

export function ArrowCircleLeft() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.6" />
      <path d="M13 8l-4 4 4 4M9 12h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
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

export function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 20h4L20 8l-4-4L4 16v4z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ─── Composite: open-source link button ─────────────────────────── */

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
