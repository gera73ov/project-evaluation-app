/**
 * FE-002, FE-003 · форматирование чисел (DESIGN.md раздел 11, SPEC BR-CALC-03).
 *
 * Часы — 1 знак, деньги — целые, проценты — целые, курс — 4 знака; ROUND_HALF_UP; тысячи
 * отделяются неразрывным пробелом, дробная часть — запятой; минус — U+2212. Значения приходят
 * как decimal.js или десятичная строка API: `Intl.NumberFormat` не годится — он работает с
 * числами с плавающей точкой и теряет точность денег больше 2^53.
 */
import { D, roundHalfUp, type Dec } from '../calc/decimal';

export const NBSP = ' ';
export const MINUS = '−';
export const DASH = '—';

type Value = Dec | string;

function group(integer: string): string {
  let out = '';
  for (let i = 0; i < integer.length; i += 1) {
    if (i > 0 && (integer.length - i) % 3 === 0) out += NBSP;
    out += integer.charAt(i);
  }
  return out;
}

/** Число с `places` знаками: `1 240,5`, `−4,7`. */
export function formatNumber(value: Value, places: number, options: { sign?: boolean } = {}): string {
  const rounded = roundHalfUp(new D(value), places);
  const [integer = '0', fraction] = rounded.abs().toFixed(places).split('.');
  const body = fraction === undefined ? group(integer) : `${group(integer)},${fraction}`;
  if (rounded.isNegative() && !rounded.isZero()) return `${MINUS}${body}`;
  return options.sign ? `+${body}` : body;
}

/** Часы — 1 знак всегда: `406,5`; с единицей — `425,5 ч`. */
export function formatHours(value: Value | null, options: { unit?: boolean; sign?: boolean } = {}): string {
  if (value === null) return DASH;
  const text = formatNumber(value, 1, options);
  return options.unit ? `${text}${NBSP}ч` : text;
}

/** Деньги — целые с валютой: `1 146 798 ₽`, `12 978 USD`; `null` (переполнение) — «—». */
export function formatMoney(value: Value | null, currency = 'RUB'): string {
  if (value === null) return DASH;
  const symbol = currency === 'RUB' ? '₽' : currency;
  return `${formatNumber(value, 0)}${NBSP}${symbol}`;
}

/** Проценты — целые: `27%`; `null` (знаменатель 0) — «—». */
export function formatPercent(value: Value | null, places = 0): string {
  if (value === null) return DASH;
  return `${formatNumber(value, places)}%`;
}

/** Курс — 4 знака: `92,5000`. */
export function formatRate(value: Value): string {
  return formatNumber(value, 4);
}

/** Ввод O/R/P без лишнего нуля: `12`, `12,5`. */
export function formatHoursInput(value: Value | null): string {
  if (value === null) return '';
  return new D(value).toFixed().replace('.', ',');
}

/** Вилка O–R–P через короткое тире: `40–60–100`. */
export function formatFork(o: Value | null, r: Value | null, p: Value | null): string {
  return [o, r, p].map((v) => (v === null ? DASH : formatHoursInput(v))).join('–');
}
