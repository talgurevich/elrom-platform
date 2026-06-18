import { useState } from "react";
import Search from "./pages/Search";
import Review from "./pages/Review";
import Authoritative from "./pages/Authoritative";
import Lexicon from "./pages/Lexicon";

type Tab = "search" | "review" | "authoritative" | "lexicon";

const tabs: { id: Tab; label: string }[] = [
  { id: "search", label: "חיפוש" },
  { id: "review", label: "תור בדיקה" },
  { id: "authoritative", label: "תשובות מאושרות" },
  { id: "lexicon", label: "מילון" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("search");

  return (
    <div className="min-h-screen bg-stone-50 text-ink font-sans">
      <nav className="bg-white border-b border-stone-200 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-3 flex items-center gap-1">
          <div className="text-xs tracking-widest uppercase text-accent font-bold ml-4">אלרום</div>
          <div className="flex gap-1 text-sm">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 rounded ${
                  tab === t.id
                    ? "bg-accent text-white"
                    : "text-ink-soft hover:bg-stone-100 hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </nav>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {tab === "search" && <Search />}
        {tab === "review" && <Review />}
        {tab === "authoritative" && <Authoritative />}
        {tab === "lexicon" && <Lexicon />}
      </main>
    </div>
  );
}
