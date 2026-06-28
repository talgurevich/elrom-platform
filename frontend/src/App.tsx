import { useEffect, useState } from "react";
import Authoritative from "./pages/Authoritative";
import Eval from "./pages/Eval";
import Lexicon from "./pages/Lexicon";
import Login from "./pages/Login";
import Review from "./pages/Review";
import Search from "./pages/Search";
import Upload from "./pages/Upload";
import { useAuth } from "./lib/auth";
import { api, type TenantItem } from "./lib/api";

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
    <div className="w-8 h-8 bg-ink text-surface text-sm font-bold flex items-center justify-center">
      {initial}
    </div>
  );
}

export default function App() {
  const { state, signOut, switchTenant, exitSwitch } = useAuth();
  const [tab, setTab] = useState<Tab>("search");
  const [menuOpen, setMenuOpen] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [tenants, setTenants] = useState<TenantItem[]>([]);

  const isSuper =
    state.kind === "signed_in" && state.user.is_super_admin === true;
  const isViewingOther =
    state.kind === "signed_in" && state.user.viewing_other_tenant === true;

  // Lazy-load the tenant list for super-admins once on mount.
  useEffect(() => {
    if (!isSuper) return;
    let cancelled = false;
    api
      .listTenants()
      .then((ts) => {
        if (!cancelled) setTenants(ts);
      })
      .catch(() => {
        if (!cancelled) setTenants([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isSuper]);

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
    <div className="min-h-screen flex flex-col text-ink font-sans">
      <nav className="bg-surface border-b border-ink sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between gap-6">
          {/* Wordmark — driven by the current tenant's name. For super-admins,
              it becomes a dropdown that lists every tenant. */}
          <div className="relative shrink-0">
            <button
              onClick={() => isSuper && setSwitcherOpen((o) => !o)}
              onBlur={() => setTimeout(() => setSwitcherOpen(false), 120)}
              className={`flex items-baseline gap-3 ${
                isSuper ? "cursor-pointer hover:opacity-80" : "cursor-default"
              }`}
              disabled={!isSuper}
              title={isSuper ? "החלף ארגון (super-admin)" : undefined}
            >
              <span
                className={`font-display font-black text-2xl leading-none tracking-tight ${
                  isViewingOther ? "text-accent" : "text-ink"
                }`}
              >
                {user.tenant_name || "—"}
              </span>
              {isSuper && (
                <span className="text-ink-soft text-xs leading-none">▾</span>
              )}
              <span className="hidden sm:inline text-[10px] tracking-[0.2em] uppercase text-ink-soft border-r border-line-strong pr-3">
                Organizational Memory
              </span>
            </button>
            {switcherOpen && isSuper && (
              <div className="absolute right-0 mt-3 min-w-[240px] bg-surface border border-ink overflow-hidden animate-fade-up">
                <div className="px-3 py-2 text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold border-b border-line">
                  צפייה כארגון
                </div>
                {tenants.map((t) => {
                  const isCurrent = t.id === user.tenant_id;
                  return (
                    <button
                      key={t.id}
                      onClick={() => {
                        setSwitcherOpen(false);
                        void switchTenant(t.id);
                      }}
                      className={`w-full text-right px-3 py-2 text-sm hover:bg-line/60 flex items-center justify-between ${
                        isCurrent ? "bg-line/40 font-semibold" : ""
                      }`}
                    >
                      <span>{t.name}</span>
                      {isCurrent && (
                        <span className="text-[10px] text-accent">●</span>
                      )}
                    </button>
                  );
                })}
                {isViewingOther && (
                  <button
                    onClick={() => {
                      setSwitcherOpen(false);
                      void exitSwitch();
                    }}
                    className="w-full text-right px-3 py-2 text-sm border-t border-line hover:bg-line/60 text-accent"
                  >
                    חזרה ל-{user.home_tenant_name || "ארגון הבית"}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Nav — flat underline-on-active, no pills */}
          <div className="flex-1 flex justify-center">
            <div className="flex gap-1 text-sm">
              {tabs.map((t) => {
                const active = tab === t.id;
                return (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    className={`relative px-3 py-5 transition-colors ${
                      active
                        ? "text-ink font-semibold"
                        : "text-ink-soft hover:text-ink"
                    }`}
                  >
                    {t.label}
                    {active && (
                      <span className="absolute inset-x-3 bottom-0 h-[3px] bg-accent" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="relative shrink-0">
            <button
              onClick={() => setMenuOpen((o) => !o)}
              onBlur={() => setTimeout(() => setMenuOpen(false), 120)}
              className="flex items-center gap-2 px-2 py-1 hover:bg-line/60 transition"
            >
              <InitialAvatar name={user.display_name || user.email} />
              <span className="hidden md:block text-sm text-ink-soft max-w-[140px] truncate">
                {user.display_name || user.email}
              </span>
            </button>
            {menuOpen && (
              <div className="absolute left-0 mt-2 w-56 bg-surface border border-ink overflow-hidden animate-fade-up">
                <div className="px-4 py-3 border-b border-line">
                  <div className="text-sm font-semibold text-ink truncate">
                    {user.display_name || "—"}
                  </div>
                  <div className="text-xs text-ink-soft truncate">{user.email}</div>
                  <div className="mt-1 inline-block text-[10px] tracking-[0.2em] uppercase text-accent font-bold">
                    {user.role}
                  </div>
                </div>
                <button
                  onClick={signOut}
                  className="w-full text-right px-4 py-2.5 text-sm text-ink-soft hover:bg-line/40 hover:text-ink"
                >
                  התנתקות
                </button>
              </div>
            )}
          </div>
        </div>
      </nav>

      {isViewingOther && (
        <div className="bg-accent text-surface">
          <div className="max-w-6xl mx-auto px-6 py-2 text-xs flex flex-wrap items-center justify-between gap-3">
            <span>
              <span className="font-bold tracking-wide">צפייה בלבד</span>
              <span className="opacity-90 mr-3">
                אתה צופה כ-{user.tenant_name}. פעולות כתיבה (העלאה, מחיקה,
                סיווג, אישור) חסומות. שאלות בחיפוש כן עובדות וייכתבו ליומן של
                ארגון זה.
              </span>
            </span>
            <button
              onClick={() => void exitSwitch()}
              className="text-surface underline underline-offset-2 hover:no-underline whitespace-nowrap"
            >
              חזרה ל-{user.home_tenant_name || "ארגון הבית"}
            </button>
          </div>
        </div>
      )}

      <main className="flex-1 w-full max-w-6xl mx-auto px-6 py-12 animate-fade-up">
        {tab === "search" && <Search />}
        {tab === "upload" && <Upload />}
        {tab === "review" && <Review />}
        {tab === "authoritative" && <Authoritative />}
        {tab === "lexicon" && <Lexicon />}
        {tab === "eval" && <Eval />}
      </main>

      <footer className="mt-20 border-t border-ink">
        <div className="max-w-6xl mx-auto px-6 py-6 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-soft">
          <span>© כל הזכויות שמורות לאלרום סטודיוס בע״מ</span>
          <span className="flex items-center gap-3">
            <a
              href="mailto:tal@elrom.tv"
              className="hover:text-accent transition-colors"
            >
              תמיכה: tal@elrom.tv
            </a>
            <span className="text-line-strong">·</span>
            <a
              href="https://github.com/talgurevich/elrom-platform/commits/main"
              target="_blank"
              rel="noreferrer noopener"
              className="hover:text-accent transition-colors"
              title="פיד פיתוח חי — כל שינוי שהוטמע במערכת"
            >
              עדכוני פיתוח
            </a>
            <span className="text-line-strong">·</span>
            <span>גרסה 0.3</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
