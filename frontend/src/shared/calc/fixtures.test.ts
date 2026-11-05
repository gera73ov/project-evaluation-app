/**
 * FE-002 · клиентский расчёт на эталонных фикстурах CORE-001: Vitest-версии TC-CALC-01…04 и
 * TC-MONEY-01. Сравнение — по правилам contracts/fixtures/calc/README.md раздел 2.
 */
import { describe, expect, it } from 'vitest';

import edge from '../../../../contracts/fixtures/calc/edge-cases.json';
import portal from '../../../../contracts/fixtures/calc/portal-dilerov.json';
import {
  calculate,
  calculateMoney,
  controlRatio,
  dec,
  decomposition,
  leafP80,
  leafP90,
  parseInput,
  projectCache,
  roundHalfUp,
  shares,
  sigmaOf,
  totalsP80,
  totalsP90,
  unaccountedWarning,
  volumes,
  type Dec,
  type DetailLevel,
  type Figures,
  type RawProjectInput,
} from './index';

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
type Actual = Dec | Json | undefined | Actual[] | { [key: string]: Actual };

function isDec(value: unknown): value is Dec {
  return typeof value === 'object' && value !== null && 'toDecimalPlaces' in value;
}

function places(expected: string): number {
  const dot = expected.indexOf('.');
  return dot < 0 ? 0 : expected.length - dot - 1;
}

/** Проверяются только ключи, которые есть в ожидании (ключ `from_spec` пропускается). */
function assertMatches(actual: Actual, expected: Json, path: string): void {
  if (expected !== null && typeof expected === 'object' && !Array.isArray(expected)) {
    expect(actual, `${path}: ожидался объект`).toBeTypeOf('object');
    const obj = new Map(Object.entries(actual as Record<string, Actual>));
    for (const [key, value] of Object.entries(expected)) {
      if (key === 'from_spec') continue;
      expect(obj.has(key), `${path}.${key}: нет в результате`).toBe(true);
      assertMatches(obj.get(key), value, `${path}.${key}`);
    }
  } else if (typeof expected === 'string' && isDec(actual)) {
    expect(roundHalfUp(actual, places(expected)).toFixed(places(expected)), path).toBe(expected);
  } else {
    expect(actual, path).toEqual(expected);
  }
}

function figures(f: Figures): Record<string, Dec> {
  return { e: f.e, sigma: f.sigma, p80: f.p80, p90: f.p90 };
}

function obj<V>(map: ReadonlyMap<string, V>): Record<string, V> {
  return Object.fromEntries(map);
}

function wrap(expected: Record<string, Json>, key: string, values: Record<string, Actual>) {
  const group = new Map(Object.entries(expected)).get(key);
  const hasValues = group !== null && typeof group === 'object' && 'values' in (group as object);
  return hasValues ? { values } : values;
}

function withLevel(raw: RawProjectInput, level: DetailLevel) {
  return calculate({ ...parseInput(raw), detailLevel: level });
}

/** Посчитать вход фикстуры и вернуть результат в форме `expected` (как `_shape.py`). */
function shape(raw: RawProjectInput, expected: Record<string, Json>): Record<string, Actual> {
  const input = parseInput(raw);
  const result = calculate(input);
  const nodes = new Map<string, Actual>();
  const leaves = new Map<string, Actual>();
  const leafState = new Map<string, Actual>();
  for (const [id, node] of result.tree.nodes) {
    const t = node.totals;
    const values: Record<string, Actual> = {
      e: t.e,
      sigma: sigmaOf(t),
      p80: totalsP80(t),
      p90: totalsP90(t),
      sum_o: t.sumO,
      sum_r: t.sumR,
      sum_p: t.sumP,
    };
    if (node.leaf) {
      values.e_unit = node.leaf.eUnit;
      leaves.set(id, values);
      leafState.set(id, node.leaf.state);
      values.p80 = leafP80(node.leaf);
      values.p90 = leafP90(node.leaf);
    }
    nodes.set(id, values);
  }
  const out: Record<string, Actual> = {
    leaves: { values: obj(leaves) },
    nodes: wrap(expected, 'nodes', obj(nodes)),
    leaf_state: obj(leafState),
    disciplines: { values: Object.fromEntries([...result.disciplines].map(([d, f]) => [d, figures(f)])) },
    phases: { values: Object.fromEntries([...result.phases].map(([p, f]) => [p, figures(f)])) },
    works: wrap(expected, 'works', { ...figures(result.works), sigma_squared: result.works.sigma.pow(2) }),
    pm: wrap(expected, 'pm', {
      ...figures(result.pm),
      sigma_exact: result.pm.sigma,
      base_e: result.pm.baseE,
    }),
    total: wrap(expected, 'total', {
      ...figures(result.total),
      e_precise: result.total.e,
      p80_precise: result.total.p80,
      unaccounted_leaves: result.unaccountedLeaves,
    }),
    warning: { unaccounted_leaves: result.unaccountedLeaves, text: unaccountedWarning(result) },
  };
  const collapse = new Map(Object.entries(expected)).get('collapse_suggestion') as
    | { node_id: string }
    | undefined;
  if (collapse) {
    const s = result.tree.collapseSuggestion(collapse.node_id);
    out.collapse_suggestion = { node_id: collapse.node_id, o: s.o, r: s.r, p: s.p, multiplier: s.multiplier };
  }
  const money = input.money ? calculateMoney(result, input.money) : null;
  if (money) {
    const m: Record<string, Actual> = {
      quote_figure: money.quoteFigure,
      rates_missing: money.ratesMissing,
      vat_label: money.vatLabel,
    };
    if (money.ratesMissingText !== null) m.text = money.ratesMissingText;
    if (money.byFigure) {
      m.by_figure = Object.fromEntries(
        [...money.byFigure].map(([f, b]) => [
          f,
          {
            k: b.k,
            rows_rub: obj(b.rowsRub),
            total_rub: b.totalRub,
            vat_rub: b.vatRub,
            total_with_vat_rub: b.totalWithVatRub,
            rows_cur: obj(b.rowsCur),
            total_cur: b.totalCur,
            vat_cur: b.vatCur,
            total_with_vat_cur: b.totalWithVatCur,
            total_cur_overflow: b.overflowCur,
          },
        ]),
      );
    }
    out.money = m;
  }
  const cache = projectCache(result, money);
  out.cache = { e: cache.e, cost_rub: cache.costRub, quote_cur: cache.quoteCur };
  out.shares = [...shares(result).disciplines.values()].every((v) => v === null)
    ? 'not_computed'
    : 'computed';
  const analytics = new Map(Object.entries(expected)).get('analytics') as
    | Record<string, Json>
    | undefined;
  if (analytics) {
    const a: Record<string, Actual> = {};
    const ratio = new Map(Object.entries(analytics)).get('control_ratio_qa') as
      | { discipline_a: string; disciplines_b: string[]; min_pct: string; max_pct: string }
      | undefined;
    if (ratio) {
      const cr = controlRatio(result, ratio.discipline_a, ratio.disciplines_b, dec(ratio.min_pct), dec(ratio.max_pct));
      a.control_ratio_qa = {
        discipline_a: cr.disciplineA,
        disciplines_b: cr.disciplinesB,
        min_pct: ratio.min_pct,
        max_pct: ratio.max_pct,
        pct: cr.pct ?? null,
        verdict: cr.verdict,
      };
    }
    const found = volumes(result);
    a.volumes = Object.fromEntries(
      Object.keys((new Map(Object.entries(analytics)).get('volumes') ?? {}) as object).map((n) => [n, found.get(n)]),
    );
    for (const [key, level] of [
      ['large_leaves_medium', 'medium'],
      ['large_leaves_detailed', 'detailed'],
    ] as const) {
      const d = decomposition(withLevel(raw, level));
      Object.assign(a, {
        [key]: { threshold_hours: d.thresholdHours, large: d.large, repeating: d.repeating },
      });
      if (level === input.detailLevel) a.wide_fork_over_30pct = d.wideForks;
    }
    out.analytics = a;
  }
  return out;
}

const PORTAL_EXPECTED = portal.expected as unknown as Record<string, Json>;
const PORTAL_INPUT = portal.input as unknown as RawProjectInput;

describe('TC-CALC-01 · «Портал дилеров» (SPEC 6.5)', () => {
  const actual = shape(PORTAL_INPUT, PORTAL_EXPECTED);
  const expectedGroups = new Map(Object.entries(PORTAL_EXPECTED));

  it.each(['leaves', 'nodes', 'disciplines', 'phases', 'works', 'pm', 'total'])('часы: %s', (group) => {
    assertMatches(new Map(Object.entries(actual)).get(group), expectedGroups.get(group) ?? null, group);
  });

  it.each(['e', 'p80', 'p90'])('TC-MONEY-01 · деньги по %s', (figure) => {
    const money = expectedGroups.get('money') as { by_figure: Record<string, Json>; quote_figure: string };
    const got = actual.money as { by_figure: Record<string, Actual>; quote_figure: string };
    expect(got.quote_figure).toBe(money.quote_figure);
    assertMatches(
      new Map(Object.entries(got.by_figure)).get(figure),
      new Map(Object.entries(money.by_figure)).get(figure) ?? null,
      figure,
    );
  });

  it('итог в USD — сумма строк, а не округление итога (BR-MONEY-04)', () => {
    const got = actual.money as { by_figure: { e: { total_cur: Dec } } };
    expect(got.by_figure.e.total_cur.toFixed()).toBe('12397');
    expect(portal.expected.money.naive_total_cur_wrong).toBe('12398');
  });

  it('σ УП = 3,45 выводится как 3,5', () => {
    const pm = actual.pm as { values: { sigma_exact: Dec } };
    expect(roundHalfUp(pm.values.sigma_exact, 1).toFixed(1)).toBe('3.5');
    expect(roundHalfUp(dec('3.4499999999999999999999999999999999999'), 1).toFixed(1)).toBe('3.5');
  });

  it('доли, соотношение, объёмы, «крупные» листья (6.6, BR-TREE-09)', () => {
    assertMatches(actual.analytics, expectedGroups.get('analytics') ?? null, 'analytics');
  });
});

interface EdgeCase {
  id: string;
  input: RawProjectInput;
  expected: Record<string, Json>;
}

describe('TC-CALC-02…04 · граничные случаи', () => {
  it.each((edge.cases as unknown as EdgeCase[]).map((c) => [c.id, c] as const))('%s', (_id, c) => {
    const expected = { ...c.expected };
    const notExpected = new Map(Object.entries(expected)).get('not_expected') as
      | { nodes: Record<string, Record<string, string>> }
      | undefined;
    delete expected.not_expected;
    const actual = shape(c.input, expected);
    assertMatches(actual, expected, c.id);
    if (notExpected) {
      const nodes = new Map(Object.entries(actual.nodes as Record<string, Record<string, Dec>>));
      for (const [id, fields] of Object.entries(notExpected.nodes)) {
        const values = new Map(Object.entries(nodes.get(id) ?? {}));
        for (const [field, wrong] of Object.entries(fields)) {
          const got = values.get(field);
          expect(got && roundHalfUp(got, 1).toFixed(1)).not.toBe(wrong);
        }
      }
    }
  });
});
