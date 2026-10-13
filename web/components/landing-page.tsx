"use client";

import { ArrowRight, Bookmark, BookOpen, CalendarCheck2, Check, MessageCircle, Sparkles } from 'lucide-react';
import Link from 'next/link';
import styles from './landing-page.module.css';

function openAuth(mode: 'signup' | 'login') {
  window.dispatchEvent(new CustomEvent('openlearn-auth-open', { detail: mode }));
}

function ProductPreview() {
  return (
    <section className={styles.previewSection} aria-label="A look inside Open Learn">
      <div className={styles.previewGlow} aria-hidden="true" />
      <div className={styles.previewWindow}>
        <div className={styles.windowBar} aria-hidden="true">
          <span /><span /><span />
          <div><BookOpen size={13} /> Open Learn <span className={styles.windowDivider}>/</span> Biology</div>
          <i />
        </div>
        <div className={styles.productFrame} role="img" aria-label="Open Learn study space showing a clear explanation about autumn leaves and a note saved for later review">
          <aside className={styles.productSidebar}>
            <div className={styles.productBrand}><BookOpen size={18} /><strong>Open Learn</strong></div>
            <div className={styles.sideItem}><MessageCircle size={15} /> Chat</div>
            <div className={`${styles.sideItem} ${styles.sideItemActive}`}><Bookmark size={15} /> Notes <span>1</span></div>
            <div className={styles.sideItem}><CalendarCheck2 size={15} /> Review</div>
            <div className={styles.sideLabel}>RECENT NOTES</div>
            <div className={styles.sideNote}><span /> Why leaves change color</div>
          </aside>
          <div className={styles.productMain}>
            <div className={styles.productBreadcrumb}><span>Chat</span><span>/</span><strong>Biology</strong></div>
            <div className={styles.productContent}>
              <div className={styles.conversation}>
                <div className={styles.userMessage}>Why do leaves turn red and orange in autumn?</div>
                <article className={styles.answerCard}>
                  <div className={styles.answerByline}><span className={styles.sparkle}><Sparkles size={13} /></span><strong>Your study partner</strong><span>·</span><span>Guided</span></div>
                  <p>As days grow shorter, trees make less chlorophyll—the pigment that gives leaves their green color.</p>
                  <p>With the green fading, yellow and orange pigments already in the leaf become visible. Some trees also make red pigments called anthocyanins.</p>
                  <div className={styles.answerActions}><span><Check size={13} /> Saved to Notes</span><small>Clear explanation · Biology</small></div>
                </article>
              </div>
              <aside className={styles.noteCard}>
                <div className={styles.noteTop}><span><Bookmark size={14} /></span><small>NOTE · JUST SAVED</small><Check size={14} /></div>
                <h3>Why leaves change color</h3>
                <p>Less chlorophyll reveals the yellow and orange pigments already in a leaf. Some trees make red pigments too.</p>
                <div className={styles.noteMeta}><span>Biology</span><span>Saved just now</span></div>
              </aside>
            </div>
            <div className={styles.composer}><span>Ask a follow-up…</span><span className={styles.sendIcon}><ArrowRight size={14} /></span></div>
          </div>
        </div>
      </div>
      <p className={styles.previewCaption}>A question becomes an explanation you can keep.</p>
    </section>
  );
}

const features = [
  { icon: MessageCircle, title: 'Thoughtful conversations', copy: 'Ask anything and choose how deeply you want to explore.' },
  { icon: Bookmark, title: 'Your notes, together', copy: 'Save the explanations that click and find them when you need them.' },
  { icon: CalendarCheck2, title: 'Pick up anywhere', copy: 'Reviews and reminders help you keep a rhythm that works for you.' },
];

function FeatureRow() {
  return <div className={styles.featureGrid}>{features.map(({ icon: Icon, title, copy }) => <article className={styles.feature} key={title}>
    <span className={styles.featureIcon}><Icon size={18} strokeWidth={1.7} /></span>
    <div><h3>{title}</h3><p>{copy}</p></div>
  </article>)}</div>;
}

export function LandingPage() {
  return <div className={styles.page}>
    <header className={styles.header}>
      <Link className={styles.brand} href="/" aria-label="Open Learn home"><BookOpen size={22} strokeWidth={1.8} /><span>Open Learn</span></Link>
      <nav className={styles.headerActions} aria-label="Account">
        <button className={styles.login} onClick={() => openAuth('login')}>Log in</button>
        <button className={styles.headerSignup} onClick={() => openAuth('signup')}>Sign up for free</button>
      </nav>
    </header>

    <main>
      <section className={styles.hero}>
        <p className={styles.eyebrow}>A SPACE FOR YOUR CURIOSITY</p>
        <h1>There’s a world behind <em>every question.</em></h1>
        <p className={styles.heroCopy}>An AI study partner that explains things at the depth you choose, then turns the answers that click into notes, reviews, and quizzes.</p>
        <button className={styles.primary} onClick={() => openAuth('signup')}>Sign up for free <ArrowRight size={17} /></button>
        <p className={styles.microcopy}>Free to start. No credit card needed.</p>
      </section>

      <ProductPreview />

      <section className={styles.featuresSection} aria-labelledby="features-title">
        <p className={styles.sectionEyebrow}>LEARNING THAT STAYS WITH YOU</p>
        <h2 id="features-title">Make a little more sense of it.</h2>
        <FeatureRow />
      </section>

      <section className={styles.howSection} aria-labelledby="how-title">
        <div><p className={styles.sectionEyebrow}>A SIMPLE WAY TO KEEP GOING</p><h2 id="how-title">From a question to a habit.</h2></div>
        <ol className={styles.steps}>
          <li><span>01</span><strong>Ask</strong><small>Start with what you’re curious about.</small></li>
          <li><span>02</span><strong>Save</strong><small>Keep the ideas you want to remember.</small></li>
          <li><span>03</span><strong>Review</strong><small>Come back to them when it counts.</small></li>
        </ol>
      </section>

      <section className={styles.lastCall}>
        <span className={styles.lastIcon}><BookOpen size={19} /></span>
        <h2>Bring your next question.</h2>
        <p>Your study space is ready when you are.</p>
        <button className={styles.primary} onClick={() => openAuth('signup')}>Sign up for free <ArrowRight size={17} /></button>
      </section>
    </main>

    <footer className={styles.footer}>
      <Link className={styles.footerBrand} href="/"><BookOpen size={17} /> Open Learn</Link>
      <span>For the questions that lead somewhere.</span>
      <nav aria-label="Footer">
        <a href="https://github.com/harshilgor/Open-Learn/issues" target="_blank" rel="noreferrer">Contact</a>
      </nav>
    </footer>
  </div>;
}
