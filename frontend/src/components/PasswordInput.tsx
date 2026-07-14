import { useState, type CSSProperties, type InputHTMLAttributes } from "react";

function EyeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="w-[18px] h-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 12s3.75-7 10-7 10 7 10 7-3.75 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="w-[18px] h-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 3l18 18" />
      <path d="M10.58 10.58a3 3 0 0 0 4.24 4.24" />
      <path d="M9.88 5.09A10.94 10.94 0 0 1 12 5c6.25 0 10 7 10 7a17.7 17.7 0 0 1-3.22 4.19M6.6 6.6C3.88 8.36 2 12 2 12s3.75 7 10 7a10.8 10.8 0 0 0 3.4-.55" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="w-[18px] h-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="5 13 10 18 19 6" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="w-[18px] h-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="18" y1="6" x2="6" y2="18" />
    </svg>
  );
}

type MatchState = "match" | "mismatch" | null;

/**
 * Password <input> with a reveal/hide toggle. The eye only appears once the
 * field has content — an empty password box showing a clickable eye reads
 * as "there's something to reveal here" when there isn't.
 *
 * Usage mirrors a plain <input>: pass the same value/onChange/etc. props,
 * just omit `type` (it's managed internally).
 *
 * Optional `match` prop renders a live green check / red X on the opposite
 * side from the reveal toggle — used on a "confirm password" field to show
 * whether it currently matches the password typed above. Pass `null`
 * (default) to render a plain password field with no indicator.
 */
export function PasswordInput({
  value,
  className = "",
  match = null,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  value: string;
  match?: MatchState;
}) {
  const [visible, setVisible] = useState(false);
  const hasValue = value.length > 0;

  // Inline padding (not Tailwind pl-9/pr-9 classes) so the reserved space
  // for the icons always wins regardless of the utility-generation order of
  // whatever `px-*` class the caller passed in — a plain class string can't
  // reliably override a same-specificity px-* utility either direction.
  const inputStyle: CSSProperties = {
    ...(props.style || {}),
    ...(hasValue ? { paddingLeft: "2.25rem" } : {}),
    ...(match ? { paddingRight: "2.25rem" } : {}),
  };

  return (
    <div className="relative">
      <input
        {...props}
        value={value}
        type={visible ? "text" : "password"}
        className={className}
        style={inputStyle}
      />
      {hasValue && (
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          tabIndex={-1}
          aria-label={visible ? "הסתר סיסמה" : "הצג סיסמה"}
          className="absolute inset-y-0 left-0 px-2.5 flex items-center text-line-strong hover:text-ink transition-colors"
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      )}
      {match && (
        <span
          aria-hidden="true"
          className={`absolute inset-y-0 right-0 px-2.5 flex items-center ${
            match === "match" ? "text-emerald-600" : "text-accent"
          }`}
        >
          {match === "match" ? <CheckIcon /> : <XIcon />}
        </span>
      )}
    </div>
  );
}
