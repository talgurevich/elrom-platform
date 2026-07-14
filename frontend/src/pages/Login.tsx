import { useMemo, useState, type FormEvent } from "react";
import { api, apiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { GoogleSignInButton } from "../components/GoogleSignInButton";
import { PasswordInput } from "../components/PasswordInput";

type View = "signin" | "forgot" | "forgot_sent";

export default function Login() {
  const { signInWithPassword } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [view, setView] = useState<View>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [forgotEmail, setForgotEmail] = useState("");

  async function handlePasswordSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signInWithPassword(email.trim().toLowerCase(), password);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleForgotSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.forgotPassword(forgotEmail.trim().toLowerCase());
      setView("forgot_sent");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
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
          <h1 className="font-display text-5xl md:text-6xl font-black text-ink leading-[0.95]">
            זיכרון ארגוני
          </h1>
          <p className="text-ink-soft mt-4 text-sm">
            לקיבוצים, למושבים, ולכל מי שצריך להגיע מהר לתקנון.
          </p>
        </div>

        <div className="mt-12 pt-6 border-t border-line">
          <GoogleSignInButton onError={setError} />
        </div>

        <div className="mt-6 flex items-center gap-3 text-ink-soft">
          <div className="h-px flex-1 bg-line" />
          <span className="text-[11px] uppercase tracking-widest">או</span>
          <div className="h-px flex-1 bg-line" />
        </div>

        {view === "signin" && (
          <form onSubmit={handlePasswordSubmit} className="mt-6 flex flex-col gap-3">
            <input
              type="email"
              required
              autoComplete="email"
              placeholder="אימייל"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink text-sm"
            />
            <PasswordInput
              required
              autoComplete="current-password"
              placeholder="סיסמה"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink text-sm"
            />
            <button
              type="submit"
              disabled={busy}
              className="bg-ink text-surface px-4 py-2 text-sm font-bold hover:bg-accent disabled:opacity-40 transition"
            >
              {busy ? "מתחבר…" : "כניסה עם אימייל"}
            </button>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setForgotEmail(email);
                setView("forgot");
              }}
              className="text-xs text-ink-soft hover:text-ink transition self-center"
            >
              שכחת סיסמה?
            </button>
          </form>
        )}

        {view === "forgot" && (
          <form onSubmit={handleForgotSubmit} className="mt-6 flex flex-col gap-3">
            <p className="text-xs text-ink-soft text-center">
              נשלח קישור לאיפוס סיסמה לכתובת האימייל שלך.
            </p>
            <input
              type="email"
              required
              autoComplete="email"
              placeholder="אימייל"
              value={forgotEmail}
              onChange={(e) => setForgotEmail(e.target.value)}
              className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink text-sm"
            />
            <button
              type="submit"
              disabled={busy}
              className="bg-ink text-surface px-4 py-2 text-sm font-bold hover:bg-accent disabled:opacity-40 transition"
            >
              {busy ? "שולח…" : "שליחת קישור לאיפוס"}
            </button>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setView("signin");
              }}
              className="text-xs text-ink-soft hover:text-ink transition self-center"
            >
              חזרה לכניסה
            </button>
          </form>
        )}

        {view === "forgot_sent" && (
          <div className="mt-6 flex flex-col gap-3 text-center">
            <p className="text-sm text-ink">
              אם קיים חשבון בכתובת <strong>{forgotEmail}</strong>, נשלח אליו קישור
              לאיפוס סיסמה.
            </p>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setView("signin");
              }}
              className="text-xs text-ink-soft hover:text-ink transition self-center"
            >
              חזרה לכניסה
            </button>
          </div>
        )}

        {error && (
          <div className="w-full mt-4 px-4 py-3 border-r-4 border-accent bg-surface text-ink text-sm text-center">
            {error}
          </div>
        )}

        <p className="mt-10 text-xs text-ink-soft text-center leading-relaxed">
          הגישה למערכת מוגבלת למשתמשים מוזמנים בלבד.
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
export function NeuralMesh() {
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
