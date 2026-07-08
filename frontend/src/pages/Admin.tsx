import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  api,
  type AdminTenant,
  type AdminUser,
  type CreateUserPayload,
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
