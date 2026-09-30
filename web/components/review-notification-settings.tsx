"use client";

import { useEffect, useState } from 'react';
import { Bell } from 'lucide-react';

type DesktopPreferences = { reviewNotifications: boolean; quietHoursStart: number; quietHoursEnd: number };
type PreferenceBridge = { get: () => Promise<DesktopPreferences>; set: (value: DesktopPreferences) => Promise<DesktopPreferences> };

function bridge(): PreferenceBridge | null {
  if (typeof window === 'undefined') return null;
  return (window as Window & { formaDesktop?: { preferences?: PreferenceBridge } }).formaDesktop?.preferences || null;
}

export function ReviewNotificationSettings() {
  const [preferences] = useState<PreferenceBridge | null>(() => bridge());
  const [enabled, setEnabled] = useState(false);
  const [quietHoursStart, setQuietHoursStart] = useState(22);
  const [quietHoursEnd, setQuietHoursEnd] = useState(8);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { if (preferences) void preferences.get().then(value => { setEnabled(value.reviewNotifications); setQuietHoursStart(value.quietHoursStart); setQuietHoursEnd(value.quietHoursEnd); setReady(true); }).catch(() => { setError('Notification preferences could not be loaded.'); setReady(true); }); }, [preferences]);
  if (!preferences) return null;

  async function save(next: DesktopPreferences) {
    if (!preferences) return;
    const previous = { reviewNotifications: enabled, quietHoursStart, quietHoursEnd };
    setEnabled(next.reviewNotifications); setQuietHoursStart(next.quietHoursStart); setQuietHoursEnd(next.quietHoursEnd); setError('');
    try { await preferences.set(next); } catch { setEnabled(previous.reviewNotifications); setQuietHoursStart(previous.quietHoursStart); setQuietHoursEnd(previous.quietHoursEnd); setError('These notification settings could not be saved.'); }
  }

  return <div className="notification-preferences">
    <div className="notification-settings">
      <div><Bell size={17} /><span><strong>Review reminders</strong><small>Notify me on this device when a scheduled review is due.</small></span></div>
      <button type="button" role="switch" aria-checked={enabled} disabled={!ready} className={enabled ? 'enabled' : ''} onClick={() => void save({ reviewNotifications: !enabled, quietHoursStart, quietHoursEnd })}><span />{enabled ? 'On' : 'Off'}</button>
    </div>
    <div className="notification-quiet-hours">
      <div><strong>Quiet hours</strong><small>Review reminders pause during these local hours.</small></div>
      <label>From<select disabled={!ready || !enabled} value={quietHoursStart} onChange={event => void save({ reviewNotifications: enabled, quietHoursStart: Number(event.target.value), quietHoursEnd })}>{Array.from({ length: 24 }, (_, hour) => <option key={hour} value={hour}>{String(hour).padStart(2, '0')}:00</option>)}</select></label>
      <label>Until<select disabled={!ready || !enabled} value={quietHoursEnd} onChange={event => void save({ reviewNotifications: enabled, quietHoursStart, quietHoursEnd: Number(event.target.value) })}>{Array.from({ length: 24 }, (_, hour) => <option key={hour} value={hour}>{String(hour).padStart(2, '0')}:00</option>)}</select></label>
    </div>
    {error ? <p className="settings-message" role="alert">{error}</p> : null}
  </div>;
}
