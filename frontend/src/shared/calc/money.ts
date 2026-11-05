/**
 * FE-002 · деньги: строки, НДС, валюта (SPEC 6.4, BR-MONEY-02…06, R-01, Q-40, Q-41).
 * Зеркало `domain/calc/money.py`. Показ денег ролям решает сервер (BR-MONEY-01): клиент
 * считает, только если API отдал ставки.
 */
import { D, HUNDRED, ZERO, roundHalfUp, type Dec } from './decimal';
import { FIGURES, PM_ROW, type MoneySettings, type QuoteFigure } from './model';
import type { ProjectResult } from './project';

export const MONEY_LIMIT = new D(10).pow(20); // NUMERIC(20,0)
export const HOURS_CACHE_LIMIT = new D(10).pow(12); // NUMERIC(14,2)
export const PM_LABEL = 'УП';
export const NO_VAT_LABEL = 'НДС не облагается';

export interface FigureMoney {
  figure: QuoteFigure;
  /** K_F; при E = 0 не вычисляется. */
  k: Dec | null;
  /** id дисциплины или "pm" → сумма; `null` — переполнение NUMERIC(20,0), показывается «—». */
  rowsRub: Map<string, Dec | null>;
  totalRub: Dec | null;
  /** `null` и при «без НДС», и при переполнении. */
  vatRub: Dec | null;
  totalWithVatRub: Dec | null;
  rowsCur: Map<string, Dec | null>;
  totalCur: Dec | null;
  vatCur: Dec | null;
  totalWithVatCur: Dec | null;
  overflowRub: boolean;
  overflowCur: boolean;
}

export interface MoneyResult {
  currency: string;
  vatPercent: Dec | null;
  vatLabel: string;
  quoteFigure: QuoteFigure;
  /** id дисциплин и "pm" с часами, но без ставки (BR-MONEY-02). */
  ratesMissing: string[];
  ratesMissingText: string | null;
  /** `null`, если ставки не заданы: вместо сумм — «не заданы ставки: …». */
  byFigure: Map<QuoteFigure, FigureMoney> | null;
}

export function fitsMoney(value: Dec): boolean {
  return value.abs().lt(MONEY_LIMIT);
}

export function fitsHoursCache(value: Dec): boolean {
  return roundHalfUp(value, 2).abs().lt(HOURS_CACHE_LIMIT);
}

function fit(value: Dec): Dec | null {
  return fitsMoney(value) ? value : null;
}

function sumOrNull(values: (Dec | null)[]): Dec | null {
  let total = ZERO;
  for (const v of values) {
    if (v === null) return null;
    total = total.plus(v);
  }
  return fit(total);
}

function rowHours(project: ProjectResult): Map<string, Dec> {
  const rows = new Map<string, Dec>();
  for (const d of project.input.disciplines) rows.set(d.id, project.disciplines.get(d.id)?.e ?? ZERO);
  rows.set(PM_ROW, project.pm.e);
  return rows;
}

function rateOf(money: MoneySettings, row: string): Dec | undefined {
  return money.rates.get(row === PM_ROW ? null : row);
}

function figureTotal(project: ProjectResult, figure: QuoteFigure): Dec {
  if (figure === 'p80') return project.total.p80;
  if (figure === 'p90') return project.total.p90;
  return project.total.e;
}

function figureMoney(project: ProjectResult, money: MoneySettings, figure: QuoteFigure): FigureMoney {
  const eTotal = project.total.e;
  const k = eTotal.isZero() ? null : figureTotal(project, figure).div(eTotal);
  const factor = k ?? ZERO; // E = 0: деления нет, все строки равны 0
  const rowsRub = new Map<string, Dec | null>();
  for (const [row, hours] of rowHours(project)) {
    const rate = rateOf(money, row) ?? ZERO; // пустая ставка допустима только при E = 0
    rowsRub.set(row, fit(roundHalfUp(hours.times(rate).times(factor))));
  }
  const totalRub = sumOrNull([...rowsRub.values()]);
  const fx = money.exchangeRate;
  const rowsCur = new Map<string, Dec | null>();
  for (const [row, rub] of rowsRub) rowsCur.set(row, rub === null ? null : fit(roundHalfUp(rub.div(fx))));
  const totalCur = sumOrNull([...rowsCur.values()]);
  let vatRub: Dec | null = null;
  let vatCur: Dec | null = null;
  let totalWithVatRub: Dec | null = null;
  let totalWithVatCur: Dec | null = null;
  if (money.vatPercent !== null && totalRub !== null) {
    vatRub = fit(roundHalfUp(totalRub.times(money.vatPercent).div(HUNDRED)));
    totalWithVatRub = sumOrNull([totalRub, vatRub]);
    if (vatRub !== null) vatCur = fit(roundHalfUp(vatRub.div(fx)));
    if (totalCur !== null) totalWithVatCur = sumOrNull([totalCur, vatCur]);
  }
  return {
    figure,
    k,
    rowsRub,
    totalRub,
    vatRub,
    totalWithVatRub,
    rowsCur,
    totalCur,
    vatCur,
    totalWithVatCur,
    overflowRub: totalRub === null,
    overflowCur: totalCur === null,
  };
}

/** Строки с часами без ставки: дисциплины с E > 0 и УП при E_УП > 0 (BR-MONEY-02). */
export function ratesMissing(project: ProjectResult, money: MoneySettings): string[] {
  const missing: string[] = [];
  for (const [row, hours] of rowHours(project)) {
    if (hours.gt(ZERO) && rateOf(money, row) === undefined) missing.push(row);
  }
  return missing;
}

export function ratesMissingText(project: ProjectResult, missing: string[]): string {
  const names = new Map(project.input.disciplines.map((d) => [d.id, d.name]));
  const labels = missing.map((row) => (row === PM_ROW ? PM_LABEL : (names.get(row) ?? row)));
  return `не заданы ставки: ${labels.join(', ')}`;
}

export function vatLabel(vatPercent: Dec | null): string {
  return vatPercent === null ? NO_VAT_LABEL : `НДС ${vatPercent.toFixed()}%`;
}

/** Деньги проекта по E, P80 и P90 (SPEC 6.4). */
export function calculateMoney(project: ProjectResult, money: MoneySettings): MoneyResult {
  const missing = ratesMissing(project, money);
  return {
    currency: money.currency,
    vatPercent: money.vatPercent,
    vatLabel: vatLabel(money.vatPercent),
    quoteFigure: project.input.quoteFigure,
    ratesMissing: missing,
    ratesMissingText: missing.length > 0 ? ratesMissingText(project, missing) : null,
    byFigure:
      missing.length > 0
        ? null
        : new Map(FIGURES.map((f) => [f, figureMoney(project, money, f)] as const)),
  };
}

export interface ProjectCache {
  e: Dec | null;
  costRub: Dec | null;
  quoteCur: Dec | null;
}

/** Кэш итогов для списков (SPEC 14.2): не помещается — `null`, в списке «—». */
export function projectCache(project: ProjectResult, money: MoneyResult | null): ProjectCache {
  const e = roundHalfUp(project.total.e, 2);
  const byFigure = money?.byFigure ?? null;
  return {
    e: fitsHoursCache(e) ? e : null,
    costRub: byFigure?.get('e')?.totalRub ?? null,
    quoteCur: (money && byFigure?.get(money.quoteFigure)?.totalCur) ?? null,
  };
}
