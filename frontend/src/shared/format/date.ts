/**
 * FE-003 · даты и время (FR-UI-02, DESIGN.md 11): ДД.ММ.ГГГГ, ЧЧ:ММ по часовому поясу
 * пользователя (`users.timezone`; null — часовой пояс приложения, его подставляет вызывающий).
 */
export type DateInput = string | Date;

function parts(value: DateInput, timeZone: string | undefined): Map<string, string> {
  const date = typeof value === 'string' ? new Date(value) : value;
  const fmt = new Intl.DateTimeFormat('ru-RU', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  return new Map(fmt.formatToParts(date).map((p) => [p.type, p.value]));
}

/** `05.11.2026`; `short` — `05.11` (в плотных местах текущего года). */
export function formatDate(value: DateInput, timeZone?: string, short = false): string {
  const p = parts(value, timeZone);
  const day = `${p.get('day')}.${p.get('month')}`;
  return short ? day : `${day}.${p.get('year')}`;
}

/** `14:20`. */
export function formatTime(value: DateInput, timeZone?: string): string {
  const p = parts(value, timeZone);
  return `${p.get('hour')}:${p.get('minute')}`;
}

/** `01.11.2026 11:07`. */
export function formatDateTime(value: DateInput, timeZone?: string, short = false): string {
  return `${formatDate(value, timeZone, short)} ${formatTime(value, timeZone)}`;
}
