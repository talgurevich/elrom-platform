import { useEffect, useState, type ReactNode } from "react";
import Amendments from "./pages/Amendments";
import Authoritative from "./pages/Authoritative";
import Eval from "./pages/Eval";
import Lexicon from "./pages/Lexicon";
import Login from "./pages/Login";
import Review from "./pages/Review";
import Search from "./pages/Search";
import Upload from "./pages/Upload";
import { useAuth } from "./lib/auth";
import { api, type TenantItem } from "./lib/api";

type Tab =
  | "search"
  | "upload"
  | "review"
  | "authoritative"
  | "lexicon"
  | "amendments"
  | "eval";

const SIDEBAR_COLLAPSED_KEY = "elrom.sidebarCollapsed";

// Small inline icons — keep them consistent (24x24 viewBox, stroke=1.75) so the
// rail feels calm rather than a zoo of clashing symbols.
const Icon = {
  search: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <line x1="20" y1="20" x2="16" y2="16" />
    </svg>
  ),
  upload: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
      <polyline points="8 8 12 4 16 8" />
      <line x1="12" y1="4" x2="12" y2="16" />
    </svg>
  ),
  review: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <polyline points="9 12 11 14 15 10" />
    </svg>
  ),
  authoritative: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 3h12v18l-6-4-6 4z" />
    </svg>
  ),
  lexicon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h11a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3z" />
      <line x1="8" y1="9" x2="14" y2="9" />
    </svg>
  ),
  amendments: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 1 0-5.66-5.66l-1.5 1.5" />
      <path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1.5-1.5" />
    </svg>
  ),
  eval: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <line x1="4" y1="20" x2="20" y2="20" />
      <rect x="6" y="12" width="3" height="8" />
      <rect x="11" y="8" width="3" height="12" />
      <rect x="16" y="14" width="3" height="6" />
    </svg>
  ),
} satisfies Record<Tab, ReactNode>;

const tabs: { id: Tab; label: string }[] = [
  { id: "search", label: "חיפוש" },
  { id: "upload", label: "מסמכים" },
  { id: "review", label: "תור בדיקה" },
  { id: "authoritative", label: "תשובות מאושרות" },
  { id: "lexicon", label: "מילון" },
  { id: "amendments", label: "תיקונים" },
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

function HamburgerIcon({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="w-5 h-5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="square"
    >
      {open ? (
        <>
          <line x1="5" y1="5" x2="19" y2="19" />
          <line x1="19" y1="5" x2="5" y2="19" />
        </>
      ) : (
        <>
          <line x1="4" y1="7" x2="20" y2="7" />
          <line x1="4" y1="12" x2="20" y2="12" />
          <line x1="4" y1="17" x2="20" y2="17" />
        </>
      )}
    </svg>
  );
}

// Chevron pointing into the sidebar when expanded, out when collapsed. Sits on
// the physical-left edge of the sidebar (which is its inner edge in RTL).
function CollapseChevron({ collapsed }: { collapsed: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="w-4 h-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* In RTL a right-pointing arrow means "away from sidebar" when the
          sidebar is on the right. When collapsed we point RIGHT (into the
          sidebar); when expanded we point LEFT (out, i.e. collapse it). */}
      {collapsed ? (
        <polyline points="9 6 15 12 9 18" />
      ) : (
        <polyline points="15 6 9 12 15 18" />
      )}
    </svg>
  );
}

function SideNav({
  currentTab,
  onSelect,
  collapsed,
}: {
  currentTab: Tab;
  onSelect: (t: Tab) => void;
  collapsed: boolean;
}) {
  return (
    <nav className="flex flex-col text-sm" aria-label="ניווט ראשי">
      <div
        className={`border-b border-line ${
          collapsed ? "px-2 py-3 flex justify-center" : "px-5 py-4"
        }`}
      >
        {collapsed ? (
          <div
            aria-hidden="true"
            className="w-8 h-8 flex items-center justify-center bg-ink text-surface font-display font-black text-xs tracking-tight"
          >
            אלר
          </div>
        ) : (
          <>
            <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold">
              ניווט
            </div>
            <div className="mt-1 font-display font-black text-lg text-ink leading-tight">
              זיכרון ארגוני
            </div>
          </>
        )}
      </div>
      <ul className={`flex flex-col ${collapsed ? "gap-1 px-2 pt-3" : "gap-0.5 px-3 pt-4"}`}>
        {tabs.map((t) => {
          const active = currentTab === t.id;
          return (
            <li key={t.id}>
              <button
                onClick={() => onSelect(t.id)}
                aria-current={active ? "page" : undefined}
                title={collapsed ? t.label : undefined}
                className={`group relative w-full flex items-center transition-colors ${
                  collapsed
                    ? "justify-center h-11 w-11 mx-auto rounded-md"
                    : "gap-3 pr-3 pl-2 py-2.5 rounded-md"
                } ${
                  active
                    ? "bg-ink text-surface"
                    : "text-ink-soft hover:text-ink hover:bg-line/50"
                }`}
              >
                {active && !collapsed && (
                  <span className="absolute right-0 top-1/2 -translate-y-1/2 w-[3px] h-6 bg-accent rounded-l" />
                )}
                <span
                  className={`shrink-0 ${collapsed ? "w-5 h-5" : "w-[18px] h-[18px]"}`}
                  aria-hidden="true"
                >
                  {Icon[t.id]}
                </span>
                {!collapsed && (
                  <span className="flex-1 text-right truncate">{t.label}</span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default function App() {
  const { state, signOut, switchTenant, exitSwitch } = useAuth();
  const [tab, setTab] = useState<Tab>("search");
  const [menuOpen, setMenuOpen] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  });
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

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  if (state.kind === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-ink-soft text-sm animate-pulse">טוען…</div>
      </div>
    );
  }

  if (state.kind === "anonymous") return <Login />;

  const { user } = state;

  const handleTabSelect = (t: Tab) => {
    setTab(t);
    setSidebarOpen(false); // close mobile drawer on selection
  };

  return (
    <div className="min-h-screen flex flex-col text-ink font-sans bg-line/10">
      <header className="bg-surface border-b border-ink sticky top-0 z-30">
        <div className="w-full px-4 md:px-6 h-16 flex items-center justify-between gap-4">
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

          <div className="flex items-center gap-2">
            {/* User menu */}
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
                    <div className="text-xs text-ink-soft truncate">
                      {user.email}
                    </div>
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

            {/* Hamburger — mobile only. Opens the right-side drawer. */}
            <button
              onClick={() => setSidebarOpen((o) => !o)}
              className="lg:hidden p-2 hover:bg-line/60 transition text-ink"
              aria-label={sidebarOpen ? "סגור תפריט" : "פתח תפריט"}
              aria-expanded={sidebarOpen}
            >
              <HamburgerIcon open={sidebarOpen} />
            </button>
          </div>
        </div>
      </header>

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

      {/* Layout: desktop sidebar is FIXED to the viewport's right edge from
          the bottom of the header to the bottom of the screen. Being fixed
          (not sticky-inside-a-flex-child) means it always visually spans the
          full page-height regardless of how long the main content is —
          otherwise it ends at its content height and looks like a cut-off
          rectangle in the middle of a long page. Main content gets a
          matching right padding on lg+ so it doesn't slide under the aside. */}
      <aside
        className={`hidden lg:flex lg:flex-col fixed top-16 bottom-0 right-0 z-20 bg-surface border-l border-ink shadow-[inset_1px_0_0_rgba(0,0,0,0.02)] transition-[width] duration-200 ease-out ${
          sidebarCollapsed ? "w-16" : "w-60"
        }`}
      >
        <div className="flex-1 overflow-y-auto py-2">
          <SideNav
            currentTab={tab}
            onSelect={handleTabSelect}
            collapsed={sidebarCollapsed}
          />
        </div>
        <button
          onClick={() => setSidebarCollapsed((c) => !c)}
          className={`border-t border-line px-3 py-3 text-ink-soft hover:text-ink hover:bg-line/40 transition-colors flex items-center text-xs ${
            sidebarCollapsed ? "justify-center" : "justify-between gap-2"
          }`}
          aria-label={sidebarCollapsed ? "הרחב תפריט" : "כווץ תפריט"}
          title={sidebarCollapsed ? "הרחב תפריט" : "כווץ תפריט"}
        >
          {!sidebarCollapsed && <span>כווץ</span>}
          <CollapseChevron collapsed={sidebarCollapsed} />
        </button>
      </aside>

      <div className="flex-1 flex w-full min-h-0">
        <main
          className={`flex-1 min-w-0 w-full max-w-5xl mx-auto px-4 md:px-6 py-12 animate-fade-up transition-[padding] duration-200 ease-out ${
            sidebarCollapsed ? "lg:pr-20" : "lg:pr-64"
          }`}
        >
          {tab === "search" && <Search />}
          {tab === "upload" && <Upload />}
          {tab === "review" && <Review />}
          {tab === "authoritative" && <Authoritative />}
          {tab === "lexicon" && <Lexicon />}
          {tab === "amendments" && <Amendments />}
          {tab === "eval" && <Eval />}
        </main>
      </div>

      {/* Mobile drawer — slides in from the physical-right edge. */}
      {sidebarOpen && (
        <>
          <div
            className="lg:hidden fixed inset-0 bg-ink/40 z-30 animate-fade-up"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />
          <aside
            className="lg:hidden fixed top-16 bottom-0 right-0 w-64 bg-surface border-l border-ink z-40 overflow-y-auto animate-fade-up"
            role="dialog"
            aria-label="תפריט ניווט"
          >
            <SideNav
              currentTab={tab}
              onSelect={handleTabSelect}
              collapsed={false}
            />
          </aside>
        </>
      )}

      <footer
        className={`mt-20 border-t border-ink bg-surface transition-[padding] duration-200 ease-out ${
          sidebarCollapsed ? "lg:pr-16" : "lg:pr-60"
        }`}
      >
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
