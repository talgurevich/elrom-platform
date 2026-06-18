import { useState } from "react";

const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

type Source = {
  chunk_id: string;
  document_filename: string;
  section_path: string | null;
  text: string;
};

type SearchResponse = {
  question: string;
  answer: string;
  confidence: "confident" | "uncertain" | "refused";
  sources: Source[];
  llm_used: boolean;
};

export default function App() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await fetch(`${API}/api/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!r.ok) throw new Error(await r.text());
      setResult(await r.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-stone-50 text-ink font-sans">
      <div className="max-w-3xl mx-auto px-6 py-10">
        <header className="mb-10">
          <div className="text-xs tracking-widest uppercase text-accent font-bold mb-1">אלרום</div>
          <h1 className="text-3xl font-bold">חיפוש בזיכרון הארגוני</h1>
          <p className="text-ink-soft mt-2">שאל שאלה בעברית. קבל תשובה מבוססת מקורות.</p>
        </header>

        <form onSubmit={submit} className="mb-8">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="לדוגמה: מה הוחלט בעניין קדימות לקומה שנייה?"
            rows={3}
            className="w-full px-4 py-3 border border-stone-300 rounded-md focus:border-accent focus:ring-2 focus:ring-accent/20 outline-none text-base"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="mt-3 px-6 py-2 bg-accent text-white font-semibold rounded-md disabled:opacity-50"
          >
            {loading ? "מחפש..." : "שאל"}
          </button>
        </form>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-md text-red-900 text-sm whitespace-pre-wrap">
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-6">
            <div className="p-5 bg-white border border-stone-200 rounded-md">
              <div className="text-xs tracking-wider uppercase text-accent font-bold mb-2">
                תשובה ({result.confidence === "confident" ? "מבוססת" : result.confidence === "uncertain" ? "חלקית" : "אין תשובה"})
              </div>
              <p className="text-lg leading-relaxed whitespace-pre-wrap">{result.answer}</p>
            </div>

            {result.sources.length > 0 && (
              <div>
                <div className="text-xs tracking-wider uppercase text-accent font-bold mb-3">מקורות</div>
                <div className="space-y-3">
                  {result.sources.map((s, i) => (
                    <div key={s.chunk_id} className="p-4 bg-white border border-stone-200 rounded-md">
                      <div className="text-xs text-ink-soft mb-1">
                        [{i + 1}] {s.document_filename}
                        {s.section_path && ` / ${s.section_path}`}
                      </div>
                      <div className="text-sm leading-relaxed whitespace-pre-wrap">{s.text}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
