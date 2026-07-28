import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type AnalyticsUserRow,
  type AnalyticsWeek,
  type TenantAnalytics,
  type TenantItem,
} from "../lib/api";

/**
 * Per-tenant engagement analytics. Super-admin only — the tab is gated in
 * App.tsx and the endpoint re-checks server-side.
 *
 * Every metric on this page carries a definition that appears on hover.
 * These numbers get quoted in customer conversations, and several of them
 * (refusal rate, conversation depth, "dormant") mean something specific
 * and non-obvious. The definitions live in DEFINITIONS below so there is
 * exactly one wording, shared by tiles and table headers.
 */

// ── Definitions surfaced on hover ───────────────────────────────────────
const DEFINITIONS: Record<string, string> = {
  total_questions:
    "כל השאלות שנשאלו אי־פעם בארגון זה. לא כולל הרצות הערכה (golden questions) ולא תעבורה של מנהלי־על, אלא אם סומן אחרת.",
  questions_30d: "שאלות שנשאלו ב־30 הימים האחרונים.",
  trend_pct:
    "השינוי באחוזים בין 30 הימים האחרונים ל־30 הימים שקדמו להם. מוצג כ־״—״ כשאין תקופה קודמת להשוואה (ארגון צעיר מ־60 יום).",
  active_users_7d:
    "משתמשים ייחודיים ששאלו לפחות שאלה אחת בשבוע האחרון. מי שנכנס לאפליקציה ולא שאל — אינו נספר כאן.",
  active_users_30d:
    "משתמשים ייחודיים ששאלו לפחות שאלה אחת ב־30 הימים האחרונים.",
  adoption:
    "כמה מהמשתמשים שהוקצו לארגון שאלו אי־פעם שאלה. זהו מדד הבריאות המשמעותי ביותר: מושבים שהוקצו ולא נוצלו הם הסימן המוקדם לנטישה.",
  avg_conversation_depth:
    "מספר השאלות הממוצע בכל שיחה. ערך קרוב ל־1 מעיד שמשתמשים שואלים שאלה אחת ועוזבים; ערך גבוה יותר מעיד על חידוד והעמקה. שיחות שקדמו למעבר לשיחות (מיגרציה 0008) אינן נספרות.",
  refusal_rate_30d:
    "אחוז השאלות שהמערכת סירבה לענות עליהן ב־30 הימים האחרונים. שיעור גבוה מצביע על פערים במאגר המסמכים — לא בהכרח על תקלה.",
  negative_feedback_30d:
    "מספר הפעמים שמשתמש סימן תשובה כשגויה (👎) ב־30 הימים האחרונים.",
  total_conversations: "מספר השיחות שנפתחו בארגון זה מאז ומתמיד.",
  never_asked:
    "משתמשים שהוקצו לארגון בשירות הזהויות אך לא שאלו מעולם ולו שאלה אחת.",
  // Table columns
  col_user: "שם המשתמש כפי שהוא רשום בשירות הזהויות.",
  col_total: "סך השאלות שהמשתמש שאל אי־פעם.",
  col_30d: "שאלות שהמשתמש שאל ב־30 הימים האחרונים.",
  col_last: "מתי המשתמש שאל לאחרונה, ולפני כמה ימים.",
  col_convos: "מספר השיחות הנפרדות שהמשתמש פתח.",
  col_depth: "ממוצע השאלות בכל שיחה של המשתמש.",
  col_refusal:
    "אחוז השאלות של המשתמש שהמערכת סירבה לענות עליהן, לאורך כל ההיסטוריה שלו.",
  col_first_impression:
    "מתוך חמש השאלות הראשונות של המשתמש — כמה נדחו. זהו המנבא החזק ביותר לנטישה: מי שהתרשם בהתחלה שהמערכת לא יודעת, לרוב לא חוזר.",
  col_dormant:
    "משתמש שצבר היסטוריה אמיתית אך שתק לאורך זמן. הספים מוצגים בראש הטבלה וניתן לשנותם בקוד השירות.",
  weekly_chart:
    "שאלות לפי שבוע (שבוע מתחיל ביום ראשון, שעון ישראל). שבועות ללא פעילות מוצגים כרווח ריק — הפער עצמו הוא המידע.",
  include_staff:
    "כברירת מחדל תעבורה של מנהלי־על מסוננת החוצה. כשמנהל־על בודק דברים בתוך ארגון של לקוח, השאלות שלו נרשמות תחת אותו ארגון ונראות כמו שימוש אמיתי.",
};

// ── Hover definition ────────────────────────────────────────────────────
/**
 * Renders its children with a small info marker; the definition appears
 * above on hover or keyboard focus. `focus-within` (not just `hover`)
 * keeps it reachable without a mouse.
 */
function Hint({
  text,
  children,
  align = "center",
  placement = "top",
}: {
  text: string;
  children: React.ReactNode;
  align?: "center" | "start";
  placement?: "top" | "bottom";
}) {
  return (
    <span className="relative inline-flex items-center gap-1 group/hint">
      {children}
      <span
        tabIndex={0}
        role="button"
        aria-label="הסבר"
        // preventDefault stops a click from activating an enclosing <label>
        // (the staff toggle would otherwise flip every time the hint is
        // clicked rather than hovered).
        onClick={(e) => e.preventDefault()}
        className="w-3.5 h-3.5 shrink-0 border border-line-strong text-ink-soft text-[9px] leading-none flex items-center justify-center cursor-help select-none hover:border-ink hover:text-ink focus:outline-none focus:border-accent focus:text-accent transition"
      >
        ?
      </span>
      <span
        role="tooltip"
        className={`pointer-events-none absolute z-30 w-64 p-3 bg-ink text-surface text-xs leading-relaxed font-normal text-right normal-case tracking-normal opacity-0 invisible group-hover/hint:opacity-100 group-hover/hint:visible group-focus-within/hint:opacity-100 group-focus-within/hint:visible transition ${
          placement === "bottom" ? "top-full mt-2" : "bottom-full mb-2"
        } ${align === "start" ? "right-0" : "left-1/2 -translate-x-1/2"}`}
      >
        {text}
      </span>
    </span>
  );
}

// ── Formatters ──────────────────────────────────────────────────────────
const pct = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${Math.round(n * 100)}%`;

const num = (n: number) => n.toLocaleString("he-IL");

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("he-IL", { day: "numeric", month: "short" });
}

function daysLabel(days: number): string {
  if (days === 0) return "היום";
  if (days === 1) return "אתמול";
  return `לפני ${num(days)} ימים`;
}

// ── Stat tile ───────────────────────────────────────────────────────────
function Tile({
  label,
  value,
  sub,
  definition,
  alarm = false,
}: {
  label: string;
  value: string;
  sub?: string;
  definition: string;
  alarm?: boolean;
}) {
  return (
    <div className="border-2 border-ink bg-surface p-4">
      <div className="text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold mb-2">
        <Hint text={definition}>{label}</Hint>
      </div>
      <div
        className={`font-display text-3xl leading-none ${
          alarm ? "text-accent" : "text-ink"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1.5 text-xs text-ink-soft">{sub}</div>}
    </div>
  );
}

// ── Weekly bar chart ────────────────────────────────────────────────────
/**
 * One series (questions per week), so no legend — the title names it.
 * Refusals ride along in the tooltip rather than as a second colour: the
 * design system carries a single accent by choice, and a near-black
 * second series reads as ink, not as a category.
 *
 * The plot is dir="ltr" even though the app is RTL — a time axis running
 * left-to-right is what people expect from a chart, and flipping it makes
 * the trend read backwards.
 */
function WeeklyChart({ weeks }: { weeks: AnalyticsWeek[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...weeks.map((w) => w.questions));
  // Label roughly six ticks regardless of range, so they never collide.
  const labelEvery = Math.max(1, Math.ceil(weeks.length / 6));

  if (!weeks.length) {
    return <div className="text-sm text-ink-soft">אין נתונים להצגה.</div>;
  }

  return (
    <div dir="ltr" className="relative">
      {/* Recessive gridlines behind the bars */}
      <div className="relative h-48">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <div
            key={f}
            className="absolute inset-x-0 border-t border-line"
            style={{ bottom: `${f * 100}%` }}
          >
            <span className="absolute -top-2 left-0 text-[10px] text-ink-soft bg-surface pr-1">
              {f === 0 ? "" : num(Math.round(max * f))}
            </span>
          </div>
        ))}

        <div className="absolute inset-0 flex items-end gap-[2px]">
          {weeks.map((w, i) => {
            const h = (w.questions / max) * 100;
            return (
              <div
                key={w.week_start}
                className="flex-1 h-full flex items-end"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                <div
                  className={`w-full rounded-t-[4px] transition-colors ${
                    hover === i ? "bg-accent-dark" : "bg-accent"
                  }`}
                  style={{ height: `${h}%`, minHeight: w.questions ? "2px" : "0" }}
                />
              </div>
            );
          })}
        </div>

        {/* Tooltip — positioned over the hovered bar */}
        {hover !== null && (
          <div
            dir="rtl"
            className="pointer-events-none absolute bottom-full mb-2 z-20 w-44 p-2.5 bg-ink text-surface text-xs leading-relaxed"
            style={{
              left: `${((hover + 0.5) / weeks.length) * 100}%`,
              transform: "translateX(-50%)",
            }}
          >
            <div className="font-bold mb-1">
              שבוע {shortDate(weeks[hover].week_start)}
            </div>
            <div>שאלות: {num(weeks[hover].questions)}</div>
            <div>שואלים: {num(weeks[hover].active_users)}</div>
            <div>סירובים: {num(weeks[hover].refused)}</div>
          </div>
        )}
      </div>

      <div className="flex gap-[2px] mt-1.5">
        {weeks.map((w, i) => (
          <div
            key={w.week_start}
            className="flex-1 text-[10px] text-ink-soft text-center truncate"
          >
            {i % labelEvery === 0 ? shortDate(w.week_start) : ""}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── User table ──────────────────────────────────────────────────────────
function UserTable({ rows }: { rows: AnalyticsUserRow[] }) {
  if (!rows.length) {
    return (
      <div className="text-sm text-ink-soft py-6 text-center border border-line">
        אף משתמש בארגון זה לא שאל שאלה עדיין.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          {/* Column hints open downward: the wrapper is overflow-x-auto,
              which also clips vertically, so an upward tooltip on the top
              row would be cut off. Downward ones render over the rows. */}
          <tr className="border-b-2 border-ink text-right">
            <th className="py-2 pl-3 font-bold">
              <Hint text={DEFINITIONS.col_user} align="start" placement="bottom">
                משתמש
              </Hint>
            </th>
            <th className="py-2 px-3 font-bold whitespace-nowrap">
              <Hint text={DEFINITIONS.col_total} placement="bottom">
                שאלות
              </Hint>
            </th>
            <th className="py-2 px-3 font-bold whitespace-nowrap">
              <Hint text={DEFINITIONS.col_30d} placement="bottom">
                30 יום
              </Hint>
            </th>
            <th className="py-2 px-3 font-bold whitespace-nowrap">
              <Hint text={DEFINITIONS.col_last} placement="bottom">
                פעילות אחרונה
              </Hint>
            </th>
            <th className="py-2 px-3 font-bold whitespace-nowrap">
              <Hint text={DEFINITIONS.col_convos} placement="bottom">
                שיחות
              </Hint>
            </th>
            <th className="py-2 px-3 font-bold whitespace-nowrap">
              <Hint text={DEFINITIONS.col_depth} placement="bottom">
                עומק
              </Hint>
            </th>
            <th className="py-2 px-3 font-bold whitespace-nowrap">
              <Hint text={DEFINITIONS.col_refusal} placement="bottom">
                סירוב
              </Hint>
            </th>
            <th className="py-2 px-3 font-bold whitespace-nowrap">
              <Hint
                text={DEFINITIONS.col_first_impression}
                align="start"
                placement="bottom"
              >
                רושם ראשוני
              </Hint>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr
              key={u.user_id ?? "unattributed"}
              className={`border-b border-line text-right ${
                u.is_dormant ? "bg-accent/5" : ""
              }`}
            >
              <td className="py-2.5 pl-3">
                <div className="font-semibold text-ink flex items-center gap-2">
                  {u.display_name || u.email || "לא מזוהה"}
                  {u.is_dormant && (
                    <span className="text-[9px] tracking-widest uppercase text-accent border border-accent px-1.5 py-0.5">
                      רדום
                    </span>
                  )}
                </div>
                {u.email && u.display_name && (
                  <div className="text-xs text-ink-soft">{u.email}</div>
                )}
              </td>
              <td className="py-2.5 px-3 tabular-nums">{num(u.total_questions)}</td>
              <td className="py-2.5 px-3 tabular-nums">{num(u.questions_30d)}</td>
              <td className="py-2.5 px-3 whitespace-nowrap">
                <div className="tabular-nums">{shortDate(u.last_question_at)}</div>
                <div className="text-xs text-ink-soft">
                  {daysLabel(u.days_since_last)}
                </div>
              </td>
              <td className="py-2.5 px-3 tabular-nums">{num(u.conversations)}</td>
              <td className="py-2.5 px-3 tabular-nums">
                {u.avg_turns_per_conversation.toFixed(1)}
              </td>
              <td
                className={`py-2.5 px-3 tabular-nums ${
                  u.refusal_rate >= 0.3 ? "text-accent font-semibold" : ""
                }`}
              >
                {pct(u.refusal_rate)}
              </td>
              <td className="py-2.5 px-3 tabular-nums">
                {u.first_impression_n ? (
                  <span
                    className={
                      u.first_impression_refused >= 3
                        ? "text-accent font-semibold"
                        : ""
                    }
                  >
                    {u.first_impression_refused}/{u.first_impression_n}
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────────────────
export default function Analytics({ tenants }: { tenants: TenantItem[] }) {
  const [tenantId, setTenantId] = useState<string>("");
  const [weeks, setWeeks] = useState(12);
  const [includeStaff, setIncludeStaff] = useState(false);
  const [data, setData] = useState<TenantAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Default to the first tenant once the list arrives.
  useEffect(() => {
    if (!tenantId && tenants.length) setTenantId(tenants[0].id);
  }, [tenants, tenantId]);

  const load = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.adminAnalytics(tenantId, { weeks, includeStaff }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "שגיאה בטעינת הנתונים");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [tenantId, weeks, includeStaff]);

  useEffect(() => {
    void load();
  }, [load]);

  const ov = data?.overview;
  const adoption = data?.adoption;

  const dormantCount = useMemo(
    () => (data?.users ?? []).filter((u) => u.is_dormant).length,
    [data]
  );

  const trendLabel =
    ov?.trend_pct === null || ov?.trend_pct === undefined
      ? "—"
      : `${ov.trend_pct > 0 ? "+" : ""}${ov.trend_pct}%`;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl text-ink">נתוני שימוש</h1>
          <p className="text-sm text-ink-soft mt-1">
            עד כמה הארגון באמת משתמש במערכת. רחפו מעל שם של מדד לקבלת הגדרה
            מדויקת.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="border-2 border-ink bg-surface px-3 py-2 text-sm font-semibold"
          >
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <select
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
            className="border border-line-strong bg-surface px-3 py-2 text-sm"
          >
            <option value={8}>8 שבועות</option>
            <option value={12}>12 שבועות</option>
            <option value={26}>26 שבועות</option>
            <option value={52}>52 שבועות</option>
          </select>
          <label className="flex items-center gap-2 text-sm border border-line-strong px-3 py-2 cursor-pointer">
            <input
              type="checkbox"
              checked={includeStaff}
              onChange={(e) => setIncludeStaff(e.target.checked)}
            />
            <Hint text={DEFINITIONS.include_staff} align="start">
              כולל מנהלי־על
            </Hint>
          </label>
        </div>
      </header>

      {loading && <div className="text-sm text-ink-soft animate-pulse">טוען…</div>}

      {error && (
        <div className="border-2 border-accent text-accent p-4 text-sm">{error}</div>
      )}

      {data && ov && adoption && !loading && (
        <>
          <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Tile
              label="שאלות (30 יום)"
              value={num(ov.questions_30d)}
              sub={`מגמה ${trendLabel} מול התקופה הקודמת`}
              definition={DEFINITIONS.questions_30d}
            />
            <Tile
              label="משתמשים פעילים (7 ימים)"
              value={num(ov.active_users_7d)}
              sub={`${num(ov.active_users_30d)} ב־30 יום`}
              definition={DEFINITIONS.active_users_7d}
            />
            <Tile
              label="אימוץ מושבים"
              value={`${num(adoption.users_ever_asked)}/${num(
                adoption.provisioned_users
              )}`}
              sub={
                adoption.never_asked.length
                  ? `${num(adoption.never_asked.length)} לא שאלו מעולם`
                  : "כל המשתמשים התחילו"
              }
              definition={DEFINITIONS.adoption}
              alarm={
                adoption.provisioned_users > 0 &&
                adoption.users_ever_asked / adoption.provisioned_users < 0.5
              }
            />
            <Tile
              label="שיעור סירוב (30 יום)"
              value={pct(ov.refusal_rate_30d)}
              sub={`${num(ov.negative_feedback_30d)} משובים שליליים`}
              definition={DEFINITIONS.refusal_rate_30d}
              alarm={ov.refusal_rate_30d >= 0.25}
            />
            <Tile
              label="סה״כ שאלות"
              value={num(ov.total_questions)}
              sub={`מאז ${shortDate(ov.first_question_at)}`}
              definition={DEFINITIONS.total_questions}
            />
            <Tile
              label="עומק שיחה ממוצע"
              value={ov.avg_conversation_depth.toFixed(1)}
              sub={`${num(ov.total_conversations)} שיחות`}
              definition={DEFINITIONS.avg_conversation_depth}
              alarm={ov.avg_conversation_depth > 0 && ov.avg_conversation_depth < 1.3}
            />
            <Tile
              label="משתמשים רדומים"
              value={num(dormantCount)}
              sub={`${data.dormant_min_questions}+ שאלות, שקט ${data.dormant_after_days} יום`}
              definition={DEFINITIONS.col_dormant}
              alarm={dormantCount > 0}
            />
            <Tile
              label="פעילות אחרונה"
              value={shortDate(ov.last_question_at)}
              sub="השאלה האחרונה בארגון"
              definition="מתי מישהו בארגון שאל שאלה בפעם האחרונה. שקט ממושך כאן הוא הסימן הברור ביותר לנטישה."
            />
          </section>

          <section className="border-2 border-ink bg-surface p-5">
            <h2 className="font-display text-lg text-ink mb-4">
              <Hint text={DEFINITIONS.weekly_chart} align="start">
                שאלות לפי שבוע
              </Hint>
            </h2>
            <WeeklyChart weeks={data.weekly} />
          </section>

          {adoption.never_asked.length > 0 && (
            <section className="border border-line-strong bg-surface p-5">
              <h2 className="font-display text-lg text-ink mb-1">
                <Hint text={DEFINITIONS.never_asked} align="start">
                  הוקצו אך לא שאלו מעולם
                </Hint>
              </h2>
              <p className="text-xs text-ink-soft mb-3">
                {num(adoption.never_asked.length)} מתוך{" "}
                {num(adoption.provisioned_users)} משתמשים.
              </p>
              <div className="flex flex-wrap gap-2">
                {adoption.never_asked.map((n) => (
                  <span
                    key={n}
                    className="text-xs border border-line-strong px-2 py-1 text-ink-soft"
                  >
                    {n}
                  </span>
                ))}
              </div>
            </section>
          )}

          <section className="border-2 border-ink bg-surface p-5">
            <h2 className="font-display text-lg text-ink mb-1">פעילות לפי משתמש</h2>
            <p className="text-xs text-ink-soft mb-4">
              ממוין לפי משך השתיקה — מי שנעלם מופיע ראשון.
            </p>
            <UserTable rows={data.users} />
          </section>

          <p className="text-xs text-ink-soft">
            עודכן {new Date(data.generated_at).toLocaleString("he-IL")} · הרצות
            הערכה מסוננות תמיד
            {data.include_staff
              ? " · כולל תעבורת מנהלי־על"
              : " · תעבורת מנהלי־על מסוננת"}
          </p>
        </>
      )}
    </div>
  );
}
