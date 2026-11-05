/**
 * API-006 · десятичные значения API (contracts/api-conventions.md 2.1).
 *
 * Часы, деньги, проценты и коэффициенты приходят и уходят строками ("12.5", "1146798"), чтобы
 * не терять точность (SPEC BR-CALC-03). Branded-тип не даёт подставить произвольную строку
 * туда, где ожидается число: значение получают через asDecimalString или из ответа API.
 */
import type Decimal from 'decimal.js';

declare const brand: unique symbol;

export type DecimalString = string & { readonly [brand]: 'DecimalString' };

// два простых выражения вместо одного с необязательной группой (security/detect-unsafe-regex)
const INTEGER_RE = /^-?\d+$/;
const FRACTION_RE = /^-?\d+\.\d+$/;

/** Проверить строку и пометить её как десятичную. Запятая не принимается: формат API — точка. */
export function asDecimalString(value: string): DecimalString {
  if (!INTEGER_RE.test(value) && !FRACTION_RE.test(value)) {
    throw new RangeError(`не десятичное значение API: ${value}`);
  }
  return value as DecimalString;
}

/** Decimal → строка API без экспоненты (decimal.js toFixed без аргумента). */
export function toDecimalString(value: Decimal): DecimalString {
  return asDecimalString(value.toFixed());
}
