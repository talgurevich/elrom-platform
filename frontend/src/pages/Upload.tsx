import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api,
  documentFileUrl,
  type ChunkPreview,
  type DocumentItem,
  type DocumentMetadataPatch,
  type UploadResponse,
} from "../lib/api";

type SortKey = "recent" | "alpha" | "chunks";
type GroupKey = "none" | "type" | "folder";

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
  const [folderFilter, setFolderFilter] = useState<string | null>(null);

  const filteredSortedDocs = useMemo(() => {
    const q = search.trim().toLowerCase();
    let out = docs.filter((d) => {
      if (typeFilter && (d.doc_type || "unclassified") !== typeFilter) return false;
      if (folderFilter && (d.folder || "__none__") !== folderFilter) return false;
      if (!q) return true;
      const hay = `${d.filename} ${d.summary || ""} ${d.folder || ""}`.toLowerCase();
      return hay.includes(q);
    });
    out = [...out].sort((a, b) => {
      if (sortKey === "alpha") return a.filename.localeCompare(b.filename, "he");
      if (sortKey === "chunks") return b.chunks - a.chunks;
      // "recent" — newest first; mirror the API default
      return new Date(b.ingested_at).getTime() - new Date(a.ingested_at).getTime();
    });
    return out;
  }, [docs, search, sortKey, typeFilter, folderFilter]);

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

  // Distinct folders across the corpus (for the filter-chip row).
  const folderCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of docs) {
      const k = d.folder || "__none__";
      m[k] = (m[k] || 0) + 1;
    }
    return m;
  }, [docs]);

  const folderList = useMemo(
    () =>
      Object.keys(folderCounts)
        .filter((k) => k !== "__none__")
        .sort((a, b) => a.localeCompare(b, "he")),
    [folderCounts]
  );

  // Group the (already-filtered+sorted) list by the chosen key.
  const groupedDocs = useMemo(() => {
    if (groupKey === "none") return null;
    const m: Record<string, DocumentItem[]> = {};
    const keyOf = (d: DocumentItem) =>
      groupKey === "type"
        ? d.doc_type || "unclassified"
        : d.folder || "__none__";
    for (const d of filteredSortedDocs) {
      const k = keyOf(d);
      (m[k] ||= []).push(d);
    }
    if (groupKey === "type") {
      return DOC_TYPE_ORDER.filter((k) => m[k]?.length).map((k) => ({
        key: k,
        label: DOC_TYPE_LABELS[k] || k,
        items: m[k],
      }));
    }
    // Folder grouping: alphabetical, with "ללא תיקייה" last.
    const folderKeys = Object.keys(m).sort((a, b) => {
      if (a === "__none__") return 1;
      if (b === "__none__") return -1;
      return a.localeCompare(b, "he");
    });
    return folderKeys.map((k) => ({
      key: k,
      label: k === "__none__" ? "ללא תיקייה" : k,
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

  // Drawer state — which document is open for browsing/metadata review.
  const [openDoc, setOpenDoc] = useState<DocumentItem | null>(null);
  // Kept fresh so patched metadata immediately reflects in the drawer + row.
  const refreshOpen = (patched: DocumentItem | null) => {
    setOpenDoc(patched);
    if (patched) {
      setDocs((ds) => ds.map((d) => (d.id === patched.id ? patched : d)));
    }
  };

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
                  <option value="folder">לפי תיקייה</option>
                </select>
              </label>
            </div>

            {/* Type filter chips — show only types that have at least one doc */}
            <div className="flex flex-wrap gap-px bg-line border-t border-line">
              <span className="px-3 py-1.5 text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold bg-surface flex items-center">
                סוג
              </span>
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

            {/* Folder filter chips — appear only once AI has assigned at least one folder */}
            {folderList.length > 0 && (
              <div className="flex flex-wrap gap-px bg-line border-t border-line">
                <span className="px-3 py-1.5 text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold bg-surface flex items-center">
                  תיקייה
                </span>
                <button
                  onClick={() => setFolderFilter(null)}
                  className={`px-3 py-1.5 text-xs flex items-baseline gap-2 ${
                    folderFilter === null
                      ? "bg-ink text-surface"
                      : "bg-surface hover:bg-line text-ink"
                  }`}
                >
                  <span>הכל</span>
                </button>
                {folderList.map((f) => (
                  <button
                    key={f}
                    onClick={() => setFolderFilter(folderFilter === f ? null : f)}
                    className={`px-3 py-1.5 text-xs flex items-baseline gap-2 ${
                      folderFilter === f
                        ? "bg-ink text-surface"
                        : "bg-surface hover:bg-line text-ink"
                    }`}
                  >
                    <span>{f}</span>
                    <span className="font-mono text-[10px] opacity-70">
                      {folderCounts[f]}
                    </span>
                  </button>
                ))}
                {folderCounts.__none__ && (
                  <button
                    onClick={() =>
                      setFolderFilter(folderFilter === "__none__" ? null : "__none__")
                    }
                    className={`px-3 py-1.5 text-xs flex items-baseline gap-2 italic ${
                      folderFilter === "__none__"
                        ? "bg-ink text-surface"
                        : "bg-surface hover:bg-line text-ink-soft"
                    }`}
                  >
                    <span>ללא תיקייה</span>
                    <span className="font-mono text-[10px] opacity-70">
                      {folderCounts.__none__}
                    </span>
                  </button>
                )}
              </div>
            )}
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
                    <DocumentRow
                      key={d.id}
                      doc={d}
                      onDelete={() => deleteDoc(d)}
                      onOpen={() => setOpenDoc(d)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredSortedDocs.map((d) => (
              <DocumentRow
                key={d.id}
                doc={d}
                onDelete={() => deleteDoc(d)}
                onOpen={() => setOpenDoc(d)}
              />
            ))}
          </div>
        )}
      </section>

      {openDoc && (
        <DocumentDrawer
          doc={openDoc}
          onClose={() => setOpenDoc(null)}
          onSaved={(patched) => refreshOpen(patched)}
        />
      )}
    </>
  );
}

function DocumentRow({
  doc,
  onDelete,
  onOpen,
}: {
  doc: DocumentItem;
  onDelete: () => void;
  onOpen: () => void;
}) {
  const needsReview = !!doc.ai_classified && !doc.metadata_reviewed;
  return (
    <div
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className="p-4 bg-surface border border-line hover:border-accent hover:bg-line/30 transition cursor-pointer"
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="font-semibold text-ink text-base">{doc.filename}</span>
            {doc.ai_classified && (
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-accent border border-accent px-1.5 py-0.5">
                AI
              </span>
            )}
            {needsReview && (
              <span
                className="text-[10px] tracking-[0.2em] uppercase font-bold text-amber-900 bg-amber-100 border border-amber-300 px-1.5 py-0.5"
                title="המערכת מילאה מטא־דאטה אוטומטית — כדאי לאשר"
              >
                בדיקה
              </span>
            )}
            {doc.doc_type && (
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-ink-soft border border-line-strong px-1.5 py-0.5">
                {DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}
              </span>
            )}
            {doc.folder && (
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold bg-ink text-surface px-1.5 py-0.5">
                {doc.folder}
              </span>
            )}
            {doc.effective_date && (
              <span
                className="text-[10px] font-mono text-ink-soft border border-line-strong px-1.5 py-0.5"
                title="תאריך תוקף"
              >
                {doc.effective_date}
              </span>
            )}
            {doc.has_file && (
              <a
                href={documentFileUrl(doc.id)}
                target="_blank"
                rel="noreferrer noopener"
                onClick={(e) => e.stopPropagation()}
                className="text-[10px] tracking-[0.2em] uppercase font-bold text-accent border border-accent px-1.5 py-0.5 hover:bg-accent hover:text-surface transition"
                title="פתח את קובץ המקור בכרטיסייה חדשה"
              >
                פתח מקור ↗
              </a>
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
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="text-xs px-3 py-1.5 text-ink-soft hover:text-accent hover:border-accent border border-transparent transition shrink-0"
        >
          מחק
        </button>
      </div>
    </div>
  );
}

type DrawerTab = "details" | "content";

function DocumentDrawer({
  doc,
  onClose,
  onSaved,
}: {
  doc: DocumentItem;
  onClose: () => void;
  onSaved: (patched: DocumentItem) => void;
}) {
  const [tab, setTab] = useState<DrawerTab>("details");
  const [chunks, setChunks] = useState<ChunkPreview[] | null>(null);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksErr, setChunksErr] = useState<string | null>(null);

  const [form, setForm] = useState<DocumentMetadataPatch>({
    doc_type: doc.doc_type || undefined,
    folder: doc.folder || undefined,
    effective_date: doc.effective_date || undefined,
    document_date: doc.document_date || undefined,
    meeting_number: doc.meeting_number || undefined,
    decision_number: doc.decision_number || undefined,
    bylaw_section_range: doc.bylaw_section_range || undefined,
    parties: doc.parties || undefined,
    summary: doc.summary || undefined,
  });
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [chunkQuery, setChunkQuery] = useState("");

  useEffect(() => {
    if (tab !== "content" || chunks !== null) return;
    setChunksLoading(true);
    setChunksErr(null);
    api
      .getDocumentChunks(doc.id)
      .then((rows) => setChunks(rows))
      .catch((err) =>
        setChunksErr(err instanceof Error ? err.message : String(err))
      )
      .finally(() => setChunksLoading(false));
  }, [tab, doc.id, chunks]);

  // Escape to close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const dtype = form.doc_type || doc.doc_type || "";
  const showMeeting = dtype === "minutes";
  const showDecision = dtype === "decision";
  const showBylawRange = dtype === "bylaw" || dtype === "sub_bylaw";
  const showParties = dtype === "other";

  const filteredChunks = useMemo(() => {
    if (!chunks || !chunkQuery.trim()) return chunks || [];
    const q = chunkQuery.trim();
    return chunks.filter(
      (c) =>
        (c.text || "").includes(q) ||
        (c.section_path || "").includes(q)
    );
  }, [chunks, chunkQuery]);

  const save = async () => {
    setSaving(true);
    setSaveErr(null);
    try {
      // Send only the fields that are non-empty; empty strings clear.
      const payload: DocumentMetadataPatch = {};
      const keys: (keyof DocumentMetadataPatch)[] = [
        "doc_type",
        "folder",
        "effective_date",
        "document_date",
        "meeting_number",
        "decision_number",
        "bylaw_section_range",
        "summary",
      ];
      for (const k of keys) {
        const v = form[k];
        if (typeof v === "string") payload[k] = v as never;
      }
      if (Array.isArray(form.parties)) payload.parties = form.parties;

      await api.updateDocumentMetadata(doc.id, payload);
      const patched: DocumentItem = {
        ...doc,
        doc_type: payload.doc_type ?? doc.doc_type,
        folder: payload.folder ?? doc.folder,
        effective_date: payload.effective_date ?? doc.effective_date,
        document_date: payload.document_date ?? doc.document_date,
        meeting_number: payload.meeting_number ?? doc.meeting_number,
        decision_number: payload.decision_number ?? doc.decision_number,
        bylaw_section_range:
          payload.bylaw_section_range ?? doc.bylaw_section_range,
        parties: payload.parties ?? doc.parties,
        summary: payload.summary ?? doc.summary,
        metadata_reviewed: true,
      };
      onSaved(patched);
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 bg-ink/40 z-40 animate-fade-up"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-label={`מסמך: ${doc.filename}`}
        className="fixed top-0 bottom-0 left-0 w-full max-w-[560px] bg-surface z-50 border-l border-ink flex flex-col animate-fade-up shadow-2xl"
      >
        <header className="border-b border-line px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-1">
              {DOC_TYPE_LABELS[doc.doc_type || "unclassified"]}
              {doc.folder && ` · ${doc.folder}`}
            </div>
            <div className="font-display font-black text-lg text-ink leading-tight truncate">
              {doc.has_file ? (
                <a
                  href={documentFileUrl(doc.id)}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="hover:text-accent"
                  title="פתח את קובץ המקור בכרטיסייה חדשה"
                >
                  {doc.filename} ↗
                </a>
              ) : (
                doc.filename
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-ink-soft hover:text-ink text-xl leading-none px-2"
            aria-label="סגור"
          >
            ×
          </button>
        </header>

        <div className="flex border-b border-line">
          <button
            onClick={() => setTab("details")}
            className={`flex-1 py-2.5 text-sm font-semibold ${
              tab === "details"
                ? "bg-ink text-surface"
                : "text-ink-soft hover:text-ink"
            }`}
          >
            פרטים
          </button>
          <button
            onClick={() => setTab("content")}
            className={`flex-1 py-2.5 text-sm font-semibold ${
              tab === "content"
                ? "bg-ink text-surface"
                : "text-ink-soft hover:text-ink"
            }`}
          >
            תוכן ({doc.chunks} קטעים)
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {tab === "details" ? (
            <div className="p-5 space-y-4 text-sm">
              {doc.ai_classified && !doc.metadata_reviewed && (
                <div className="p-3 bg-amber-50 border border-amber-200 text-amber-900 text-xs">
                  המערכת מילאה את השדות אוטומטית מקריאת המסמך. אנא ודא ותקן
                  לפני שמירה.
                </div>
              )}

              <Field label="סוג מסמך">
                <select
                  value={form.doc_type || ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, doc_type: e.target.value }))
                  }
                  className="w-full px-2 py-1.5 border border-line-strong bg-white"
                >
                  <option value="">—</option>
                  {docTypes.map((dt) => (
                    <option key={dt.value} value={dt.value}>
                      {dt.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="תיקייה">
                <input
                  type="text"
                  value={form.folder || ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, folder: e.target.value }))
                  }
                  placeholder="למשל: פנסיה, שיוך דירות"
                  className="w-full px-2 py-1.5 border border-line-strong bg-white"
                />
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="תאריך המסמך" hint="מופיע במסמך">
                  <input
                    type="date"
                    value={form.document_date || ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, document_date: e.target.value }))
                    }
                    className="w-full px-2 py-1.5 border border-line-strong bg-white"
                  />
                </Field>
                <Field label="תאריך תוקף" hint="נכנס לתוקף">
                  <input
                    type="date"
                    value={form.effective_date || ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, effective_date: e.target.value }))
                    }
                    className="w-full px-2 py-1.5 border border-line-strong bg-white"
                  />
                </Field>
              </div>

              {showMeeting && (
                <Field label="מספר ישיבה">
                  <input
                    type="text"
                    value={form.meeting_number || ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, meeting_number: e.target.value }))
                    }
                    placeholder="למשל: 234"
                    className="w-full px-2 py-1.5 border border-line-strong bg-white"
                  />
                </Field>
              )}
              {showDecision && (
                <Field label="מספר החלטה">
                  <input
                    type="text"
                    value={form.decision_number || ""}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        decision_number: e.target.value,
                      }))
                    }
                    placeholder="למשל: 47/22"
                    className="w-full px-2 py-1.5 border border-line-strong bg-white"
                  />
                </Field>
              )}
              {showBylawRange && (
                <Field label="טווח סעיפים">
                  <input
                    type="text"
                    value={form.bylaw_section_range || ""}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        bylaw_section_range: e.target.value,
                      }))
                    }
                    placeholder="למשל: סעיפים 12-18"
                    className="w-full px-2 py-1.5 border border-line-strong bg-white"
                  />
                </Field>
              )}
              {showParties && (
                <Field label="צדדים" hint="שורה לכל צד">
                  <textarea
                    value={(form.parties || []).join("\n")}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        parties: e.target.value
                          .split("\n")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      }))
                    }
                    rows={3}
                    className="w-full px-2 py-1.5 border border-line-strong bg-white font-mono text-xs"
                  />
                </Field>
              )}

              <Field label="תקציר">
                <textarea
                  value={form.summary || ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, summary: e.target.value }))
                  }
                  rows={3}
                  className="w-full px-2 py-1.5 border border-line-strong bg-white leading-relaxed"
                />
              </Field>

              {saveErr && (
                <div className="p-2 bg-red-50 border border-red-200 text-red-800 text-xs">
                  {saveErr}
                </div>
              )}

              <div className="flex gap-2 pt-2">
                <button
                  onClick={save}
                  disabled={saving}
                  className="px-4 py-2 bg-accent text-white text-sm font-semibold disabled:opacity-50"
                >
                  {saving ? "שומר..." : "שמור ואשר"}
                </button>
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-sm text-ink-soft hover:text-ink"
                >
                  ביטול
                </button>
                {doc.metadata_reviewed && (
                  <span className="mr-auto text-[10px] tracking-[0.2em] uppercase text-emerald-700 self-center">
                    ✓ אושר
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col h-full">
              <div className="p-3 border-b border-line bg-surface sticky top-0">
                <input
                  type="text"
                  placeholder="חיפוש בטקסט המסמך…"
                  value={chunkQuery}
                  onChange={(e) => setChunkQuery(e.target.value)}
                  className="w-full px-2 py-1.5 border border-line-strong bg-white text-sm"
                />
              </div>
              {chunksLoading ? (
                <div className="p-5 text-sm text-ink-soft">טוען קטעים...</div>
              ) : chunksErr ? (
                <div className="p-5 text-sm text-red-700">{chunksErr}</div>
              ) : filteredChunks.length === 0 ? (
                <div className="p-5 text-sm text-ink-soft">
                  {chunks && chunks.length === 0
                    ? "אין קטעים במסמך."
                    : "לא נמצא טקסט תואם."}
                </div>
              ) : (
                <div className="divide-y divide-line">
                  {filteredChunks.map((c) => (
                    <div key={c.position} className="p-4">
                      <div className="text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold mb-2 flex gap-3">
                        <span>#{c.position + 1}</span>
                        {c.section_path && <span>{c.section_path}</span>}
                        <span className="font-mono">{c.chars} תווים</span>
                      </div>
                      <div className="text-sm text-ink leading-relaxed whitespace-pre-wrap">
                        {c.text}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <div className="text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold mb-1 flex items-baseline gap-2">
        <span>{label}</span>
        {hint && (
          <span className="normal-case tracking-normal text-ink-soft/70 font-normal">
            {hint}
          </span>
        )}
      </div>
      {children}
    </label>
  );
}
