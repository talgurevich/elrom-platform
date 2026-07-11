import { useEffect, useState } from "react";

type Props = {
  onLogin: () => void;
};

export default function Landing({ onLogin }: Props) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="min-h-screen bg-surface text-ink font-sans flex flex-col">
      <header
        className={`sticky top-0 z-40 bg-surface border-b transition-colors ${
          scrolled ? "border-ink" : "border-line"
        }`}
      >
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-baseline gap-3">
            <span className="font-display font-black text-2xl leading-none tracking-tight text-ink">
              Klaser
            </span>
            <span className="hidden sm:inline text-[10px] tracking-[0.25em] uppercase text-ink-soft border-r border-line-strong pr-3">
              קלאסר · זיכרון ארגוני
            </span>
          </div>

          <nav className="hidden md:flex items-center gap-6 text-sm text-ink-soft">
            <button onClick={() => scrollTo("benefits")} className="hover:text-ink transition">
              יתרונות
            </button>
            <button onClick={() => scrollTo("products")} className="hover:text-ink transition">
              מוצרים
            </button>
            <button onClick={() => scrollTo("about")} className="hover:text-ink transition">
              עלינו
            </button>
          </nav>

          <button
            onClick={onLogin}
            className="bg-ink text-surface px-5 py-2.5 text-sm font-bold hover:bg-accent transition-colors"
          >
            כניסה למערכת ←
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-ink">
        <BackgroundMesh />
        <div className="relative max-w-6xl mx-auto px-6 py-24 md:py-32 grid md:grid-cols-12 gap-10 items-center">
          <div className="md:col-span-8">
            <div className="text-[11px] tracking-[0.3em] uppercase text-accent font-bold mb-4">
              Klaser · הפלטפורמה שהופכת מסמכים לזיכרון פעיל
            </div>
            <h1 className="font-display font-black leading-[0.95] text-5xl md:text-7xl text-ink">
              קלאסר.
              <br />
              הזיכרון של הארגון,
              <br />
              <span className="text-accent">בהישג שאלה.</span>
            </h1>
            <p className="mt-6 text-lg md:text-xl text-ink-soft max-w-2xl leading-relaxed">
              קלאסר בונה כלים לארגונים שמנהלים ידע מסמכי — תקנונים, פרוטוקולים,
              נהלים ותקדימים. במקום לחפש שעות בקבצים, שואלים שאלה ומקבלים תשובה
              מבוססת מקור.
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-4">
              <button
                onClick={onLogin}
                className="bg-accent text-surface px-8 py-4 text-base font-bold hover:bg-accent-dark transition-colors shadow-lift"
              >
                כניסה למערכת ←
              </button>
              <button
                onClick={() => scrollTo("products")}
                className="border-2 border-ink text-ink px-8 py-4 text-base font-bold hover:bg-ink hover:text-surface transition-colors"
              >
                למה זה טוב לי?
              </button>
            </div>
            <div className="mt-8 flex flex-wrap items-center gap-6 text-xs text-ink-soft">
              <span className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-accent inline-block" />
                תשובות עם ציטוטים מהמקור
              </span>
              <span className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-accent inline-block" />
                עברית מלאה · RTL
              </span>
              <span className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-accent inline-block" />
                מותאם לקיבוצים, מושבים וארגונים
              </span>
            </div>
          </div>

          <div className="md:col-span-4 hidden md:block">
            <div className="border-2 border-ink bg-surface p-6 shadow-lift">
              <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-3">
                דוגמה חיה
              </div>
              <div className="border-r-2 border-accent pr-3 mb-4">
                <div className="text-xs text-ink-soft mb-1">שאלה:</div>
                <div className="text-sm font-semibold text-ink">
                  מה קורה אם חבר לא שילם דמי חבר במשך שנתיים?
                </div>
              </div>
              <div className="border border-line p-3">
                <div className="text-xs text-ink-soft mb-1">תשובה מהתקנון:</div>
                <div className="text-sm text-ink leading-relaxed">
                  סעיף 12(ב) קובע כי חבר שאינו משלם דמי חבר במשך תקופה העולה על
                  שנה — יוזמן לשימוע…
                </div>
                <div className="mt-3 text-[10px] tracking-widest uppercase text-accent font-bold">
                  מקור: תקנון עדכני · עמוד 4
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Benefits */}
      <section id="benefits" className="border-b border-ink">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-28">
          <div className="text-[11px] tracking-[0.3em] uppercase text-accent font-bold mb-3">
            למה קלאסר
          </div>
          <h2 className="font-display font-black text-4xl md:text-5xl text-ink leading-tight max-w-3xl">
            מהיר יותר. מדויק יותר. עם מקור.
          </h2>
          <div className="mt-14 grid md:grid-cols-3 gap-px bg-ink border border-ink">
            {BENEFITS.map((b) => (
              <div key={b.title} className="bg-surface p-8">
                <div className="text-4xl font-display font-black text-accent leading-none">
                  {b.num}
                </div>
                <h3 className="mt-4 font-display font-black text-xl text-ink">
                  {b.title}
                </h3>
                <p className="mt-3 text-sm text-ink-soft leading-relaxed">
                  {b.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Products */}
      <section id="products" className="border-b border-ink bg-line/20">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-28">
          <div className="text-[11px] tracking-[0.3em] uppercase text-accent font-bold mb-3">
            המוצרים שלנו
          </div>
          <h2 className="font-display font-black text-4xl md:text-5xl text-ink leading-tight max-w-3xl">
            כלים ממוקדים. לא עוד פלטפורמה גנרית.
          </h2>

          <div className="mt-14 grid md:grid-cols-3 gap-6">
            {/* Featured product — Takanon */}
            <div className="md:col-span-2 border-2 border-ink bg-surface p-10 relative">
              <span className="absolute top-6 left-6 text-[10px] tracking-[0.25em] uppercase text-surface bg-accent px-2 py-1 font-bold">
                מוצר דגל
              </span>
              <div className="text-[11px] tracking-[0.3em] uppercase text-ink-soft font-bold mb-2">
                Takanon
              </div>
              <h3 className="font-display font-black text-4xl md:text-5xl text-ink">
                תקנון
              </h3>
              <p className="mt-4 text-base text-ink-soft leading-relaxed max-w-xl">
                שיחה חכמה עם התקנון של הארגון שלכם. תקנון קורא, מבין וממפה את
                המסמכים המחייבים — ומחזיר תשובות מדויקות עם ציטוט מהמקור, כולל
                מעקב אחר תיקונים ואישורי ועדה.
              </p>
              <ul className="mt-6 grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm text-ink">
                <li className="flex gap-2">
                  <span className="text-accent font-bold">←</span>
                  חיפוש סמנטי בעברית
                </li>
                <li className="flex gap-2">
                  <span className="text-accent font-bold">←</span>
                  ציטוטים ישירים מהתקנון
                </li>
                <li className="flex gap-2">
                  <span className="text-accent font-bold">←</span>
                  מעקב תיקונים ואמנדמנטים
                </li>
                <li className="flex gap-2">
                  <span className="text-accent font-bold">←</span>
                  תשובות מאושרות ע"י ועדה
                </li>
                <li className="flex gap-2">
                  <span className="text-accent font-bold">←</span>
                  מילון מונחים ארגוני
                </li>
                <li className="flex gap-2">
                  <span className="text-accent font-bold">←</span>
                  תור בדיקה לאיכות תשובות
                </li>
              </ul>
              <button
                onClick={onLogin}
                className="mt-10 bg-ink text-surface px-6 py-3 text-sm font-bold hover:bg-accent transition-colors"
              >
                כניסה לתקנון ←
              </button>
            </div>

            {/* Coming soon */}
            <div className="border-2 border-dashed border-line-strong bg-surface p-8 flex flex-col">
              <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-4">
                בקרוב
              </div>
              <h3 className="font-display font-black text-2xl text-ink leading-tight">
                מוצרים נוספים בפיתוח
              </h3>
              <p className="mt-3 text-sm text-ink-soft leading-relaxed flex-1">
                אנחנו בונים כלים נוספים סביב זיכרון ארגוני — פרוטוקולים,
                החלטות ועד, ניהול תקדימים ותשובות מאושרות בין-ארגוניות.
              </p>
              <div className="mt-6 pt-6 border-t border-line space-y-3 text-xs text-ink-soft">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-line-strong inline-block" />
                  פרוטוקולים חכמים
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-line-strong inline-block" />
                  ארכיון החלטות
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-line-strong inline-block" />
                  מאגר תקדימים
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* About */}
      <section id="about" className="border-b border-ink">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-28 grid md:grid-cols-12 gap-10">
          <div className="md:col-span-5">
            <div className="text-[11px] tracking-[0.3em] uppercase text-accent font-bold mb-3">
              עלינו
            </div>
            <h2 className="font-display font-black text-4xl md:text-5xl text-ink leading-tight">
              נבנה עם ארגונים,
              <br />
              לא עבורם.
            </h2>
          </div>
          <div className="md:col-span-7 text-lg text-ink-soft leading-relaxed space-y-6">
            <p>
              קלאסר נולד מתוך עבודה משותפת עם קיבוצים, מושבים וארגונים שבהם
              המסמכים המחייבים — התקנון, הפרוטוקולים, ההחלטות — הם ליבת
              ההתנהלות היומיומית.
            </p>
            <p>
              במקום להציע פלטפורמת AI גנרית, אנחנו בונים כלים ממוקדים לבעיות
              אמיתיות: להביא את התשובה הנכונה, מהמקור הנכון, בזמן שצריך אותה.
            </p>
            <p className="text-ink font-semibold">
              הידע כבר קיים בארגון. אנחנו רק דואגים שהוא יהיה זמין.
            </p>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="bg-ink text-surface">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-24 flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
          <div>
            <h2 className="font-display font-black text-3xl md:text-5xl leading-tight">
              מוכנים להתחיל?
            </h2>
            <p className="mt-3 text-surface/70 max-w-lg">
              היכנסו למערכת עם חשבון Google מאושר. הגישה מוגבלת למשתמשים
              רשומים בלבד.
            </p>
          </div>
          <button
            onClick={onLogin}
            className="bg-accent text-surface px-10 py-5 text-lg font-bold hover:bg-accent-light transition-colors"
          >
            כניסה למערכת ←
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-surface border-t border-ink mt-auto">
        <div className="max-w-6xl mx-auto px-6 py-10 grid md:grid-cols-4 gap-8">
          <div className="md:col-span-2">
            <div className="font-display font-black text-2xl text-ink">Klaser</div>
            <p className="mt-3 text-sm text-ink-soft max-w-sm leading-relaxed">
              קלאסר בונה זיכרון ארגוני חכם לארגונים מבוססי-מסמכים. מוצר הדגל
              שלנו — תקנון — כבר משרת קיבוצים ומושבים.
            </p>
          </div>
          <div>
            <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-3">
              מוצרים
            </div>
            <ul className="space-y-2 text-sm text-ink">
              <li>
                <button onClick={onLogin} className="hover:text-accent transition">
                  תקנון
                </button>
              </li>
              <li>
                <span className="text-ink-soft">פרוטוקולים · בקרוב</span>
              </li>
            </ul>
          </div>
          <div>
            <div className="text-[10px] tracking-[0.25em] uppercase text-ink-soft font-bold mb-3">
              יצירת קשר
            </div>
            <ul className="space-y-2 text-sm text-ink">
              <li>
                <a href="mailto:tal@elrom.tv" className="hover:text-accent transition">
                  tal@elrom.tv
                </a>
              </li>
              <li>
                <button onClick={onLogin} className="hover:text-accent transition">
                  כניסה למערכת
                </button>
              </li>
            </ul>
          </div>
        </div>
        <div className="border-t border-line">
          <div className="max-w-6xl mx-auto px-6 py-5 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-soft">
            <span>© {new Date().getFullYear()} Klaser · כל הזכויות שמורות</span>
            <span>klaser.co.il</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

const BENEFITS = [
  {
    num: "01",
    title: "מקור לכל תשובה",
    body: "כל תשובה מגיעה עם ציטוט ישיר וקישור למסמך המקור. לא ניחושים, לא הזיות — רק מה שכתוב.",
  },
  {
    num: "02",
    title: "עברית שמבינה עברית",
    body: "בנוי מהיסוד לעברית — מכיר את הטיות השורש, את הניואנסים ואת המונחים הארגוניים הייחודיים.",
  },
  {
    num: "03",
    title: "מעקב אחר שינויים",
    body: "תיקונים ואישורי ועדה מסומנים אוטומטית. תמיד יודעים מה הגרסה התקפה של כל סעיף.",
  },
];

function BackgroundMesh() {
  return (
    <svg
      className="absolute inset-0 w-full h-full opacity-[0.06] pointer-events-none"
      viewBox="0 0 1200 800"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <defs>
        <pattern
          id="landing-grid"
          width="40"
          height="40"
          patternUnits="userSpaceOnUse"
        >
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#171717" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="1200" height="800" fill="url(#landing-grid)" />
    </svg>
  );
}
