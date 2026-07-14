import { useEffect, useRef, useState } from "react";
import { apiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: {
              theme?: "outline" | "filled_blue" | "filled_black";
              size?: "small" | "medium" | "large";
              shape?: "rectangular" | "pill" | "circle" | "square";
              text?: "signin_with" | "signup_with" | "continue_with" | "signin";
              locale?: string;
              width?: number;
            }
          ) => void;
        };
      };
    };
  }
}

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

/**
 * Renders Google's own "Sign in with Google" button and wires it to our
 * session-based auth (POST /api/auth/google, matched by email — see
 * app/routes/auth.py::google_login).
 *
 * Shared between the login page and the invite-registration page: the
 * backend only requires a User row with a matching, verified email, and
 * that row already exists the moment a super-admin invites someone (before
 * they ever set a password) — so an invited user can sign in with Google
 * immediately instead of going through the password form. The invite email
 * itself already advertises this ("אפשר גם להתחבר ישירות עם חשבון Google
 * של אותה כתובת, בלי להגדיר סיסמה").
 */
export function GoogleSignInButton({
  onError,
  onSuccess,
}: {
  onError: (msg: string | null) => void;
  onSuccess?: () => void;
}) {
  const { signInWithGoogle } = useAuth();
  const btnRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!CLIENT_ID) {
      onError("VITE_GOOGLE_CLIENT_ID לא הוגדר");
      return;
    }

    const SCRIPT_ID = "google-identity-services";
    if (document.getElementById(SCRIPT_ID)) {
      init();
      return;
    }
    const s = document.createElement("script");
    s.id = SCRIPT_ID;
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.onload = init;
    document.head.appendChild(s);

    function init() {
      if (!window.google || !btnRef.current) return;
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID!,
        callback: async (response) => {
          setBusy(true);
          onError(null);
          try {
            await signInWithGoogle(response.credential);
            onSuccess?.();
          } catch (err) {
            onError(apiErrorMessage(err));
            setBusy(false);
          }
        },
      });
      btnRef.current.innerHTML = "";
      window.google.accounts.id.renderButton(btnRef.current, {
        theme: "outline",
        size: "large",
        shape: "pill",
        text: "continue_with",
        locale: "he",
        width: 280,
      });
    }
    // signInWithGoogle/onError/onSuccess are stable enough in practice
    // (useCallback / inline setState setters); re-running this on every
    // render would re-inject the script and thrash the rendered button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signInWithGoogle]);

  return (
    <div className="flex flex-col items-center gap-3">
      <div ref={btnRef} className={busy ? "opacity-50 pointer-events-none" : ""} />
      {busy && <div className="text-xs text-ink-soft animate-pulse">מתחבר…</div>}
    </div>
  );
}
