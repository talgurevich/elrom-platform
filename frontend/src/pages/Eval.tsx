import { useCallback, useEffect, useState } from "react";
import {
  api,
  type EvalRunResult,
  type EvalSummary,
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
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [runProgress, setRunProgress] = useState<{ done: number; total: number } | null>(null);
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

  const run = async () => {
    setRunning(true);
    setError(null);
    setSummary(null);
    // Per-golden loop: the batch /run endpoint dies on Render's proxy
    // timeout once you have ~10+ goldens (each does embed + retrieve + LLM).
    // Iterating client-side keeps each request short and gives real progress.
    const results: EvalRunResult[] = [];
    setRunProgress({ done: 0, total: goldens.length });
    try {
      for (let i = 0; i < goldens.length; i++) {
        const g = goldens[i];
        try {
          const r = await api.runSingleGolden(g.id);
          results.push(r);
        } catch (err) {
          setError(
            `נכשל בשאלה "${g.question.slice(0, 60)}...": ${
              err instanceof Error ? err.message : String(err)
            }. הפעלה נעצרת.`
          );
          break;
        }
        setRunProgress({ done: i + 1, total: goldens.length });
      }

      if (results.length > 0) {
        // Aggregate exactly like the backend batch endpoint used to.
        const avg_score = results.reduce((a, r) => a + r.score, 0) / results.length;
        const retScores = results
          .map((r) => r.retrieval_score)
          .filter((s): s is number => s !== null);
        const kwScores = results
          .map((r) => r.keyword_score)
          .filter((s): s is number => s !== null);
        const confCounts: Record<string, number> = {};
        for (const r of results) {
          confCounts[r.confidence] = (confCounts[r.confidence] || 0) + 1;
        }
        setSummary({
          total: results.length,
          avg_score,
          avg_retrieval: retScores.length
            ? retScores.reduce((a, b) => a + b, 0) / retScores.length
            : null,
          avg_keyword: kwScores.length
            ? kwScores.reduce((a, b) => a + b, 0) / kwScores.length
            : null,
          confidence_counts: confCounts,
          results,
        });
      }
      await load();
      await loadReport();
    } finally {
      setRunning(false);
      setRunProgress(null);
    }
  };

  const remove = async (id: string) => {
    if (!confirm("למחוק שאלת זהב?")) return;
    await api.deleteGolden(id);
    await load();
  };

  return (
    <>
      <header className="mb-10 flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
            הערכה
          </div>
          <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
            שאלות זהב
          </h1>
          <p className="text-ink-soft mt-4 text-sm max-w-xl leading-relaxed">
            מאגר שאלות מבחן להרצה חוזרת. מודד דיוק שליפה וניסוח אחרי כל
            שינוי במערכת.
          </p>
        </div>
        <button
          onClick={run}
          disabled={running || goldens.length === 0}
          className="px-6 py-3 bg-accent hover:bg-accent-dark text-surface font-bold tracking-wide disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {running
            ? runProgress
              ? `מריץ ${runProgress.done}/${runProgress.total}...`
              : "מריץ..."
            : `הרץ הערכה (${goldens.length})`}
        </button>
      </header>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200  text-red-900 text-sm">
          {error}
        </div>
      )}

      {summary && (
        <div className="mb-8 p-5 bg-white border border-line  animate-fade-up">
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
          {goldens.map((g) => (
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
          ))}
        </div>
      )}
    </>
  );
}
