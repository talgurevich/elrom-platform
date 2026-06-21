import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type DocumentItem, type UploadResponse } from "../lib/api";

type SortKey = "recent" | "alpha" | "chunks";
type GroupKey = "none" | "type";

const DOC_TYPE_LABELS: Record<string, string> = {
  bylaw: "תקנון",
  sub_bylaw: "תקנון משנה",
  minutes: "פרוטוקול",
  decision: "החלטה",
  other: "אחר",
  unclassified: "ללא סיווג",
};

const DOC_TYPE_ORDER = ["bylaw", "sub_bylaw", "decision", "minutes", "other", "unclassified"];

type FileStatus =
  | { kind: "queued" }
  | { kind: "uploading" }
  | { kind: "done"; result: UploadResponse }
  | { kind: "error"; message: string };

type Queued = {
  id: string;
  file: File;
  docType: string;
  status: FileStatus;
};

const docTypes = [
  { value: "bylaw", label: "תקנון" },
  { value: "sub_bylaw", label: "תקנון משנה" },
  { value: "minutes", label: "פרוטוקול" },
  { value: "decision", label: "החלטה" },
  { value: "other", label: "אחר" },
];

const SUPPORTED = [".pdf", ".docx", ".txt", ".md"];

function formatChars(n: number) {
  if (n < 1000) return `${n} תווים`;
  return `${(n / 1000).toFixed(1)}K תווים`;
}

function QualityBadge({ doc }: { doc: DocumentItem }) {
  const q = doc.quality ?? "unknown";
  if (q === "ok") {
    const density =
      doc.pages && doc.chars_extracted ? Math.round(doc.chars_extracted / doc.pages) : null;
    return (
      <span
        className="text-[10px] px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded-full"
        title={density ? `${density} תווים לעמוד` : "ingest תקין"}
      >
        ✓ תקין
      </span>
    );
  }
  if (q === "partial") {
    return (
      <span
        className="text-[10px] px-2 py-0.5 bg-amber-50 text-amber-800 rounded-full"
        title={doc.extraction_note || "OCR חלקי"}
      >
        ⚠ חלקי
      </span>
    );
  }
  if (q === "low_density") {
    const density =
      doc.pages && doc.chars_extracted ? Math.round(doc.chars_extracted / doc.pages) : null;
    return (
      <span
        className="text-[10px] px-2 py-0.5 bg-red-50 text-red-700 rounded-full"
        title={density ? `רק ${density} תווים לעמוד — חשד ל-OCR שנכשל` : "טקסט דליל מדי"}
      >
        ⚠ דליל
      </span>
    );
  }
  if (q === "suspect") {
    return (
      <span className="text-[10px] px-2 py-0.5 bg-red-50 text-red-700 rounded-full">
        ⚠ ללא קטעים
      </span>
    );
  }
  return (
    <span
      className="text-[10px] px-2 py-0.5 bg-line text-ink-soft rounded-full"
      title="המסמך הוטען לפני שהמערכת תיעדה מדדי איכות"
    >
      ? ישן
    </span>
  );
}

export default function Upload() {
  const [queue, setQueue] = useState<Queued[]>([]);
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [defaultDocType, setDefaultDocType] = useState("bylaw");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocs = useCallback(async () => {
    setLoadingDocs(true);
    setError(null);
    try {
      setDocs(await api.listDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const next: Queued[] = [];
      for (const f of Array.from(files)) {
        const ext = "." + (f.name.split(".").pop() || "").toLowerCase();
        if (!SUPPORTED.includes(ext)) {
          setError(`סוג קובץ לא נתמך: ${f.name}. נתמכים: ${SUPPORTED.join(", ")}`);
          continue;
        }
        next.push({
          id: `${f.name}-${Date.now()}-${Math.random()}`,
          file: f,
          docType: defaultDocType,
          status: { kind: "queued" },
        });
      }
      if (next.length) setQueue((q) => [...q, ...next]);
    },
    [defaultDocType]
  );

  const upload = async (entry: Queued) => {
    setQueue((q) =>
      q.map((e) => (e.id === entry.id ? { ...e, status: { kind: "uploading" } } : e))
    );
    try {
      const result = await api.uploadDocument(entry.file, entry.docType);
      setQueue((q) =>
        q.map((e) => (e.id === entry.id ? { ...e, status: { kind: "done", result } } : e))
      );
      loadDocs();
    } catch (err) {
      setQueue((q) =>
        q.map((e) =>
          e.id === entry.id
            ? {
                ...e,
                status: { kind: "error", message: err instanceof Error ? err.message : String(err) },
              }
            : e
        )
      );
    }
  };

  const uploadAll = async () => {
    for (const entry of queue) {
      if (entry.status.kind === "queued") {
        // eslint-disable-next-line no-await-in-loop
        await upload(entry);
      }
    }
  };

  const removeFromQueue = (id: string) => setQueue((q) => q.filter((e) => e.id !== id));
  const clearDone = () => setQueue((q) => q.filter((e) => e.status.kind !== "done"));

  const deleteDoc = async (doc: DocumentItem) => {
    if (!confirm(`למחוק את "${doc.filename}" ואת כל ${doc.chunks} הקטעים שלו?`)) return;
    try {
      await api.deleteDocument(doc.id);
      loadDocs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const deleteAllDocs = async () => {
    const n = docs.length;
    if (n === 0) return;
    const msg =
      `למחוק את כל ${n} המסמכים ואת כל הקטעים שלהם?\n\n` +
      `הפעולה אינה הפיכה. שאלות שכבר נשאלו יישארו, אך הקטעים שאליהם הן הפנו ייעלמו.`;
    if (!confirm(msg)) return;
    if (!confirm(`אישור אחרון: למחוק את כל ${n} המסמכים?`)) return;
    try {
      const r = await api.deleteAllDocuments();
      setClassifyMsg(`נמחקו ${r.documents_deleted} מסמכים ו-${r.chunks_deleted} קטעים.`);
      await loadDocs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const [classifying, setClassifying] = useState(false);
  const [classifyMsg, setClassifyMsg] = useState<string | null>(null);

  // Library controls — sort, group, filter. All client-side over the
  // already-loaded docs array; the API doesn't need to know.
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const [groupKey, setGroupKey] = useState<GroupKey>("none");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  const filteredSortedDocs = useMemo(() => {
    const q = search.trim().toLowerCase();
    let out = docs.filter((d) => {
      if (typeFilter && (d.doc_type || "unclassified") !== typeFilter) return false;
      if (!q) return true;
      const hay = `${d.filename} ${d.summary || ""}`.toLowerCase();
      return hay.includes(q);
    });
    out = [...out].sort((a, b) => {
      if (sortKey === "alpha") return a.filename.localeCompare(b.filename, "he");
      if (sortKey === "chunks") return b.chunks - a.chunks;
      // "recent" — newest first; mirror the API default
      return new Date(b.ingested_at).getTime() - new Date(a.ingested_at).getTime();
    });
    return out;
  }, [docs, search, sortKey, typeFilter]);

  // Counts per type, computed over the *unfiltered* set so the chips show the
  // total even when one is selected.
  const typeCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of docs) {
      const k = d.doc_type || "unclassified";
      m[k] = (m[k] || 0) + 1;
    }
    return m;
  }, [docs]);

  // Group the (already-filtered+sorted) list by doc_type when requested.
  const groupedDocs = useMemo(() => {
    if (groupKey === "none") return null;
    const m: Record<string, DocumentItem[]> = {};
    for (const d of filteredSortedDocs) {
      const k = d.doc_type || "unclassified";
      (m[k] ||= []).push(d);
    }
    return DOC_TYPE_ORDER.filter((k) => m[k]?.length).map((k) => ({
      key: k,
      label: DOC_TYPE_LABELS[k] || k,
      items: m[k],
    }));
  }, [filteredSortedDocs, groupKey]);

  const classify = async (force = false) => {
    setClassifying(true);
    setClassifyMsg(null);
    setError(null);
    try {
      const r = await api.classifyDocuments(force);
      setClassifyMsg(`סווגו ${r.classified} מסמכים מתוך ${r.total}. ${r.skipped} דולגו.`);
      await loadDocs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setClassifying(false);
    }
  };

  const queuedCount = queue.filter((e) => e.status.kind === "queued").length;

  return (
    <>
      <header className="mb-10">
        <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
          מסמכים
        </div>
        <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
          העלאה וניהול
        </h1>
        <p className="text-ink-soft mt-4 text-sm max-w-xl leading-relaxed">
          תקנונים, פרוטוקולים, החלטות. נתמך: PDF, Word, טקסט. סריקות PDF
          עוברות OCR אוטומטי, ומסמכים מסווגים אוטומטית עם כותרת בעברית.
        </p>
      </header>

      {/* Dropzone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
        }}
        onClick={() => fileInputRef.current?.click()}
        className={`mb-4 border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          dragOver
            ? "border-accent bg-accent/10"
            : "border-line-strong bg-white hover:border-accent/50 hover:bg-line"
        }`}
      >
        <input
          type="file"
          ref={fileInputRef}
          multiple
          accept={SUPPORTED.join(",")}
          onChange={(e) => {
            if (e.target.files?.length) addFiles(e.target.files);
            e.target.value = "";
          }}
          className="hidden"
        />
        <div className="text-ink-soft text-sm">
          גרור קבצים לכאן, או לחץ כדי לבחור
        </div>
        <div className="text-xs text-ink-soft mt-1">PDF · Word · טקסט</div>
      </div>

      <div className="mb-6 flex items-center gap-3 text-sm">
        <label className="text-ink-soft">סוג מסמך (ברירת מחדל):</label>
        <select
          value={defaultDocType}
          onChange={(e) => setDefaultDocType(e.target.value)}
          className="px-2 py-1 border border-line-strong rounded"
        >
          {docTypes.map((dt) => (
            <option key={dt.value} value={dt.value}>
              {dt.label}
            </option>
          ))}
        </select>
        {queuedCount > 0 && (
          <button
            onClick={uploadAll}
            className="mr-auto px-3 py-1.5 bg-accent text-white rounded"
          >
            העלה את כל {queuedCount} הקבצים
          </button>
        )}
        {queue.some((e) => e.status.kind === "done") && (
          <button
            onClick={clearDone}
            className="px-3 py-1.5 bg-line hover:bg-stone-200 rounded"
          >
            נקה גמורים
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {/* Queue */}
      {queue.length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-bold text-accent uppercase tracking-wider mb-2">תור</h2>
          <div className="space-y-2">
            {queue.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center gap-3 p-3 bg-white border border-line rounded text-sm"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-ink truncate">{entry.file.name}</div>
                  <div className="text-xs text-ink-soft">
                    {(entry.file.size / 1024).toFixed(1)} KB
                  </div>
                  {entry.status.kind === "error" && (
                    <div className="text-xs text-red-700 mt-1">{entry.status.message}</div>
                  )}
                  {entry.status.kind === "done" && (
                    <div
                      className={`text-xs mt-1 ${
                        entry.status.result.partial
                          ? "text-amber-700"
                          : "text-emerald-700"
                      }`}
                    >
                      {entry.status.result.partial ? "⚠" : "✓"}{" "}
                      {entry.status.result.chunks_created} קטעים
                      {entry.status.result.pages != null &&
                        ` · ${entry.status.result.pages} עמ׳`}
                      {entry.status.result.chars_extracted != null &&
                        entry.status.result.pages
                          ? ` · ${Math.round(
                              entry.status.result.chars_extracted /
                                entry.status.result.pages
                            )} תווים/עמ׳`
                          : ""}
                      {entry.status.result.used_ocr && " · OCR"}
                      {entry.status.result.note && ` · ${entry.status.result.note}`}
                    </div>
                  )}
                </div>
                <select
                  value={entry.docType}
                  onChange={(e) =>
                    setQueue((q) =>
                      q.map((x) => (x.id === entry.id ? { ...x, docType: e.target.value } : x))
                    )
                  }
                  disabled={entry.status.kind !== "queued"}
                  className="px-2 py-1 border border-line-strong rounded text-xs"
                >
                  {docTypes.map((dt) => (
                    <option key={dt.value} value={dt.value}>
                      {dt.label}
                    </option>
                  ))}
                </select>
                <div className="w-32 text-left">
                  {entry.status.kind === "queued" && (
                    <button
                      onClick={() => upload(entry)}
                      className="px-3 py-1 bg-accent text-white rounded text-xs"
                    >
                      העלה
                    </button>
                  )}
                  {entry.status.kind === "uploading" && (
                    <span className="text-xs text-ink-soft">מעלה...</span>
                  )}
                  {(entry.status.kind === "done" || entry.status.kind === "error") && (
                    <button
                      onClick={() => removeFromQueue(entry.id)}
                      className="text-xs text-ink-soft hover:text-red-700"
                    >
                      הסר
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Existing documents */}
      <section>
        <div className="text-[11px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-4 flex items-center gap-3">
          <span>מסמכים במאגר</span>
          {docs.length > 0 && (
            <span className="font-mono text-ink-soft normal-case tracking-normal">
              ({docs.length})
            </span>
          )}
          <span className="flex-1 h-px bg-line" />
          {docs.length > 0 && (
            <div className="flex gap-1 normal-case tracking-normal">
              <button
                onClick={() => classify(false)}
                disabled={classifying}
                className="px-3 py-1.5 border border-line-strong hover:border-accent text-xs text-ink-soft hover:text-accent transition disabled:opacity-50"
                title="קרא את תוכן כל מסמך עם Claude, תן לו כותרת ותקציר"
              >
                {classifying ? "מסווג..." : "סווג חדשים"}
              </button>
              <button
                onClick={() => classify(true)}
                disabled={classifying}
                className="px-3 py-1.5 text-xs text-ink-soft hover:text-ink disabled:opacity-50"
                title="סווג מחדש את כל המסמכים, כולל כאלה שכבר סווגו"
              >
                סווג הכל מחדש
              </button>
              <button
                onClick={deleteAllDocs}
                className="px-3 py-1.5 text-xs text-accent hover:bg-surface border border-transparent hover:border-accent transition"
                title="מחיקת כל המסמכים מהמאגר"
              >
                מחק הכל
              </button>
            </div>
          )}
        </div>

        {classifyMsg && (
          <div className="mb-4 px-4 py-3 bg-surface border-r-4 border-accent text-sm text-ink">
            {classifyMsg}
          </div>
        )}

        {/* Library toolbar — search + sort + group + type filter */}
        {docs.length > 0 && (
          <div className="mb-5 border border-line bg-surface">
            <div className="flex items-stretch flex-wrap">
              <input
                type="text"
                placeholder="חיפוש בשם או בתקציר…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="flex-1 min-w-[200px] px-4 py-2.5 bg-transparent text-sm placeholder:text-ink-soft outline-none border-l border-line"
              />
              <label className="flex items-center px-3 border-l border-line text-xs text-ink-soft">
                <span className="ml-2">מיון:</span>
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                  className="bg-transparent py-2.5 text-sm text-ink outline-none cursor-pointer"
                >
                  <option value="recent">אחרון שעודכן</option>
                  <option value="alpha">א–ת</option>
                  <option value="chunks">מספר קטעים</option>
                </select>
              </label>
              <label className="flex items-center px-3 text-xs text-ink-soft">
                <span className="ml-2">קיבוץ:</span>
                <select
                  value={groupKey}
                  onChange={(e) => setGroupKey(e.target.value as GroupKey)}
                  className="bg-transparent py-2.5 text-sm text-ink outline-none cursor-pointer"
                >
                  <option value="none">ללא</option>
                  <option value="type">לפי סוג מסמך</option>
                </select>
              </label>
            </div>

            {/* Type filter chips — show only types that have at least one doc */}
            <div className="flex flex-wrap gap-px bg-line border-t border-line">
              <button
                onClick={() => setTypeFilter(null)}
                className={`px-3 py-1.5 text-xs flex items-baseline gap-2 ${
                  typeFilter === null
                    ? "bg-ink text-surface"
                    : "bg-surface hover:bg-line text-ink"
                }`}
              >
                <span>הכל</span>
                <span className="font-mono text-[10px] opacity-70">{docs.length}</span>
              </button>
              {DOC_TYPE_ORDER.filter((k) => typeCounts[k]).map((k) => (
                <button
                  key={k}
                  onClick={() => setTypeFilter(typeFilter === k ? null : k)}
                  className={`px-3 py-1.5 text-xs flex items-baseline gap-2 ${
                    typeFilter === k
                      ? "bg-ink text-surface"
                      : "bg-surface hover:bg-line text-ink"
                  }`}
                >
                  <span>{DOC_TYPE_LABELS[k]}</span>
                  <span className="font-mono text-[10px] opacity-70">
                    {typeCounts[k]}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {loadingDocs ? (
          <div className="text-ink-soft text-sm">טוען...</div>
        ) : docs.length === 0 ? (
          <div className="border border-line p-12 text-center text-sm text-ink-soft">
            אין מסמכים. העלה את הראשון.
          </div>
        ) : filteredSortedDocs.length === 0 ? (
          <div className="border border-line p-12 text-center text-sm text-ink-soft">
            לא נמצאו מסמכים תואמים. נסה לאפס את הפילטר.
          </div>
        ) : groupedDocs ? (
          <div className="space-y-8">
            {groupedDocs.map((g) => (
              <div key={g.key}>
                <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3 flex items-baseline gap-3">
                  <span>{g.label}</span>
                  <span className="font-mono text-ink-soft text-[10px] normal-case tracking-normal">
                    {g.items.length}
                  </span>
                  <span className="flex-1 h-px bg-line" />
                </div>
                <div className="space-y-2">
                  {g.items.map((d) => (
                    <DocumentRow key={d.id} doc={d} onDelete={() => deleteDoc(d)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredSortedDocs.map((d) => (
              <DocumentRow key={d.id} doc={d} onDelete={() => deleteDoc(d)} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function DocumentRow({
  doc,
  onDelete,
}: {
  doc: DocumentItem;
  onDelete: () => void;
}) {
  return (
    <div className="p-4 bg-surface border border-line">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="font-semibold text-ink text-base">{doc.filename}</span>
            {doc.ai_classified && (
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-accent border border-accent px-1.5 py-0.5">
                AI
              </span>
            )}
            {doc.doc_type && (
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-ink-soft border border-line-strong px-1.5 py-0.5">
                {DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}
              </span>
            )}
          </div>
          {doc.summary && (
            <div className="text-sm text-ink-soft mt-1.5 leading-relaxed">
              {doc.summary}
            </div>
          )}
          <div className="text-xs text-ink-soft mt-2 flex gap-3 flex-wrap items-center">
            <QualityBadge doc={doc} />
            <span>{doc.chunks} קטעים</span>
            <span>{formatChars(doc.chars)}</span>
            {doc.pages != null && <span>{doc.pages} עמודים</span>}
            {doc.extractor && (
              <span title="מנוע חילוץ הטקסט">
                {doc.extractor === "azure_ocr"
                  ? "OCR"
                  : doc.extractor === "pdfplumber"
                  ? "PDF native"
                  : doc.extractor}
              </span>
            )}
            <span>{new Date(doc.ingested_at).toLocaleString("he-IL")}</span>
          </div>
          {doc.extraction_note && (
            <div className="text-xs text-amber-700 mt-1">⚠ {doc.extraction_note}</div>
          )}
        </div>
        <button
          onClick={onDelete}
          className="text-xs px-3 py-1.5 text-ink-soft hover:text-accent hover:border-accent border border-transparent transition shrink-0"
        >
          מחק
        </button>
      </div>
    </div>
  );
}
