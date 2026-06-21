import { useEffect, useMemo, useRef, useState } from "react";
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
    <div className="relative min-h-screen flex items-center justify-center px-6 overflow-hidden bg-surface">
      <NeuralMesh />
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

/**
 * Neural mesh background — nodes + connecting lines suggesting synapses.
 * Pure SVG, no external asset. A few nodes pulse in accent to hint at activity.
 *
 * Layout: jittered grid (more uniform than pure random, less clumpy). Edges
 * connect each node to its 2 nearest neighbors. Generated once at mount and
 * memoized — no re-shuffle between renders.
 */
function NeuralMesh() {
  const W = 1000;
  const H = 1000;
  const COLS = 9;
  const ROWS = 9;
  const ACTIVE_COUNT = 5;
  const NEIGHBORS = 2;

  const { nodes, edges } = useMemo(() => {
    // Seeded pseudo-random so the pattern is stable across renders / users.
    let seed = 0xc0ffee;
    const rand = () => {
      seed = (seed * 9301 + 49297) % 233280;
      return seed / 233280;
    };

    type Node = { x: number; y: number; active: boolean };
    const ns: Node[] = [];
    const cellW = W / COLS;
    const cellH = H / ROWS;
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        ns.push({
          x: cellW * c + cellW * (0.2 + rand() * 0.6),
          y: cellH * r + cellH * (0.2 + rand() * 0.6),
          active: false,
        });
      }
    }
    const activeIdx = new Set<number>();
    while (activeIdx.size < ACTIVE_COUNT) {
      activeIdx.add(Math.floor(rand() * ns.length));
    }
    activeIdx.forEach((i) => (ns[i].active = true));

    // Edges: each node → 2 nearest neighbors. Dedup symmetric pairs.
    const es: { a: number; b: number }[] = [];
    const seen = new Set<string>();
    for (let i = 0; i < ns.length; i++) {
      const dists = ns
        .map((n, j) => ({ j, d: (n.x - ns[i].x) ** 2 + (n.y - ns[i].y) ** 2 }))
        .filter((x) => x.j !== i)
        .sort((a, b) => a.d - b.d)
        .slice(0, NEIGHBORS);
      for (const { j } of dists) {
        const key = i < j ? `${i}-${j}` : `${j}-${i}`;
        if (!seen.has(key)) {
          seen.add(key);
          es.push({ a: i, b: j });
        }
      }
    }
    return { nodes: ns, edges: es };
  }, []);

  return (
    <>
      <style>{`
        @keyframes neural-pulse {
          0%, 100% { opacity: 0.95; }
          50% { opacity: 0.35; }
        }
        .neural-active { animation: neural-pulse 3.6s ease-in-out infinite; }
        .neural-active-2 { animation-delay: 0.9s; }
        .neural-active-3 { animation-delay: 1.8s; }
        .neural-active-4 { animation-delay: 2.7s; }
      `}</style>
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
      >
        <g stroke="#171717" strokeOpacity="0.07" strokeWidth="0.8">
          {edges.map((e, i) => (
            <line
              key={`e-${i}`}
              x1={nodes[e.a].x}
              y1={nodes[e.a].y}
              x2={nodes[e.b].x}
              y2={nodes[e.b].y}
            />
          ))}
        </g>
        <g>
          {nodes.map((n, i) =>
            n.active ? (
              <circle
                key={`n-${i}`}
                cx={n.x}
                cy={n.y}
                r={4}
                fill="#b8412b"
                className={`neural-active ${
                  i % 4 === 1
                    ? "neural-active-2"
                    : i % 4 === 2
                    ? "neural-active-3"
                    : i % 4 === 3
                    ? "neural-active-4"
                    : ""
                }`}
              />
            ) : (
              <circle
                key={`n-${i}`}
                cx={n.x}
                cy={n.y}
                r={2}
                fill="#171717"
                fillOpacity={0.18}
              />
            )
          )}
        </g>
      </svg>
    </>
  );
}
