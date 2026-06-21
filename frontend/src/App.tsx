import { useState } from "react";
import Authoritative from "./pages/Authoritative";
import Eval from "./pages/Eval";
import Lexicon from "./pages/Lexicon";
import Login from "./pages/Login";
import Review from "./pages/Review";
import Search from "./pages/Search";
import Upload from "./pages/Upload";
import { useAuth } from "./lib/auth";

type Tab = "search" | "upload" | "review" | "authoritative" | "lexicon" | "eval";

const tabs: { id: Tab; label: string }[] = [
  { id: "search", label: "חיפוש" },
  { id: "upload", label: "מסמכים" },
  { id: "review", label: "תור בדיקה" },
  { id: "authoritative", label: "תשובות מאושרות" },
  { id: "lexicon", label: "מילון" },
  { id: "eval", label: "הערכה" },
];

function InitialAvatar({ name }: { name: string }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return (
    <div className="w-8 h-8 rounded-full bg-brand-gradient text-white text-sm font-semibold flex items-center justify-center shadow-soft">
      {initial}
    </div>
  );
}

export default function App() {
  const { state, signOut } = useAuth();
  const [tab, setTab] = useState<Tab>("search");
  const [menuOpen, setMenuOpen] = useState(false);

  if (state.kind === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-ink-soft text-sm animate-pulse">טוען…</div>
      </div>
    );
  }

  if (state.kind === "anonymous") return <Login />;

  const { user } = state;

  return (
    <div className="min-h-screen text-ink font-sans">
      <nav className="bg-white/80 backdrop-blur-md border-b border-stone-200/70 sticky top-0 z-20">
        <div className="max-w-5xl mx-auto px-6 h-16 flex items-center justify-between gap-6">
          <div className="flex items-center gap-3 shrink-0">
            <div className="w-9 h-9 rounded-xl bg-brand-gradient flex items-center justify-center shadow-soft">
              <span className="text-white font-display font-bold text-base">א</span>
            </div>
            <div className="hidden sm:flex flex-col leading-tight">
              <span className="font-display font-bold text-ink text-base">אלרום</span>
              <span className="text-[10px] tracking-widest uppercase text-ink-soft">
                Organizational Memory
              </span>
            </div>
          </div>

          <div className="flex-1 flex justify-center">
            <div className="flex gap-1 text-sm bg-stone-100/70 rounded-full p-1 ring-1 ring-stone-200/60">
              {tabs.map((t) => {
                const active = tab === t.id;
                return (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    className={`relative px-4 py-1.5 rounded-full transition-all duration-200 ${
                      active
                        ? "bg-brand-gradient text-white shadow-soft"
                        : "text-ink-soft hover:text-ink"
                    }`}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="relative shrink-0">
            <button
              onClick={() => setMenuOpen((o) => !o)}
              onBlur={() => setTimeout(() => setMenuOpen(false), 120)}
              className="flex items-center gap-2 px-2 py-1 rounded-full hover:bg-stone-100 transition"
            >
              <InitialAvatar name={user.display_name || user.email} />
              <span className="hidden md:block text-sm text-ink-soft max-w-[140px] truncate">
                {user.display_name || user.email}
              </span>
            </button>
            {menuOpen && (
              <div className="absolute left-0 mt-2 w-56 bg-white border border-stone-200 rounded-xl shadow-lift overflow-hidden animate-fade-up">
                <div className="px-4 py-3 border-b border-stone-100">
                  <div className="text-sm font-semibold text-ink truncate">
                    {user.display_name || "—"}
                  </div>
                  <div className="text-xs text-ink-soft truncate">{user.email}</div>
                  <div className="mt-1 inline-block text-[10px] tracking-widest uppercase text-accent font-bold">
                    {user.role}
                  </div>
                </div>
                <button
                  onClick={signOut}
                  className="w-full text-right px-4 py-2.5 text-sm text-ink-soft hover:bg-stone-50 hover:text-ink"
                >
                  התנתקות
                </button>
              </div>
            )}
          </div>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-6 py-10 animate-fade-up">
        {tab === "search" && <Search />}
        {tab === "upload" && <Upload />}
        {tab === "review" && <Review />}
        {tab === "authoritative" && <Authoritative />}
        {tab === "lexicon" && <Lexicon />}
        {tab === "eval" && <Eval />}
      </main>

      <footer className="mt-16 border-t border-stone-200">
        <div className="max-w-5xl mx-auto px-6 py-6 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-soft">
          <span>© כל הזכויות שמורות לאלרום סטודיוס בע״מ</span>
          <span className="flex items-center gap-3">
            <a
              href="mailto:tal@elrom.tv"
              className="hover:text-ink transition-colors"
            >
              תמיכה: tal@elrom.tv
            </a>
            <span className="text-stone-300">·</span>
            <a
              href="https://github.com/talgurevich/elrom-platform/commits/main"
              target="_blank"
              rel="noreferrer noopener"
              className="hover:text-ink transition-colors"
              title="פיד פיתוח חי — כל שינוי שהוטמע במערכת"
            >
              עדכוני פיתוח
            </a>
            <span className="text-stone-300">·</span>
            <span>גרסה 0.2</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
