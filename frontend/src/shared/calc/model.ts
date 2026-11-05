/**
 * FE-002 · вход расчёта: проект, фазы, дисциплины, плоский список узлов (SPEC 14.3).
 * Формат `input` фикстур contracts/fixtures/calc (README 1.1); зеркало `domain/calc/model.py`.
 */
import { dec, type Dec } from './decimal';

export const PM_ROW = 'pm';

export type NodeKind = 'phase' | 'discipline' | 'item';
export type BranchStatus = 'not_started' | 'draft' | 'done' | 'not_needed';
export type QuoteFigure = 'e' | 'p80' | 'p90';
export type DetailLevel = 'coarse' | 'medium' | 'detailed';
export const FIGURES: readonly QuoteFigure[] = ['e', 'p80', 'p90'];

export interface Phase {
  id: string;
  name: string;
  isCrossCutting: boolean;
  inPmBase: boolean;
  enabled: boolean;
}

export interface Discipline {
  id: string;
  name: string;
}

export interface CalcNode {
  id: string;
  parentId: string | null;
  kind: NodeKind;
  phaseId: string;
  disciplineId: string | null;
  type: string | null;
  title: string;
  o: Dec | null;
  r: Dec | null;
  p: Dec | null;
  multiplier: number;
}

export interface MoneySettings {
  currency: string;
  exchangeRate: Dec;
  vatPercent: Dec | null;
  /** Дисциплина → ставка ₽/ч; ключ `null` — ставка УП. Нет ключа — ставка не задана. */
  rates: Map<string | null, Dec>;
}

export interface ProjectInput {
  pmPercent: Dec;
  quoteFigure: QuoteFigure;
  detailLevel: DetailLevel;
  phases: Phase[];
  disciplines: Discipline[];
  nodes: CalcNode[];
  /** Ключ `${phaseId}/${disciplineId}`. */
  branchStatus: Map<string, BranchStatus>;
  money: MoneySettings | null;
}

export function branchKey(phaseId: string, disciplineId: string): string {
  return `${phaseId}/${disciplineId}`;
}

/* ---- разбор формата фикстур и API (десятичные — строки) ---- */

interface RawNode {
  id: string;
  parent_id: string | null;
  kind: NodeKind;
  phase_id: string;
  discipline_id?: string | null;
  type?: string | null;
  title?: string;
  o?: string;
  r?: string;
  p?: string;
  multiplier?: number;
}

export interface RawProjectInput {
  project: { pm_percent: string; quote_figure: QuoteFigure; detail_level: DetailLevel };
  phases: {
    id: string;
    name: string;
    is_cross_cutting: boolean;
    in_pm_base: boolean;
    enabled: boolean;
  }[];
  disciplines: { id: string; name: string }[];
  nodes: RawNode[];
  branch_status?: { phase_id: string; discipline_id: string; status: BranchStatus }[];
  money?: {
    currency: string;
    exchange_rate: string;
    vat_percent: string | null;
    rates?: { discipline_id: string | null; rate_rub: string }[];
  };
}

function optional(value: string | undefined): Dec | null {
  return value === undefined ? null : dec(value);
}

export function parseNode(n: RawNode): CalcNode {
  return {
    id: n.id,
    parentId: n.parent_id,
    kind: n.kind,
    phaseId: n.phase_id,
    disciplineId: n.discipline_id ?? null,
    type: n.type ?? null,
    title: n.title ?? '',
    o: optional(n.o),
    r: optional(n.r),
    p: optional(n.p),
    multiplier: n.multiplier ?? 1,
  };
}

export function parseInput(data: RawProjectInput): ProjectInput {
  const money = data.money;
  return {
    pmPercent: dec(data.project.pm_percent),
    quoteFigure: data.project.quote_figure,
    detailLevel: data.project.detail_level,
    phases: data.phases.map((p) => ({
      id: p.id,
      name: p.name,
      isCrossCutting: p.is_cross_cutting,
      inPmBase: p.in_pm_base,
      enabled: p.enabled,
    })),
    disciplines: data.disciplines.map((d) => ({ id: d.id, name: d.name })),
    nodes: data.nodes.map(parseNode),
    branchStatus: new Map(
      (data.branch_status ?? []).map((b) => [branchKey(b.phase_id, b.discipline_id), b.status]),
    ),
    money:
      money === undefined
        ? null
        : {
            currency: money.currency,
            exchangeRate: dec(money.exchange_rate),
            vatPercent: money.vat_percent === null ? null : dec(money.vat_percent),
            rates: new Map((money.rates ?? []).map((r) => [r.discipline_id, dec(r.rate_rub)])),
          },
  };
}
