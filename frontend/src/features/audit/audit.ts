/**
 * FE-065 · правила журнала аудита (SEC-AUD-06, Q-27): какие категории видит роль, список типов
 * событий для фильтра (из contracts/audit-events.yaml), границы периода и параметры запроса.
 */
import { AUDIT_CATEGORIES, AUDIT_EVENTS } from '../../shared/api/generated/audit-events';

export type AuditResult = 'success' | 'failure' | 'denied';
export const RESULTS: readonly AuditResult[] = ['success', 'failure', 'denied'];

export type AuditFilters = {
  from: string;
  to: string;
  userId: string | null;
  eventType: string | null;
  result: AuditResult | null;
};

/** Категории, которые видит пользователь с этими системными ролями. */
export function visibleCategories(roles: readonly string[]): string[] {
  return Object.entries(AUDIT_CATEGORIES)
    .filter(([, c]) => c.visible_to.some((r) => roles.includes(r)))
    .map(([key]) => key);
}

/** Типы событий для фильтра: только видимых категорий, сгруппированы по категории. */
export function eventOptions(roles: readonly string[]): { group: string; items: { value: string; label: string }[] }[] {
  const cats = new Map(Object.entries(AUDIT_CATEGORIES));
  return visibleCategories(roles).map((cat) => ({
    group: cats.get(cat)?.title ?? cat,
    items: Object.entries(AUDIT_EVENTS)
      .filter(([, e]) => e.category === cat)
      .map(([code, e]) => ({ value: code, label: `${e.title} · ${code}` })),
  }));
}

export const eventTitle = (code: string) => new Map(Object.entries(AUDIT_EVENTS)).get(code)?.title ?? code;
export const categoryTitle = (key: string) => new Map(Object.entries(AUDIT_CATEGORIES)).get(key)?.title ?? key;

/** Дата `YYYY-MM-DD` по местному времени. */
export function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** По умолчанию — последние 7 дней, включая сегодня. */
export function defaultFilters(now = new Date()): AuditFilters {
  const from = new Date(now);
  from.setDate(from.getDate() - 6);
  return { from: isoDay(from), to: isoDay(now), userId: null, eventType: null, result: null };
}

/** Период задан и не перевёрнут. */
export const periodValid = (f: AuditFilters) => Boolean(f.from && f.to && f.from <= f.to);

/** Границы периода в UTC: начало первого дня и конец последнего по местному времени. */
export function periodOf(f: AuditFilters): { from: string; to: string } {
  const start = new Date(`${f.from}T00:00:00`);
  const end = new Date(`${f.to}T23:59:59.999`);
  return { from: start.toISOString(), to: end.toISOString() };
}

/** Параметры `GET /system/audit` без пустых фильтров. */
export function queryOf(f: AuditFilters) {
  return {
    ...periodOf(f),
    ...(f.userId ? { user_id: f.userId } : {}),
    ...(f.eventType ? { event_type: f.eventType } : {}),
    ...(f.result ? { result: f.result } : {}),
  };
}
