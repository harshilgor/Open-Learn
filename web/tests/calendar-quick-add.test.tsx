import { describe, expect, it } from 'vitest';
import { parseQuickAdd } from '@/lib/calendar-quick-add';
import { clockTime, dragRange, slotEnd, snapRound } from '@/lib/calendar-slots';

// Wednesday.
const TODAY = '2026-10-14';
const parse = (input: string) => parseQuickAdd(input, TODAY);

describe('calendar quick add parser', () => {
  it('reads relative days and 12-hour times, defaulting to one hour', () => {
    expect(parse('Bio study tomorrow 3pm')).toEqual({ title: 'Bio study', day: '2026-10-15', time: '15:00', endDay: '2026-10-15', endTime: '16:00', type: 'study', mode: 'timed' });
    expect(parse('Call mum today at 7:30 pm')).toMatchObject({ title: 'Call mum', day: TODAY, time: '19:30', endTime: '20:30' });
    expect(parse('Lunch tonight at noon')).toMatchObject({ title: 'Lunch', day: TODAY, time: '12:00' });
  });

  it('reads weekday names relative to today', () => {
    expect(parse('Gym friday 6am').day).toBe('2026-10-16');
    expect(parse('Gym wednesday 6am').day).toBe(TODAY);
    expect(parse('Gym monday 6am').day).toBe('2026-10-19');
    expect(parse('Gym next friday 6am').day).toBe('2026-10-23');
    expect(parse('Tutoring on Tue 4pm')).toMatchObject({ title: 'Tutoring', day: '2026-10-20', time: '16:00' });
    // "SAT" is a test, not Saturday, unless introduced as a day.
    expect(parse('SAT prep tomorrow')).toMatchObject({ title: 'SAT prep', day: '2026-10-15' });
    expect(parse('Hike on sat').day).toBe('2026-10-17');
  });

  it('reads month-name and numeric dates, rolling past dates into next year', () => {
    expect(parse('Chem exam Oct 20 9am')).toMatchObject({ title: 'Chem exam', day: '2026-10-20', time: '09:00', type: 'exam' });
    expect(parse('Chem exam October 20th, 2027').day).toBe('2027-10-20');
    expect(parse('Trip 3 Nov').day).toBe('2026-11-03');
    expect(parse('Quiz 10/20 2pm')).toMatchObject({ title: 'Quiz', day: '2026-10-20', time: '14:00', type: 'exam' });
    expect(parse('Quiz 20/10').day).toBe('2026-10-20');
    expect(parse('Party 1/5').day).toBe('2027-01-05');
    expect(parse('Party 2026-12-01').day).toBe('2026-12-01');
    expect(parse('Party Feb 30')).toMatchObject({ title: 'Party Feb 30', day: TODAY });
  });

  it('reads time ranges with shared or 24-hour notation', () => {
    expect(parse('Lab 3-5pm')).toMatchObject({ title: 'Lab', time: '15:00', endTime: '17:00', type: 'class' });
    expect(parse('Lab 11-1pm')).toMatchObject({ time: '11:00', endTime: '13:00' });
    expect(parse('Lab 9:30am to 11')).toMatchObject({ time: '09:30', endTime: '11:00' });
    expect(parse('Lecture from 15:00-16:30')).toMatchObject({ title: 'Lecture', time: '15:00', endTime: '16:30' });
    expect(parse('Party fri 11pm-1am')).toMatchObject({ day: '2026-10-16', time: '23:00', endDay: '2026-10-17', endTime: '01:00' });
    expect(parse('Read chapters 3-5 tomorrow')).toMatchObject({ title: 'Read chapters 3-5', day: '2026-10-15' });
    expect(parse('Read chapters 3-5 tomorrow').time).toBeUndefined();
  });

  it('reads durations and uses a morning start when only a duration is given', () => {
    expect(parse('Essay writing tomorrow 2pm for 2h')).toMatchObject({ title: 'Essay writing', time: '14:00', endTime: '16:00', type: 'assignment' });
    expect(parse('Revision 4pm for 90 min')).toMatchObject({ title: 'Revision', time: '16:00', endTime: '17:30' });
    expect(parse('Revision 4pm 1h 30m')).toMatchObject({ endTime: '17:30' });
    expect(parse('Revision for an hour')).toMatchObject({ title: 'Revision', time: '09:00', endTime: '10:00' });
    expect(parse('Night owl study 11pm for 2 hours')).toMatchObject({ day: TODAY, time: '23:00', endDay: '2026-10-15', endTime: '01:00' });
  });

  it('picks a category from the earliest keyword and makes date-only due items deadlines', () => {
    expect(parse('Study for physics exam').type).toBe('study');
    expect(parse('Exam review').type).toBe('exam');
    expect(parse('History essay due by Friday')).toEqual({ title: 'History essay due', day: '2026-10-16', type: 'assignment', mode: 'deadline' });
    expect(parse('Remind me to email TA tomorrow').type).toBe('reminder');
    expect(parse('Coffee with Sam')).toEqual({ title: 'Coffee with Sam', day: TODAY });
  });

  it('keeps the title clean when only a date or time is typed', () => {
    expect(parse('tomorrow at 3pm')).toMatchObject({ title: '', day: '2026-10-15', time: '15:00' });
    expect(parse('  ')).toEqual({ title: '', day: TODAY });
  });
});

describe('calendar slot helpers', () => {
  it('snaps drag ranges to quarter hours and keeps them inside the visible hours', () => {
    expect(dragRange(9 * 60 + 5, 10 * 60 + 20, 6 * 60, 22 * 60)).toEqual({ start: 540, end: 630 });
    expect(dragRange(10 * 60 + 20, 9 * 60 + 5, 6 * 60, 22 * 60)).toEqual({ start: 540, end: 630 });
    expect(dragRange(9 * 60, 30 * 60, 6 * 60, 22 * 60)).toEqual({ start: 540, end: 1320 });
    expect(dragRange(5 * 60, 5 * 60, 6 * 60, 22 * 60)).toEqual({ start: 360, end: 375 });
    expect(snapRound(9 * 60 + 8)).toBe(555);
  });
  it('formats wall clocks and rolls slot ends past midnight', () => {
    expect(clockTime(15)).toBe('00:15');
    expect(slotEnd('2026-10-14', 1440)).toEqual({ day: '2026-10-15', time: '00:00' });
    expect(slotEnd('2026-10-14', 600)).toEqual({ day: '2026-10-14', time: '10:00' });
  });
});
