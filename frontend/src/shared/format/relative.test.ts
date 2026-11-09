import { describe, expect, it } from 'vitest';

import { formatWhen } from './relative';

const now = new Date('2026-11-09T11:20:00Z'); // 14:20 по Москве
const tz = 'Europe/Moscow';

describe('formatWhen (FR-UI-02)', () => {
  it('сегодня, вчера, дата', () => {
    expect(formatWhen('2026-11-09T08:05:00Z', { now, timeZone: tz })).toBe('сегодня 11:05');
    expect(formatWhen('2026-11-08T20:00:00Z', { now, timeZone: tz })).toBe('вчера');
    expect(formatWhen('2026-11-02T10:00:00Z', { now, timeZone: tz })).toBe('02.11.2026');
  });
  it('граница суток по часовому поясу пользователя', () => {
    // 21:30 UTC 8-го — это уже 9-е по Москве
    expect(formatWhen('2026-11-08T21:30:00Z', { now, timeZone: tz })).toBe('сегодня 00:30');
  });
  it('минуты для колокольчика', () => {
    expect(formatWhen('2026-11-09T11:19:40Z', { now, timeZone: tz, minutes: true })).toBe('только что');
    expect(formatWhen('2026-11-09T11:10:00Z', { now, timeZone: tz, minutes: true })).toBe('10 мин назад');
  });
});
