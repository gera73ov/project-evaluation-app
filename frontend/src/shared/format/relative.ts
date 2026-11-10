/**
 * FE-010 · «когда» в списках (11.3 «Изменён», колокольчик): «только что», «10 мин назад»,
 * «сегодня 14:20», «вчера», иначе дата ДД.ММ.ГГГГ (FR-UI-02). Сутки — по часовому поясу пользователя.
 */
import i18n from '../i18n';
import { formatDate, formatTime, type DateInput } from './date';

function dayKey(value: Date, timeZone: string | undefined): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(value);
}

export function formatWhen(
  value: DateInput,
  options: { now?: Date; timeZone?: string | undefined; minutes?: boolean } = {},
): string {
  const date = typeof value === 'string' ? new Date(value) : value;
  const now = options.now ?? new Date();
  const diff = now.getTime() - date.getTime();
  if (options.minutes && diff >= 0 && diff < 60 * 60_000) {
    const minutes = Math.floor(diff / 60_000);
    return minutes < 1 ? i18n.t('common.when.justNow') : i18n.t('common.when.minutesAgo', { count: minutes });
  }
  const today = dayKey(now, options.timeZone);
  const yesterday = dayKey(new Date(now.getTime() - 24 * 3600_000), options.timeZone);
  const day = dayKey(date, options.timeZone);
  if (day === today) return i18n.t('common.when.today', { time: formatTime(date, options.timeZone) });
  if (day === yesterday) return i18n.t('common.when.yesterday');
  return formatDate(date, options.timeZone);
}
