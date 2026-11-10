/**
 * FE-072 · производственный календарь (SPEC 7.5, GAP-03, Q-43): по году хранятся исключения из
 * Пн–Пт — нерабочие будни и рабочие выходные. CSV открытых данных data.gov.ru разбирается как есть:
 * строка года, в столбцах месяцев — нерабочие дни через запятую; «*» — сокращённый рабочий день,
 * «+» — перенесённый выходной (нерабочий). Года без календаря считаются по Пн–Пт.
 */
type Day = { date: string; is_working: boolean };

/** 2026 год демо: новогодние каникулы 1–9 января, 23 февраля, 9 марта, 1 и 11 мая, 12 июня, 4 ноября, 31 декабря. */
const SEED_2026 = [
  "2026-01-01",
  "2026-01-02",
  "2026-01-05",
  "2026-01-06",
  "2026-01-07",
  "2026-01-08",
  "2026-01-09",
  "2026-02-23",
  "2026-03-09",
  "2026-05-01",
  "2026-05-11",
  "2026-06-12",
  "2026-11-04",
  "2026-12-31",
];

const years = new Map<number, Day[]>();

export function resetDemoCalendar() {
  years.clear();
  years.set(
    2026,
    SEED_2026.map((date) => ({ date, is_working: false })),
  );
}
resetDemoCalendar();

export function list(year?: number) {
  return [...years.entries()]
    .filter(([y]) => year === undefined || y === year)
    .sort(([a], [b]) => a - b)
    .map(([y, days]) => ({ year: y, days }));
}

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;
const weekend = (y: number, m: number, d: number) =>
  [0, 6].includes(new Date(Date.UTC(y, m - 1, d)).getUTCDay());
const daysIn = (y: number, m: number) =>
  new Date(Date.UTC(y, m, 0)).getUTCDate();

/** Исключения из Пн–Пт по набору нерабочих дней года. */
function exceptions(year: number, off: Set<string>): Day[] {
  const out: Day[] = [];
  for (let m = 1; m <= 12; m += 1)
    for (let d = 1; d <= daysIn(year, m); d += 1) {
      const date = iso(year, m, d);
      const isOff = off.has(date);
      if (isOff !== weekend(year, m, d)) out.push({ date, is_working: !isOff });
    }
  return out;
}

export function preview(year: number, days: readonly Day[]) {
  const map = new Map(days.map((d) => [d.date, d.is_working]));
  const months = [];
  for (let m = 1; m <= 12; m += 1) {
    let working = 0;
    const nonWorking: string[] = [];
    const workingWeekends: string[] = [];
    for (let d = 1; d <= daysIn(year, m); d += 1) {
      const date = iso(year, m, d);
      const we = weekend(year, m, d);
      const isWorking = map.get(date) ?? !we;
      if (isWorking) working += 1;
      if (!isWorking && !we) nonWorking.push(date);
      if (isWorking && we) workingWeekends.push(date);
    }
    months.push({
      month: m,
      working_days: working,
      non_working: nonWorking,
      working_weekends: workingWeekends,
    });
  }
  return months;
}

/** Строки CSV с учётом кавычек: `2026,"1,2,3+,4",…`. */
function rows(text: string): string[][] {
  const out: string[][] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const cells: string[] = [];
    let cur = "";
    let quoted = false;
    for (const ch of line) {
      if (ch === '"') quoted = !quoted;
      else if (ch === "," && !quoted) {
        cells.push(cur);
        cur = "";
      } else cur += ch;
    }
    cells.push(cur);
    out.push(cells.map((c) => c.trim()));
  }
  return out;
}

/**
 * Разбор CSV data.gov.ru: берётся последняя строка с годом 2000–2100 (файл содержит годы подряд,
 * новый год — внизу). Возвращает год и исключения или null, если формат не узнан.
 */
export function parseCsv(text: string): { year: number; days: Day[] } | null {
  const data = rows(text).filter((r) => /^\d{4}$/.test(r[0] ?? ""));
  const row = data.at(-1);
  if (!row || row.length < 13) return null;
  const year = Number(row[0]);
  if (year < 2000 || year > 2100) return null;
  const off = new Set<string>();
  for (let m = 1; m <= 12; m += 1) {
    for (const token of (row[m] ?? "").split(",")) {
      const t = token.trim();
      if (!t || t.endsWith("*")) continue;
      const d = Number(t.replace("+", ""));
      if (!Number.isInteger(d) || d < 1 || d > daysIn(year, m)) return null;
      off.add(iso(year, m, d));
    }
  }
  return { year, days: exceptions(year, off) };
}

export type CalendarError = "VALIDATION_FAILED" | "UNSUPPORTED_MEDIA_TYPE";

type Upload = {
  file?: { file_name?: string; text?: string };
  dry_run?: string | boolean;
};

/** Пустое тело (проверка моков) — предпросмотр сохранённого 2026 года. */
export function upload(body: unknown) {
  const b = (body ?? {}) as Upload;
  if (!b.file) {
    const days = years.get(2026) ?? [];
    return { year: 2026, months: preview(2026, days), saved: false };
  }
  if (!(b.file.file_name ?? "").toLowerCase().endsWith(".csv"))
    return { error: "UNSUPPORTED_MEDIA_TYPE" as const };
  const parsed = parseCsv(b.file.text ?? "");
  if (!parsed) return { error: "VALIDATION_FAILED" as const };
  const save = b.dry_run === false || b.dry_run === "false";
  if (save) years.set(parsed.year, parsed.days);
  return {
    year: parsed.year,
    months: preview(parsed.year, parsed.days),
    saved: save,
  };
}

export function put(year: number, body: unknown) {
  const days = ((body ?? {}) as { days?: Day[] }).days;
  if (!Array.isArray(days)) return { year, days: years.get(year) ?? [] };
  if (days.some((d) => !String(d.date).startsWith(`${year}-`)))
    return { error: "VALIDATION_FAILED" as const };
  years.set(year, days);
  return { year, days };
}

export function remove(year: number) {
  years.delete(year);
}
