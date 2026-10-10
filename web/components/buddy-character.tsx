"use client";
import styles from "./buddy-character.module.css";
export const concepts = [
  { name: 'Pebble', note: 'A smooth, asymmetric silhouette with a softly flattened base.', path: 'M23 68C15 49 23 25 44 20C64 14 84 28 88 49C93 71 77 85 54 86C39 87 28 81 23 68Z', color: '#B8CFA8' },
  { name: 'Bean', note: 'An organic curve with a little extra height on one side.', path: 'M26 77C13 64 17 43 31 34C41 28 38 15 55 16C77 16 91 39 86 61C82 82 44 94 26 77Z', color: '#F0BA68' },
  { name: 'Pocket', note: 'A compact square with soft corners and a slight lean.', path: 'M22 32Q23 19 39 20L70 23Q86 24 86 40L83 72Q82 86 65 85L35 82Q19 81 20 65Z', color: '#A9BDE2' },
  { name: 'Petal', note: 'Five rounded lobes around a compact center.', path: 'M52 16C65 12 68 29 70 31C91 24 97 43 81 54C98 72 81 89 65 78C56 99 35 90 36 75C13 80 10 58 27 49C13 30 32 18 44 30C44 22 47 17 52 16Z', color: '#E99381' },
  { name: 'Droplet', note: 'A tapered crown and a generous rounded base.', path: 'M46 18C52 9 62 23 72 35C85 50 92 69 78 80C61 94 28 86 22 70C15 51 33 35 46 18Z', color: '#BEA9DD' },
  { name: 'Cloud', note: 'A wide, scalloped outline with room for a tiny face.', path: 'M23 73C8 67 13 47 25 44C22 27 42 19 52 31C65 16 86 28 82 43C101 48 93 72 80 73C75 90 57 88 50 80C38 91 22 86 23 73Z', color: '#B8CFA8' },
  { name: 'Arch', note: 'A tall dome with two little feet built into its outline.', path: 'M24 77L25 48C26 8 79 10 81 48L83 77Q83 90 70 85L56 78L41 86Q23 91 24 77Z', color: '#F0BA68' },
  { name: 'Kite', note: 'Four soft points and a gently tilted silhouette.', path: 'M45 19Q53 9 63 22L86 46Q96 55 84 66L61 87Q51 95 41 83L19 60Q10 50 23 40Z', color: '#A9BDE2' },
];
export const expressions = ['Neutral', 'Curious', 'Thinking', 'Happy', 'Puzzled', 'Sleepy', 'Sleeping', 'Waking'] as const;
export type Expression = typeof expressions[number];

export type Accessory = 'Cap' | 'Beanie' | 'Scarf' | 'Glasses' | 'Backpack';
export const accessoryChoices: Accessory[] = ['Beanie', 'Cap', 'Scarf', 'Glasses', 'Backpack'];

export function Buddy({ index, color, accessories = [], face = 'classic', celebration = 'auto', palette = 'original', keepsake = 'none', expression = 'Neutral', size = 160, animated = false }: { index: number; color: string; accessories?: Accessory[]; face?: 'classic'|'round'|'soft'; celebration?: 'auto'|'roll'|'dance'|'bounce'; palette?: 'original'|'ocean'|'berry'; keepsake?: 'none'|'star'|'heart'; expression?: Expression; size?: number; animated?: boolean }) {
  const tilt = expression === 'Curious' ? -10 : expression === 'Puzzled' ? 9 : 0;
  return <svg width={size} height={size} viewBox="0 0 104 104" role="img" aria-label={`${concepts[index].name}, ${expression.toLowerCase()}${accessories.length ? `, wearing ${accessories.join(", ")}` : ""}`} className={`${styles.character} ${animated ? styles.live : ''}`} data-expression={expression.toLowerCase()} data-shape={concepts[index].name.toLowerCase()} data-face={face} data-celebration={celebration} data-palette={palette}>
    <ellipse className={styles.shadow} cx="53" cy="94" rx="24" ry="3" fill="currentColor" opacity=".12"/>
    <g className={styles.travel}><g className={styles.bodyMotion}><g transform={`rotate(${tilt} 52 54)`}>
      {accessories.includes('Backpack') && <g className={styles.backpack}><rect x="75" y="47" width="21" height="30" rx="8" fill="#B9794E"/><path d="M81 48V44Q85 39 89 44V48" fill="none" stroke="#694932" strokeWidth="3"/><rect x="83" y="58" width="10" height="12" rx="3" fill="#E6B983"/><path d="M86 61H90" stroke="#694932" strokeWidth="2"/></g>}
      <path d={concepts[index].path} fill={color}/>
      {accessories.includes('Backpack') && <path d="M74 38Q83 53 75 72" fill="none" stroke="#694932" strokeWidth="4" strokeLinecap="round"/>}
      {accessories.includes('Scarf') && <g>
        <path d="M28 72L76 70L78 80L29 82Q25 78 28 72Z" fill="#C96850"/>
        <path d="M29 72L75 70L76 75L28 77Z" fill="#E49A79"/>
        <path d="M32 78L60 77" stroke="#AE503E" strokeWidth="1.5" strokeLinecap="round"/>
        <g className={styles.scarfTail}>
          <path d="M69 76L79 77L88 92L80 96L72 85Z" fill="#B85A45"/>
          <path d="M65 76L75 77L73 98L63 97Z" fill="#DC8064"/>
          <path d="M64 91L74 92M78 88L85 85" stroke="#F3CF9E" strokeWidth="3"/>
          <path d="M64 97L64 100M68 98L68 101M72 98L72 101M81 94L83 97M85 92L87 95" stroke="#DC8064" strokeWidth="1.5" strokeLinecap="round"/>
        </g>
        <path d="M65 72Q70 70 76 74L75 82Q70 84 65 80Z" fill="#D77A5F"/>
        <path d="M68 74L72 80" stroke="#E9A785" strokeWidth="1.5" strokeLinecap="round"/>
      </g>}
      {accessories.includes('Cap') && <g transform={`translate(${index === 1 ? 3 : 0} ${index === 5 ? 9 : index === 3 ? -2 : 0})`}><g className={styles.hat}>
        <path d="M30 28Q31 8 51 8Q70 8 75 28Z" fill="#3C6570"/>
        <path d="M51 9Q60 14 60 27" fill="none" stroke="#6C9298" strokeWidth="1.6"/>
        <path d="M32 25L73 25L76 30L30 31Z" fill="#2B4C58"/>
        <ellipse cx="51" cy="8" rx="3" ry="2" fill="#294B56"/>
        <path d="M44 16L47 19L44 22L41 19Z" fill="#ECD9AF"/>
        <g className={styles.capBrim}><path d="M57 26Q77 22 89 29Q94 32 88 35Q73 39 57 31Z" fill="#56808A"/><path d="M60 31Q78 36 89 32" fill="none" stroke="#294B56" strokeWidth="1.5" strokeLinecap="round"/></g>
      </g></g>}
      {accessories.includes('Beanie') && <g transform={`translate(${index === 1 ? 3 : 0} ${index === 5 ? 9 : index === 3 ? -2 : 0})`}><g className={styles.hat}><path d="M32 28Q30 4 51 3Q73 3 75 28Z" fill="#475E80"/><path d="M42 9L41 23M52 7V23M62 10L65 23" stroke="#7186A4" strokeWidth="2" strokeLinecap="round"/><rect x="28" y="22" width="51" height="11" rx="5" fill="#7186A4"/><rect x="57" y="24" width="8" height="7" rx="1" fill="#F1DDB6"/><circle className={styles.pompom} cx="51" cy="3" r="6" fill="#D7DFE8"/></g></g>}
      <g className={styles.faceMotion} fill="none" stroke="#252B27" strokeWidth="5" strokeLinecap="round">
        {expression === 'Sleeping' ? <><path d="M38 48Q43 51 48 48"/><path d="M58 48Q63 51 68 48"/></> : expression === 'Sleepy' ? <><path d="M39 48L47 49"/><path d="M59 48L67 49"/></> : expression === 'Waking' ? <><path d="M43 41L43 51"/><path d="M63 41L63 51"/><ellipse cx="53" cy="62" rx="3" ry="4" strokeWidth="2"/></> : expression === 'Happy' ? <><path d="M39 49Q43 43 47 49"/><path d="M59 49Q63 43 67 49"/></> : expression === 'Thinking' ? <><path d="M39 48L46 48"/><path d="M61 44L61 51"/></> : expression === 'Puzzled' ? <><path d="M40 44L45 49"/><path d="M61 43L61 51"/></> : face === 'round' ? <><circle cx="43" cy="47" r="3" fill="#252B27" strokeWidth="1"/><circle cx="63" cy="47" r="3" fill="#252B27" strokeWidth="1"/></> : face === 'soft' ? <><path d="M39 46Q43 43 47 46"/><path d="M59 46Q63 43 67 46"/></> : <><path d="M43 43L43 50"/><path d={`M63 ${expression === 'Curious' ? 40 : 43}L63 50`}/></>}
      </g>
      {accessories.includes('Glasses') && <g className={styles.glasses} fill="none" stroke="#514137" strokeWidth="2.3"><circle cx="43" cy="47" r="9"/><circle cx="63" cy="47" r="9"/><path d="M52 46Q53 44 54 46M34 45L28 42M72 45L78 42"/><path d="M38 43L41 40M58 43L61 40" stroke="#FFF6E2" strokeWidth="1.4"/></g>}
      {keepsake !== 'none' && <g transform="translate(33 59)"><circle r="6" fill="#F4D993" stroke="#B58D4E" strokeWidth="1"/>{keepsake === 'star' ? <path d="M0 -4L1 -1L4 -1L2 1L3 4L0 2L-3 4L-2 1L-4 -1L-1 -1Z" fill="#94693A"/> : <path d="M0 3C-8 -1 -3 -6 0 -2C3 -6 8 -1 0 3" fill="#B96955"/>}</g>}
    </g></g></g>
    {expression === 'Sleeping' && <text x="79" y="15" fontSize="10" fill="currentColor" className={styles.sleepMark}>z</text>}
  </svg>;
}

