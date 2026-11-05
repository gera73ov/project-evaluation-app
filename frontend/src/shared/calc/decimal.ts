/**
 * FE-002 · десятичная арифметика клиентского расчёта (SPEC 6, BR-CALC-03, 13.1).
 *
 * Зеркало `backend/src/estimator/domain/calc/_decimal.py`: 40 значащих цифр, промежуточные
 * значения без округления, вывод — только ROUND_HALF_UP. Числа с плавающей точкой не используются:
 * расхождение клиента и сервера — дефект (SPEC 6).
 */
import Decimal from 'decimal.js';

export const PRECISION = 40;

/** Отдельный конструктор: глобальные настройки decimal.js остаются нетронутыми. */
export const D = Decimal.clone({
  precision: PRECISION,
  rounding: Decimal.ROUND_HALF_EVEN,
  toExpNeg: -60,
  toExpPos: 60,
});
export type Dec = Decimal;

export const ZERO = new D(0);
export const ONE = new D(1);
export const HUNDRED = new D(100);

/** z-квантили нормального распределения (SPEC 6.2). */
export const Z80 = new D('0.8416');
export const Z90 = new D('1.2816');

/**
 * Шум последних знаков (σ_УП = 3,4500…001 вместо 3,45) снимается приведением к 20 знакам перед
 * округлением для вывода — так же, как на сервере (GUARD_PLACES).
 */
export const GUARD_PLACES = 20;

/** ROUND_HALF_UP до `places` знаков после запятой: 0,05 → 0,1; 3,45 → 3,5; 2,5 → 3. */
export function roundHalfUp(value: Decimal, places = 0): Decimal {
  return new D(value)
    .toDecimalPlaces(GUARD_PLACES, Decimal.ROUND_HALF_EVEN)
    .toDecimalPlaces(places, Decimal.ROUND_HALF_UP);
}

/** Строка с ровно `places` знаками после точки (формат API и фикстур). */
export function toFixedHalfUp(value: Decimal, places = 0): string {
  return roundHalfUp(value, places).toFixed(places);
}

export function p80(e: Decimal, sigma: Decimal): Decimal {
  return e.plus(Z80.times(sigma));
}

export function p90(e: Decimal, sigma: Decimal): Decimal {
  return e.plus(Z90.times(sigma));
}

export function dec(value: string | number | Decimal): Decimal {
  return new D(value);
}
