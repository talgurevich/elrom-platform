import { useEffect, useState } from "react";
import {
  api,
  type CorpusFlagItem,
  type DecisionResolutionItem,
  type GapItem,
} from "../lib/api";

type Section = "resolutions" | "flags" | "gaps";

const FORUM_LABELS: Record<string, string> = {
  ballot: "קלפי",
  assembly: "אסיפה",
  committee: "ועד הנהלה",
  sub_committee: "ועדת משנה",
};

const KIND_LABELS: Record<CorpusFlagItem["kind"], string> = {
  contradicts: "סתירה",
  supersedes: "החלפה בפועל",
  duplicates: "כפילות",
};

const KIND_STYLES: Record<CorpusFlagItem["kind"], string> = {
  contradicts: "bg-red-100 text-red-900",
  supersedes: "bg-amber-100 text-amber-900",
  duplicates: "bg-slate-100 text-slate-700",
};

function forumLabel(forum: string | null): string {
  return forum ? FORUM_LABELS[forum] ?? forum : "לא ידוע";
}

export default function Governance() {
  const [section, setSection] = useState<Section>("resolutions");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [resolutions, setResolutions] = useState<DecisionResolutionItem[]>([]);
  const [resFilter, setResFilter] = useState<"needs_review" | "active" | "all">(
    "needs_review",
  );
  const [flags, setFlags] = useState<CorpusFlagItem[]>([]);
  const [flagFilter, setFlagFilter] = useState<
    "pending" | "confirmed" | "dismissed" | "all"
  >("pending");
  const [gaps, setGaps] = useState<GapItem[]>([]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      if (section === "resolutions") {
        const needs = resFilter === "all" ? undefined : resFilter === "needs_review";
        setResolutions(await api.listResolutions(needs));
      } else if (section === "flags") {
        setFlags(await api.listCorpusFlags(flagFilter));
      } else {
        setGaps(await api.listDecisionGaps());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, resFilter, flagFilter]);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusyId(id);
    try {
      await fn();
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
          שרשראות החלטה וסתירות
        </h1>
        <p className="text-ink-soft mt-4 text-sm max-w-2xl leading-relaxed">
          שרשרת החלטה קושרת סעיף שהועבר לפורום גבוה (ועד ← אסיפה ← קלפי) אל
          ההכרעה הסופית. קישורים מאושרים גורמים למערכת לצטט את ההכרעה — לא את
          ההעברה. סתירות הן ממצאים שעלו בקליטת מסמך חדש מול המאגר הקיים, ופערים
          הם נושאים שהועברו להכרעה שלא נמצא לה תיעוד.
        </p>
      </header>

      <div className="flex items-center gap-2 mb-6 text-sm">
        {(
          [
            ["resolutions", "שרשראות החלטה"],
            ["flags", "סתירות וכפילויות"],
            ["gaps", "פערים — ממתין להכרעה"],
          ] as [Section, string][]
        ).map(([s, label]) => (
          <button
            key={s}
            onClick={() => setSection(s)}
            className={`px-3 py-1 rounded border ${
              section === s
                ? "bg-ink text-surface border-ink"
                : "bg-white text-ink border-line hover:border-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {section === "resolutions" && (
        <>
          <div className="flex items-center gap-2 mb-4 text-sm">
            {(["needs_review", "active", "all"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setResFilter(f)}
                className={`px-3 py-1 rounded border ${
                  resFilter === f
                    ? "bg-ink text-surface border-ink"
                    : "bg-white text-ink border-line hover:border-ink"
                }`}
              >
                {f === "needs_review" ? "ממתין לבדיקה" : f === "active" ? "פעיל" : "הכל"}
              </button>
            ))}
            <span className="text-ink-soft ml-auto">סה"כ {resolutions.length}</span>
          </div>
          {loading ? (
            <div className="text-ink-soft">טוען…</div>
          ) : resolutions.length === 0 ? (
            <div className="text-ink-soft py-8 text-center">
              {resFilter === "needs_review"
                ? "אין שרשראות שממתינות לבדיקה. יופי."
                : "אין שרשראות החלטה במאגר."}
            </div>
          ) : (
            <div className="space-y-3">
              {resolutions.map((it) => (
                <div
                  key={it.id}
                  className={`bg-white border rounded-md p-4 ${
                    it.needs_review ? "border-amber-400" : "border-line"
                  }`}
                >
                  <div className="flex items-start gap-3 mb-3">
                    <div className="flex-1">
                      {it.topic && (
                        <div className="text-sm text-ink font-semibold mb-1">{it.topic}</div>
                      )}
                      <div className="text-sm text-ink">
                        <span className="text-ink-soft">הועבר מ:</span>{" "}
                        {it.escalation_doc_filename}
                        {it.escalation_section ? ` (${it.escalation_section})` : ""}
                      </div>
                      <div className="text-sm text-ink mt-1">
                        <span className="text-ink-soft">הוכרע ב:</span>{" "}
                        {forumLabel(it.terminal_forum)} · {it.terminal_doc_filename}
                      </div>
                      <div className="text-xs text-ink-soft mt-2">
                        נוצר {new Date(it.created_at).toLocaleString("he-IL")} · מודל ביטחון{" "}
                        {it.extractor_confidence?.toFixed(2) ?? "?"}
                      </div>
                    </div>
                    <span
                      className={`text-xs px-2 py-1 rounded shrink-0 ${
                        it.needs_review
                          ? "bg-amber-100 text-amber-900"
                          : "bg-emerald-100 text-emerald-900"
                      }`}
                    >
                      {it.needs_review ? "ממתין לבדיקה" : "פעיל"}
                    </span>
                  </div>

                  {it.escalation_text && (
                    <div className="text-xs text-ink-soft mb-2 border-r-2 border-line pr-2">
                      <span className="font-semibold">ההעברה:</span> {it.escalation_text}
                    </div>
                  )}
                  {it.terminal_text && (
                    <div className="text-xs text-ink-soft mb-3 border-r-2 border-emerald-300 pr-2">
                      <span className="font-semibold">ההכרעה:</span> {it.terminal_text}
                    </div>
                  )}

                  <div className="flex gap-2 justify-end">
                    {it.needs_review && (
                      <button
                        onClick={() => act(it.id, () => api.approveResolution(it.id))}
                        disabled={busyId === it.id}
                        className="text-xs px-3 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                      >
                        אשר
                      </button>
                    )}
                    <button
                      onClick={() => {
                        if (confirm("למחוק את הקישור? הפריט יחזור לרשימת הפערים.")) {
                          void act(it.id, () => api.rejectResolution(it.id));
                        }
                      }}
                      disabled={busyId === it.id}
                      className="text-xs px-3 py-1 rounded text-red-700 hover:bg-red-50"
                    >
                      מחק
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {section === "flags" && (
        <>
          <div className="flex items-center gap-2 mb-4 text-sm">
            {(["pending", "confirmed", "dismissed", "all"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFlagFilter(f)}
                className={`px-3 py-1 rounded border ${
                  flagFilter === f
                    ? "bg-ink text-surface border-ink"
                    : "bg-white text-ink border-line hover:border-ink"
                }`}
              >
                {f === "pending"
                  ? "ממתין"
                  : f === "confirmed"
                    ? "אושר"
                    : f === "dismissed"
                      ? "נדחה"
                      : "הכל"}
              </button>
            ))}
            <span className="text-ink-soft ml-auto">סה"כ {flags.length}</span>
          </div>
          {loading ? (
            <div className="text-ink-soft">טוען…</div>
          ) : flags.length === 0 ? (
            <div className="text-ink-soft py-8 text-center">
              {flagFilter === "pending" ? "אין ממצאים שממתינים לבדיקה. יופי." : "אין ממצאים."}
            </div>
          ) : (
            <div className="space-y-3">
              {flags.map((f) => (
                <div
                  key={f.id}
                  className={`bg-white border rounded-md p-4 ${
                    f.status === "pending" && f.kind === "contradicts"
                      ? "border-red-400"
                      : f.status === "pending"
                        ? "border-amber-400"
                        : "border-line"
                  }`}
                >
                  <div className="flex items-start gap-3 mb-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`text-xs px-2 py-0.5 rounded ${KIND_STYLES[f.kind]}`}
                        >
                          {KIND_LABELS[f.kind]}
                        </span>
                        {f.topic && (
                          <span className="text-sm text-ink font-semibold">{f.topic}</span>
                        )}
                      </div>
                      <div className="text-sm text-ink">
                        <span className="text-ink-soft">מסמך חדש:</span> {f.new_doc_filename}
                        {f.new_section ? ` (${f.new_section})` : ""}
                      </div>
                      <div className="text-sm text-ink mt-1">
                        <span className="text-ink-soft">מול קיים:</span>{" "}
                        {f.existing_doc_filename}
                        {f.existing_section ? ` (${f.existing_section})` : ""}
                      </div>
                      <div className="text-xs text-ink-soft mt-2">
                        נוצר {new Date(f.created_at).toLocaleString("he-IL")} · מודל ביטחון{" "}
                        {f.confidence?.toFixed(2) ?? "?"}
                      </div>
                    </div>
                  </div>

                  {f.explanation && (
                    <div className="text-sm text-ink mb-2">{f.explanation}</div>
                  )}
                  {f.evidence_new && (
                    <div className="text-xs text-ink-soft mb-1 border-r-2 border-line pr-2">
                      <span className="font-semibold">מהחדש:</span> {f.evidence_new}
                    </div>
                  )}
                  {f.evidence_existing && (
                    <div className="text-xs text-ink-soft mb-3 border-r-2 border-line pr-2">
                      <span className="font-semibold">מהקיים:</span> {f.evidence_existing}
                    </div>
                  )}

                  {f.status === "pending" ? (
                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={() => act(f.id, () => api.confirmCorpusFlag(f.id))}
                        disabled={busyId === f.id}
                        className="text-xs px-3 py-1 rounded bg-ink text-surface hover:opacity-90 disabled:opacity-50"
                      >
                        אשר ממצא
                      </button>
                      <button
                        onClick={() => act(f.id, () => api.dismissCorpusFlag(f.id))}
                        disabled={busyId === f.id}
                        className="text-xs px-3 py-1 rounded text-ink-soft hover:bg-slate-50"
                      >
                        דחה
                      </button>
                    </div>
                  ) : (
                    <div className="text-xs text-ink-soft text-left">
                      {f.status === "confirmed" ? "אושר" : "נדחה"}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {section === "gaps" && (
        <>
          {loading ? (
            <div className="text-ink-soft">טוען…</div>
          ) : gaps.length === 0 ? (
            <div className="text-ink-soft py-8 text-center">
              אין נושאים פתוחים — לכל ההעברות נמצאה הכרעה. יופי.
            </div>
          ) : (
            <>
              <p className="text-sm text-ink-soft mb-4">
                {gaps.length} נושאים הועברו להכרעה בפורום גבוה יותר ולא נמצא להם תיעוד
                של ההחלטה. ייתכן שהמסמך המכריע (פרוטוקול אסיפה / תוצאת קלפי) טרם
                הועלה למאגר — או שהנושא באמת עדיין פתוח.
              </p>
              <div className="space-y-3">
                {gaps.map((g) => (
                  <div key={g.chunk_id} className="bg-white border border-line rounded-md p-4">
                    <div className="text-sm text-ink font-semibold">
                      {g.doc_filename}
                      {g.section_path ? ` · ${g.section_path}` : ""}
                    </div>
                    <div className="text-xs text-ink-soft mt-1">
                      {forumLabel(g.forum)}
                      {g.effective_date ? ` · ${g.effective_date}` : ""}
                    </div>
                    <div className="text-sm text-ink-soft mt-2 leading-relaxed">{g.text}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
