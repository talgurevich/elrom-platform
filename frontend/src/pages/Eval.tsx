import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Golden,
  type GoldenInput,
  type GoldenReport,
} from "../lib/api";

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
        className="px-4 py-2 bg-white border border-line-strong hover:border-accent rounded-full text-sm font-semibold text-ink-soft hover:text-accent transition"
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
    <div className="p-5 bg-white border border-line  space-y-3">
      <div>
        <label className="block text-xs font-semibold text-ink-soft mb-1">שאלה</label>
        <textarea
          value={form.question}
          onChange={(e) => setForm({ ...form, question: e.target.value })}
          rows={2}
          className="w-full px-3 py-2 border border-line-strong rounded-lg text-sm focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
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
          className="w-full px-3 py-2 border border-line-strong rounded-lg text-xs font-mono focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
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
          className="w-full px-3 py-2 border border-line-strong rounded-lg text-sm focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-ink-soft mb-1">הערות</label>
        <input
          type="text"
          value={form.notes || ""}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
          className="w-full px-3 py-2 border border-line-strong rounded-lg text-sm focus:border-accent focus:ring-2 focus:ring-accent/15 outline-none"
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
          className="px-4 py-2 bg-accent text-white font-semibold rounded-full text-sm disabled:opacity-50"
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

export default function Eval({ onRunInChat }: { onRunInChat?: () => void } = {}) {
  const [goldens, setGoldens] = useState<Golden[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<GoldenReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const loadReport = useCallback(async () => {
    setReportLoading(true);
    try {
      setReport(await api.goldenReport());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReportLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReport();
  }, [loadReport]);

  const gradeRun = async (queryId: string, feedback: "positive" | "negative") => {
    try {
      await api.feedback(queryId, feedback);
      await loadReport();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const runInChat = (g: Golden) => {
    // Write ?golden=&q= to the URL and switch to the search tab. Search.tsx
    // mounts, reads those params, auto-runs the question with golden_id, and
    // strips both params so a refresh doesn't re-fire.
    const url = new URL(window.location.href);
    url.searchParams.set("golden", g.id);
    url.searchParams.set("q", g.question);
    // Clear any lingering conversation id so the run starts fresh.
    url.searchParams.delete("c");
    window.history.replaceState({}, "", url.toString());
    onRunInChat?.();
  };

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

  const remove = async (id: string) => {
    if (!confirm("למחוק שאלת זהב?")) return;
    await api.deleteGolden(id);
    await load();
  };

  return (
    <>
      <header className="mb-10">
        <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
          הערכה
        </div>
        <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
          שאלות זהב
        </h1>
        <p className="text-ink-soft mt-4 text-sm max-w-xl leading-relaxed">
          מאגר שאלות מבחן. לחץ "▶ הרץ בצ'אט" על שאלה, סמן 👍/👎 על התשובה,
          ודוח הפסיקות למטה יתעדכן. כך מודדים איכות אחרי שינוי במערכת.
        </p>
      </header>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200  text-red-900 text-sm">
          {error}
        </div>
      )}


      <div className="mb-8 p-5 bg-white border border-line">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs tracking-wider uppercase text-accent font-bold">
            דוח פסיקות אנושי (👍/👎)
          </div>
          <button
            onClick={loadReport}
            disabled={reportLoading}
            className="text-[11px] text-ink-soft hover:text-accent underline underline-offset-4"
          >
            {reportLoading ? "טוען..." : "רענן"}
          </button>
        </div>
        {report === null ? (
          <div className="text-ink-soft text-sm">טוען דוח...</div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
              <div>
                <div className={`text-3xl font-bold ${scoreColor(report.overall_pass_rate)}`}>
                  {pct(report.overall_pass_rate)}
                </div>
                <div className="text-xs text-ink-soft">ציון פסיקה כולל</div>
              </div>
              <div>
                <div className="text-3xl font-bold text-ink">{report.total_runs}</div>
                <div className="text-xs text-ink-soft">
                  הרצות ({report.goldens_with_runs}/{report.total_goldens} שאלות)
                </div>
              </div>
              <div>
                <div className="text-3xl font-bold text-emerald-700">
                  {report.total_positive}
                </div>
                <div className="text-xs text-ink-soft">👍 נכון</div>
              </div>
              <div>
                <div className="text-3xl font-bold text-red-700">
                  {report.total_negative}
                </div>
                <div className="text-xs text-ink-soft">👎 שגוי</div>
              </div>
            </div>
            {report.rows.some((r) => r.total_runs > 0) && (
              <div className="border-t border-line pt-3">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-ink-soft text-right">
                      <th className="py-1 pl-2 font-semibold">שאלה</th>
                      <th className="py-1 font-semibold">הרצות</th>
                      <th className="py-1 font-semibold">👍</th>
                      <th className="py-1 font-semibold">👎</th>
                      <th className="py-1 font-semibold">ללא סימון</th>
                      <th className="py-1 pr-2 font-semibold">ציון</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows
                      .filter((r) => r.total_runs > 0)
                      .map((r) => (
                        <tr key={r.golden_id} className="border-t border-line/50">
                          <td className="py-2 pl-2 text-ink truncate max-w-md">
                            {r.question}
                          </td>
                          <td className="py-2 text-ink-soft">{r.total_runs}</td>
                          <td className="py-2 text-emerald-700 font-semibold">
                            {r.positive}
                          </td>
                          <td className="py-2 text-red-700 font-semibold">
                            {r.negative}
                          </td>
                          <td className="py-2 text-ink-soft">{r.unmarked}</td>
                          <td className={`py-2 pr-2 font-semibold ${scoreColor(r.pass_rate)}`}>
                            {pct(r.pass_rate)}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
            {report.total_runs === 0 && (
              <div className="text-xs text-ink-soft">
                עדיין לא רצו שאלות זהב בצ'אט. לחץ "▶ הרץ בצ'אט" על אחת מהשאלות למטה.
              </div>
            )}
          </>
        )}
      </div>

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
          {goldens.map((g) => {
            const reportRow = report?.rows.find((r) => r.golden_id === g.id);
            const needsGrading =
              reportRow?.latest_query_id &&
              reportRow?.last_feedback === null &&
              reportRow?.latest_answer;
            return (
            <div
              key={g.id}
              className="p-4 bg-white border border-line "
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
                  {needsGrading && reportRow && (
                    <div className="mt-3 p-3 border border-amber-300 bg-amber-50/60 rounded">
                      <div className="text-[10px] tracking-wider uppercase text-amber-800 font-bold mb-1">
                        הרצה אחרונה — ממתינה לפסיקה ({reportRow.latest_confidence})
                      </div>
                      <div className="text-xs text-ink whitespace-pre-wrap leading-relaxed max-h-32 overflow-y-auto">
                        {reportRow.latest_answer}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <button
                          onClick={() =>
                            reportRow.latest_query_id &&
                            gradeRun(reportRow.latest_query_id, "positive")
                          }
                          className="px-3 py-1 text-xs font-semibold border-2 border-ink bg-surface hover:bg-ink hover:text-surface transition"
                        >
                          👍 נכון
                        </button>
                        <button
                          onClick={() =>
                            reportRow.latest_query_id &&
                            gradeRun(reportRow.latest_query_id, "negative")
                          }
                          className="px-3 py-1 text-xs font-semibold border-2 border-accent text-accent bg-surface hover:bg-accent hover:text-surface transition"
                        >
                          👎 שגוי
                        </button>
                      </div>
                    </div>
                  )}
                </div>
                <div className="text-right shrink-0">
                  {(() => {
                    const row = report?.rows.find((r) => r.golden_id === g.id);
                    if (!row || row.total_runs === 0) {
                      return <div className="text-xs text-ink-soft">לא הורץ</div>;
                    }
                    return (
                      <>
                        <div className={`text-2xl font-bold ${scoreColor(row.pass_rate)}`}>
                          {pct(row.pass_rate)}
                        </div>
                        <div className="text-[10px] text-ink-soft">
                          👍 {row.positive} · 👎 {row.negative}
                          {row.unmarked > 0 ? ` · ${row.unmarked} ללא סימון` : ""}
                        </div>
                      </>
                    );
                  })()}
                  <button
                    onClick={() => runInChat(g)}
                    className="mt-2 block text-[11px] px-2 py-1 bg-accent/10 hover:bg-accent/20 text-accent font-semibold rounded"
                    title="הרץ בצ'אט ותאסוף 👍/👎 לדוח"
                  >
                    ▶ הרץ בצ'אט
                  </button>
                  <button
                    onClick={() => remove(g.id)}
                    className="mt-2 text-[10px] text-red-600 hover:text-red-700"
                  >
                    מחק
                  </button>
                </div>
              </div>
            </div>
            );
          })}
        </div>
      )}
    </>
  );
}
