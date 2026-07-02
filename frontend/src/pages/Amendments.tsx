import { useEffect, useMemo, useState } from "react";
import { api, type AmendmentItem } from "../lib/api";

type Filter = "needs_review" | "active" | "all";

const ACTION_LABELS: Record<AmendmentItem["action"], string> = {
  replace: "החלפה",
  add_after: "הוספה אחרי",
  add_before: "הוספה לפני",
  delete: "מחיקה",
  clarify: "הבהרה",
};

export default function Amendments() {
  const [items, setItems] = useState<AmendmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("needs_review");
  const [editing, setEditing] = useState<Record<string, Partial<AmendmentItem>>>({});

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const needs = filter === "all" ? undefined : filter === "needs_review";
      setItems(await api.listAmendments(needs));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const counts = useMemo(() => {
    const total = items.length;
    const review = items.filter((i) => i.needs_review).length;
    return { total, review, active: total - review };
  }, [items]);

  const patch = (id: string, key: keyof AmendmentItem, value: string) => {
    setEditing((cur) => ({ ...cur, [id]: { ...(cur[id] ?? {}), [key]: value } }));
  };

  const save = async (item: AmendmentItem) => {
    const changes = editing[item.id];
    if (!changes || Object.keys(changes).length === 0) return;
    setBusyId(item.id);
    try {
      await api.updateAmendment(item.id, changes as Parameters<typeof api.updateAmendment>[1]);
      setEditing((cur) => {
        const { [item.id]: _, ...rest } = cur;
        return rest;
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const approve = async (item: AmendmentItem) => {
    setBusyId(item.id);
    try {
      const r = await api.approveAmendment(item.id);
      if (r.chunks_superseded > 0) {
        alert(`אושר — ${r.chunks_superseded} קטעים סומנו כמבוטלים`);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const reject = async (item: AmendmentItem) => {
    if (!confirm(`למחוק את התיקון לסעיף ${item.target_section}?`)) return;
    setBusyId(item.id);
    try {
      await api.rejectAmendment(item.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <header className="mb-10">
        <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
          היררכיה
        </div>
        <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
          תיקונים בין מסמכים
        </h1>
        <p className="text-ink-soft mt-4 text-sm max-w-2xl leading-relaxed">
          כל תיקון קושר סעיף במסמך יעד (למשל תקנון ראשי) לנוסח מעודכן במסמך מתקן
          (תקנון משנה או החלטה). תיקונים מאושרים משפיעים על מה שהמערכת מציגה
          כתשובה — סעיפים ישנים שהוחלפו נסננים מהחיפוש.
        </p>
      </header>

      <div className="flex items-center gap-2 mb-4 text-sm">
        {(["needs_review", "active", "all"] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1 rounded border ${
              filter === f
                ? "bg-ink text-surface border-ink"
                : "bg-white text-ink border-line hover:border-ink"
            }`}
          >
            {f === "needs_review" ? "ממתין לבדיקה" : f === "active" ? "פעיל" : "הכל"}
          </button>
        ))}
        <span className="text-ink-soft ml-auto">
          סה"כ {counts.total} · ממתין {counts.review} · פעיל {counts.active}
        </span>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-ink-soft">טוען…</div>
      ) : items.length === 0 ? (
        <div className="text-ink-soft py-8 text-center">
          {filter === "needs_review"
            ? "אין תיקונים שממתינים לבדיקה. יופי."
            : "אין תיקונים במאגר."}
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((it) => {
            const draft = editing[it.id] ?? {};
            const section = (draft.target_section ?? it.target_section) as string;
            const eff = (draft.effective_date ?? it.effective_date ?? "") as string;
            const newText = (draft.new_text ?? it.new_text ?? "") as string;
            const action = (draft.action ?? it.action) as AmendmentItem["action"];
            const dirty = Object.keys(draft).length > 0;
            return (
              <div
                key={it.id}
                className={`bg-white border rounded-md p-4 ${
                  it.needs_review ? "border-amber-400" : "border-line"
                }`}
              >
                <div className="flex items-start gap-3 mb-3">
                  <div className="flex-1">
                    <div className="text-sm text-ink font-semibold">
                      <span className="text-ink-soft">מתקן:</span> {it.amendment_doc_filename}
                    </div>
                    <div className="text-sm text-ink mt-1">
                      <span className="text-ink-soft">יעד:</span> {it.target_doc_filename}
                    </div>
                    <div className="text-xs text-ink-soft mt-2">
                      נוצר {new Date(it.created_at).toLocaleString("he-IL")} · מודל ביטחון{" "}
                      {it.extractor_confidence?.toFixed(2) ?? "?"}
                    </div>
                  </div>
                  <div className="flex flex-col gap-1 items-end shrink-0">
                    {it.needs_review ? (
                      <span className="text-xs bg-amber-100 text-amber-900 px-2 py-1 rounded">
                        ממתין לבדיקה
                      </span>
                    ) : (
                      <span className="text-xs bg-emerald-100 text-emerald-900 px-2 py-1 rounded">
                        פעיל
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                  <label className="text-xs text-ink-soft">
                    סעיף יעד
                    <input
                      dir="ltr"
                      value={section}
                      onChange={(e) => patch(it.id, "target_section", e.target.value)}
                      className="mt-1 w-full border border-line rounded px-2 py-1 text-ink text-sm"
                    />
                  </label>
                  <label className="text-xs text-ink-soft">
                    פעולה
                    <select
                      value={action}
                      onChange={(e) => patch(it.id, "action", e.target.value)}
                      className="mt-1 w-full border border-line rounded px-2 py-1 text-ink text-sm bg-white"
                    >
                      {Object.entries(ACTION_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-ink-soft">
                    תאריך תוקף
                    <input
                      dir="ltr"
                      type="date"
                      value={eff}
                      onChange={(e) => patch(it.id, "effective_date", e.target.value)}
                      className="mt-1 w-full border border-line rounded px-2 py-1 text-ink text-sm"
                    />
                  </label>
                </div>

                <label className="text-xs text-ink-soft block mb-3">
                  נוסח חדש
                  <textarea
                    value={newText}
                    onChange={(e) => patch(it.id, "new_text", e.target.value)}
                    rows={3}
                    className="mt-1 w-full border border-line rounded px-2 py-1 text-ink text-sm"
                  />
                </label>

                {it.evidence_span && (
                  <div className="text-xs text-ink-soft italic mb-3 border-r-2 border-line pr-2">
                    ציטוט מהמסמך המתקן: {it.evidence_span}
                  </div>
                )}

                <div className="flex gap-2 justify-end">
                  {dirty && (
                    <button
                      onClick={() => save(it)}
                      disabled={busyId === it.id}
                      className="text-xs px-3 py-1 rounded bg-ink text-surface hover:opacity-90"
                    >
                      שמור שינויים
                    </button>
                  )}
                  {it.needs_review && (
                    <button
                      onClick={() => approve(it)}
                      disabled={busyId === it.id || dirty}
                      className="text-xs px-3 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                      title={dirty ? "שמור שינויים לפני אישור" : ""}
                    >
                      אשר
                    </button>
                  )}
                  <button
                    onClick={() => reject(it)}
                    disabled={busyId === it.id}
                    className="text-xs px-3 py-1 rounded text-red-700 hover:bg-red-50"
                  >
                    מחק
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
