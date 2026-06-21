import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DocumentItem, type UploadResponse } from "../lib/api";

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
      className="text-[10px] px-2 py-0.5 bg-stone-100 text-ink-soft rounded-full"
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
      <header className="mb-6">
        <h1 className="text-2xl font-bold">העלאת מסמכים</h1>
        <p className="text-ink-soft mt-1 text-sm">
          תקנונים, פרוטוקולים, החלטות. נתמך: PDF, Word, טקסט. סריקות PDF עוברות OCR אוטומטי.
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
            : "border-stone-300 bg-white hover:border-accent/50 hover:bg-stone-100"
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
          className="px-2 py-1 border border-stone-300 rounded"
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
            className="px-3 py-1.5 bg-stone-100 hover:bg-stone-200 rounded"
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
                className="flex items-center gap-3 p-3 bg-white border border-stone-200 rounded text-sm"
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
                  className="px-2 py-1 border border-stone-300 rounded text-xs"
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
        <div className="flex items-end justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-sm font-bold text-accent uppercase tracking-wider">
            מסמכים במאגר
          </h2>
          {docs.length > 0 && (
            <div className="flex gap-2">
              <button
                onClick={() => classify(false)}
                disabled={classifying}
                className="px-3 py-1.5 bg-white border border-stone-300 hover:border-accent text-xs rounded-full text-ink-soft hover:text-accent transition disabled:opacity-50"
                title="קרא את תוכן כל מסמך עם Claude, תן לו כותרת ותקציר"
              >
                {classifying ? "מסווג..." : "✨ סווג מסמכים חדשים"}
              </button>
              <button
                onClick={() => classify(true)}
                disabled={classifying}
                className="px-3 py-1.5 text-xs text-ink-soft hover:text-ink rounded-full disabled:opacity-50"
                title="סווג מחדש את כל המסמכים, כולל כאלה שכבר סווגו"
              >
                סווג הכל מחדש
              </button>
              <button
                onClick={deleteAllDocs}
                className="px-3 py-1.5 text-xs text-red-700 hover:bg-red-50 rounded-full transition"
                title="מחיקת כל המסמכים מהמאגר"
              >
                🗑 מחק הכל
              </button>
            </div>
          )}
        </div>

        {classifyMsg && (
          <div className="mb-3 p-3 bg-emerald-50 border border-emerald-200 rounded text-emerald-900 text-sm">
            {classifyMsg}
          </div>
        )}

        {loadingDocs ? (
          <div className="text-ink-soft text-sm">טוען...</div>
        ) : docs.length === 0 ? (
          <div className="text-ink-soft py-8 text-center text-sm">
            אין מסמכים. העלה את הראשון.
          </div>
        ) : (
          <div className="space-y-2">
            {docs.map((d) => (
              <div
                key={d.id}
                className="p-4 bg-white border border-stone-200 rounded-xl shadow-soft"
              >
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="font-semibold text-ink text-base">{d.filename}</span>
                      {d.ai_classified && (
                        <span className="text-[10px] px-2 py-0.5 bg-accent/10 text-accent rounded-full">
                          ✨ סווג AI
                        </span>
                      )}
                      {d.doc_type && (
                        <span className="text-[10px] px-2 py-0.5 bg-stone-100 text-ink-soft rounded-full">
                          {d.doc_type}
                        </span>
                      )}
                    </div>
                    {d.summary && (
                      <div className="text-sm text-ink-soft mt-1.5 leading-relaxed">
                        {d.summary}
                      </div>
                    )}
                    <div className="text-xs text-ink-soft mt-2 flex gap-3 flex-wrap items-center">
                      <QualityBadge doc={d} />
                      <span>{d.chunks} קטעים</span>
                      <span>{formatChars(d.chars)}</span>
                      {d.pages != null && <span>{d.pages} עמודים</span>}
                      {d.extractor && (
                        <span title="מנוע חילוץ הטקסט">
                          {d.extractor === "azure_ocr"
                            ? "OCR"
                            : d.extractor === "pdfplumber"
                            ? "PDF native"
                            : d.extractor}
                        </span>
                      )}
                      <span>{new Date(d.ingested_at).toLocaleString("he-IL")}</span>
                    </div>
                    {d.extraction_note && (
                      <div className="text-xs text-amber-700 mt-1">⚠ {d.extraction_note}</div>
                    )}
                  </div>
                  <button
                    onClick={() => deleteDoc(d)}
                    className="text-xs px-2 py-1 text-red-700 hover:bg-red-50 rounded shrink-0"
                  >
                    מחק
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
