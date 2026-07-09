import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  api,
  type AdminTenant,
  type AdminUser,
  type CreateUserPayload,
  type DebugQueueItem,
  type TenantContext,
  type TenantSegment,
} from "../lib/api";

const SEGMENT_LABELS: Record<TenantSegment, string> = {
  kibbutz_shitufi: "קיבוץ שיתופי",
  kibbutz_mitchadesh: "קיבוץ מתחדש",
  moshav: "מושב",
};

const ROLE_LABELS: Record<AdminUser["role"], string> = {
  admin: "מנהל",
  reviewer: "בודק",
  secretary: "מזכיר/ה",
};

type Notice = { kind: "ok" | "err"; text: string } | null;

export default function Admin({ currentUserId }: { currentUserId: string }) {
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice>(null);

  const flash = useCallback((kind: "ok" | "err", text: string) => {
    setNotice({ kind, text });
    window.setTimeout(() => setNotice(null), 4000);
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [ts, us] = await Promise.all([
        api.adminListTenants(),
        api.adminListUsers(),
      ]);
      setTenants(ts);
      setUsers(us);
      // Keep the previously selected tenant if it still exists.
      if (ts.length) {
        setSelectedTenantId((prev) =>
          prev && ts.some((t) => t.id === prev) ? prev : ts[0].id
        );
      } else {
        setSelectedTenantId(null);
      }
    } catch (err) {
      flash("err", err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [flash]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const filteredUsers = useMemo(
    () =>
      selectedTenantId
        ? users.filter((u) => u.tenant_id === selectedTenantId)
        : users,
    [users, selectedTenantId]
  );
  const superAdmins = useMemo(
    () => users.filter((u) => u.is_super_admin),
    [users]
  );

  return (
    <div className="max-w-5xl mx-auto space-y-10">
      <header>
        <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold">
          Super-admin
        </div>
        <h1 className="mt-1 font-display font-black text-3xl md:text-4xl text-ink">
          פאנל ניהול
        </h1>
        <p className="mt-2 text-ink-soft text-sm max-w-2xl">
          ניהול ארגונים, משתמשים והרשאות. פעולות אלו מבוצעות מחשבון המנהל
          הראשי (super-admin) בלבד — אין להיות במצב "צפייה כארגון" בזמן ההפעלה.
        </p>
      </header>

      {notice && (
        <div
          className={`px-4 py-3 border text-sm ${
            notice.kind === "ok"
              ? "border-ink bg-line/40 text-ink"
              : "border-accent bg-surface text-accent"
          }`}
        >
          {notice.text}
        </div>
      )}

      <StatsRow
        tenants={tenants}
        users={users}
        superAdmins={superAdmins.length}
      />

      <TenantsSection
        tenants={tenants}
        loading={loading}
        selectedId={selectedTenantId}
        onSelect={setSelectedTenantId}
        onCreated={async (t) => {
          flash("ok", `ארגון "${t.name}" נוצר`);
          await reload();
          setSelectedTenantId(t.id);
        }}
        onError={(msg) => flash("err", msg)}
      />

      <UsersSection
        tenants={tenants}
        users={filteredUsers}
        selectedTenantId={selectedTenantId}
        currentUserId={currentUserId}
        loading={loading}
        onChanged={async (msg) => {
          flash("ok", msg);
          await reload();
        }}
        onError={(msg) => flash("err", msg)}
      />

      {selectedTenantId && (
        <TenantContextSection
          tenantId={selectedTenantId}
          tenantName={
            tenants.find((t) => t.id === selectedTenantId)?.name || "—"
          }
          onSaved={(msg) => flash("ok", msg)}
          onError={(msg) => flash("err", msg)}
        />
      )}

      <DebugQueueSection
        tenants={tenants}
        onError={(msg) => flash("err", msg)}
        onDismissed={(msg) => flash("ok", msg)}
      />

      <SuperAdminsSection superAdmins={superAdmins} />
    </div>
  );
}

function StatsRow({
  tenants,
  users,
  superAdmins,
}: {
  tenants: AdminTenant[];
  users: AdminUser[];
  superAdmins: number;
}) {
  const totalDocs = tenants.reduce((s, t) => s + t.document_count, 0);
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-ink border border-ink">
      <Stat label="ארגונים" value={tenants.length} />
      <Stat label="משתמשים" value={users.length} />
      <Stat label="Super-admins" value={superAdmins} />
      <Stat label='מסמכים סה"כ' value={totalDocs} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-surface p-5">
      <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold">
        {label}
      </div>
      <div className="mt-2 font-display font-black text-3xl text-ink leading-none">
        {value}
      </div>
    </div>
  );
}

/* ─── Tenants ─────────────────────────────────────────────────────── */

function TenantsSection({
  tenants,
  loading,
  selectedId,
  onSelect,
  onCreated,
  onError,
}: {
  tenants: AdminTenant[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreated: (t: AdminTenant) => Promise<void> | void;
  onError: (msg: string) => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [segment, setSegment] = useState<TenantSegment>("kibbutz_mitchadesh");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const t = await api.adminCreateTenant({ name: name.trim(), segment });
      setName("");
      setShowForm(false);
      await onCreated(t);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <SectionHeader
        title="ארגונים"
        subtitle="כל הארגונים במערכת. לחצו על שורה לצפייה במשתמשי הארגון."
        action={
          <button
            onClick={() => setShowForm((v) => !v)}
            className="bg-ink text-surface px-4 py-2 text-sm font-bold hover:bg-accent transition"
          >
            {showForm ? "בטל" : "+ ארגון חדש"}
          </button>
        }
      />

      {showForm && (
        <div className="mt-4 border-2 border-ink bg-surface p-6 grid md:grid-cols-3 gap-4">
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="text-xs text-ink-soft">שם ארגון</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="למשל: קיבוץ דגניה"
              className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-soft">סוג</span>
            <select
              value={segment}
              onChange={(e) => setSegment(e.target.value as TenantSegment)}
              className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink"
            >
              {Object.entries(SEGMENT_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <div className="md:col-span-3 flex justify-end">
            <button
              onClick={submit}
              disabled={busy || !name.trim()}
              className="bg-accent text-surface px-5 py-2.5 text-sm font-bold hover:bg-accent-dark disabled:opacity-50 transition"
            >
              {busy ? "יוצר..." : "צור ארגון"}
            </button>
          </div>
        </div>
      )}

      <div className="mt-6 border border-ink bg-surface overflow-hidden">
        <div className="grid grid-cols-12 border-b border-ink bg-line/40 text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold px-4 py-3">
          <div className="col-span-5">שם</div>
          <div className="col-span-3">סוג</div>
          <div className="col-span-2 text-center">משתמשים</div>
          <div className="col-span-2 text-center">מסמכים</div>
        </div>
        {loading && tenants.length === 0 ? (
          <div className="p-8 text-center text-ink-soft text-sm animate-pulse">
            טוען…
          </div>
        ) : tenants.length === 0 ? (
          <div className="p-8 text-center text-ink-soft text-sm">
            אין ארגונים עדיין. יצרו את הראשון.
          </div>
        ) : (
          tenants.map((t) => {
            const active = t.id === selectedId;
            return (
              <button
                key={t.id}
                onClick={() => onSelect(t.id)}
                className={`w-full grid grid-cols-12 px-4 py-4 text-right border-b border-line last:border-b-0 transition ${
                  active ? "bg-ink text-surface" : "hover:bg-line/50"
                }`}
              >
                <div className="col-span-5 font-semibold">{t.name}</div>
                <div className={`col-span-3 text-sm ${active ? "opacity-80" : "text-ink-soft"}`}>
                  {SEGMENT_LABELS[t.segment as TenantSegment] || t.segment}
                </div>
                <div className="col-span-2 text-center text-sm">
                  {t.user_count}
                </div>
                <div className="col-span-2 text-center text-sm">
                  {t.document_count}
                </div>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}

/* ─── Users ────────────────────────────────────────────────────────── */

function UsersSection({
  tenants,
  users,
  selectedTenantId,
  currentUserId,
  loading,
  onChanged,
  onError,
}: {
  tenants: AdminTenant[];
  users: AdminUser[];
  selectedTenantId: string | null;
  currentUserId: string;
  loading: boolean;
  onChanged: (msg: string) => void | Promise<void>;
  onError: (msg: string) => void;
}) {
  const selectedTenant = tenants.find((t) => t.id === selectedTenantId) || null;
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);

  const initialForm = (): CreateUserPayload => ({
    tenant_id: selectedTenantId || "",
    email: "",
    role: "reviewer",
    display_name: "",
    is_super_admin: false,
  });
  const [form, setForm] = useState<CreateUserPayload>(initialForm);

  useEffect(() => {
    setForm((f) => ({ ...f, tenant_id: selectedTenantId || "" }));
  }, [selectedTenantId]);

  const submit = async () => {
    if (!form.email.trim() || !form.tenant_id) return;
    setBusy(true);
    try {
      await api.adminCreateUser({
        ...form,
        email: form.email.trim().toLowerCase(),
        display_name: form.display_name?.trim() || null,
      });
      setShowForm(false);
      setForm(initialForm());
      await onChanged(`המשתמש ${form.email} נוסף`);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (u: AdminUser, role: AdminUser["role"]) => {
    try {
      await api.adminUpdateUser(u.id, { role });
      await onChanged(`תפקיד עודכן: ${u.email}`);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    }
  };

  const toggleSuper = async (u: AdminUser) => {
    if (u.id === currentUserId && u.is_super_admin) {
      onError("אי אפשר להסיר הרשאת super-admin מהמשתמש שאיתו התחברת");
      return;
    }
    if (
      !confirm(
        u.is_super_admin
          ? `להסיר הרשאת super-admin מ-${u.email}?`
          : `להעניק הרשאת super-admin ל-${u.email}?`
      )
    )
      return;
    try {
      await api.adminUpdateUser(u.id, { is_super_admin: !u.is_super_admin });
      await onChanged(
        u.is_super_admin
          ? `הרשאת super-admin הוסרה מ-${u.email}`
          : `הרשאת super-admin ניתנה ל-${u.email}`
      );
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    }
  };

  const removeUser = async (u: AdminUser) => {
    if (u.id === currentUserId) {
      onError("אי אפשר למחוק את המשתמש הנוכחי");
      return;
    }
    if (!confirm(`למחוק את ${u.email}? פעולה זו אינה הפיכה.`)) return;
    try {
      await api.adminDeleteUser(u.id);
      await onChanged(`המשתמש ${u.email} נמחק`);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    }
  };

  return (
    <section>
      <SectionHeader
        title="משתמשים"
        subtitle={
          selectedTenant
            ? `משתמשי ${selectedTenant.name}`
            : "בחרו ארגון מלמעלה כדי לראות את המשתמשים שלו"
        }
        action={
          selectedTenant && (
            <button
              onClick={() => setShowForm((v) => !v)}
              className="bg-ink text-surface px-4 py-2 text-sm font-bold hover:bg-accent transition"
            >
              {showForm ? "בטל" : "+ משתמש חדש"}
            </button>
          )
        }
      />

      {showForm && selectedTenant && (
        <div className="mt-4 border-2 border-ink bg-surface p-6 grid md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-soft">אימייל (Google)</span>
            <input
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="user@example.com"
              className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink"
              type="email"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-soft">שם תצוגה (רשות)</span>
            <input
              value={form.display_name || ""}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              placeholder="שם מלא"
              className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-soft">תפקיד</span>
            <select
              value={form.role}
              onChange={(e) =>
                setForm({ ...form, role: e.target.value as AdminUser["role"] })
              }
              className="border border-line-strong px-3 py-2 bg-surface focus:outline-none focus:border-ink"
            >
              {Object.entries(ROLE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 pt-6">
            <input
              type="checkbox"
              checked={!!form.is_super_admin}
              onChange={(e) =>
                setForm({ ...form, is_super_admin: e.target.checked })
              }
              className="w-4 h-4 accent-accent"
            />
            <span className="text-sm text-ink">
              הענק גם הרשאת super-admin
            </span>
          </label>
          <div className="md:col-span-2 flex justify-end">
            <button
              onClick={submit}
              disabled={busy || !form.email.trim()}
              className="bg-accent text-surface px-5 py-2.5 text-sm font-bold hover:bg-accent-dark disabled:opacity-50 transition"
            >
              {busy ? "מוסיף..." : "הוסף משתמש"}
            </button>
          </div>
        </div>
      )}

      <div className="mt-6 border border-ink bg-surface overflow-hidden">
        <div className="grid grid-cols-12 border-b border-ink bg-line/40 text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold px-4 py-3">
          <div className="col-span-4">אימייל</div>
          <div className="col-span-3">שם</div>
          <div className="col-span-2">תפקיד</div>
          <div className="col-span-1 text-center">Super</div>
          <div className="col-span-2 text-left">פעולות</div>
        </div>
        {loading && users.length === 0 ? (
          <div className="p-8 text-center text-ink-soft text-sm animate-pulse">
            טוען…
          </div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center text-ink-soft text-sm">
            {selectedTenant
              ? "אין משתמשים בארגון זה עדיין."
              : "בחרו ארגון מלמעלה."}
          </div>
        ) : (
          users.map((u) => (
            <div
              key={u.id}
              className="grid grid-cols-12 px-4 py-3 items-center border-b border-line last:border-b-0"
            >
              <div className="col-span-4 text-sm truncate">
                {u.email}
                {u.id === currentUserId && (
                  <span className="mr-2 text-[10px] tracking-widest uppercase text-accent">
                    · את/ה
                  </span>
                )}
              </div>
              <div className="col-span-3 text-sm text-ink-soft truncate">
                {u.display_name || "—"}
              </div>
              <div className="col-span-2">
                <select
                  value={u.role}
                  onChange={(e) =>
                    changeRole(u, e.target.value as AdminUser["role"])
                  }
                  className="border border-line px-2 py-1 bg-surface text-sm w-full"
                >
                  {Object.entries(ROLE_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-span-1 text-center">
                <button
                  onClick={() => toggleSuper(u)}
                  className={`w-6 h-6 border-2 border-ink transition ${
                    u.is_super_admin ? "bg-accent" : "bg-surface"
                  }`}
                  title={
                    u.is_super_admin
                      ? "הסר super-admin"
                      : "הענק super-admin"
                  }
                  aria-label="toggle super-admin"
                />
              </div>
              <div className="col-span-2 text-left">
                <button
                  onClick={() => removeUser(u)}
                  disabled={u.id === currentUserId}
                  className="text-xs text-ink-soft hover:text-accent disabled:opacity-30 disabled:pointer-events-none"
                >
                  מחק
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

/* ─── Tenant system context editor ─────────────────────────────────── */

function TenantContextSection({
  tenantId,
  tenantName,
  onSaved,
  onError,
}: {
  tenantId: string;
  tenantName: string;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [data, setData] = useState<TenantContext | null>(null);
  const [draft, setDraft] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .adminGetTenant(tenantId)
      .then((t) => {
        if (cancelled) return;
        setData(t);
        setDraft(t.system_context || "");
      })
      .catch((err) => {
        if (cancelled) return;
        onError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, onError]);

  const dirty = (data?.system_context || "") !== draft;

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.adminUpdateTenantContext(
        tenantId,
        draft.trim() || null
      );
      setData(updated);
      setDraft(updated.system_context || "");
      onSaved(
        updated.system_context
          ? `הקשר ארגוני נשמר עבור ${tenantName}`
          : `הקשר ארגוני נמחק עבור ${tenantName} — יחזור לתבנית ברירת מחדל`
      );
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const revert = () => {
    setDraft(data?.system_context || "");
  };

  const clearOverride = async () => {
    if (
      !confirm(
        `למחוק את ההקשר הארגוני של ${tenantName}? המערכת תחזור לתבנית ברירת מחדל.`
      )
    )
      return;
    setDraft("");
    setSaving(true);
    try {
      const updated = await api.adminUpdateTenantContext(tenantId, null);
      setData(updated);
      onSaved(`הקשר ארגוני נמחק — ${tenantName} משתמש עכשיו בתבנית ברירת מחדל`);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <SectionHeader
        title="הקשר ארגוני"
        subtitle={`הבלוק הזה מוזרק לתוך system-prompt של המערכת בכל שאלה של ${tenantName}. כאן מגדירים מפת מסמכים, מונחים ייחודיים, וכללי היררכיה של הארגון. אופציונלי — אם ריק, המערכת נופלת לתבנית ברירת מחדל שבה רק שם הארגון + כלל היררכיה גנרי.`}
        action={
          data?.system_context && (
            <button
              onClick={clearOverride}
              className="text-xs text-ink-soft hover:text-accent underline underline-offset-4"
            >
              מחק והחזר לברירת מחדל
            </button>
          )
        }
      />

      <div className="mt-4 border-2 border-ink bg-surface p-4">
        {loading ? (
          <div className="p-6 text-center text-ink-soft text-sm animate-pulse">
            טוען…
          </div>
        ) : (
          <>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              dir="rtl"
              placeholder={CONTEXT_PLACEHOLDER}
              className="w-full h-96 border border-line-strong p-3 bg-surface focus:outline-none focus:border-ink text-sm leading-relaxed font-sans resize-y"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-soft">
              <span>
                {draft.trim().length.toLocaleString()} תווים
                {!data?.system_context && draft.trim().length === 0 && (
                  <span className="mr-2">· משתמש בתבנית ברירת מחדל</span>
                )}
              </span>
              <div className="flex items-center gap-2">
                {dirty && (
                  <button
                    onClick={revert}
                    className="text-ink-soft hover:text-ink underline underline-offset-4"
                  >
                    בטל שינויים
                  </button>
                )}
                <button
                  onClick={save}
                  disabled={!dirty || saving}
                  className="bg-ink text-surface px-5 py-2 text-sm font-bold hover:bg-accent disabled:opacity-40 transition"
                >
                  {saving ? "שומר…" : "שמור"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

const CONTEXT_PLACEHOLDER = `דוגמה למה כדאי לכתוב כאן:

## זהות והיררכיית מקורות

אתה יועץ של [שם הארגון].

מפת מסמכים:
- תקנון ראשי — משנת ...
- תקנוני משנה קיימים: פנסיה, שיוך דירות, ...
- החלטות אסיפה: מהשנתיים האחרונות

מונחים חשובים:
- "ותק" = שנות חברות מלאות בארגון
- "מזכירות" ≠ "ועד הנהלה"

כללים ייחודיים:
- כשמופיע "החלטת אסיפה" — צטט לפי תאריך ההחלטה, המאוחרת גוברת.
- ...

אם משאירים ריק — המערכת משתמשת בתבנית ברירת מחדל: שם הארגון + כללי היררכיה גנריים בלבד.`;

/* ─── Debug queue ─────────────────────────────────────────────────── */

function DebugQueueSection({
  tenants,
  onError,
  onDismissed,
}: {
  tenants: AdminTenant[];
  onError: (msg: string) => void;
  onDismissed: (msg: string) => void;
}) {
  const [items, setItems] = useState<DebugQueueItem[]>([]);
  const [tenantFilter, setTenantFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [copiedFor, setCopiedFor] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.adminDebugQueue(tenantFilter || undefined);
      setItems(rows);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [tenantFilter, onError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const copyMarkdown = async (item: DebugQueueItem) => {
    const md = buildDebugMarkdown(item);
    try {
      await navigator.clipboard.writeText(md);
      setCopiedFor(item.query_id);
      window.setTimeout(
        () => setCopiedFor((prev) => (prev === item.query_id ? null : prev)),
        2000
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  const dismiss = async (item: DebugQueueItem) => {
    if (!confirm("להסיר מהתור?")) return;
    try {
      await api.adminDismissDebug(item.query_id);
      onDismissed("הוסר מהתור");
      await reload();
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    }
  };

  return (
    <section>
      <SectionHeader
        title="תור באגים"
        subtitle="שאלות שהמשתמש סימן כתשובה שגויה — הקורפוס יודע, השליפה פספסה. פתחו כדי לראות את מקורות השליפה והעתיקו את הדיווח לניפוי."
        action={
          <div className="flex items-center gap-2">
            <select
              value={tenantFilter}
              onChange={(e) => setTenantFilter(e.target.value)}
              className="border border-line-strong px-3 py-2 bg-surface text-sm"
            >
              <option value="">כל הארגונים</option>
              {tenants.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <button
              onClick={() => void reload()}
              className="border border-line-strong px-3 py-2 text-sm hover:border-ink transition"
              title="רענן"
            >
              רענן
            </button>
          </div>
        }
      />

      <div className="mt-6 border border-ink bg-surface overflow-hidden">
        {loading && items.length === 0 ? (
          <div className="p-8 text-center text-ink-soft text-sm animate-pulse">
            טוען…
          </div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-ink-soft text-sm">
            אין באגים ממתינים.
          </div>
        ) : (
          items.map((item) => {
            const open = expanded.has(item.query_id);
            return (
              <div
                key={item.query_id}
                className="border-b border-line last:border-b-0"
              >
                <button
                  onClick={() => toggle(item.query_id)}
                  className="w-full text-right px-4 py-3 grid grid-cols-12 gap-3 items-baseline hover:bg-line/40 transition"
                >
                  <div className="col-span-6">
                    <div className="text-sm font-semibold text-ink truncate">
                      {item.question}
                    </div>
                    {item.answer && (
                      <div className="text-xs text-ink-soft mt-1 line-clamp-1">
                        {item.answer.slice(0, 160)}
                      </div>
                    )}
                  </div>
                  <div className="col-span-3 text-xs text-ink-soft truncate">
                    {item.tenant_name || item.tenant_id}
                  </div>
                  <div className="col-span-2 text-xs text-ink-soft">
                    {formatDate(item.created_at)}
                  </div>
                  <div className="col-span-1 text-left text-xs text-accent font-bold">
                    {open ? "−" : "+"}
                  </div>
                </button>

                {open && (
                  <div className="border-t border-line bg-line/20 px-5 py-5 space-y-5">
                    <div>
                      <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-1">
                        שאלה
                      </div>
                      <p className="text-sm text-ink whitespace-pre-wrap">
                        {item.question}
                      </p>
                    </div>

                    <div>
                      <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-1">
                        תשובה שהוחזרה
                        {item.confidence && (
                          <span className="mr-2 text-accent">
                            · {item.confidence}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-ink whitespace-pre-wrap bg-surface border-r-4 border-accent px-3 py-2">
                        {item.answer || "(אין תשובה)"}
                      </p>
                    </div>

                    <div>
                      <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-2">
                        קטעי טקסט שנשלפו ({item.source_chunks.length})
                      </div>
                      {item.source_chunks.length === 0 ? (
                        <p className="text-xs text-ink-soft">
                          לא הוחזרו קטעים.
                        </p>
                      ) : (
                        <div className="grid gap-px bg-line border border-line">
                          {item.source_chunks.map((c, i) => (
                            <details
                              key={c.chunk_id}
                              className="bg-surface"
                              open={i < 2}
                            >
                              <summary className="cursor-pointer px-3 py-2 text-sm flex items-baseline gap-3 hover:bg-line/40">
                                <span className="font-mono text-accent">
                                  [{i + 1}]
                                </span>
                                <span className="text-ink truncate">
                                  {c.document_filename}
                                </span>
                                {c.section_path && (
                                  <span className="text-ink-soft font-mono text-xs">
                                    {c.section_path}
                                  </span>
                                )}
                              </summary>
                              <pre className="px-3 py-2 border-t border-line text-xs leading-relaxed whitespace-pre-wrap text-ink-soft font-sans">
                                {c.text}
                              </pre>
                            </details>
                          ))}
                        </div>
                      )}
                    </div>

                    {item.retrieval_debug && (
                      <details>
                        <summary className="cursor-pointer text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold hover:text-ink">
                          Retrieval trace (JSON)
                        </summary>
                        <pre className="mt-2 text-[11px] leading-relaxed bg-surface border border-line p-3 overflow-auto max-h-64 whitespace-pre-wrap text-ink-soft font-mono">
                          {JSON.stringify(item.retrieval_debug, null, 2)}
                        </pre>
                      </details>
                    )}

                    <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-line">
                      <button
                        onClick={() => void copyMarkdown(item)}
                        className="bg-ink text-surface px-4 py-2 text-sm font-bold hover:bg-accent transition"
                      >
                        {copiedFor === item.query_id
                          ? "✓ הועתק"
                          : "העתק דיווח Markdown"}
                      </button>
                      <button
                        onClick={() => void dismiss(item)}
                        className="border border-line-strong px-4 py-2 text-sm text-ink-soft hover:border-ink hover:text-ink transition"
                      >
                        הסר מהתור
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

function buildDebugMarkdown(item: DebugQueueItem): string {
  const lines: string[] = [];
  lines.push(`# Debug report — query ${item.query_id}`);
  lines.push("");
  lines.push(`- **Tenant**: ${item.tenant_name || item.tenant_id}`);
  lines.push(`- **When**: ${item.created_at}`);
  lines.push(`- **Confidence**: ${item.confidence || "—"}`);
  lines.push(`- **LLM used**: ${item.llm_used ? "yes" : "no"}`);
  lines.push("");
  lines.push("## Question");
  lines.push("");
  lines.push("```");
  lines.push(item.question);
  lines.push("```");
  lines.push("");
  lines.push("## Answer returned to user");
  lines.push("");
  lines.push("```");
  lines.push(item.answer || "(no answer)");
  lines.push("```");
  lines.push("");
  lines.push(`## Retrieved chunks (${item.source_chunks.length})`);
  lines.push("");
  item.source_chunks.forEach((c, i) => {
    lines.push(
      `### [${i + 1}] ${c.document_filename}${
        c.section_path ? ` · ${c.section_path}` : ""
      }`
    );
    lines.push("");
    lines.push("```");
    lines.push(c.text);
    lines.push("```");
    lines.push("");
  });
  if (item.retrieval_debug) {
    lines.push("## Retrieval trace");
    lines.push("");
    lines.push("```json");
    lines.push(JSON.stringify(item.retrieval_debug, null, 2));
    lines.push("```");
  }
  return lines.join("\n");
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("he-IL", {
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

/* ─── Super admins ─────────────────────────────────────────────────── */

function SuperAdminsSection({ superAdmins }: { superAdmins: AdminUser[] }) {
  return (
    <section>
      <SectionHeader
        title="Super-admins"
        subtitle="משתמשים בעלי הרשאת מנהל-על. יכולים לנהל את כל הארגונים ולצפות בכל הנתונים."
      />
      <div className="mt-4 border border-ink bg-surface overflow-hidden">
        {superAdmins.length === 0 ? (
          <div className="p-6 text-center text-ink-soft text-sm">
            אין super-admins.
          </div>
        ) : (
          superAdmins.map((u) => (
            <div
              key={u.id}
              className="px-4 py-3 flex items-center justify-between border-b border-line last:border-b-0"
            >
              <div>
                <div className="text-sm font-semibold text-ink">
                  {u.display_name || u.email}
                </div>
                <div className="text-xs text-ink-soft">
                  {u.email} · ארגון בית: {u.tenant_name || "—"}
                </div>
              </div>
              <span className="text-[10px] tracking-[0.25em] uppercase text-accent font-bold">
                super-admin
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

/* ─── Shared ───────────────────────────────────────────────────────── */

function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-ink pb-3">
      <div>
        <h2 className="font-display font-black text-2xl text-ink leading-none">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-2 text-sm text-ink-soft max-w-2xl">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}
