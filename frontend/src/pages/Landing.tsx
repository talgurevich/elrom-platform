import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

type Props = {
  onLogin: () => void;
};

type ContactStatus = "idle" | "sending" | "sent" | "error";

type QASample = {
  question: string;
  answer: string;
  source: string;
};

const HERO_SAMPLES: QASample[] = [
  {
    question: "מה קורה אם חבר לא שילם דמי חבר במשך שנתיים?",
    answer:
      "סעיף 12(ב) קובע כי חבר שאינו משלם דמי חבר במשך תקופה העולה על שנה — יוזמן לשימוע…",
    source: "תקנון עדכני · עמוד 4",
  },
  {
    question: "מתי אושרה תוספת הבנייה במגרשי הצעירים?",
    answer:
      "החלטת ועדת בינוי מיום 14.3.2024 (החלטה מס' 27/2024) אישרה תוספת של עד 40 מ״ר לכל יחידת דיור צעירה, בכפוף לאישור הוועדה המקומית…",
    source: "פרוטוקול ועדת בינוי · מרץ 2024",
  },
  {
    question: "מה הנוהל להעברת נחלה לבן ממשיך?",
    answer:
      "לפי נוהל העברות (סעיף 4), נדרשים אישור ועד הנהלה, הצהרת מס וחתימת שני עדים. הנוהל עודכן ב-2024 בעקבות החלטה 1553…",
    source: "נוהל העברות נחלה · עודכן 2024",
  },
];

const HERO_SAMPLE_INTERVAL_MS = 5500;

export default function Landing({ onLogin }: Props) {
  const [scrolled, setScrolled] = useState(false);
  const [contactName, setContactName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [contactMessage, setContactMessage] = useState("");
  const [contactStatus, setContactStatus] = useState<ContactStatus>("idle");
  const [contactError, setContactError] = useState<string | null>(null);
  const [activeSample, setActiveSample] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => {
      setActiveSample((i) => (i + 1) % HERO_SAMPLES.length);
    }, HERO_SAMPLE_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const submitContact = async (e: React.FormEvent) => {
    e.preventDefault();
    if (contactStatus === "sending") return;
    setContactStatus("sending");
    setContactError(null);
    try {
      await api.sendContact({
        name: contactName.trim(),
        email: contactEmail.trim(),
        phone: contactPhone.trim() || undefined,
        message: contactMessage.trim(),
      });
      setContactStatus("sent");
      setContactName("");
      setContactEmail("");
      setContactPhone("");
      setContactMessage("");
    } catch (err) {
      setContactStatus("error");
      setContactError(
        err instanceof Error && err.message
          ? "לא הצלחנו לשלוח את ההודעה. נסה שוב או שלח מייל ישירות."
          : "שגיאה לא ידועה."
      );
    }
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
              קלסר · זיכרון ארגוני
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
            <button onClick={() => scrollTo("contact")} className="hover:text-ink transition">
              יצירת קשר
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
              קלסר.
              <br />
              הזיכרון של הארגון,
              <br />
              <span className="text-accent">במרחק שאלה.</span>
            </h1>
            <p className="mt-6 text-lg md:text-xl text-ink-soft max-w-2xl leading-relaxed">
              קלסר בונה כלים לארגונים שמנהלים ידע מסמכי — תקנונים, פרוטוקולים,
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
              <div className="flex items-baseline justify-between mb-5">
                <div className="font-display font-black text-2xl text-ink tracking-tight leading-none">
                  דוגמה חיה
                </div>
                <span className="flex items-center gap-1.5" aria-hidden>
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
                  </span>
                  <span className="text-[10px] tracking-[0.2em] uppercase text-ink-soft font-bold">
                    Live
                  </span>
                </span>
              </div>

              {/* Fixed-height wrapper so cycling samples of different length
                  don't jerk the layout around. */}
              <div className="relative min-h-[240px]">
                <div key={activeSample} className="animate-fade-up">
                  <div className="border-r-2 border-accent pr-3 mb-4">
                    <div className="text-xs text-ink-soft mb-1">שאלה:</div>
                    <div className="text-sm font-semibold text-ink leading-snug">
                      {HERO_SAMPLES[activeSample].question}
                    </div>
                  </div>
                  <div className="border border-line p-3">
                    <div className="text-xs text-ink-soft mb-1">תשובה מהמקור:</div>
                    <div className="text-sm text-ink leading-relaxed">
                      {HERO_SAMPLES[activeSample].answer}
                    </div>
                    <div className="mt-3 text-[10px] tracking-widest uppercase text-accent font-bold">
                      מקור: {HERO_SAMPLES[activeSample].source}
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-4 border-t border-line flex items-center justify-center gap-2">
                {HERO_SAMPLES.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => setActiveSample(i)}
                    aria-label={`דוגמה ${i + 1}`}
                    className={`h-1.5 transition-all ${
                      i === activeSample
                        ? "w-8 bg-accent"
                        : "w-3 bg-line-strong hover:bg-ink-soft"
                    }`}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Benefits */}
      <section id="benefits" className="border-b border-ink">
        <div className="max-w-6xl mx-auto px-6 py-20 md:py-28">
          <div className="text-[11px] tracking-[0.3em] uppercase text-accent font-bold mb-3">
            למה קלסר
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
              קלסר נולד מתוך עבודה משותפת עם קיבוצים, מושבים וארגונים שבהם
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

      {/* Contact */}
      <section id="contact" className="border-b border-ink bg-line/20">
        <div className="max-w-4xl mx-auto px-6 py-20 md:py-24">
          <div className="mb-10">
            <div className="text-[10px] tracking-[0.25em] uppercase text-accent font-bold mb-3">
              יצירת קשר
            </div>
            <h2 className="font-display font-black text-3xl md:text-5xl leading-tight text-ink">
              מעוניינים לשמוע עוד?
            </h2>
            <p className="mt-4 text-ink-soft max-w-xl leading-relaxed">
              השאירו פרטים ונחזור אליכם. אפשר גם לשלוח מייל ישירות ל־
              <a href="mailto:tal.gurevich@elrom.tv" className="text-accent hover:underline">
                tal.gurevich@elrom.tv
              </a>
              .
            </p>
          </div>

          <form
            onSubmit={submitContact}
            className="bg-surface border border-line p-8 md:p-10 space-y-5"
            noValidate
          >
            <div className="grid md:grid-cols-2 gap-5">
              <label className="block">
                <span className="text-xs font-bold text-ink-soft tracking-[0.15em] uppercase">שם</span>
                <input
                  type="text"
                  required
                  maxLength={120}
                  value={contactName}
                  onChange={(e) => setContactName(e.target.value)}
                  disabled={contactStatus === "sending"}
                  className="mt-2 w-full border border-line px-4 py-3 text-ink bg-surface focus:outline-none focus:border-ink transition-colors"
                />
              </label>

              <label className="block">
                <span className="text-xs font-bold text-ink-soft tracking-[0.15em] uppercase">טלפון</span>
                <input
                  type="tel"
                  maxLength={40}
                  value={contactPhone}
                  onChange={(e) => setContactPhone(e.target.value)}
                  disabled={contactStatus === "sending"}
                  className="mt-2 w-full border border-line px-4 py-3 text-ink bg-surface focus:outline-none focus:border-ink transition-colors"
                />
              </label>
            </div>

            <label className="block">
              <span className="text-xs font-bold text-ink-soft tracking-[0.15em] uppercase">אימייל</span>
              <input
                type="email"
                required
                dir="ltr"
                value={contactEmail}
                onChange={(e) => setContactEmail(e.target.value)}
                disabled={contactStatus === "sending"}
                className="mt-2 w-full border border-line px-4 py-3 text-ink bg-surface focus:outline-none focus:border-ink transition-colors"
              />
            </label>

            <label className="block">
              <span className="text-xs font-bold text-ink-soft tracking-[0.15em] uppercase">הודעה</span>
              <textarea
                required
                rows={5}
                maxLength={4000}
                value={contactMessage}
                onChange={(e) => setContactMessage(e.target.value)}
                disabled={contactStatus === "sending"}
                className="mt-2 w-full border border-line px-4 py-3 text-ink bg-surface focus:outline-none focus:border-ink transition-colors resize-y"
              />
            </label>

            <div className="flex flex-col sm:flex-row sm:items-center gap-4 pt-2">
              <button
                type="submit"
                disabled={contactStatus === "sending" || contactStatus === "sent"}
                className="bg-ink text-surface px-8 py-3 text-sm font-bold hover:bg-accent transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {contactStatus === "sending" ? "שולח…" : contactStatus === "sent" ? "נשלח ✓" : "שלח הודעה ←"}
              </button>

              {contactStatus === "sent" && (
                <span className="text-sm text-accent font-medium">
                  תודה. נחזור אליכם בהקדם.
                </span>
              )}
              {contactStatus === "error" && contactError && (
                <span className="text-sm text-red-600">{contactError}</span>
              )}
            </div>
          </form>
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
              קלסר בונה זיכרון ארגוני חכם לארגונים מבוססי-מסמכים. מוצר הדגל
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
                <button onClick={() => scrollTo("contact")} className="hover:text-accent transition">
                  שלח לנו הודעה
                </button>
              </li>
              <li>
                <a href="mailto:tal.gurevich@elrom.tv" className="hover:text-accent transition">
                  tal.gurevich@elrom.tv
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
            <span className="flex items-center gap-3">
              <span>klaser.co.il</span>
              <span className="text-ink-soft/60">·</span>
              <span>
                Built by{" "}
                <a
                  href="https://errn.io"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-accent transition"
                >
                  errn.io
                </a>
              </span>
            </span>
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

/* Interactive grid: mouse repel + scroll-velocity-driven ripple.
   Straight at rest — the wave only appears while the user is actively
   scrolling and decays back to flat. Mouse repel is always on when the
   cursor is inside the hero. Vanilla canvas, single rAF loop, honors
   prefers-reduced-motion. */
function BackgroundMesh() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;

    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const SPACING = 44;
    const REPEL_RADIUS = 160;
    const REPEL_STRENGTH = 55;
    const WAVE_AMPLITUDE = 7;
    const WAVE_WAVELENGTH = 260;
    const COLOR = "rgba(23, 23, 23, 0.35)";
    const ACCENT = "rgba(184, 65, 43, 0.85)";
    const DOT_R = 1.1;

    let W = 0;
    let H = 0;
    const mouse = { x: -9999, y: -9999, active: false };
    let scrollY = window.scrollY || 0;
    let lastScrollY = scrollY;
    let waveEnergy = 0;
    let raf = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      W = rect.width;
      H = rect.height;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const onMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if (x >= 0 && x <= rect.width && y >= 0 && y <= rect.height) {
        mouse.x = x;
        mouse.y = y;
        mouse.active = true;
      } else {
        mouse.active = false;
      }
    };
    const onLeave = () => {
      mouse.active = false;
    };
    const onScroll = () => {
      const y = window.scrollY || 0;
      const delta = Math.abs(y - lastScrollY);
      lastScrollY = y;
      scrollY = y;
      waveEnergy = Math.min(1, waveEnergy + delta * 0.02);
    };
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("mouseleave", onLeave, { passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });

    const nodeAt = (cx: number, cy: number, phase: number, amp: number) => {
      const bx = -SPACING + cx * SPACING;
      const by = -SPACING + cy * SPACING;
      const wave =
        amp === 0
          ? 0
          : Math.sin(((bx + by) / WAVE_WAVELENGTH) * Math.PI * 2 + phase) * amp;
      let x = bx + wave * 0.6;
      let y = by + wave;
      if (mouse.active) {
        const dx = x - mouse.x;
        const dy = y - mouse.y;
        const d2 = dx * dx + dy * dy;
        const r2 = REPEL_RADIUS * REPEL_RADIUS;
        if (d2 < r2 && d2 > 0.01) {
          const d = Math.sqrt(d2);
          const falloff = 1 - d / REPEL_RADIUS;
          const push = REPEL_STRENGTH * falloff * falloff;
          x += (dx / d) * push;
          y += (dy / d) * push;
        }
      }
      return { x, y };
    };

    const strokeNear = (mx: number, my: number) => {
      if (!mouse.active) return COLOR;
      const dx = mx - mouse.x;
      const dy = my - mouse.y;
      const d2 = dx * dx + dy * dy;
      if (d2 < REPEL_RADIUS * REPEL_RADIUS) {
        const t = 1 - Math.sqrt(d2) / REPEL_RADIUS;
        if (t > 0.5) return ACCENT;
      }
      return COLOR;
    };

    const render = () => {
      ctx.clearRect(0, 0, W, H);
      const cols = Math.ceil(W / SPACING) + 2;
      const rows = Math.ceil(H / SPACING) + 2;
      const phase = scrollY * 0.008;
      const amp = WAVE_AMPLITUDE * waveEnergy;
      waveEnergy *= 0.94;
      if (waveEnergy < 0.001) waveEnergy = 0;

      let prev: { x: number; y: number }[] = new Array(rows);
      let cur: { x: number; y: number }[] = new Array(rows);
      for (let r = 0; r < rows; r++) prev[r] = nodeAt(0, r, phase, amp);

      ctx.lineWidth = 1;
      for (let c = 1; c < cols; c++) {
        for (let r = 0; r < rows; r++) cur[r] = nodeAt(c, r, phase, amp);
        for (let r = 0; r < rows; r++) {
          const a = prev[r];
          const b = cur[r];
          ctx.strokeStyle = strokeNear((a.x + b.x) * 0.5, (a.y + b.y) * 0.5);
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
          if (r > 0) {
            const top = cur[r - 1];
            ctx.strokeStyle = strokeNear((top.x + b.x) * 0.5, (top.y + b.y) * 0.5);
            ctx.beginPath();
            ctx.moveTo(top.x, top.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
        const tmp = prev;
        prev = cur;
        cur = tmp;
      }

      for (let cc = 0; cc < cols; cc++) {
        for (let rr = 0; rr < rows; rr++) {
          const n = nodeAt(cc, rr, phase, amp);
          ctx.fillStyle = strokeNear(n.x, n.y);
          ctx.beginPath();
          ctx.arc(n.x, n.y, DOT_R, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      raf = requestAnimationFrame(render);
    };
    raf = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseleave", onLeave);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full opacity-40 pointer-events-none"
      aria-hidden="true"
    />
  );
}
