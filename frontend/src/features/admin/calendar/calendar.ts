/**
 * FE-072 · правила производственного календаря (SPEC 7.5, GAP-03, Q-43): год хранит исключения из
 * Пн–Пт — нерабочие будни и рабочие выходные; без календаря год считается по Пн–Пт.
 */
export type Day = { date: string; is_working: boolean };
export type Exceptions = ReadonlyMap<string, boolean>;

const pad = (n: number) => String(n).padStart(2, '0');
export const iso = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;
const utc = (date: string) => new Date(`${date}T00:00:00Z`);
export const daysIn = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();
export const isWeekend = (date: string) => [0, 6].includes(utc(date).getUTCDay());

/** Рабочий ли день: исключение года или Пн–Пт. */
export const isWorking = (ex: Exceptions, date: string) => ex.get(date) ?? !isWeekend(date);

export const exceptionsOf = (days: readonly Day[]): Exceptions =>
  new Map(days.filter((d) => d.is_working === isWeekend(d.date)).map((d) => [d.date, d.is_working]));

/** Ручная правка: день меняет статус; совпавший с Пн–Пт статус перестаёт быть исключением. */
export function toggle(ex: Exceptions, date: string): Exceptions {
  const next = new Map(ex);
  const value = !isWorking(ex, date);
  if (value === !isWeekend(date)) next.delete(date);
  else next.set(date, value);
  return next;
}

export const daysOf = (ex: Exceptions): Day[] =>
  [...ex.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, is_working]) => ({ date, is_working }));

export const sameExceptions = (a: Exceptions, b: Exceptions) =>
  a.size === b.size && [...a.entries()].every(([k, v]) => b.get(k) === v);

/** Недели месяца с понедельника: null — пустые клетки до 1-го и после последнего дня. */
export function monthWeeks(year: number, month: number): (string | null)[][] {
  const first = (utc(iso(year, month, 1)).getUTCDay() + 6) % 7;
  const cells: (string | null)[] = [
    ...Array<null>(first).fill(null),
    ...Array.from({ length: daysIn(year, month) }, (_, i) => iso(year, month, i + 1)),
  ];
  while (cells.length % 7) cells.push(null);
  const weeks: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

export const workingDays = (ex: Exceptions, year: number, month: number) =>
  Array.from({ length: daysIn(year, month) }, (_, i) => iso(year, month, i + 1)).filter((d) => isWorking(ex, d)).length;

const MONTH = new Intl.DateTimeFormat('ru-RU', { month: 'long', timeZone: 'UTC' });
const DAY = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' });
export const monthName = (m: number) => {
  const s = MONTH.format(new Date(Date.UTC(2000, m - 1, 1)));
  return s.charAt(0).toUpperCase() + s.slice(1);
};
export const dayLabel = (date: string) => DAY.format(utc(date));
export const dayNumber = (date: string) => Number(date.slice(8));
