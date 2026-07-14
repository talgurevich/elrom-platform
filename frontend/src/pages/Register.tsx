import { useEffect, useState, type FormEvent } from "react";
import { api, apiErrorMessage, type RegistrationInfo } from "../lib/api";
import { useAuth } from "../lib/auth";
import { GoogleSignInButton } from "../components/GoogleSignInButton";
import { PasswordInput } from "../components/PasswordInput";
import { NeuralMesh } from "./Login";

const ROLE_LABELS: Record<string, string> = {
  admin: "מנהל",
  reviewer: "בודק",
  secretary: "מזכיר/ה",
};

type LoadState =
  | { kind: "loading" }
  | { kind: "invalid"; message: string }
  | { kind: "ready"; info: RegistrationInfo };

export default function Register({
  token,
  onDone,
}: {
  token: string;
  onDone: () => void;
}) {
  const { registerWithToken } = useAuth();
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getRegistrationInfo(token)
      .then((info) => {
        if (cancelled) return;
        setLoad({ kind: "ready", info });
        setDisplayName(info.display_name || "");
      })
      .catch((err) => {
        if (cancelled) return;
        setLoad({ kind: "invalid", message: apiErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("הסיסמאות אינן תואמות");
      return;
    }
    setBusy(true);
    try {
      await registerWithToken(token, password, displayName.trim() || undefined);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="relative min-h-screen flex items-center justify-center px-6 overflow-hidden bg-surface">
      <NeuralMesh />
      <div className="relative w-full max-w-md border-2 border-ink bg-surface p-12 animate-fade-up">
        <div className="text-center">
          <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
            Organizational Memory
          </div>
          <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
            הרשמה ל-Klaser
          </h1>
        </div>

        {load.kind === "loading" && (
          <p className="mt-10 text-sm text-ink-soft text-center animate-pulse">
            בודק קישור…
          </p>
        )}

        {load.kind === "invalid" && (
          <div className="mt-10 flex flex-col gap-3 text-center">
            <p className="text-sm text-ink">{load.message}</p>
            <p className="text-xs text-ink-soft">
              הקישור אולי פג תוקף. פנה למנהל המערכת לקבלת הזמנה חדשה.
            </p>
          </div>
        )}

        {load.kind === "ready" && (
          <>
            <p className="mt-8 text-sm text-ink-soft text-center leading-relaxed">
              מצטרף לארגון <strong className="text-ink">{load.info.tenant_name}</strong> בתור{" "}
              <strong className="text-ink">
                {ROLE_LABELS[load.info.role] || load.info.role}
              </strong>
              <br />
              <span dir="ltr" className="text-xs">
                {load.info.email}
              </span>
            </p>

            <div className="mt-8 pt-6 border-t border-line">
              <GoogleSignInButton onError={setError} onSuccess={onDone} />
            </div>

            <div className="mt-6 flex items-center gap-3 text-ink-soft">
              <div className="h-px flex-1 bg-line" />
              <span className="text-[11px] uppercase tracking-widest">או</span>
              <div className="h-px flex-1 bg-line" />
            </div>

            <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-3">
              <input
                type="text"
                placeholder="שם מלא"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink text-sm"
              />
              <PasswordInput
                required
                autoComplete="new-password"
                placeholder="סיסמה (לפחות 8 תווים)"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink text-sm"
              />
              <PasswordInput
                required
                autoComplete="new-password"
                placeholder="אימות סיסמה"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                match={
                  confirmPassword.length === 0
                    ? null
                    : confirmPassword === password
                    ? "match"
                    : "mismatch"
                }
                className="w-full border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink text-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="bg-ink text-surface px-4 py-2 text-sm font-bold hover:bg-accent disabled:opacity-40 transition"
              >
                {busy ? "יוצר חשבון…" : "יצירת חשבון וכניסה"}
              </button>
            </form>

            {error && (
              <div className="w-full mt-4 px-4 py-3 border-r-4 border-accent bg-surface text-ink text-sm text-center">
                {error}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
