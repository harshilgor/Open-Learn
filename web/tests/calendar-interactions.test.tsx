import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CalendarTimeline } from '@/components/calendar/calendar-timeline';
import { CalendarMiniMonth } from '@/components/calendar/calendar-mini-month';
import { CalendarEventForm } from '@/components/calendar/calendar-event-form';
import type { CalendarEvent } from '@/lib/calendar-client';

const DAYS = ['2026-10-14', '2026-10-15'];
// Each day column is 200px wide; the grid starts at y=0 with 48px hours from 6 AM, so y = (minute - 360) * 0.8.
const COLUMN = 200;
const yAt = (hour: number, minute = 0) => ((hour * 60 + minute) - 360) * 48 / 60;
const event = (id: string, start: string, end: string, canEdit: boolean): CalendarEvent => ({ id, calendarId: 'cal', title: id, type: 'study', revision: 1, busy: true, canEdit, temporal: { mode: 'timed', timezone: 'UTC', start, end } });
const editable = event('Essay', '2026-10-14T10:00:00Z', '2026-10-14T11:00:00Z', true);
const readOnly = event('Lecture', '2026-10-14T13:00:00Z', '2026-10-14T14:00:00Z', false);

let container: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    const index = DAYS.indexOf((this as HTMLElement).dataset?.trackDay ?? '');
    const left = Math.max(0, index) * COLUMN;
    return { top: 0, bottom: 800, left, right: left + COLUMN, width: COLUMN, height: 800, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function pointer(target: Element, type: string, clientX: number, clientY: number) {
  const native = new MouseEvent(type, { bubbles: true, cancelable: true, clientX, clientY, button: 0 });
  Object.defineProperties(native, { pointerId: { value: 1 }, pointerType: { value: 'mouse' } });
  act(() => { target.dispatchEvent(native); });
}
const hourCell = (day: number, hour: number) => container.querySelectorAll('[data-track-day]')[day].querySelectorAll('button')[hour - 6];
const eventButton = (title: string) => [...container.querySelectorAll('button')].find(button => button.querySelector('strong')?.textContent === title)!;

describe('calendar timeline drag gestures', () => {
  const handlers = () => ({ onSelect: vi.fn(), onAdd: vi.fn(), onMove: vi.fn(), onDay: vi.fn() });
  const render = (props: ReturnType<typeof handlers>) => act(() => root.render(<CalendarTimeline days={DAYS} events={[editable, readOnly]} zone="UTC" calendars={[]} {...props}/>));

  it('creates a snapped range by dragging down an empty column and keeps plain clicks working', () => {
    const props = handlers(); render(props);
    const cell = hourCell(0, 9);
    pointer(cell, 'pointerdown', 50, yAt(9, 5));
    pointer(cell, 'pointermove', 50, yAt(10, 20));
    expect(container.querySelector('[data-kind=create]')?.textContent).toMatch(/9:00.*10:30/);
    pointer(cell, 'pointerup', 50, yAt(10, 20));
    act(() => (cell as HTMLButtonElement).click()); // the browser's click after the drag is ignored
    expect(props.onAdd).toHaveBeenCalledTimes(1);
    expect(props.onAdd).toHaveBeenCalledWith('2026-10-14', '09:00', { day: '2026-10-14', time: '10:30' });
    expect(container.querySelector('[data-kind=create]')).toBeNull();

    pointer(cell, 'pointerdown', 50, yAt(9, 5));
    pointer(cell, 'pointerup', 50, yAt(9, 5));
    act(() => (cell as HTMLButtonElement).click());
    expect(props.onAdd).toHaveBeenLastCalledWith('2026-10-14', '09:00');
  });

  it('cancels a drag on Escape without creating anything', () => {
    const props = handlers(); render(props);
    const cell = hourCell(1, 15);
    pointer(cell, 'pointerdown', 250, yAt(15));
    pointer(cell, 'pointermove', 250, yAt(16, 30));
    expect(container.querySelector('[data-kind=create]')).not.toBeNull();
    act(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); });
    expect(container.querySelector('[data-kind=create]')).toBeNull();
    pointer(cell, 'pointerup', 250, yAt(16, 30));
    act(() => (cell as HTMLButtonElement).click());
    expect(props.onAdd).not.toHaveBeenCalled();
  });

  it('moves an editable event across days in 15 minute steps and still opens it on click', () => {
    const props = handlers(); render(props);
    const button = eventButton('Essay');
    expect(button.dataset.movable).toBe('true');
    pointer(button, 'pointerdown', 50, yAt(10, 15));
    pointer(button, 'pointermove', 250, yAt(12, 22));
    expect(button.dataset.dragging).toBe('true');
    const preview = container.querySelectorAll('[data-track-day]')[1].querySelector('[data-kind=move]');
    expect(preview?.textContent).toMatch(/Essay.*12:00.*1:00/);
    pointer(button, 'pointerup', 250, yAt(12, 22));
    act(() => button.click());
    expect(props.onMove).toHaveBeenCalledWith(editable, '2026-10-15', '12:00');
    expect(props.onSelect).not.toHaveBeenCalled();

    pointer(button, 'pointerdown', 50, yAt(10, 15));
    pointer(button, 'pointerup', 50, yAt(10, 15));
    act(() => button.click());
    expect(props.onSelect).toHaveBeenCalledWith(editable);
    expect(props.onMove).toHaveBeenCalledTimes(1);
  });

  it('does not drag read-only events', () => {
    const props = handlers(); render(props);
    const button = eventButton('Lecture');
    expect(button.dataset.movable).toBeUndefined();
    pointer(button, 'pointerdown', 50, yAt(13, 15));
    pointer(button, 'pointermove', 250, yAt(15));
    pointer(button, 'pointerup', 250, yAt(15));
    expect(container.querySelector('[data-kind=move]')).toBeNull();
    act(() => button.click());
    expect(props.onMove).not.toHaveBeenCalled();
    expect(props.onSelect).toHaveBeenCalledWith(readOnly);
  });
});

describe('calendar mini month', () => {
  it('highlights today and the visible week, navigates months and picks dates', () => {
    const onPick = vi.fn();
    act(() => root.render(<CalendarMiniMonth day="2026-10-14" today="2026-10-14" rangeStart="2026-10-12" rangeEnd="2026-10-19" onPick={onPick}/>));
    expect(container.querySelector('h2')?.textContent).toBe('October 2026');
    expect(container.querySelector('[aria-current=date]')?.getAttribute('data-date')).toBe('2026-10-14');
    expect([...container.querySelectorAll('td[aria-selected=true] button')].map(b => b.getAttribute('data-date'))).toEqual(['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17', '2026-10-18']);
    expect(container.querySelectorAll('td button[tabindex="0"]')).toHaveLength(1);

    act(() => (container.querySelector('[data-date="2026-10-22"]') as HTMLButtonElement).click());
    expect(onPick).toHaveBeenCalledWith('2026-10-22');

    act(() => (container.querySelector('[aria-label="Next month"]') as HTMLButtonElement).click());
    expect(container.querySelector('h2')?.textContent).toBe('November 2026');
    expect(container.querySelector('td button[tabindex="0"]')?.getAttribute('data-date')).toBe('2026-11-01');
  });

  it('moves focus between dates with the arrow keys', () => {
    act(() => root.render(<CalendarMiniMonth day="2026-10-31" today="2026-10-14" rangeStart="2026-10-31" rangeEnd="2026-11-01" onPick={vi.fn()}/>));
    const start = container.querySelector('[data-date="2026-10-31"]') as HTMLButtonElement;
    start.focus();
    act(() => { start.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); });
    expect(container.querySelector('h2')?.textContent).toBe('November 2026');
    expect(document.activeElement?.getAttribute('data-date')).toBe('2026-11-01');
  });
});

describe('calendar event form prefill', () => {
  it('starts a new event from a dragged range or quick-add draft', () => {
    act(() => root.render(<CalendarEventForm day="2026-10-14" time="23:00" endDay="2026-10-15" endTime="00:30" defaults={{ title: 'Night study', type: 'exam' }} zone="UTC" calendars={[{ id: 'cal', title: 'Mine', source: 'local', color: '', canEdit: true, permission: { revision: 1, read: 'details', edit: 'ask' } }]} courses={[]} onClose={vi.fn()} onSaved={vi.fn()}/>));
    const inputs = [...document.querySelectorAll<HTMLInputElement>('input[type=datetime-local]')].map(input => input.value);
    expect(inputs).toEqual(['2026-10-14T23:00', '2026-10-15T00:30']);
    expect(document.querySelector<HTMLInputElement>('input[placeholder="Physics revision"]')?.value).toBe('Night study');
    expect(document.querySelector('select')?.value).toBe('exam');
  });
});
