import { useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
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

export default function Login() {
  const { signInWithGoogle } = useAuth();
  const btnRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!CLIENT_ID) {
      setError("VITE_GOOGLE_CLIENT_ID לא הוגדר");
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
          setError(null);
          try {
            await signInWithGoogle(response.credential);
          } catch (err) {
            if (err instanceof ApiError) {
              setError(err.message.replace(/^\{"detail":"|"\}$/g, ""));
            } else {
              setError(err instanceof Error ? err.message : String(err));
            }
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
  }, [signInWithGoogle]);

  return (
    <div className="relative min-h-screen flex items-center justify-center px-6 overflow-hidden">
      {/* Background — close-up of tree bark from Unsplash (photo by Annie Spratt).
          Heavily blurred + darkened so it reads as texture, not a photo, and the
          card on top stays the visual subject. Slight scale to hide blur edges. */}
      <div
        className="absolute inset-0 bg-cover bg-center"
        style={{
          backgroundImage:
            "url('https://images.unsplash.com/photo-1523440775332-daeb15e69286?fm=jpg&q=60&w=2400&auto=format&fit=crop&ixlib=rb-4.1.0')",
          filter: "blur(6px) brightness(0.45) saturate(0.85)",
          transform: "scale(1.06)",
        }}
        aria-hidden="true"
      />
      {/* Warm ink wash to tie the bark hues into the modernist palette. */}
      <div
        className="absolute inset-0"
        style={{ backgroundColor: "rgba(23, 23, 23, 0.35)" }}
        aria-hidden="true"
      />

      <div className="relative w-full max-w-md border-2 border-ink bg-surface p-12 animate-fade-up">
        <div className="text-center">
          <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
            Organizational Memory
          </div>
          <h1 className="font-display text-5xl md:text-6xl font-black text-ink leading-[0.95]">
            זיכרון ארגוני
          </h1>
          <p className="text-ink-soft mt-4 text-sm">
            לקיבוצים, למושבים, ולכל מי שצריך להגיע מהר לתקנון.
          </p>
        </div>

        <div className="mt-12 pt-6 border-t border-line flex flex-col items-center gap-3">
          <div ref={btnRef} className={busy ? "opacity-50 pointer-events-none" : ""} />
          {busy && (
            <div className="text-xs text-ink-soft animate-pulse">מתחבר…</div>
          )}
          {error && (
            <div className="w-full mt-2 px-4 py-3 border-r-4 border-accent bg-surface text-ink text-sm text-center">
              {error}
            </div>
          )}
        </div>

        <p className="mt-10 text-xs text-ink-soft text-center leading-relaxed">
          הגישה למערכת מוגבלת למשתמשים מאושרים בלבד.
          <br />
          אם אינך מצליח להתחבר — פנה למנהל המערכת.
        </p>
      </div>
    </div>
  );
}
