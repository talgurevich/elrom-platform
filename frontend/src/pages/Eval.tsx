import { useCallback, useEffect, useState } from "react";
import { api, type EvalSummary, type Golden, type GoldenInput } from "../lib/api";

function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 100)}%`;
}

function scoreColor(n: number | null): string {
  if (n === null) return "text-ink-soft";
  if (n >= 0.8) return "text-emerald-700";
  if (n >= 0.5) return "text-amber-700";
  return "text-red-700";
}

function NewGoldenForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<GoldenInput>({ question: "" });
  const [filenamesStr, setFilenamesStr] = useState("");
  const [keywordsStr, setKeywordsStr] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="px-4 py-2 bg-white border border-stone-300 hover:border-accent rounded-full text-sm font-semibold text-ink-soft hover:text-accent transition"
      >
        + הוסף שאלת זהב
      </button>
    );
  }

  const submit = async () => {
    if (!form.question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createGolden({
        question: form.question.trim(),
        expected_doc_filenames:
          filenamesStr.trim()
            ? filenamesStr.split("\n").map((s) => s.trim()).filter(Boolean)
            : undefined,
        expected_keywords:
          keywordsStr.trim()
            ? keywordsStr.split(",").map((s) => s.trim()).filter(Boolean)
            : undefined,
        expected_answer: form.expected_answer,
        notes: form.notes,
      });
      setForm({ question: "" });
      setFilenamesStr("");
      setKeywordsStr("");
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-5 bg-white border border-stone-200 rounded-xl shadow-soft space-y-3">
      <div>
        <label className="block text-xs font-semibold text-ink-soft mb-1">שאלה</label>
        <textarea
          value={form.question}
          onChange={(e) => setForm({ ...form, question: e.target.value })}
          rows={2}
          className="w-full px-3 py-2 border border-stone-300 rounded-lg text-sm focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-ink-soft mb-1">
          שמות קבצים שחייבים להופיע במקורות (אחד לשורה)
        </label>
        <textarea
          value={filenamesStr}
          onChange={(e) => setFilenamesStr(e.target.value)}
          rows={2}
          placeholder="תקנון קיבוץ אלרום 2009.pdf"
          className="w-full px-3 py-2 border border-stone-300 rounded-lg text-xs font-mono focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-ink-soft mb-1">
          מילות מפתח שחייבות להופיע בתשובה (מופרדות בפסיק)
        </label>
        <input
          type="text"
          value={keywordsStr}
          onChange={(e) => setKeywordsStr(e.target.value)}
          placeholder="קומה שנייה, רוב מיוחס"
          className="w-full px-3 py-2 border border-stone-300 rounded-lg text-sm focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-ink-soft mb-1">הערות</label>
        <input
          type="text"
          value={form.notes || ""}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
          className="w-full px-3 py-2 border border-stone-300 rounded-lg text-sm focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
        />
      </div>
      {error && (
        <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-red-900 text-sm">
          {error}
        </div>
      )}
      <div className="flex gap-2">
        <button
          onClick={submit}
          disabled={busy || !form.question.trim()}
          className="px-4 py-2 bg-brand-gradient text-white font-semibold rounded-full text-sm disabled:opacity-50"
        >
          {busy ? "שומר..." : "שמור"}
        </button>
        <button
          onClick={() => setOpen(false)}
          className="px-4 py-2 text-ink-soft hover:text-ink text-sm"
        >
          ביטול
        </button>
      </div>
    </div>
  );
}

export default function Eval() {
  const [goldens, setGoldens] = useState<Golden[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<EvalSummary | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setGoldens(await api.listGoldens());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const result = await api.runEval();
      setSummary(result);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const remove = async (id: string) => {
    if (!confirm("למחוק שאלת זהב?")) return;
    await api.deleteGolden(id);
    await load();
  };

  return (
    <>
      <header className="mb-8 flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-tight">הערכה (Eval)</h1>
          <p className="text-ink-soft mt-2 text-sm">
            מאגר שאלות זהב להרצה חוזרת. מודד דיוק שליפה וניסוח אחרי כל שינוי במערכת.
          </p>
        </div>
        <button
          onClick={run}
          disabled={running || goldens.length === 0}
          className="px-5 py-2.5 bg-brand-gradient text-white font-semibold rounded-full shadow-soft hover:shadow-lift disabled:opacity-50 transition"
        >
          {running ? "מריץ..." : `הרץ הערכה (${goldens.length})`}
        </button>
      </header>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-900 text-sm">
          {error}
        </div>
      )}

      {summary && (
        <div className="mb-8 p-5 bg-white border border-stone-200 rounded-xl shadow-soft animate-fade-up">
          <div className="text-xs tracking-wider uppercase text-accent font-bold mb-3">
            תוצאות אחרונות
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <div className="text-3xl font-bold text-ink">{pct(summary.avg_score)}</div>
              <div className="text-xs text-ink-soft">ציון כללי</div>
            </div>
            <div>
              <div className={`text-3xl font-bold ${scoreColor(summary.avg_retrieval)}`}>
                {pct(summary.avg_retrieval)}
              </div>
              <div className="text-xs text-ink-soft">שליפה</div>
            </div>
            <div>
              <div className={`text-3xl font-bold ${scoreColor(summary.avg_keyword)}`}>
                {pct(summary.avg_keyword)}
              </div>
              <div className="text-xs text-ink-soft">מילות מפתח</div>
            </div>
            <div>
              <div className="text-sm text-ink-soft flex flex-wrap gap-x-3 gap-y-1 pt-2">
                {Object.entries(summary.confidence_counts).map(([k, v]) => (
                  <span key={k}>
                    <span className="font-semibold text-ink">{v}</span> {k}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="mb-6">
        <NewGoldenForm onCreated={load} />
      </div>

      {loading ? (
        <div className="text-ink-soft text-sm animate-pulse">טוען...</div>
      ) : goldens.length === 0 ? (
        <div className="text-center py-12 text-ink-soft text-sm">
          אין שאלות זהב עדיין. הוסף את הראשונה למעלה, או לחץ "קבע כשאלת זהב" על תשובה בעמוד החיפוש.
        </div>
      ) : (
        <div className="space-y-3">
          {goldens.map((g) => (
            <div
              key={g.id}
              className="p-4 bg-white border border-stone-200 rounded-xl shadow-soft"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-base font-semibold text-ink">{g.question}</div>
                  {g.notes && (
                    <div className="text-xs text-ink-soft mt-1">{g.notes}</div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
                    {g.expected_doc_filenames && g.expected_doc_filenames.length > 0 && (
                      <span>
                        📄 {g.expected_doc_filenames.length} מסמכים נדרשים
                      </span>
                    )}
                    {g.expected_keywords && g.expected_keywords.length > 0 && (
                      <span>🔑 {g.expected_keywords.join(", ")}</span>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  {g.last_run_at ? (
                    <>
                      <div className={`text-2xl font-bold ${scoreColor(g.last_score)}`}>
                        {pct(g.last_score)}
                      </div>
                      <div className="text-[10px] text-ink-soft">
                        שליפה {pct(g.last_retrieval_score)} · מילים {pct(g.last_keyword_score)}
                      </div>
                      <div className="text-[10px] text-ink-soft">
                        {g.last_confidence}
                      </div>
                    </>
                  ) : (
                    <div className="text-xs text-ink-soft">לא הורץ</div>
                  )}
                  <button
                    onClick={() => remove(g.id)}
                    className="mt-2 text-[10px] text-red-600 hover:text-red-700"
                  >
                    מחק
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
