import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api,
  documentFileUrl,
  type ChunkPreview,
  type DocumentItem,
  type DocumentMetadataPatch,
  type DuplicateGroup,
  type IngestJobStatus,
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

// Lifecycle maturity — how binding the doc is. Non-adopted docs are
// demoted at retrieval and never cited as the operative rule.
const DOC_STATUS_LABELS: Record<string, string> = {
  adopted: "בתוקף",
  proposal: "הצעה",
  draft: "טיוטה",
  discussion: "דיון",
  background: "רקע",
  invitation: "הזמנה",
};

type FileStatus =
  | { kind: "queued" }
  | { kind: "uploading" }
  | { kind: "processing"; stage: string | null }
  | { kind: "done"; chunks: number | null }
  | { kind: "error"; message: string };

const STAGE_LABELS: Record<string, string> = {
  extracting: "מחלץ טקסט…",
  chunking: "מפרק לקטעים…",
  embedding: "מחשב הטמעות…",
  finalizing: "מסיים…",
};

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

  const [duplicates, setDuplicates] = useState<DuplicateGroup[]>([]);
  const [dedupSelection, setDedupSelection] = useState<Set<string>>(new Set());
  const [dedupBusy, setDedupBusy] = useState(false);
  const [dedupCollapsed, setDedupCollapsed] = useState(false);

  const loadDocs = useCallback(async () => {
    setLoadingDocs(true);
    setError(null);
    try {
      const [docs, dupes] = await Promise.all([
        api.listDocuments(),
        api.listDuplicates(),
      ]);
      setDocs(docs);
      setDuplicates(dupes);
      // Pre-select "delete all but the oldest" per group. `docs` inside
      // each group already arrive sorted by ingested_at asc from the API,
      // so index 0 is the recommended keep.
      const preselect = new Set<string>();
      for (const g of dupes) {
        for (let i = 1; i < g.docs.length; i++) {
          preselect.add(g.docs[i].id);
        }
      }
      setDedupSelection(preselect);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const toggleDedup = (docId: string) => {
    setDedupSelection((s) => {
      const next = new Set(s);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
  };

  const runDedup = async () => {
    const ids = Array.from(dedupSelection);
    if (!ids.length) return;
    // Warn if any selected doc is cited by an approved answer.
    const risky: string[] = [];
    for (const g of duplicates) {
      for (const d of g.docs) {
        if (dedupSelection.has(d.id) && d.authoritative_ref_count > 0) {
          risky.push(`${d.filename} (מצוטט ב-${d.authoritative_ref_count} תשובות)`);
        }
      }
    }
    const warn = risky.length
      ? `שים לב — המסמכים הבאים מצוטטים בתשובות מאושרות:\n\n${risky.join("\n")}\n\nמחיקתם תשאיר ציטוטים "יתומים". להמשיך?`
      : `למחוק ${ids.length} מסמכים כפולים?`;
    if (!confirm(warn)) return;
    setDedupBusy(true);
    try {
      await api.batchDeleteDocuments(ids);
      await loadDocs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDedupBusy(false);
    }
  };

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

  // Batch-level guard so a second click on "העלה את כל" doesn't start a
  // second concurrent iteration over a stale queue snapshot (each closure
  // would re-check status.queued from its own snapshot, causing duplicate
  // POSTs even though React would eventually reconcile the state).
  // Also used per-file: the per-entry button is disabled while ANY upload
  // is in flight — simpler mental model, and prevents the same race.
  const uploadingRef = useRef(false);
  const [uploading, setUploading] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);
  // Track which entries have an inflight request so we can also render a
  // per-file disabled state (defense in depth against double-click on the
  // small "העלה" button next to each row).
  const inflightIds = useRef<Set<string>>(new Set());

  // Poll a server-side job until it settles, pushing stage updates into
  // the queue row. Processing survives page navigation server-side; this
  // loop only drives the UI.
  const waitForJob = async (
    entryId: string,
    jobId: string
  ): Promise<IngestJobStatus> => {
    for (;;) {
      const j = await api.getIngestJob(jobId);
      if (j.status === "done" || j.status === "failed") return j;
      setQueue((q) =>
        q.map((e) =>
          e.id === entryId
            ? { ...e, status: { kind: "processing", stage: j.stage } }
            : e
        )
      );
      await new Promise((r) => setTimeout(r, 2500));
    }
  };

  const upload = async (entry: Queued) => {
    if (inflightIds.current.has(entry.id)) return;  // per-file re-entry guard
    inflightIds.current.add(entry.id);
    setQueue((q) =>
      q.map((e) => (e.id === entry.id ? { ...e, status: { kind: "uploading" } } : e))
    );
    try {
      // Enqueue on the server (fast — returns 202 + job id), then poll.
      // The heavy work (OCR, embedding) runs in the backend worker, so a
      // dropped connection or page reload no longer kills the ingest.
      const job = await api.uploadDocumentAsync(entry.file, entry.docType);
      setQueue((q) =>
        q.map((e) =>
          e.id === entry.id ? { ...e, status: { kind: "processing", stage: job.stage } } : e
        )
      );
      const settled = await waitForJob(entry.id, job.job_id);
      if (settled.status === "failed") {
        throw new Error(settled.error || "העיבוד נכשל");
      }
      setQueue((q) =>
        q.map((e) =>
          e.id === entry.id
            ? { ...e, status: { kind: "done", chunks: settled.chunks_created } }
            : e
        )
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
    } finally {
      inflightIds.current.delete(entry.id);
    }
  };

  const uploadAll = async () => {
    if (uploadingRef.current) return;  // batch re-entry guard
    uploadingRef.current = true;
    setUploading(true);
    // Snapshot the queue once at the start so per-entry state changes
    // don't invalidate our target list.
    const targets = queue.filter((e) => e.status.kind === "queued");
    setBatchProgress({ done: 0, total: targets.length });
    try {
      // Server-side queue processes jobs one at a time per worker — fire
      // all enqueues in parallel and let each row's poll loop track its
      // own job. Progress ticks as each job settles.
      let done = 0;
      await Promise.all(
        targets.map(async (entry) => {
          await upload(entry);
          done += 1;
          setBatchProgress({ done, total: targets.length });
        })
      );
    } finally {
      uploadingRef.current = false;
      setUploading(false);
      // Keep the last progress visible for a moment so the counter doesn't
      // vanish the instant the last file finishes — the user just watched
      // it tick and deserves the "done" frame.
      setTimeout(() => setBatchProgress(null), 1500);
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
  // Multi-select filters — empty set = no restriction on that axis.
  // Kept as Set for O(1) toggle; wrapped in state via functional setter.
  const [typeFilters, setTypeFilters] = useState<Set<string>>(new Set());
  const [folderFilters, setFolderFilters] = useState<Set<string>>(new Set());
  // Date range: "all" | "1y" | "2y" — anchored to *today*, filters on
  // effective_date. Chosen conservatively: docs without an effective_date
  // are included in every range so we don't hide unreviewed material.
  const [dateRange, setDateRange] = useState<"all" | "1y" | "2y">("all");
  const [onlyWithFile, setOnlyWithFile] = useState(false);
  const [onlyReviewed, setOnlyReviewed] = useState(false);

  const activeFilterCount =
    typeFilters.size +
    folderFilters.size +
    (dateRange !== "all" ? 1 : 0) +
    (onlyWithFile ? 1 : 0) +
    (onlyReviewed ? 1 : 0);

  const clearAllFilters = () => {
    setTypeFilters(new Set());
    setFolderFilters(new Set());
    setDateRange("all");
    setOnlyWithFile(false);
    setOnlyReviewed(false);
  };

  const toggleInSet = (
    setter: React.Dispatch<React.SetStateAction<Set<string>>>,
    value: string
  ) => {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const filteredSortedDocs = useMemo(() => {
    const q = search.trim().toLowerCase();
    const now = Date.now();
    const yearMs = 365 * 24 * 60 * 60 * 1000;
    const cutoff =
      dateRange === "1y"
        ? now - yearMs
        : dateRange === "2y"
        ? now - 2 * yearMs
        : null;

    let out = docs.filter((d) => {
      if (typeFilters.size && !typeFilters.has(d.doc_type || "unclassified"))
        return false;
      if (folderFilters.size && !folderFilters.has(d.folder || "__none__"))
        return false;
      if (onlyWithFile && !d.has_file) return false;
      if (onlyReviewed && !d.metadata_reviewed) return false;
      if (cutoff !== null && d.effective_date) {
        const t = new Date(d.effective_date).getTime();
        if (!Number.isNaN(t) && t < cutoff) return false;
      }
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
  }, [docs, search, sortKey, typeFilters, folderFilters, dateRange, onlyWithFile, onlyReviewed]);

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

  // Duplicate detection: docs sharing (chars_extracted, pages, chunks) are
  // almost certainly the same file uploaded multiple times with different
  // filenames. False-positive rate at ~7K-char precision is effectively zero.
  // Map: docId -> list of sibling ids (excluding self).
  const duplicateSiblings = useMemo(() => {
    const groups: Record<string, string[]> = {};
    for (const d of docs) {
      if (d.chars_extracted == null || d.pages == null) continue;
      const key = `${d.chars_extracted}:${d.pages}:${d.chunks}`;
      (groups[key] ||= []).push(d.id);
    }
    const out: Record<string, string[]> = {};
    for (const ids of Object.values(groups)) {
      if (ids.length < 2) continue;
      for (const id of ids) {
        out[id] = ids.filter((x) => x !== id);
      }
    }
    return out;
  }, [docs]);

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

      {/* Dropzone — dashed teal border, teal upload icon centered */}
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
        className={`mb-5 border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors ${
          dragOver
            ? "border-turquoise bg-turquoise/5"
            : "border-turquoise/40 bg-white hover:border-turquoise hover:bg-turquoise/5"
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
        <div className="flex flex-col items-center gap-3">
          <UploadCloudIcon />
          <div className="font-rubik font-medium text-base text-ink">
            גרור קבצים לכאן, או לחץ כדי לבחור
          </div>
          <div className="font-rubik text-xs text-ink-soft">PDF · Word · טקסט</div>
        </div>
      </div>

      {/* Default doc-type + upload-all + clear-done row */}
      <div className="mb-6 flex items-center gap-4 flex-wrap">
        {/* Right in RTL: label + select */}
        <label className="flex items-center gap-3 flex-1">
          <span className="font-rubik text-sm text-ink-soft whitespace-nowrap">
            סוג מסמך (ברירת מחדל):
          </span>
          <div className="relative min-w-[180px]">
            <select
              value={defaultDocType}
              onChange={(e) => setDefaultDocType(e.target.value)}
              className="w-full appearance-none bg-white border border-line rounded-md py-2.5 px-3 pl-8 text-sm text-ink font-rubik font-medium outline-none cursor-pointer hover:border-turquoise transition"
            >
              {docTypes.map((dt) => (
                <option key={dt.value} value={dt.value}>
                  {dt.label}
                </option>
              ))}
            </select>
            <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none text-ink-soft">
              <DsChevronDown />
            </span>
          </div>
        </label>
        {queuedCount > 0 && (
          <button
            onClick={uploadAll}
            disabled={uploading}
            className="inline-flex items-center gap-2 bg-turquoise text-white h-11 px-6 rounded-md font-rubik font-bold text-sm hover:bg-turquoise-dark transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {uploading && batchProgress
              ? `מעלה ${batchProgress.done}/${batchProgress.total}…`
              : `העלה את כל ${queuedCount} הקבצים`}
          </button>
        )}
        {!uploading && batchProgress && batchProgress.done === batchProgress.total && batchProgress.total > 0 && (
          <StatusPill variant="success">
            <DsCheckMark />
            <span>הועלו {batchProgress.total} קבצים</span>
          </StatusPill>
        )}
        {queue.some((e) => e.status.kind === "done") && (
          <Chip variant="grey" onClick={clearDone}>
            נקה גמורים
          </Chip>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {/* Duplicates cleanup — appears only when dupes exist. See
          backend/app/routes/documents.py:list_duplicates_by_hash. */}
      {duplicates.length > 0 && (
        <section className="mb-8 border-2 border-amber-400 bg-amber-50 rounded-md">
          <button
            onClick={() => setDedupCollapsed((c) => !c)}
            className="w-full flex items-center justify-between px-4 py-3 text-right"
          >
            <div>
              <div className="text-sm font-bold text-amber-900 tracking-wide">
                נמצאו {duplicates.length} קבוצות של מסמכים כפולים
              </div>
              <div className="text-xs text-amber-800 mt-1">
                סה״כ {duplicates.reduce((s, g) => s + g.count, 0)} מסמכים
                בקבוצות. ברירת המחדל: להשאיר את הראשון שנקלט, למחוק את השאר.
                {dedupSelection.size > 0 &&
                  ` · ${dedupSelection.size} נבחרו למחיקה.`}
              </div>
            </div>
            <span className="text-amber-700 text-lg">
              {dedupCollapsed ? "▼" : "▲"}
            </span>
          </button>
          {!dedupCollapsed && (
            <div className="border-t border-amber-300 p-4 space-y-4">
              {duplicates.map((g) => (
                <div
                  key={g.content_sha256}
                  className="bg-white rounded border border-amber-200"
                >
                  <div className="px-3 py-2 border-b border-amber-100 flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-mono text-ink-soft">
                      {g.content_sha256.slice(0, 10)}…
                    </span>
                    <span className="text-xs text-amber-900 font-bold">
                      {g.count} עותקים
                    </span>
                  </div>
                  <ul className="divide-y divide-amber-100">
                    {g.docs.map((d, i) => {
                      const isRecommendedKeep = i === 0;
                      const selected = dedupSelection.has(d.id);
                      return (
                        <li
                          key={d.id}
                          className={`flex items-start gap-3 px-3 py-2 ${
                            selected ? "bg-red-50" : ""
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleDedup(d.id)}
                            className="mt-1"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm text-ink font-medium truncate">
                                {d.filename}
                              </span>
                              {isRecommendedKeep && (
                                <span className="text-[10px] uppercase tracking-widest text-emerald-700 font-bold">
                                  מומלץ להשאיר
                                </span>
                              )}
                              {d.authoritative_ref_count > 0 && (
                                <span className="text-[10px] uppercase tracking-widest text-red-700 font-bold">
                                  מצוטט ב-{d.authoritative_ref_count} תשובות
                                  מאושרות
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-ink-soft mt-1">
                              נקלט{" "}
                              {new Date(d.ingested_at).toLocaleString("he-IL")}
                              {d.chunks_created !== null &&
                                ` · ${d.chunks_created} קטעים`}
                              {d.folder && ` · תיקייה: ${d.folder}`}
                              {d.doc_type && ` · סוג: ${d.doc_type}`}
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
              <div className="flex items-center justify-between pt-2">
                <button
                  onClick={() => setDedupSelection(new Set())}
                  disabled={dedupBusy || dedupSelection.size === 0}
                  className="text-xs px-2 py-1 text-ink-soft hover:bg-white/60 rounded disabled:opacity-50"
                >
                  נקה בחירה
                </button>
                <button
                  onClick={runDedup}
                  disabled={dedupBusy || dedupSelection.size === 0}
                  className="px-3 py-1.5 bg-red-700 text-white text-sm rounded disabled:opacity-50"
                >
                  {dedupBusy
                    ? "מוחק…"
                    : `מחק ${dedupSelection.size} מסמכים שנבחרו`}
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Queue */}
      {queue.length > 0 && (
        <section className="mb-8">
          <div className="mb-4 flex items-center gap-3">
            <span className="font-rubik font-bold text-base tracking-[0.15em] text-turquoise">תור</span>
            <span className="flex-1 h-px bg-line" />
          </div>
          <div className="space-y-3">
            {queue.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center gap-4 p-4 bg-white border border-line rounded-lg"
              >
                {/* Right: filename + size + status */}
                <div className="flex-1 min-w-0">
                  <div className="font-rubik font-bold text-sm text-ink truncate text-right">
                    {entry.file.name}
                  </div>
                  <div className="text-xs text-ink-soft mt-1 text-right font-rubik">
                    {(entry.file.size / 1024).toFixed(1)} KB
                  </div>
                  {entry.status.kind === "error" && (
                    <div className="text-xs text-danger mt-1 text-right">{entry.status.message}</div>
                  )}
                  {entry.status.kind === "done" && (
                    <div className="text-xs mt-1 text-success text-right">
                      ✓ נקלט
                      {entry.status.chunks != null && ` · ${entry.status.chunks} קטעים`}
                    </div>
                  )}
                </div>
                {/* Doc-type select — with chevron */}
                <div className="relative min-w-[140px]">
                  <select
                    value={entry.docType}
                    onChange={(e) =>
                      setQueue((q) =>
                        q.map((x) => (x.id === entry.id ? { ...x, docType: e.target.value } : x))
                      )
                    }
                    disabled={entry.status.kind !== "queued"}
                    className="w-full appearance-none bg-white border border-line rounded-md py-2 px-3 pl-8 text-sm text-ink font-rubik font-medium outline-none cursor-pointer hover:border-turquoise transition disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {docTypes.map((dt) => (
                      <option key={dt.value} value={dt.value}>
                        {dt.label}
                      </option>
                    ))}
                  </select>
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none text-ink-soft">
                    <DsChevronDown />
                  </span>
                </div>
                {/* Left: action button */}
                <div className="w-24 flex justify-end">
                  {entry.status.kind === "queued" && (
                    <button
                      onClick={() => upload(entry)}
                      disabled={uploading}
                      className="inline-flex items-center gap-2 bg-turquoise text-white h-9 px-4 rounded-md font-rubik font-bold text-xs hover:bg-turquoise-dark transition disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      העלה
                    </button>
                  )}
                  {entry.status.kind === "uploading" && (
                    <span className="text-xs text-ink-soft font-rubik">מעלה...</span>
                  )}
                  {entry.status.kind === "processing" && (
                    <span className="text-xs text-ink-soft font-rubik text-left">
                      {(entry.status.stage && STAGE_LABELS[entry.status.stage]) || "בתור..."}
                    </span>
                  )}
                  {(entry.status.kind === "done" || entry.status.kind === "error") && (
                    <button
                      onClick={() => removeFromQueue(entry.id)}
                      className="text-xs text-ink-soft hover:text-danger font-rubik"
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
        <div className="mb-6 flex items-center gap-4 flex-wrap justify-between">
          {/* Right in RTL: title + count */}
          <div className="font-rubik font-bold text-base tracking-[0.15em] text-turquoise">
            מסמכים במאגר{docs.length > 0 && ` (${docs.length})`}
          </div>
          {docs.length > 0 && (
            <div className="flex items-center gap-2">
              <Chip
                variant="active"
                onClick={() => classify(false)}
                disabled={classifying}
                title="קרא את תוכן כל מסמך עם Claude, תן לו כותרת ותקציר"
              >
                {classifying ? "מסווג..." : "סווג חדשים"}
              </Chip>
              <Chip
                variant="grey"
                onClick={() => classify(true)}
                disabled={classifying}
                title="סווג מחדש את כל המסמכים, כולל כאלה שכבר סווגו"
              >
                סווג הכל מחדש
              </Chip>
              <span className="w-px h-6 bg-line mx-1" />
              <button
                type="button"
                onClick={deleteAllDocs}
                title="מחיקת כל המסמכים מהמאגר"
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-danger text-danger bg-white hover:bg-danger hover:text-white transition font-rubik font-medium text-xs"
              >
                <TrashIcon />
                <span>מחק הכל</span>
              </button>
            </div>
          )}
        </div>
        <div className="h-px bg-line mb-5" />

        {classifyMsg && (
          <div className="mb-4 px-4 py-3 bg-surface border-r-4 border-accent text-sm text-ink">
            {classifyMsg}
          </div>
        )}

        {/* Library toolbar — search + sort + group. */}
        {docs.length > 0 && (
          <div className="mb-6 border border-line bg-white rounded-lg">
            <div className="flex items-stretch flex-wrap">
              {/* Search — DOM first → right in RTL */}
              <div className="flex-1 min-w-[200px] flex items-center gap-2 px-4 border-l border-line">
                <input
                  type="text"
                  placeholder="חיפוש בשם או בתקציר…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="flex-1 py-3 bg-transparent text-sm text-ink placeholder:text-ink-soft outline-none text-right"
                />
                <span className="text-ink-soft"><SearchIcon /></span>
              </div>
              <label className="flex items-center gap-2 px-4 border-l border-line text-sm text-ink-soft font-rubik">
                <span>מיון:</span>
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                  className="bg-transparent py-3 pl-6 text-sm text-ink font-rubik font-medium outline-none cursor-pointer appearance-none"
                >
                  <option value="recent">אחרון שעודכן</option>
                  <option value="alpha">א–ת</option>
                  <option value="chunks">מספר קטעים</option>
                </select>
                <span className="text-ink-soft -mr-4"><DsChevronDown /></span>
              </label>
              <label className="flex items-center gap-2 px-4 border-l border-line text-sm text-ink-soft font-rubik">
                <span>קיבוץ:</span>
                <select
                  value={groupKey}
                  onChange={(e) => setGroupKey(e.target.value as GroupKey)}
                  className="bg-transparent py-3 pl-6 text-sm text-ink font-rubik font-medium outline-none cursor-pointer appearance-none"
                >
                  <option value="none">ללא</option>
                  <option value="type">לפי סוג מסמך</option>
                  <option value="folder">לפי תיקייה</option>
                </select>
                <span className="text-ink-soft -mr-4"><DsChevronDown /></span>
              </label>
              <div className="flex items-center px-4 text-sm text-ink-soft font-rubik">
                <span>
                  {filteredSortedDocs.length}/{docs.length}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Two-column layout: sidebar with facets + main doc grid. Collapses
            to a stacked single column on mobile so the sidebar becomes a
            top-of-page filter block instead of a side-rail. */}
        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6">
          {docs.length > 0 && (
            <FilterSidebar
              typeCounts={typeCounts}
              folderList={folderList}
              folderCounts={folderCounts}
              typeFilters={typeFilters}
              folderFilters={folderFilters}
              dateRange={dateRange}
              onlyWithFile={onlyWithFile}
              onlyReviewed={onlyReviewed}
              activeCount={activeFilterCount}
              onToggleType={(k) => toggleInSet(setTypeFilters, k)}
              onToggleFolder={(k) => toggleInSet(setFolderFilters, k)}
              onDateRange={setDateRange}
              onToggleWithFile={() => setOnlyWithFile((v) => !v)}
              onToggleReviewed={() => setOnlyReviewed((v) => !v)}
              onClear={clearAllFilters}
            />
          )}

          <div className="min-w-0">
            {loadingDocs ? (
              <div className="text-ink-soft text-sm">טוען...</div>
            ) : docs.length === 0 ? (
              <div className="border border-line p-12 text-center text-sm text-ink-soft">
                אין מסמכים. העלה את הראשון.
              </div>
            ) : filteredSortedDocs.length === 0 ? (
              <div className="border border-line p-12 text-center text-sm text-ink-soft">
                לא נמצאו מסמכים תואמים.{" "}
                <button
                  onClick={clearAllFilters}
                  className="underline underline-offset-4 hover:text-accent"
                >
                  נקה את כל הסינון
                </button>
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
                          duplicateSiblingCount={duplicateSiblings[d.id]?.length ?? 0}
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
                    duplicateSiblingCount={duplicateSiblings[d.id]?.length ?? 0}
                    onDelete={() => deleteDoc(d)}
                    onOpen={() => setOpenDoc(d)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
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

/* ─── Faceted filter sidebar ─────────────────────────────────────── */

function FilterSidebar({
  typeCounts,
  folderList,
  folderCounts,
  typeFilters,
  folderFilters,
  dateRange,
  onlyWithFile,
  onlyReviewed,
  activeCount,
  onToggleType,
  onToggleFolder,
  onDateRange,
  onToggleWithFile,
  onToggleReviewed,
  onClear,
}: {
  typeCounts: Record<string, number>;
  folderList: string[];
  folderCounts: Record<string, number>;
  typeFilters: Set<string>;
  folderFilters: Set<string>;
  dateRange: "all" | "1y" | "2y";
  onlyWithFile: boolean;
  onlyReviewed: boolean;
  activeCount: number;
  onToggleType: (k: string) => void;
  onToggleFolder: (k: string) => void;
  onDateRange: (v: "all" | "1y" | "2y") => void;
  onToggleWithFile: () => void;
  onToggleReviewed: () => void;
  onClear: () => void;
}) {
  return (
    <aside className="lg:sticky lg:top-24 self-start bg-white rounded-lg border border-line p-5 text-sm lg:max-h-[calc(100vh-7.5rem)] lg:overflow-y-auto overscroll-contain">
      <div className="flex items-center justify-between pb-3 mb-4 border-b border-line">
        <span className="font-rubik font-bold text-base tracking-[0.15em] text-turquoise">
          סינון
        </span>
        {activeCount > 0 && (
          <button
            onClick={onClear}
            className="text-xs text-turquoise font-rubik font-medium hover:underline underline-offset-4"
            title="נקה את כל הפילטרים"
          >
            נקה ({activeCount})
          </button>
        )}
      </div>

      <FacetGroup title="סוג מסמך">
        {DOC_TYPE_ORDER.filter((k) => typeCounts[k]).map((k) => (
          <FacetCheckbox
            key={k}
            checked={typeFilters.has(k)}
            onChange={() => onToggleType(k)}
            label={DOC_TYPE_LABELS[k] || k}
            count={typeCounts[k]}
          />
        ))}
      </FacetGroup>

      {folderList.length > 0 && (
        <FacetGroup title="תיקייה">
          {folderList.map((f) => (
            <FacetCheckbox
              key={f}
              checked={folderFilters.has(f)}
              onChange={() => onToggleFolder(f)}
              label={f}
              count={folderCounts[f] || 0}
            />
          ))}
          {folderCounts.__none__ && (
            <FacetCheckbox
              checked={folderFilters.has("__none__")}
              onChange={() => onToggleFolder("__none__")}
              label="ללא תיקייה"
              count={folderCounts.__none__}
              italic
            />
          )}
        </FacetGroup>
      )}

      <FacetGroup title="תוקף">
        <FacetRadio
          checked={dateRange === "all"}
          onChange={() => onDateRange("all")}
          label="כל התאריכים"
        />
        <FacetRadio
          checked={dateRange === "1y"}
          onChange={() => onDateRange("1y")}
          label="השנה האחרונה"
        />
        <FacetRadio
          checked={dateRange === "2y"}
          onChange={() => onDateRange("2y")}
          label="השנתיים האחרונות"
        />
      </FacetGroup>

      <FacetGroup title="מצב">
        <FacetCheckbox
          checked={onlyWithFile}
          onChange={onToggleWithFile}
          label="יש קובץ מקור"
        />
        <FacetCheckbox
          checked={onlyReviewed}
          onChange={onToggleReviewed}
          label="מטא־דאטה נבדק"
        />
      </FacetGroup>
    </aside>
  );
}

function FacetGroup({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-5 last:mb-0 pb-5 last:pb-0 border-b border-line last:border-b-0">
      <div className="font-rubik font-bold text-sm text-turquoise mb-3">
        {title}
      </div>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function FacetCheckbox({
  checked,
  onChange,
  label,
  count,
  italic,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  count?: number;
  italic?: boolean;
}) {
  return (
    <div
      onClick={onChange}
      className="flex items-center gap-3 cursor-pointer group"
    >
      <DsCheckbox checked={checked} onChange={onChange} ariaLabel={label} />
      <span
        className={`flex-1 text-sm leading-tight text-right ${
          checked ? "text-ink font-medium" : "text-ink group-hover:text-turquoise"
        } ${italic ? "italic text-ink-soft" : ""}`}
      >
        {label}
      </span>
      {count !== undefined && (
        <span className="text-xs text-ink-soft font-rubik">{count}</span>
      )}
    </div>
  );
}

function FacetRadio({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <div
      onClick={onChange}
      className="flex items-center gap-3 cursor-pointer group"
    >
      <DsRadio checked={checked} onChange={onChange} ariaLabel={label} />
      <span
        className={`flex-1 text-sm leading-tight text-right ${
          checked ? "text-ink font-medium" : "text-ink group-hover:text-turquoise"
        }`}
      >
        {label}
      </span>
    </div>
  );
}

function DocumentRow({
  doc,
  duplicateSiblingCount = 0,
  onDelete,
  onOpen,
}: {
  doc: DocumentItem;
  duplicateSiblingCount?: number;
  onDelete: () => void;
  onOpen: () => void;
}) {
  const needsReview = !!doc.ai_classified && !doc.metadata_reviewed;
  // Doc-status resolves for the bottom-right status pill.
  const statusVariant: "success" | "warning" | "danger" | "neutral" =
    doc.superseded_by_id
      ? "neutral"
      : doc.doc_status && doc.doc_status !== "adopted"
      ? "warning"
      : "success";
  const statusLabel = doc.superseded_by_id
    ? "גרסה ישנה"
    : doc.doc_status && doc.doc_status !== "adopted"
    ? DOC_STATUS_LABELS[doc.doc_status] || doc.doc_status
    : "פעיל";

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
      className="p-5 bg-white rounded-lg border border-line hover:border-turquoise/40 shadow-[0px_1px_0_rgba(0,0,0,0.03),0px_4px_16px_-4px_rgba(0,0,0,0.06)] transition cursor-pointer"
    >
      {/* ── Top row: metadata tags (right in RTL) + delete (left) ─────── */}
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-2 justify-start">
            {doc.ai_classified && <StatusPill variant="teal">AI</StatusPill>}
            {needsReview && (
              <StatusPill variant="warning">בדיקה</StatusPill>
            )}
            {duplicateSiblingCount > 0 && (
              <StatusPill variant="danger">כפילות אפשרית</StatusPill>
            )}
          </div>
          <div className="font-rubik font-bold text-lg text-ink text-right leading-snug">
            {doc.filename}
          </div>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-danger text-danger bg-white hover:bg-danger hover:text-white transition font-rubik font-medium text-xs"
          title="מחק את המסמך הזה"
        >
          <TrashIcon />
          <span>מחק</span>
        </button>
      </div>

      <div className="h-px bg-line my-4" />

      {/* ── Middle row: doc-type / folder / date chips (right) + open button (left) ── */}
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 justify-start">
            {doc.doc_type && (
              <DsTag>{DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}</DsTag>
            )}
            {doc.folder && <DsTag>{doc.folder}</DsTag>}
            {doc.effective_date && <DsTag>{doc.effective_date}</DsTag>}
          </div>
          {doc.summary && (
            <p className="mt-3 text-sm text-ink leading-relaxed text-right">
              {doc.summary}
            </p>
          )}
          {doc.extraction_note && (
            <div className="mt-2 text-xs text-warning-dark text-right">
              ⚠ {doc.extraction_note}
            </div>
          )}
        </div>
        {doc.has_file && (
          <a
            href={documentFileUrl(doc.id)}
            target="_blank"
            rel="noreferrer noopener"
            onClick={(e) => e.stopPropagation()}
            title="פתח את קובץ המקור בכרטיסייה חדשה"
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-turquoise text-turquoise bg-white hover:bg-turquoise hover:text-white transition font-rubik font-medium text-xs"
          >
            <DsExternalLink />
            <span>פתח מקור</span>
          </a>
        )}
      </div>

      <div className="h-px bg-line my-4" />

      {/* ── Bottom row: metadata (right) + status pill (left) ─────────── */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-0 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-soft font-rubik">
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
        <StatusPill variant={statusVariant}>
          {statusVariant === "success" && <DsCheckMark />}
          <span>{statusLabel}</span>
        </StatusPill>
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
    doc_status: doc.doc_status || undefined,
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
        "doc_status",
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
        doc_status: payload.doc_status ?? doc.doc_status,
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
        className="fixed top-0 bottom-0 left-0 w-full max-w-[560px] bg-white z-50 flex flex-col animate-fade-up shadow-2xl font-sans"
      >
        {/* Header — close on LEFT, breadcrumb + title on RIGHT */}
        <header className="border-b border-line px-6 py-5 flex items-start gap-3">
          <button
            onClick={onClose}
            className="shrink-0 text-ink-soft hover:text-ink w-8 h-8 flex items-center justify-center rounded-md hover:bg-line/60 transition"
            aria-label="סגור"
          >
            <CloseIcon />
          </button>
          <div className="flex-1 min-w-0 text-right">
            <div className="font-rubik font-bold text-xs tracking-[0.15em] text-turquoise mb-2">
              {DOC_TYPE_LABELS[doc.doc_type || "unclassified"]}
              {doc.folder && ` · ${doc.folder}`}
            </div>
            <div className="font-rubik font-bold text-lg text-ink leading-tight truncate">
              {doc.has_file ? (
                <a
                  href={documentFileUrl(doc.id)}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="hover:text-turquoise inline-flex items-center gap-1.5"
                  title="פתח את קובץ המקור בכרטיסייה חדשה"
                >
                  <span>{doc.filename}</span>
                  <DsExternalLink />
                </a>
              ) : (
                doc.filename
              )}
            </div>
          </div>
        </header>

        {/* Tab switcher — teal filled active, grey inactive */}
        <div className="flex gap-0 border-b border-line px-6 pt-4">
          <button
            onClick={() => setTab("details")}
            className={`flex-1 py-3 rounded-t-md font-rubik font-medium text-sm transition ${
              tab === "details"
                ? "bg-turquoise text-white"
                : "bg-line/50 text-ink-soft hover:text-ink hover:bg-line"
            }`}
          >
            פרטים
          </button>
          <button
            onClick={() => setTab("content")}
            className={`flex-1 py-3 rounded-t-md font-rubik font-medium text-sm transition ${
              tab === "content"
                ? "bg-turquoise text-white"
                : "bg-line/50 text-ink-soft hover:text-ink hover:bg-line"
            }`}
          >
            תוכן ({doc.chunks} קטעים)
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {tab === "details" ? (
            <div className="p-6 space-y-4 text-sm">
              {doc.ai_classified && !doc.metadata_reviewed && (
                <div className="p-3 bg-warning/10 border border-warning/30 rounded-md text-ink text-xs font-rubik">
                  המערכת מילאה את השדות אוטומטית מקריאת המסמך. אנא ודא ותקן
                  לפני שמירה.
                </div>
              )}

              <Field label="סוג מסמך">
                <DsSelect
                  value={form.doc_type || ""}
                  onChange={(v) => setForm((f) => ({ ...f, doc_type: v }))}
                >
                  <option value="">—</option>
                  {docTypes.map((dt) => (
                    <option key={dt.value} value={dt.value}>
                      {dt.label}
                    </option>
                  ))}
                </DsSelect>
              </Field>

              <Field label="מעמד" hint="הצעה/טיוטה לא יצוטטו כהכלל המחייב">
                <DsSelect
                  value={form.doc_status ?? doc.doc_status ?? ""}
                  onChange={(v) => setForm((f) => ({ ...f, doc_status: v }))}
                >
                  <option value="">—</option>
                  {Object.entries(DOC_STATUS_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </DsSelect>
              </Field>

              <Field label="תיקייה">
                <DsInput
                  value={form.folder || ""}
                  onChange={(v) => setForm((f) => ({ ...f, folder: v }))}
                  placeholder="למשל: פנסיה, שיוך דירות"
                />
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="תאריך המסמך" hint="מופיע במסמך">
                  <DsInput
                    type="date"
                    value={form.document_date || ""}
                    onChange={(v) => setForm((f) => ({ ...f, document_date: v }))}
                  />
                </Field>
                <Field label="תאריך תוקף" hint="נכנס לתוקף">
                  <DsInput
                    type="date"
                    value={form.effective_date || ""}
                    onChange={(v) => setForm((f) => ({ ...f, effective_date: v }))}
                  />
                </Field>
              </div>

              {showMeeting && (
                <Field label="מספר ישיבה">
                  <DsInput
                    value={form.meeting_number || ""}
                    onChange={(v) => setForm((f) => ({ ...f, meeting_number: v }))}
                    placeholder="למשל: 234"
                  />
                </Field>
              )}
              {showDecision && (
                <Field label="מספר החלטה">
                  <DsInput
                    value={form.decision_number || ""}
                    onChange={(v) => setForm((f) => ({ ...f, decision_number: v }))}
                    placeholder="למשל: 47/22"
                  />
                </Field>
              )}
              {showBylawRange && (
                <Field label="טווח סעיפים">
                  <DsInput
                    value={form.bylaw_section_range || ""}
                    onChange={(v) => setForm((f) => ({ ...f, bylaw_section_range: v }))}
                    placeholder="למשל: סעיפים 12-18"
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
                    className="w-full px-3 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
                  />
                </Field>
              )}

              <Field label="תקציר">
                <textarea
                  value={form.summary || ""}
                  onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))}
                  rows={4}
                  className="w-full px-3 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik leading-relaxed outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
                />
              </Field>

              {saveErr && (
                <div className="p-3 bg-danger/10 border border-danger/30 rounded-md text-danger text-xs font-rubik">
                  {saveErr}
                </div>
              )}

              {/* Actions row — DOM order: save first (LEFT in RTL), cancel second */}
              <div className="flex items-center gap-3 pt-2 flex-row-reverse">
                <button
                  onClick={save}
                  disabled={saving}
                  className="inline-flex items-center gap-2 bg-turquoise text-white h-10 px-6 rounded-md font-rubik font-bold text-sm hover:bg-turquoise-dark transition disabled:opacity-50"
                >
                  {saving ? "שומר..." : "שמור ואשר"}
                </button>
                <button
                  onClick={onClose}
                  className="inline-flex items-center h-10 px-4 rounded-md text-sm text-ink-soft font-rubik font-medium hover:text-ink hover:bg-line/60 transition"
                >
                  ביטול
                </button>
                {doc.metadata_reviewed && (
                  <StatusPill variant="success">
                    <DsCheckMark />
                    <span>אושר</span>
                  </StatusPill>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col h-full">
              <div className="p-4 border-b border-line bg-white sticky top-0">
                <div className="relative">
                  <input
                    type="text"
                    placeholder="חיפוש בטקסט המסמך…"
                    value={chunkQuery}
                    onChange={(e) => setChunkQuery(e.target.value)}
                    className="w-full pr-4 pl-10 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
                  />
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft">
                    <SearchIcon />
                  </span>
                </div>
              </div>
              {chunksLoading ? (
                <div className="p-5 text-sm text-ink-soft font-rubik">טוען קטעים...</div>
              ) : chunksErr ? (
                <div className="p-5 text-sm text-danger font-rubik">{chunksErr}</div>
              ) : filteredChunks.length === 0 ? (
                <div className="p-5 text-sm text-ink-soft font-rubik">
                  {chunks && chunks.length === 0
                    ? "אין קטעים במסמך."
                    : "לא נמצא טקסט תואם."}
                </div>
              ) : (
                <div className="p-4 space-y-3">
                  {filteredChunks.map((c) => (
                    <div key={c.position} className="p-4 bg-white rounded-lg border border-line">
                      <div className="mb-3 flex flex-wrap gap-2 justify-start">
                        <DsTag>#{c.position + 1}</DsTag>
                        {c.section_path && <DsTag>{c.section_path}</DsTag>}
                        <DsTag>{c.chars} תווים</DsTag>
                      </div>
                      <div className="text-sm text-ink leading-relaxed whitespace-pre-wrap text-right">
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
      <div className="font-rubik font-medium text-xs text-turquoise mb-2 flex items-baseline gap-2 justify-start">
        <span>{label}</span>
        {hint && (
          <span className="text-ink-soft font-normal">{hint}</span>
        )}
      </div>
      {children}
    </label>
  );
}

/* DS-styled text input — full-width, rounded, teal focus ring. */
function DsInput({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full px-3 py-2.5 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
    />
  );
}

/* DS-styled select — same visual as DsInput + chevron on the left. */
function DsSelect({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none px-3 py-2.5 pl-9 border border-line rounded-md bg-white text-sm text-ink font-rubik text-right outline-none cursor-pointer focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition"
      >
        {children}
      </select>
      <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none text-ink-soft">
        <DsChevronDown />
      </span>
    </div>
  );
}

function CloseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* ─── DS helper components for Documents page ────────────────────────── */

function UploadCloudIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true" className="text-turquoise">
      <path d="M16 20V8m0 0l-5 5m5-5l5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 20a2 2 0 002 2h12a2 2 0 002-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M10 11v6M14 11v6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.8" />
      <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function DsChevronDown() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DsExternalLink() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14 4h6v6M20 4L10 14M20 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DsCheckMark() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* Grey / colored / active chip — used for classification buttons and filter chips. */
function Chip({
  children,
  variant = "grey",
  onClick,
  disabled,
  title,
}: {
  children: ReactNode;
  variant?: "grey" | "active" | "teal-outline";
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
}) {
  const styles =
    variant === "active"
      ? "bg-turquoise/10 text-turquoise hover:bg-turquoise/15"
      : variant === "teal-outline"
      ? "bg-white border border-turquoise text-turquoise hover:bg-turquoise/5"
      : "bg-line text-ink-soft hover:bg-line-strong";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center px-3 py-1.5 rounded-md font-rubik font-medium text-xs transition disabled:opacity-50 disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  );
}

/* Small rounded pill for doc-type / category tags — read-only. */
function DsTag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-line text-ink-soft font-rubik text-xs">
      {children}
    </span>
  );
}

/* Status pill — green (active), grey (superseded), etc. */
function StatusPill({
  variant,
  children,
}: {
  variant: "success" | "warning" | "danger" | "neutral" | "teal";
  children: ReactNode;
}) {
  const styles: Record<typeof variant, string> = {
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning-dark",
    danger: "bg-danger/10 text-danger",
    neutral: "bg-line text-ink-soft",
    teal: "bg-turquoise/10 text-turquoise",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md font-rubik font-medium text-xs ${styles[variant]}`}
    >
      {children}
    </span>
  );
}

/* DS-styled checkbox — teal filled + white check when checked; rounded square. */
function DsCheckbox({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: () => void;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={`w-5 h-5 rounded-md flex items-center justify-center transition shrink-0 ${
        checked
          ? "bg-turquoise text-white"
          : "bg-white border border-line-strong hover:border-turquoise"
      }`}
    >
      {checked && <DsCheckMark />}
    </button>
  );
}

/* DS-styled radio — teal filled circle when selected. */
function DsRadio({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: () => void;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={`w-5 h-5 rounded-full flex items-center justify-center transition shrink-0 ${
        checked
          ? "border-2 border-turquoise"
          : "border border-line-strong hover:border-turquoise"
      }`}
    >
      {checked && <span className="w-2.5 h-2.5 rounded-full bg-turquoise" />}
    </button>
  );
}
