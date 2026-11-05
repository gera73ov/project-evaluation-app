/**
 * FE-002 · расчёт листа (SPEC 6.1, BR-CALC-02…04, FR-TREE-21, NFR-LIM-01).
 * Зеркало `domain/calc/leaf.py`.
 */
import { D, ZERO, p80, p90, type Dec } from './decimal';

export const HOURS_MAX = new D('99999.5');
export const MULTIPLIER_MIN = 1;
export const MULTIPLIER_MAX = 10_000;

export type LeafState = 'empty' | 'invalid' | 'zero' | 'valid';

/** Входит ли лист в суммы (пустые и неверные — нет, BR-CALC-02). */
export function isCounted(state: LeafState): boolean {
  return state === 'valid' || state === 'zero';
}

export class CalcInputError extends Error {
  constructor(
    readonly code: 'VALIDATION_FAILED' | 'VALUE_OUT_OF_RANGE',
    message: string,
  ) {
    super(message);
    this.name = 'CalcInputError';
  }
}

export interface LeafEstimate {
  state: LeafState;
  eUnit: Dec;
  sigmaUnit: Dec;
  e: Dec;
  sigma: Dec;
  /** N·O, N·R, N·P — подсказка узла и «Свернуть в лист» (BR-TREE-03). */
  sumO: Dec;
  sumR: Dec;
  sumP: Dec;
}

export function leafP80(leaf: LeafEstimate): Dec {
  return p80(leaf.e, leaf.sigma);
}

export function leafP90(leaf: LeafEstimate): Dec {
  return p90(leaf.e, leaf.sigma);
}

export function classify(o: Dec | null, r: Dec | null, p: Dec | null): LeafState {
  if (o === null || r === null || p === null) return 'empty';
  if (o.gt(r) || r.gt(p)) return 'invalid';
  if (o.isZero() && r.isZero() && p.isZero()) return 'zero';
  return 'valid';
}

function empty(state: LeafState): LeafEstimate {
  return { state, eUnit: ZERO, sigmaUnit: ZERO, e: ZERO, sigma: ZERO, sumO: ZERO, sumR: ZERO, sumP: ZERO };
}

/** E и σ листа: `E_ед = (O + 4R + P)/6`, `σ_ед = (P − O)/6`, `E = N·E_ед`, `σ = N·σ_ед`. */
export function estimate(o: Dec | null, r: Dec | null, p: Dec | null, multiplier: number): LeafEstimate {
  if (o === null || r === null || p === null) return empty('empty');
  const state = classify(o, r, p);
  if (!isCounted(state)) return empty(state);
  const eUnit = o.plus(r.times(4)).plus(p).div(6);
  const sigmaUnit = p.minus(o).div(6);
  const n = new D(multiplier);
  return {
    state,
    eUnit,
    sigmaUnit,
    e: n.times(eUnit),
    sigma: n.times(sigmaUnit),
    sumO: n.times(o),
    sumR: n.times(r),
    sumP: n.times(p),
  };
}

export interface NormalizedHours {
  value: Dec;
  /** Каноническая строка без лишних нулей: "12", "12.5". */
  text: string;
  /** Ввод округлён до шага 0,5 — у поля показывается подсказка «округлено до …». */
  rounded: boolean;
}

// два простых выражения вместо одного с необязательной группой (security/detect-unsafe-regex)
const HOURS_INT_RE = /^-?\d+$/;
const HOURS_FRACTION_RE = /^-?\d+[.,]\d+$/;
const MULTIPLIER_RE = /^\d+$/;

/** Шаг 0,5 по ROUND_HALF_UP; запятая или точка; диапазон 0–99 999,5 после округления. */
export function normalizeHours(raw: string): NormalizedHours {
  const text = raw.trim();
  if (!HOURS_INT_RE.test(text) && !HOURS_FRACTION_RE.test(text)) {
    throw new CalcInputError('VALIDATION_FAILED', `не число: ${raw}`);
  }
  const value = new D(text.replace(',', '.'));
  let stepped = value.times(2).toDecimalPlaces(0, D.ROUND_HALF_UP).div(2);
  if (stepped.lt(ZERO) || stepped.gt(HOURS_MAX)) {
    throw new CalcInputError('VALUE_OUT_OF_RANGE', `часы вне диапазона 0–99 999,5: ${raw}`);
  }
  if (stepped.isZero()) stepped = ZERO; // «-0» → «0»
  return { value: stepped, text: stepped.toFixed(), rounded: !stepped.eq(value) };
}

/** ×N — целое 1–10 000 (NFR-LIM-01); строка допускается, если в ней только цифры. */
export function validateMultiplier(raw: unknown): number {
  let value = raw;
  if (typeof value === 'string' && MULTIPLIER_RE.test(value.trim())) value = Number(value.trim());
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    throw new CalcInputError('VALIDATION_FAILED', `×N — целое число: ${String(raw)}`);
  }
  if (value < MULTIPLIER_MIN || value > MULTIPLIER_MAX) {
    throw new CalcInputError('VALUE_OUT_OF_RANGE', `×N вне диапазона 1–10 000: ${value}`);
  }
  return value;
}
