import { addDays, clockTime, slotEnd } from './calendar-slots';

/** Prefill for the event form produced from a quick-add phrase. The user always confirms it in the form. */
export type QuickAddDraft = {
  title: string;
  /** YYYY-MM-DD the event starts on. */
  day: string;
  /** "HH:MM" start; absent when no time was typed. */
  time?: string;
  /** Day and "HH:MM" the event ends on; present whenever `time` is. */
  endDay?: string;
  endTime?: string;
  /** Event form category (class, exam, assignment, study, reminder) when a keyword names one. */
  type?: string;
  /** "deadline" for date-only due items such as "Essay due Friday". */
  mode?: 'timed' | 'deadline';
};

const MONTH = '(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\\.?';
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const WEEKDAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const MERIDIEM = '(am|pm|a\\.m\\.|p\\.m\\.)';
const DEFAULT_MINUTES = 60;
const DEFAULT_START = 9 * 60;

/** Keywords that pick a form category; the earliest keyword in the phrase wins. */
const CATEGORIES: Array<[RegExp, string]> = [
  [/\b(?:exams?|quiz(?:zes)?|midterms?|finals?|tests?)\b/i, 'exam'],
  [/\b(?:assignments?|homework|hw|essays?|due|deadlines?|psets?|problem sets?|projects?)\b/i, 'assignment'],
  [/\b(?:class(?:es)?|lectures?|labs?|seminars?|tutorials?|recitations?)\b/i, 'class'],
  [/\b(?:study|studying|review|revise|revision|practice)\b/i, 'study'],
  [/\b(?:remind(?:er)?|remember)\b/i, 'reminder'],
];

/** Words that only link a removed date or time to the title ("… at 3pm", "due by Friday"). */
const CONNECTOR = /(?:^|\s)(?:at|on|from|by|@)\s*$/i;

const daysInMonth = (year: number, month: number) => new Date(Date.UTC(year, month, 0)).getUTCDate();
const pad = (value: number) => String(value).padStart(2, '0');

/** A calendar date, or null when it doesn't exist. Dates without a year resolve to the next occurrence. */
function dateOf(today: string, month: number, day: number, year?: number) {
  if (year !== undefined && year < 100) year += 2000;
  const thisYear = Number(today.slice(0, 4));
  const resolve = (y: number) => month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth(y, month) ? `${y}-${pad(month)}-${pad(day)}` : null;
  if (year !== undefined) return resolve(year);
  const candidate = resolve(thisYear);
  return candidate && candidate < today ? resolve(thisYear + 1) : candidate ?? resolve(thisYear + 1);
}

/** Minutes since midnight for a clock reading, or null if it isn't one. */
function clock(hour: number, minute: number, meridiem?: string) {
  if (minute > 59) return null;
  if (meridiem) {
    if (hour < 1 || hour > 12) return null;
    return ((hour % 12) + (meridiem.startsWith('p') ? 12 : 0)) * 60 + minute;
  }
  return hour > 23 ? null : hour * 60 + minute;
}

/**
 * Parse a short phrase such as "Bio study tomorrow 3pm", "Chem exam Oct 20 9-11am" or "Essay due Friday"
 * into an event form prefill. `today` is the YYYY-MM-DD date in the calendar's display timezone.
 * Unrecognised words stay in the title; nothing is created without the user confirming the form.
 */
export function parseQuickAdd(input: string, today: string): QuickAddDraft {
  const source = input.replace(/\s+/g, ' ').trim();
  let masked = source;
  const consumed = new Array<boolean>(source.length).fill(false);
  /** Find the first match of `pattern` in text not consumed yet that `accept` takes, and consume it. */
  function take(pattern: RegExp, accept: (match: RegExpExecArray) => boolean = () => true) {
    const global = new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`);
    for (let match = global.exec(masked); match; match = global.exec(masked)) {
      if (!accept(match)) { if (!match[0]) global.lastIndex++; continue; }
      for (let i = match.index; i < match.index + match[0].length; i++) consumed[i] = true;
      masked = source.split('').map((char, i) => consumed[i] ? '\u0001' : char).join('');
      return match;
    }
    return null;
  }

  // ---- Date ----
  let day: string | null = null;
  take(/\b(\d{4})-(\d{2})-(\d{2})\b/, m => !!(day = dateOf(today, Number(m[2]), Number(m[3]), Number(m[1]))));
  if (!day) take(/(?<![\w/:.-])(\d{1,2})\/(\d{1,2})(?:\/(\d{4}|\d{2}))?(?![\w/])/, m => {
    let [month, date] = [Number(m[1]), Number(m[2])];
    if (month > 12 && date <= 12) [month, date] = [date, month]; // 20/10 reads as day/month
    return !!(day = dateOf(today, month, date, m[3] ? Number(m[3]) : undefined));
  });
  if (!day) take(new RegExp(`\\b${MONTH}\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:,?\\s+(\\d{4}))?(?![\\w:])(?!\\s*(?:am|pm|a\\.m|p\\.m))`, 'i'), m => !!(day = dateOf(today, MONTHS.indexOf(m[1].slice(0, 3).toLowerCase()) + 1, Number(m[2]), m[3] ? Number(m[3]) : undefined)));
  if (!day) take(new RegExp(`(?<![\\w/:.-])(\\d{1,2})(?:st|nd|rd|th)?\\s+(?:of\\s+)?${MONTH}(?:,?\\s+(\\d{4}))?(?!\\w)`, 'i'), m => !!(day = dateOf(today, MONTHS.indexOf(m[2].slice(0, 3).toLowerCase()) + 1, Number(m[1]), m[3] ? Number(m[3]) : undefined)));
  if (!day) take(/\b(today|tonight|tomorrow|tmrw|tmr)\b/i, m => !!(day = /^to(day|night)$/i.test(m[1]) ? today : addDays(today, 1)));
  if (!day) take(/\b(?:(this|next|on)\s+)?(sun(?:day)?|mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?)\b/i, m => {
    const name = m[2].toLowerCase();
    // "sat" and "sun" are also ordinary words (the SAT); only read them as days after "on/this/next".
    if (!m[1] && (name === 'sat' || name === 'sun')) return false;
    const target = WEEKDAYS.indexOf(name.slice(0, 3)), current = new Date(`${today}T12:00:00Z`).getUTCDay();
    day = addDays(today, (target - current + 7) % 7 + (m[1]?.toLowerCase() === 'next' ? 7 : 0));
    return true;
  });

  // ---- Time ----
  let start: number | null = null, end: number | null = null;
  take(new RegExp(`(?<![\\w/:.-])(\\d{1,2})(?::(\\d{2}))?\\s*${MERIDIEM}?\\s*(?:-|–|—|to|until|till)\\s*(\\d{1,2})(?::(\\d{2}))?\\s*${MERIDIEM}?(?![\\w/])`, 'i'), m => {
    const [h1, m1, h2, m2] = [Number(m[1]), Number(m[2] || 0), Number(m[4]), Number(m[5] || 0)];
    let mer1 = m[3]?.toLowerCase(), mer2 = m[6]?.toLowerCase();
    if (!mer1 && !mer2 && m[2] === undefined && m[5] === undefined) return false; // "chapters 3-5" is not a time
    if (!mer1 && mer2) { mer1 = mer2; const a = clock(h1, m1, mer1), b = clock(h2, m2, mer2); if (a !== null && b !== null && a >= b) mer1 = mer2.startsWith('p') ? 'am' : 'pm'; }
    if (mer1 && !mer2 && h2 <= 12) { mer2 = mer1; const a = clock(h1, m1, mer1), b = clock(h2, m2, mer2); if (a !== null && b !== null && b <= a) mer2 = mer1.startsWith('p') ? 'am' : 'pm'; }
    const a = clock(h1, m1, mer1), b = clock(h2, m2, mer2);
    if (a === null || b === null) return false;
    start = a; end = b <= a ? b + 1440 : b;
    return true;
  });
  let duration: number | null = null;
  take(/(?<![\w.])(?:for\s+)?(?:(\d+(?:\.\d+)?)\s*(?:h|hrs?|hours?)(?:\s*(?:and\s+)?(\d+)\s*(?:m|mins?|minutes?))?|(\d+)\s*(?:m|mins?|minutes?))(?!\w)/i, m => {
    duration = m[3] ? Number(m[3]) : Math.round(Number(m[1]) * 60) + Number(m[2] || 0);
    return duration > 0 && duration <= 24 * 60;
  });
  if (duration === null) take(/\bfor\s+(an?\s+hour|half\s+an?\s+hour)\b/i, m => !!(duration = /^half/i.test(m[1]) ? 30 : 60));
  if (start === null) take(new RegExp(`(?<![\\w/:.-])(\\d{1,2})(?::(\\d{2}))?\\s*${MERIDIEM}(?!\\w)`, 'i'), m => (start = clock(Number(m[1]), Number(m[2] || 0), m[3].toLowerCase())) !== null);
  if (start === null) take(/(?<![\w/:.-])(\d{1,2}):(\d{2})(?![\w:/])/, m => (start = clock(Number(m[1]), Number(m[2]))) !== null);
  if (start === null) take(/\b(noon|midday)\b/i, () => (start = 12 * 60) !== null);
  // "at 3" without am/pm: afternoon for 1–7, otherwise as written.
  if (start === null) take(/\bat\s+(\d{1,2})(?![\w:/])/i, m => { const hour = Number(m[1]); start = hour >= 1 && hour <= 7 ? (hour + 12) * 60 : clock(hour, 0); return start !== null; });

  // ---- Title and category ----
  // Drop connector words left dangling in front of a removed date or time.
  for (let i = 0; i < source.length; i++) {
    if (!consumed[i] || (i > 0 && consumed[i - 1])) continue;
    let before = i;
    while (before > 0 && !consumed[before - 1]) before--;
    const connector = CONNECTOR.exec(source.slice(before, i));
    if (connector) for (let j = before + connector.index; j < i; j++) consumed[j] = true;
  }
  const title = source.split('').map((char, i) => consumed[i] ? ' ' : char).join('').replace(/\s+/g, ' ').replace(/^[\s,;:–—-]+|[\s,;:–—-]+$/g, '').trim();
  const keyword = CATEGORIES.map(([pattern, type]) => ({ type, index: source.search(pattern) })).filter(hit => hit.index >= 0).sort((a, b) => a.index - b.index)[0];
  const draft: QuickAddDraft = { title, day: day ?? today, ...(keyword ? { type: keyword.type } : {}) };

  if (start === null && duration !== null) start = DEFAULT_START;
  if (start !== null) {
    const finish = end ?? start + (duration ?? DEFAULT_MINUTES);
    const until = slotEnd(draft.day, finish);
    return { ...draft, time: clockTime(start), endDay: until.day, endTime: until.time, mode: 'timed' };
  }
  return /\b(?:due|deadline)\b/i.test(source) ? { ...draft, mode: 'deadline' } : draft;
}
