import { describe, expect, it } from 'vitest';

import { formatDate, formatDateTime, formatTime } from './date';

describe('даты (FR-UI-02)', () => {
  const moment = '2026-11-05T08:07:00Z';

  it('по часовому поясу пользователя', () => {
    expect(formatDate(moment, 'Europe/Samara')).toBe('05.11.2026');
    expect(formatTime(moment, 'Europe/Samara')).toBe('12:07');
    expect(formatDateTime(moment, 'Europe/Moscow')).toBe('05.11.2026 11:07');
    expect(formatDateTime(new Date(moment), 'UTC', true)).toBe('05.11 08:07');
  });

  it('полночь — 00, а не 24', () => {
    expect(formatTime('2026-11-04T21:00:00Z', 'Europe/Moscow')).toBe('00:00');
  });
});
