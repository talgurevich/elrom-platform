import { useEffect, useState } from "react";
import {
  api,
  type FolderSuggestionItem,
  type FolderTaxonomyItem,
} from "../lib/api";

type EditorState = {
  id: string | "new";
  name: string;
  description: string;
  active: boolean;
};

const emptyEditor = (): EditorState => ({
  id: "new",
  name: "",
  description: "",
  active: true,
});

function editorFromItem(f: FolderTaxonomyItem): EditorState {
  return {
    id: f.id,
    name: f.name,
    description: f.description || "",
    active: f.active,
  };
}

export default function Folders() {
  const [folders, setFolders] = useState<FolderTaxonomyItem[]>([]);
  const [suggestions, setSuggestions] = useState<FolderSuggestionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [f, s] = await Promise.all([
        api.listFolders(),
        api.listFolderSuggestions("pending"),
      ]);
      setFolders(f);
      setSuggestions(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!editor) return;
    const name = editor.name.trim();
    if (!name) return;
    setBusy(true);
    try {
      const payload = {
        name,
        description: editor.description || undefined,
        active: editor.active,
      };
      if (editor.id === "new") {
        await api.createFolder(payload);
      } else {
        await api.updateFolder(editor.id, payload);
      }
      setEditor(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (f: FolderTaxonomyItem) => {
    if (f.doc_count > 0) {
      const target = prompt(
        `בתיקייה "${f.name}" יש ${f.doc_count} מסמכים. לאיזו תיקייה להעביר אותם? (השאר ריק לניקוי השדה)`,
        "",
      );
      if (target === null) return;
      setBusy(true);
      try {
        await api.deleteFolder(f.id, target || undefined);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
      return;
    }
    if (!confirm(`למחוק את התיקייה "${f.name}"?`)) return;
    setBusy(true);
    try {
      await api.deleteFolder(f.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const acceptSuggestion = async (s: FolderSuggestionItem) => {
    const editedName = prompt(
      "שם התיקייה החדשה (ניתן לערוך לפני האישור):",
      s.proposed_name,
    );
    if (!editedName || !editedName.trim()) return;
    setBusy(true);
    try {
      await api.acceptFolderSuggestion(s.id, {
        name: editedName.trim(),
        description: s.proposed_description || undefined,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const rejectSuggestion = async (s: FolderSuggestionItem) => {
    setBusy(true);
    try {
      await api.rejectFolderSuggestion(s.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="mb-10 flex items-end justify-between flex-wrap gap-3">
        <div>
          <div className="text-[11px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
            תיקיות
          </div>
          <h1 className="font-display text-4xl md:text-5xl font-black text-ink leading-[0.95]">
            טקסונומיית תיקיות
          </h1>
          <p className="text-ink-soft mt-4 text-sm max-w-xl leading-relaxed">
            רשימה מאוצרת של תיקיות שאליהן המסווג האוטומטי משבץ מסמכים חדשים. אם
            מסמך לא משתייך לאף תיקייה, ההצעה תופיע כאן לאישור — במקום שהמסווג
            ימציא תיקייה חדשה בעצמו.
          </p>
        </div>
        {editor === null && (
          <button
            onClick={() => setEditor(emptyEditor())}
            className="px-3 py-1.5 bg-accent text-white text-sm rounded-full"
          >
            + הוסף תיקייה
          </button>
        )}
      </header>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-900 text-sm">
          {error}
        </div>
      )}

      {suggestions.length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-bold text-ink mb-3 tracking-wide">
            הצעות ממתינות · {suggestions.length}
          </h2>
          <div className="space-y-2">
            {suggestions.map((s) => (
              <div
                key={s.id}
                className="p-3 bg-white border border-amber-300 rounded-md"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink">
                      {s.proposed_name}
                    </div>
                    {s.proposed_description && (
                      <div className="text-sm text-ink mt-1">
                        {s.proposed_description}
                      </div>
                    )}
                    {(s.source_title || s.source_summary) && (
                      <div className="text-xs text-ink-soft mt-2 italic">
                        מתוך: {s.source_title}
                        {s.source_summary
                          ? ` — ${s.source_summary}`
                          : ""}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button
                      onClick={() => void acceptSuggestion(s)}
                      disabled={busy}
                      className="text-xs px-2 py-1 bg-emerald-600 text-white hover:bg-emerald-700 rounded disabled:opacity-50"
                    >
                      קבל
                    </button>
                    <button
                      onClick={() => void rejectSuggestion(s)}
                      disabled={busy}
                      className="text-xs px-2 py-1 text-ink-soft hover:bg-stone-100 rounded"
                    >
                      דחה
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {editor && (
        <div className="mb-6 p-4 bg-white border border-accent/30 rounded-md">
          <div className="grid gap-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                שם תיקייה
              </label>
              <input
                value={editor.name}
                onChange={(e) => setEditor({ ...editor, name: e.target.value })}
                placeholder="למשל: רווחה"
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-ink-soft block mb-1">
                תיאור (משמש את המסווג — כתוב איזה סוג מסמכים שייכים לתיקייה)
              </label>
              <textarea
                value={editor.description}
                onChange={(e) =>
                  setEditor({ ...editor, description: e.target.value })
                }
                rows={2}
                placeholder="למשל: מסמכים על תשלומי רווחה, תמיכות סוציאליות, קרן חירום"
                className="w-full px-3 py-2 border border-line-strong rounded text-sm"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={editor.active}
                onChange={(e) =>
                  setEditor({ ...editor, active: e.target.checked })
                }
              />
              פעילה (זמינה למסווג האוטומטי)
            </label>
            <div className="flex gap-2 text-sm">
              <button
                onClick={save}
                disabled={busy || !editor.name.trim()}
                className="px-3 py-1.5 bg-accent text-white rounded disabled:opacity-50"
              >
                שמור
              </button>
              <button
                onClick={() => setEditor(null)}
                className="px-3 py-1.5 bg-line hover:bg-stone-200 rounded"
              >
                ביטול
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-ink-soft">טוען...</div>
      ) : folders.length === 0 && editor?.id !== "new" ? (
        <div className="text-ink-soft py-8 text-center">
          אין תיקיות עדיין. הוסף תיקייה ראשונה — המסווג ישבץ אליה מסמכים בהתאם
          לתיאור.
        </div>
      ) : (
        <div className="space-y-2">
          {folders.map((f) => (
            <div
              key={f.id}
              className={`bg-white border rounded-md p-4 ${
                f.active ? "border-line" : "border-line opacity-60"
              }`}
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-ink">{f.name}</span>
                    <span className="text-[10px] tracking-widest uppercase text-emerald-700 font-bold">
                      {f.doc_count} מסמכים
                    </span>
                    {!f.active && (
                      <span className="text-[10px] tracking-widest uppercase text-ink-soft font-bold">
                        לא פעילה
                      </span>
                    )}
                  </div>
                  {f.description && (
                    <div className="text-sm text-ink mt-1 whitespace-pre-wrap">
                      {f.description}
                    </div>
                  )}
                </div>
                <div className="flex flex-col gap-1 shrink-0">
                  <button
                    onClick={() => setEditor(editorFromItem(f))}
                    className="text-xs px-2 py-1 text-accent hover:bg-accent/10 rounded"
                  >
                    ערוך
                  </button>
                  <button
                    onClick={() => void remove(f)}
                    disabled={busy}
                    className="text-xs px-2 py-1 text-red-700 hover:bg-red-50 rounded"
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
