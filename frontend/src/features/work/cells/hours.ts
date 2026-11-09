/**
 * FE-025 · разбор ввода в ячейках (FR-TREE-21, BR-CALC-03).
 *
 * O/R/P: разделитель — запятая или точка, шаг 0,5 (округляем и говорим об этом), 0–99 999,5,
 * пусто — очистить. В поле O можно ввести всю вилку: `8-12-20` или `8/12/20`. ×N — целое 1–10 000.
 */
import { D, dec } from '../../../shared/calc';

export const HOURS_MAX = '99999.5';
export const MULTIPLIER_MAX = 10_000;

export type HoursParse =
  | { ok: true; value: string | null; rounded: boolean }
  | { ok: false; error: 'number' | 'range' };

const DIGITS = /^\d+$/;

/** «12», «12,5», «12.5»: цифры и не больше одного разделителя. */
function isNumber(text: string): boolean {
  const parts = text.split(/[.,]/);
  return parts.length <= 2 && parts.every((p) => DIGITS.test(p));
}

/** Часы из строки ввода: значение для API (точка, без лишних нулей) и признак округления. */
export function parseHours(input: string): HoursParse {
  const text = input.trim().replace(/\s/g, '');
  if (!text) return { ok: true, value: null, rounded: false };
  if (text.length > 12 || !isNumber(text)) return { ok: false, error: 'number' };
  const raw = dec(text.replace(',', '.'));
  // шаг 0,5 по ROUND_HALF_UP, как на сервере (BR-CALC-03, leaf.py)
  const value = raw.mul(2).toDecimalPlaces(0, D.ROUND_HALF_UP).div(2);
  if (value.gt(HOURS_MAX)) return { ok: false, error: 'range' };
  return { ok: true, value: value.toFixed(), rounded: !value.eq(raw) };
}

/** Быстрый ввод вилки в поле O: три числа через «-», «–» или «/». null — это не вилка. */
export function parseFork(input: string): [string, string, string] | null {
  const parts = input
    .trim()
    .split(/\s*[-–/]\s*/)
    .filter((p) => p !== '');
  if (parts.length !== 3) return null;
  const [o, r, p] = parts;
  return o !== undefined && r !== undefined && p !== undefined ? [o, r, p] : null;
}

export type MultiplierParse = { ok: true; value: number } | { ok: false; error: 'integer' };

export function parseMultiplier(input: string): MultiplierParse {
  const text = input.trim();
  if (!/^\d+$/.test(text)) return { ok: false, error: 'integer' };
  const value = Number(text);
  return value >= 1 && value <= MULTIPLIER_MAX ? { ok: true, value } : { ok: false, error: 'integer' };
}
