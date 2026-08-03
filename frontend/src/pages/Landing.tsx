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
    <div className="min-h-screen bg-white text-[#191919] font-sans flex flex-col">
      {/* Header — turquoise bg, white text (Klaser DS) */}
      <header className="sticky top-0 z-40 bg-turquoise text-white">
        <div className="max-w-6xl mx-auto px-8 h-16 flex items-center justify-between gap-4">
          {/* Brand — DOM first → right in RTL */}
          <div className="flex items-baseline gap-4">
            {/* Klaser wordmark — Heebo Black 24 */}
            <span className="font-sans font-black text-2xl leading-none tracking-tight">
              Klaser
            </span>
            {/* Tagline — Heebo Regular 10 uppercase tracking 2.5 */}
            <span className="hidden sm:inline font-sans text-[10px] tracking-[0.25em] uppercase text-white/80 border-r border-white/30 pr-4">
              קלסר · זיכרון ארגוני
            </span>
          </div>

          {/* Nav — Small 14 (Rubik Regular 14) white */}
          <nav className="hidden md:flex items-center gap-8 font-rubik text-sm">
            <button onClick={() => scrollTo("benefits")} className="hover:text-white/70 transition">
              יתרונות
            </button>
            <button onClick={() => scrollTo("products")} className="hover:text-white/70 transition">
              מוצרים
            </button>
            <button onClick={() => scrollTo("about")} className="hover:text-white/70 transition">
              עלינו
            </button>
            <button onClick={() => scrollTo("faq")} className="hover:text-white/70 transition">
              שאלות נפוצות
            </button>
            <button onClick={() => scrollTo("contact")} className="hover:text-white/70 transition">
              יצירת קשר
            </button>
          </nav>

          {/* Login CTA — DOM last → left in RTL. Transparent + 2px white border. */}
          <button
            onClick={onLogin}
            className="inline-flex items-center gap-2 bg-transparent border-2 border-white text-white h-10 px-4 rounded-md font-rubik font-bold text-sm hover:bg-white hover:text-turquoise transition-colors"
          >
            <span>כניסה למערכת</span>
            <ArrowCircleLeft />
          </button>
        </div>
      </header>

      <main>
        {/* Dotted region — binder-hole decoration spans hero → contact.
            Excluded from Dark CTA + Footer per Figma. */}
        <div className="relative">
          <BinderHoles />
          {/* Hero — Klaser DS tokens: H5 eyebrow, H1 headline, Body 2 subtitle, Caption chips */}
          <section
          className="relative overflow-hidden bg-white border-b-2 border-turquoise/15"
          aria-labelledby="hero-title"
        >
          <BackgroundMesh />
          <div className="relative max-w-6xl mx-auto px-8 py-24 grid md:grid-cols-12 gap-12 items-center">
            {/* Copy — DOM first → visually right in RTL */}
            <div className="md:col-span-7">
              {/* H5 eyebrow — Rubik Bold 16, tracking 25% */}
              <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-8">
                Klaser · הפלטפורמה שהופכת מסמכים לזיכרון פעיל
              </div>

              {/* H1 — Rubik Bold 72/72 */}
              <h1
                id="hero-title"
                className="font-rubik font-bold text-5xl md:text-[72px] md:leading-[72px] text-turquoise"
              >
                <span className="text-[#191919]">קלסר.</span>
                <br />
                הזיכרון של הארגון,
                <br />
                במרחק שאלה.
              </h1>

              {/* Body 2 — Heebo Regular 20 */}
              <p className="mt-8 font-sans text-xl leading-relaxed text-[#525252] max-w-xl">
                קלסר בונה כלים לארגונים שמנהלים ידע מסמכי — תקנונים, פרוטוקולים, נהלים ותקדימים. במקום לחפש שעות בקבצים, שואלים שאלה ומקבלים תשובה מבוססת מקור.
              </p>

              {/* CTAs — Rubik Bold 16, 4px radius per DS */}
              <div className="mt-12 flex flex-wrap items-center gap-4">
                <button
                  onClick={onLogin}
                  className="inline-flex items-center gap-2 bg-turquoise text-white h-12 px-8 rounded-md font-rubik font-bold text-base hover:bg-turquoise-dark transition-colors"
                >
                  <span>כניסה למערכת</span>
                  <ArrowCircleLeft />
                </button>
                <button
                  onClick={() => scrollTo("products")}
                  className="inline-flex items-center gap-2 bg-white border-2 border-turquoise text-turquoise h-12 px-8 rounded-md font-rubik font-bold text-base hover:bg-turquoise hover:text-white transition-colors"
                >
                  <span>למה זה טוב לי?</span>
                </button>
              </div>

              {/* Trust chips — Caption (Rubik Regular 12) */}
              <div className="mt-8 flex flex-wrap gap-x-8 gap-y-4 font-rubik text-xs text-[#525252]">
                <span className="flex items-center gap-2">
                  <TurquoiseDot />
                  תשובות עם ציטוטים מהמקור
                </span>
                <span className="flex items-center gap-2">
                  <TurquoiseDot />
                  עברית מלאה · RTL
                </span>
                <span className="flex items-center gap-2">
                  <TurquoiseDot />
                  מותאם לקיבוצים, מושבים וארגונים
                </span>
              </div>
            </div>

            {/* Live demo card — DOM last → visually left in RTL */}
            <div className="md:col-span-5 hidden md:block">
              <div className="bg-white rounded-lg p-8 shadow-[0px_2px_0_rgba(0,0,0,0.05),0px_4px_24px_0px_rgba(0,0,0,0.08)] border border-[#e7e5e4]">
                <div className="flex items-baseline justify-between mb-8">
                  {/* Card title — Body 2 bold (Heebo Bold 20) */}
                  <h2 className="font-sans font-bold text-xl text-[#191919] leading-none">
                    דוגמה חיה
                  </h2>
                  <span className="flex items-center gap-2" aria-hidden>
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-turquoise opacity-60" />
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-turquoise" />
                    </span>
                    <span className="font-rubik font-bold text-[10px] uppercase tracking-[0.2em] text-[#525252]">
                      Live
                    </span>
                  </span>
                </div>

                {/* Fixed-height wrapper so cycling samples don't jerk the layout. */}
                <div className="relative min-h-[240px]">
                  <div key={activeSample} className="animate-fade-up">
                    <div className="border-r-2 border-turquoise pr-4 mb-4">
                      {/* Label — Caption */}
                      <div className="font-rubik text-xs text-[#525252] mb-2">שאלה:</div>
                      {/* Question body — Small 14 bold */}
                      <div className="font-rubik font-bold text-sm text-[#191919] leading-snug">
                        {HERO_SAMPLES[activeSample].question}
                      </div>
                    </div>
                    <div className="border border-[#e7e5e4] rounded-md p-4">
                      <div className="font-rubik text-xs text-[#525252] mb-2">תשובה מהמקור:</div>
                      {/* Answer body — Small 14 */}
                      <div className="font-rubik text-sm text-[#191919] leading-relaxed">
                        {HERO_SAMPLES[activeSample].answer}
                      </div>
                      {/* Source — Caption uppercase teal */}
                      <div className="mt-4 font-rubik font-bold text-[10px] uppercase tracking-widest text-turquoise">
                        מקור: {HERO_SAMPLES[activeSample].source}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-4 pt-4 border-t border-[#e7e5e4] flex items-center justify-center gap-2">
                  {HERO_SAMPLES.map((_, i) => (
                    <button
                      key={i}
                      onClick={() => setActiveSample(i)}
                      aria-label={`דוגמה ${i + 1}`}
                      className={`h-1 rounded-full transition-all ${
                        i === activeSample
                          ? "w-8 bg-turquoise"
                          : "w-4 bg-[#e7e5e4] hover:bg-[#525252]"
                      }`}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Benefits — DS: H5 eyebrow, H2 title, H3 card titles, Body card bodies */}
        <section id="benefits" className="bg-white" aria-labelledby="benefits-title">
          <div className="max-w-6xl mx-auto px-8 py-24">
            <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4 text-right">
              למה קלסר
            </div>
            <h2
              id="benefits-title"
              className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-[#191919] text-right"
            >
              מהיר יותר. מדויק יותר. עם מקור.
            </h2>

            <div className="mt-16 grid md:grid-cols-3 gap-8">
              {BENEFITS.map((b) => (
                <div key={b.title}>
                  <BenefitIcon name={b.icon} />
                  {/* H3 — Rubik Bold 32 */}
                  <h3 className="mt-8 font-rubik font-bold text-[32px] leading-tight text-[#191919]">
                    {b.title}
                  </h3>
                  {/* Body — Heebo Regular 18 */}
                  <p className="mt-4 text-lg leading-relaxed text-[#525252]">
                    {b.body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Products — Coming Soon + Takanon flagship */}
        <section
          id="products"
          className="bg-white border-t border-[#e7e5e4]"
          aria-labelledby="products-title"
        >
          <div className="max-w-6xl mx-auto px-8 py-24">
            <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4 text-right">
              המוצרים שלנו
            </div>
            <h2
              id="products-title"
              className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-[#191919] text-right"
            >
              כלים ממוקדים. לא עוד פלטפורמה גנרית.
            </h2>

            <div className="mt-16 grid md:grid-cols-3 gap-8">
              {/* Takanon flagship — 2 cols. DOM first → visually RIGHT in RTL. */}
              <div className="md:col-span-2 relative bg-white rounded-lg p-8 md:p-12 border border-turquoise/15">
                <span className="absolute top-8 left-8 inline-flex items-center gap-2 font-rubik font-bold text-xs uppercase tracking-[0.2em] text-white bg-[#ff7c2a] rounded px-2 py-1">
                  <AwardIcon />
                  מוצר דגל
                </span>
                {/* H2 for product title (matches Figma extraction — Rubik Bold 48) */}
                <h3 className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-[#191919]">
                  תקנון
                </h3>
                {/* Body */}
                <p className="mt-4 text-lg leading-relaxed text-[#525252] max-w-xl">
                  שיחה חכמה עם התקנון של הארגון שלכם. תקנון קורא, מבין וממפה את המסמכים המחייבים — ומחזיר תשובות מדויקות עם ציטוט מהמקור, כולל מעקב אחר תיקונים ואישורי ועדה.
                </p>
                <ul className="mt-8 grid sm:grid-cols-2 gap-x-8 gap-y-4">
                  {TAKANON_FEATURES.map((f) => (
                    <li key={f} className="flex items-center gap-2 font-rubik text-sm text-[#191919]">
                      <CheckIcon />
                      {f}
                    </li>
                  ))}
                </ul>
                {/* CTA — Rubik Bold 16 */}
                <button
                  onClick={onLogin}
                  className="mt-12 inline-flex items-center gap-2 bg-turquoise text-white h-12 px-8 rounded-md font-rubik font-bold text-base hover:bg-turquoise-dark transition-colors"
                >
                  <span>לתקנון</span>
                  <ArrowCircleLeft />
                </button>
              </div>

              {/* אוגדן — meetings product, 1 col. DOM last → visually LEFT in RTL. */}
              <div className="bg-white rounded-lg p-8 border border-[#e7e5e4]">
                <span className="inline-block font-rubik font-bold text-xs uppercase tracking-[0.2em] text-turquoise border border-turquoise/30 rounded px-2 py-1">
                  חדש
                </span>
                {/* H4 — Rubik Bold 24 */}
                <h3 className="mt-8 font-rubik font-bold text-2xl text-[#191919]">
                  אוגדן
                </h3>
                {/* Body */}
                <p className="mt-4 text-lg leading-relaxed text-[#525252]">
                  ניהול ישיבות ופרוטוקולים מקצה לקצה. אוגדן מקליט, מתמלל ומסכם ישיבות בעברית, והופך כל החלטה למשימה עם אחראי ויעד.
                </p>
                <ul className="mt-8 space-y-4">
                  {OGDAN_FEATURES.map((f) => (
                    <li key={f} className="flex items-center gap-2 font-rubik text-sm text-[#525252]">
                      <CheckIcon />
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* About — H5 eyebrow, H2 teal, Body paragraphs, Body 2 bold closer */}
        <section id="about" className="relative overflow-hidden bg-white border-y border-[#e7e5e4]" aria-labelledby="about-title">
          <BackgroundMesh />
          <div className="relative max-w-6xl mx-auto px-8 py-24 grid md:grid-cols-12 gap-12 items-start">
            {/* Title — DOM first → right in RTL */}
            <div className="md:col-span-5">
              <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4">
                עלינו
              </div>
              <h2
                id="about-title"
                className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-turquoise"
              >
                נבנה עם ארגונים,
                <br />
                לא עבורם.
              </h2>
            </div>
            {/* Copy — DOM last → left in RTL */}
            <div className="md:col-span-7">
              <p className="text-lg leading-relaxed text-[#525252]">
                קלסר נולד מתוך עבודה משותפת עם קיבוצים, מושבים וארגונים שבהם המסמכים המחייבים — התקנון, הפרוטוקולים, ההחלטות — הם ליבת ההתנהלות היומיומית.
              </p>
              <p className="mt-4 text-lg leading-relaxed text-[#525252]">
                במקום להציע פלטפורמת AI גנרית, אנחנו בונים כלים ממוקדים לבעיות אמיתיות: להביא את התשובה הנכונה, מהמקור הנכון, בזמן שצריך אותה.
              </p>
              {/* Body 2 bold closer */}
              <p className="mt-8 font-sans font-bold text-xl leading-relaxed text-[#191919]">
                הידע כבר קיים בארגון. אנחנו רק דואגים שהוא יהיה זמין.
              </p>
            </div>
          </div>
        </section>

        {/* FAQ — H5 eyebrow, H2 centered title, Body intro, Body 2 bold questions */}
        <section id="faq" className="bg-white" aria-labelledby="faq-title">
          <div className="max-w-3xl mx-auto px-8 py-24">
            <div className="mb-12 text-right">
              <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4">
                שאלות נפוצות
              </div>
              <h2
                id="faq-title"
                className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-[#191919]"
              >
                מה שאנשים שואלים אותנו הכי הרבה.
              </h2>
              <p className="mt-4 text-lg text-[#525252] leading-relaxed max-w-2xl">
                שאלות תמימות זוכות לתשובות ישרות. חסר לכם משהו? כתבו לנו בטופס למטה.
              </p>
            </div>

            <div className="bg-white rounded-lg border border-[#e7e5e4] divide-y divide-[#e7e5e4]">
              {FAQ_ITEMS.map((item, i) => (
                <details key={i} className="group">
                  <summary className="cursor-pointer list-none py-4 px-8 flex items-start justify-between gap-4 hover:bg-[#fafaf9] transition rounded-lg">
                    {/* Body 2 bold — Heebo Bold 20 */}
                    <h3 className="font-sans font-bold text-xl text-[#191919] leading-snug">
                      {item.q}
                    </h3>
                    <span
                      aria-hidden="true"
                      className="mt-1 shrink-0 w-8 h-8 flex items-center justify-center rounded-full bg-turquoise/10 text-turquoise transition-transform group-open:rotate-45"
                    >
                      <PlusIcon />
                    </span>
                  </summary>
                  {/* Body */}
                  <div className="pb-8 px-8 text-lg leading-relaxed text-[#525252] whitespace-pre-line">
                    {item.a}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* Contact — H5 eyebrow, H2 title, Body description, form */}
        <section
          id="contact"
          className="bg-turquoise/5"
          aria-labelledby="contact-title"
        >
          <div className="max-w-3xl mx-auto px-8 py-24">
            <div className="mb-12 text-right">
              <div className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-turquoise mb-4">
                יצירת קשר
              </div>
              <h2
                id="contact-title"
                className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px] text-[#191919]"
              >
                מעוניינים לשמוע עוד?
              </h2>
              <p className="mt-4 text-lg text-[#525252] leading-relaxed max-w-xl">
                השאירו פרטים ונחזור אליכם. אפשר גם לשלוח מייל ישירות ל־
                <a href="mailto:tal.gurevich@elrom.tv" className="text-turquoise hover:underline">
                  tal.gurevich@elrom.tv
                </a>
                .
              </p>
            </div>

            <form
              onSubmit={submitContact}
              className="bg-white border border-[#e7e5e4] rounded-lg p-8 md:p-12 space-y-4"
              noValidate
            >
              <div className="grid md:grid-cols-2 gap-4">
                <label className="block">
                  <span className="font-rubik text-sm text-[#525252]">שם</span>
                  <input
                    type="text"
                    required
                    maxLength={120}
                    value={contactName}
                    onChange={(e) => setContactName(e.target.value)}
                    disabled={contactStatus === "sending"}
                    className="mt-2 w-full h-12 px-4 rounded-md border border-[#e7e5e4] text-[#191919] bg-white focus:outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition-colors"
                  />
                </label>

                <label className="block">
                  <span className="font-rubik text-sm text-[#525252]">טלפון</span>
                  <input
                    type="tel"
                    maxLength={40}
                    value={contactPhone}
                    onChange={(e) => setContactPhone(e.target.value)}
                    disabled={contactStatus === "sending"}
                    className="mt-2 w-full h-12 px-4 rounded-md border border-[#e7e5e4] text-[#191919] bg-white focus:outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition-colors"
                  />
                </label>
              </div>

              <label className="block">
                <span className="font-rubik text-sm text-[#525252]">אימייל</span>
                <input
                  type="email"
                  required
                  dir="ltr"
                  value={contactEmail}
                  onChange={(e) => setContactEmail(e.target.value)}
                  disabled={contactStatus === "sending"}
                  className="mt-2 w-full h-12 px-4 rounded-md border border-[#e7e5e4] text-[#191919] bg-white focus:outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition-colors text-right"
                />
              </label>

              <label className="block">
                <span className="font-rubik text-sm text-[#525252]">הודעה</span>
                <textarea
                  required
                  rows={5}
                  maxLength={4000}
                  value={contactMessage}
                  onChange={(e) => setContactMessage(e.target.value)}
                  disabled={contactStatus === "sending"}
                  className="mt-2 w-full px-4 py-4 rounded-md border border-[#e7e5e4] text-[#191919] bg-white focus:outline-none focus:border-turquoise focus:ring-2 focus:ring-turquoise/20 transition-colors resize-y"
                />
              </label>

              <div className="flex flex-col sm:flex-row sm:items-center gap-4 pt-4 justify-end">
                <button
                  type="submit"
                  disabled={contactStatus === "sending" || contactStatus === "sent"}
                  className="inline-flex items-center gap-2 bg-turquoise text-white h-12 px-8 rounded-md font-rubik font-bold text-base hover:bg-turquoise-dark transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {contactStatus === "sending" ? (
                    <span>שולח…</span>
                  ) : contactStatus === "sent" ? (
                    <span>נשלח ✓</span>
                  ) : (
                    <>
                      <span>שלח הודעה</span>
                      <ArrowCircleLeft />
                    </>
                  )}
                </button>

                {contactStatus === "sent" && (
                  <span className="font-rubik text-sm text-turquoise font-medium">
                    תודה. נחזור אליכם בהקדם.
                  </span>
                )}
                {contactStatus === "error" && contactError && (
                  <span className="font-rubik text-sm text-red-600">{contactError}</span>
                )}
              </div>
            </form>
          </div>
        </section>

        </div>
        {/* Dark CTA — teal band, H2 white, Body white, white outlined button */}
        <section className="bg-turquoise text-white" aria-labelledby="cta-title">
          <div className="max-w-6xl mx-auto px-8 py-20 flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
            <div>
              <h2
                id="cta-title"
                className="font-rubik font-bold text-4xl md:text-5xl md:leading-[60px]"
              >
                מוכנים להתחיל?
              </h2>
              <p className="mt-4 text-lg text-white/80 max-w-lg leading-relaxed">
                היכנסו למערכת עם חשבון Google מאושר. הגישה מוגבלת למשתמשים רשומים בלבד.
              </p>
            </div>
            <button
              onClick={onLogin}
              className="inline-flex items-center gap-2 bg-transparent border-2 border-white text-white h-12 px-8 rounded-md font-rubik font-bold text-base hover:bg-white hover:text-turquoise transition-colors"
            >
              <span>כניסה למערכת</span>
              <ArrowCircleLeft />
            </button>
          </div>
        </section>
      </main>

      {/* Footer — dark, brand + description Small, H5 column headings, Small links */}
      <footer className="bg-[#191919] text-white/80 mt-auto">
        <div className="max-w-6xl mx-auto px-8 py-16 grid md:grid-cols-4 gap-8">
          <div className="md:col-span-2">
            <div className="font-rubik font-bold text-2xl text-white">Klaser</div>
            {/* Small — Rubik Regular 14 */}
            <p className="mt-4 font-rubik text-sm text-white/60 max-w-sm leading-relaxed">
              קלסר בונה זיכרון ארגוני חכם לארגונים מבוססי-מסמכים. מוצר הדגל שלנו — תקנון — כבר משרת קיבוצים ומושבים.
            </p>
          </div>
          <div>
            {/* H5 — Rubik Bold 16, tracking 25% */}
            <h2 className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-white/60 mb-4">
              מוצרים
            </h2>
            <ul className="space-y-2 font-rubik text-sm">
              <li>
                <button onClick={onLogin} className="hover:text-turquoise transition">
                  תקנון
                </button>
              </li>
              <li>
                <span className="text-white/50">פרוטוקולים · בקרוב</span>
              </li>
            </ul>
          </div>
          <div>
            <h2 className="font-rubik font-bold text-base uppercase tracking-[0.25em] text-white/60 mb-4">
              יצירת קשר
            </h2>
            <ul className="space-y-2 font-rubik text-sm">
              <li>
                <button onClick={() => scrollTo("contact")} className="hover:text-turquoise transition">
                  שלח לנו הודעה
                </button>
              </li>
              <li>
                <a href="mailto:tal.gurevich@elrom.tv" className="hover:text-turquoise transition">
                  tal.gurevich@elrom.tv
                </a>
              </li>
              <li>
                <button onClick={onLogin} className="hover:text-turquoise transition">
                  כניסה למערכת
                </button>
              </li>
            </ul>
          </div>
        </div>
        <div className="border-t border-white/10">
          <div className="max-w-6xl mx-auto px-8 py-4 flex flex-wrap items-center justify-between gap-4 font-rubik text-xs text-white/50">
            <span>© {new Date().getFullYear()} Klaser · כל הזכויות שמורות</span>
            <span className="flex items-center gap-4">
              <span>klaser.co.il</span>
              <span className="text-white/30">·</span>
              <span>
                Built by{" "}
                <a
                  href="https://errn.io"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-turquoise transition"
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

const FAQ_ITEMS: { q: string; a: string }[] = [
  {
    q: "איך אתם מבטיחים שהתשובה נכונה?",
    a: "כל תשובה נשענת על ציטוט ישיר ממסמך אמיתי — עם קישור למקור. אם אין ראיה מוצקה בקורפוס, המערכת בוחרת שלא לענות במקום לנחש. במקביל, אנחנו מריצים באופן שוטף מערך שאלות בקרה (\"golden set\") שמעיד על יציבות התשובות לאורך זמן.",
  },
  {
    q: "מה קורה כשהתשובה שגויה?",
    a: "בכל תשובה יש כפתור \"דווח בעיה\" שמעביר אלינו את השאלה, התשובה וקישור לשיחה. הפנייה נכנסת לתור טיפול של המנהל ומעודכנת תוך יום עסקים.",
  },
  {
    q: "האם המסמכים שלנו נשמרים בסביבה מבודדת?",
    a: "כן. כל ארגון מקבל מרחב נתונים משלו — אין ערבוב בין ארגונים, אין שימוש במסמכים לאימון מודלים כלליים, והנתונים לעולם לא נמסרים לצד ג' שלא לצורך תפעולי מוגדר.",
  },
  {
    q: "אילו סוגי מסמכים נתמכים?",
    a: "PDF ו-DOCX, כולל סרוקים (עם זיהוי טקסט אוטומטי). עברית ואנגלית. המערכת מכירה במבנים של תקנונים, פרוטוקולים והחלטות ומעבדת אותם בהתאם.",
  },
  {
    q: "מה עם עברית?",
    a: "קלסר נבנתה מהיסוד לעברית — לא תרגום. מזהה הטיות שורש, קידומות (ה, ו, ב, כ, ל, מ, ש), ראשי תיבות עם גרשיים, ומטפלת נכון ב-RTL בכל ממשק.",
  },
  {
    q: "איך מתחיל התהליך?",
    a: "בשלב הזה — קליטה מלווה. אנחנו יושבים איתכם, מייבאים את הארכיון הקיים, מגדירים את הארגון, ובונים יחד את ה-golden set הראשוני. בדרך כלל מיום עסקים אחד אתם כבר עם מערכת פעילה.",
  },
  {
    q: "כמה זה עולה?",
    a: "המחיר תלוי בגודל הארגון ובנפח המסמכים. עדיין לא הצבנו מחירון פומבי — מדברים איתנו וחוזרים עם הצעה מותאמת.",
  },
  {
    q: "מה קורה אם נחליט לעזוב?",
    a: "כל המסמכים והנתונים ניתנים להורדה ולייצוא. אין נעילה על הלקוח.",
  },
  {
    q: "באילו מודלים ובאילו ספקים אתם משתמשים?",
    a: "Claude של Anthropic לניסוח התשובות, Cohere לחיפוש סמנטי, Azure Document Intelligence לזיהוי מסמכים סרוקים. הבחירה בכל אחד היא הנדסית — אנחנו יכולים להחליף כשמופיע משהו איכותי יותר.",
  },
  {
    q: "מי עוד משתמש בקלסר?",
    a: "בעבודה עם קיבוץ אל-רום כשותפי עיצוב (design partner). ארגונים נוספים — קיבוצים ומושבים — בתהליך קליטה במהלך 2026.",
  },
];

const BENEFITS: { icon: "activity" | "language" | "quote"; title: string; body: string }[] = [
  {
    icon: "activity",
    title: "מעקב אחר שינויים",
    body: "תיקונים ואישורי ועדה מסומנים אוטומטית. תמיד יודעים מה הגרסה התקפה של כל סעיף.",
  },
  {
    icon: "language",
    title: "עברית שמבינה עברית",
    body: "בנוי מהיסוד לעברית — מכיר את הטיות השורש, את הניואנסים ואת המונחים הארגוניים הייחודיים.",
  },
  {
    icon: "quote",
    title: "מקור לכל תשובה",
    body: "כל תשובה מגיעה עם ציטוט ישיר וקישור למסמך המקור. לא ניחושים, לא הזיות — רק מה שכתוב.",
  },
];

const TAKANON_FEATURES = [
  "חיפוש סמנטי בעברית",
  "ציטוטים ישירים מהתקנון",
  "מעקב תיקונים ואמנדמנטים",
  "מילון מונחים ארגוני",
  "תור בדיקה לאיכות תשובות",
  "תשובות מאושרות ע\"י ועדה",
];

const OGDAN_FEATURES = [
  "ניהול ישיבות דיגיטלי",
  "תמלול בינה מלאכותית בעברית",
  "מעקב ביצוע החלטות",
  "מעורבות הקהילה",
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
    const ACCENT = "rgba(25, 129, 154, 0.85)"; // turquoise — matches DS palette
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

/* Klaser DS hero helpers */

function ArrowCircleLeft() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.6" />
      <path d="M13 8l-4 4 4 4M9 12h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TurquoiseDot() {
  return <span className="w-1.5 h-1.5 rounded-full bg-turquoise inline-block" aria-hidden />;
}

/* Binder-hole decoration — vertical dot column on the right edge of the page,
   evoking the punched holes in a physical Klaser (folder). Absolute-positioned
   inside the root wrapper so it scrolls with content; the sticky turquoise
   header (z-40) covers the top portion at scroll top. */
function BinderHoles() {
  return (
    <div
      aria-hidden="true"
      className="hidden md:block absolute right-0 top-0 bottom-0 w-12 pointer-events-none z-10"
      style={{
        // Dot per DS spec: 24px circle, fill #F2F2F2. z-10 keeps them above the
        // hero's absolute-positioned BackgroundMesh canvas, but below the sticky
        // header (z-40) so the header still covers dots at scroll-top.
        backgroundImage: "radial-gradient(circle at center, #f2f2f2 12px, transparent 13px)",
        backgroundSize: "48px 64px",
        backgroundRepeat: "repeat-y",
        backgroundPosition: "center top",
      }}
    />
  );
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0 text-turquoise">
      <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function AwardIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="9" r="6" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8.5 14l-1.5 7 5-3 5 3-1.5-7" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* Benefit icons — user-provided exported SVGs in /public/icons/.
   Each SVG includes its own teal tile + white glyph + bottom notches. */
function BenefitIcon({ name }: { name: "activity" | "language" | "quote" }) {
  const src =
    name === "activity" ? "/icons/Maakav.svg" :
    name === "language" ? "/icons/Hebrew.svg" :
    "/icons/Makor.svg";
  const alt =
    name === "activity" ? "מעקב" :
    name === "language" ? "עברית" :
    "מקור";
  return <img src={src} alt={alt} width={64} height={64} className="w-16 h-16" />;
}
