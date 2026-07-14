import { useEffect, useState, type FormEvent } from "react";
import { api, apiErrorMessage, type ResetPasswordInfo } from "../lib/api";
import { useAuth } from "../lib/auth";
import { NeuralMesh } from "./Login";
import { PasswordInput } from "../components/PasswordInput";

type LoadState =
  | { kind: "loading" }
  | { kind: "invalid"; message: string }
  | { kind: "ready"; info: ResetPasswordInfo };

export default function ResetPassword({
  token,
  onDone,
}: {
  token: string;
  onDone: () => void;
}) {
  const { resetPasswordWithToken } = useAuth();
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getResetPasswordInfo(token)
      .then((info) => {
        if (cancelled) return;
        setLoad({ kind: "ready", info });
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
      await resetPasswordWithToken(token, password);
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
            Klaser
          </div>
          <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
            בחירת סיסמה חדשה
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
              אפשר לבקש קישור חדש בעמוד ההתחברות.
            </p>
          </div>
        )}

        {load.kind === "ready" && (
          <>
            <p className="mt-8 text-sm text-ink-soft text-center">
              <span dir="ltr" className="text-xs">
                {load.info.email}
              </span>
            </p>

            <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-3">
              <PasswordInput
                required
                autoComplete="new-password"
                placeholder="סיסמה חדשה (לפחות 8 תווים)"
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
                {busy ? "מעדכן…" : "עדכון סיסמה וכניסה"}
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
