/** FE-002 · функции листа, инкрементальный пересчёт и бенчмарк NFR-PERF-03. */
import { describe, expect, it } from 'vitest';

import edge from '../../../../contracts/fixtures/calc/edge-cases.json';
import {
  CalcInputError,
  CalcTree,
  TreeError,
  calculate,
  calculateMoney,
  classify,
  controlRatio,
  dec,
  decomposition,
  estimate,
  fitsHoursCache,
  fitsMoney,
  normalizeHours,
  projectCache,
  roundHalfUp,
  shares,
  summarize,
  unaccountedText,
  validateMultiplier,
  volumes,
  volumesText,
  type CalcNode,
  type Phase,
  type ProjectInput,
} from './index';

const F = edge.functions;

describe('функции фикстуры', () => {
  it.each(F.round_half_up.cases)('ROUND_HALF_UP $value@$places', (c) => {
    expect(roundHalfUp(dec(c.value), c.places).toFixed(c.places)).toBe(c.expected);
  });

  it.each(F.normalize_hours.cases.map((c) => [c.input, c] as const))('нормализация %j', (_i, c) => {
    if ('error' in c) {
      expect(() => normalizeHours(c.input)).toThrowError(
        expect.objectContaining({ code: c.error }) as unknown as Error,
      );
      return;
    }
    const got = normalizeHours(c.input);
    expect(got.text).toBe(c.expected);
    expect(got.rounded).toBe(c.rounded);
  });

  it.each(F.multiplier.cases.map((c) => [c.input, c] as const))('×N %j', (_i, c) => {
    if ('error' in c) {
      expect(() => validateMultiplier(c.input)).toThrowError(CalcInputError);
      try {
        validateMultiplier(c.input);
      } catch (e) {
        expect((e as CalcInputError).code).toBe(c.error);
      }
    } else {
      expect(validateMultiplier(c.input)).toBe(c.input);
    }
  });

  it.each(F.fits_cache.cases)('вместимость кэша $type $value', (c) => {
    const check = c.type === 'hours' ? fitsHoursCache : fitsMoney;
    expect(check(dec(c.value))).toBe(c.fits);
  });

  it('прочие проверки ввода', () => {
    expect(normalizeHours('99999.7').text).toBe('99999.5');
    expect(normalizeHours(' -0,2 ').text).toBe('0');
    expect(() => normalizeHours('99999.8')).toThrowError(CalcInputError);
    expect(validateMultiplier(' 12 ')).toBe(12);
    expect(() => validateMultiplier(true)).toThrowError(CalcInputError);
    expect(classify(dec(1), dec(5), dec(4))).toBe('invalid');
    expect(classify(null, dec(1), dec(2))).toBe('empty');
    expect(estimate(dec(3), dec(2), dec(4), 5).e.isZero()).toBe(true);
    expect(unaccountedText(1)).toBe('1 лист без оценки не учтён');
    expect(unaccountedText(3)).toBe('3 листа без оценки не учтены');
    expect(unaccountedText(12)).toBe('12 листов без оценки не учтены');
    expect(unaccountedText(22)).toBe('22 листа без оценки не учтены');
  });
});

/* ---- построитель деревьев ---- */

const PHASES: Phase[] = [
  { id: 'a', name: 'Разработка', isCrossCutting: false, inPmBase: true, enabled: true },
  { id: 'pm', name: 'УП', isCrossCutting: true, inPmBase: false, enabled: true },
];

function node(id: string, parentId: string | null, extra: Partial<CalcNode> = {}): CalcNode {
  return {
    id,
    parentId,
    kind: parentId === null ? 'phase' : 'item',
    phaseId: 'a',
    disciplineId: parentId === null ? null : 'be',
    type: null,
    title: id,
    o: null,
    r: null,
    p: null,
    multiplier: 1,
    ...extra,
  };
}

function leafNode(id: string, parentId: string, orp: string, multiplier = 1): CalcNode {
  const [o = '0', r = '0', p = '0'] = orp.split('-');
  return node(id, parentId, { o: dec(o), r: dec(r), p: dec(p), multiplier });
}

function input(nodes: CalcNode[], extra: Partial<ProjectInput> = {}): ProjectInput {
  return {
    pmPercent: dec(18),
    quoteFigure: 'p80',
    detailLevel: 'medium',
    phases: PHASES,
    disciplines: [
      { id: 'be', name: 'Бэкенд' },
      { id: 'qa', name: 'QA' },
    ],
    nodes: [node('a', null), node('pm', null, { phaseId: 'pm' }), node('a-be', 'a', { kind: 'discipline' }), ...nodes],
    branchStatus: new Map(),
    money: null,
    ...extra,
  };
}

/** Дерево ≈ 5 000 узлов: 50 групп по 99 листьев. */
function bigInput(): ProjectInput {
  const nodes: CalcNode[] = [];
  for (let g = 0; g < 50; g += 1) {
    nodes.push(node(`g${g}`, 'a-be'));
    for (let l = 0; l < 99; l += 1) nodes.push(leafNode(`g${g}-l${l}`, `g${g}`, '1-2-4', (l % 7) + 1));
  }
  return input(nodes);
}

describe('CalcTree', () => {
  it('инкрементальный пересчёт совпадает с полным', () => {
    const tree = new CalcTree(bigInput());
    const changed = tree.updateLeaf('g7-l3', { o: dec(10), r: dec('20.5'), p: dec(40), multiplier: 3 });
    expect(changed).toEqual(['g7-l3', 'g7', 'a-be', 'a']);
    const fresh = calculate({
      ...bigInput(),
      nodes: bigInput().nodes.map((n) =>
        n.id === 'g7-l3' ? { ...n, o: dec(10), r: dec('20.5'), p: dec(40), multiplier: 3 } : n,
      ),
    });
    const incremental = summarize(tree);
    expect(incremental.total.e.eq(fresh.total.e)).toBe(true);
    expect(roundHalfUp(incremental.total.sigma, 20).eq(roundHalfUp(fresh.total.sigma, 20))).toBe(true);
    for (const id of changed) {
      expect(tree.get(id).totals.e.eq(fresh.tree.get(id).totals.e)).toBe(true);
    }
  });

  it('NFR-PERF-03 · пересчёт при правке листа на 5 000 узлах ≤ 100 мс', () => {
    const tree = new CalcTree(bigInput());
    expect(tree.nodes.size).toBeGreaterThanOrEqual(5000);
    const runs = 20;
    const start = performance.now();
    for (let i = 0; i < runs; i += 1) {
      tree.updateLeaf(`g${i}-l${i}`, { o: dec(i), r: dec(i + 1), p: dec(i + 3), multiplier: 2 });
      summarize(tree);
    }
    const perEdit = (performance.now() - start) / runs;
    expect(perEdit).toBeLessThan(100);
  });

  it('ошибки дерева', () => {
    expect(() => new CalcTree(input([leafNode('x', 'missing', '1-1-1')]))).toThrowError(TreeError);
    expect(() => new CalcTree(input([node('x', 'y'), node('y', 'x')]))).toThrowError('цикл');
    const tree = new CalcTree(input([leafNode('l', 'a-be', '1-1-1')]));
    expect(() => tree.get('nope')).toThrowError(TreeError);
    expect(() => tree.updateLeaf('a-be', { o: null, r: null, p: null, multiplier: 1 })).toThrowError('не лист');
  });

  it('ветка «не нужно» и выключенная фаза не входят в суммы (BR-CALC-01)', () => {
    const phases: Phase[] = [...PHASES, { id: 'w', name: 'Гарантия', isCrossCutting: false, inPmBase: false, enabled: false }];
    const result = calculate(
      input(
        [
          leafNode('l1', 'a-be', '8-12-20'),
          node('a-qa', 'a', { kind: 'discipline', disciplineId: 'qa' }),
          { ...leafNode('l2', 'a-qa', '4-6-8'), disciplineId: 'qa' },
          node('w', null, { phaseId: 'w' }),
          node('w-be', 'w', { kind: 'discipline', phaseId: 'w' }),
          { ...leafNode('l3', 'w-be', '6-6-6'), phaseId: 'w' },
        ],
        { phases, branchStatus: new Map([['a/qa', 'not_needed']]) },
      ),
    );
    expect(result.tree.get('a-qa').excluded).toBe(true);
    expect(result.disciplines.get('qa')?.e.isZero()).toBe(true);
    expect(result.works.e.toFixed(4)).toBe(estimate(dec(8), dec(12), dec(20), 1).e.toFixed(4));
    expect([...result.tree.leaves()].map((l) => l.node.id)).toEqual(['l1']);
    expect([...result.tree.leaves(true)].map((l) => l.node.id)).toEqual(['l1', 'l2', 'l3']);
    expect(result.tree.get('w').totals.e.toFixed()).toBe('6');
  });
});

describe('деньги и аналитика: ветки, которых нет в фикстурах', () => {
  const nodes = [
    node('g', 'a-be', { type: 'Модуль' }),
    { ...leafNode('l1', 'g', '60-90-120'), type: 'Функция' },
    { ...leafNode('l2', 'a-be', '1-2-30', 3), type: 'Экран' },
    leafNode('l3', 'a-be', '0-0-0'),
  ];

  it('ставки не заданы, кэш без денег', () => {
    const result = calculate(input(nodes));
    const money = calculateMoney(result, { currency: 'RUB', exchangeRate: dec(1), vatPercent: dec(22), rates: new Map() });
    expect(money.ratesMissing).toEqual(['be', 'pm']);
    expect(money.ratesMissingText).toBe('не заданы ставки: Бэкенд, УП');
    expect(money.byFigure).toBeNull();
    const cache = projectCache(result, money);
    expect(cache.costRub).toBeNull();
    expect(projectCache(result, null).e?.toFixed(2)).toBe(roundHalfUp(result.total.e, 2).toFixed(2));
  });

  it('переполнение НДС при ставке НДС > 100%', () => {
    const big: CalcNode[] = [];
    for (let i = 0; i < 10; i += 1) big.push(leafNode(`m${i}`, 'a-be', '99999.5-99999.5-99999.5', 10000));
    const result = calculate(input(big, { pmPercent: dec(0) }));
    const money = calculateMoney(result, {
      currency: 'RUB',
      exchangeRate: dec(1),
      vatPercent: dec(200),
      rates: new Map([['be', dec('6000000000')], [null, dec(1)]]),
    });
    const e = money.byFigure?.get('e');
    expect(e?.totalRub).not.toBeNull();
    expect(e?.vatRub).toBeNull();
    expect(e?.totalWithVatRub).toBeNull();
  });

  it('доли, соотношения, объёмы, кандидаты', () => {
    const result = calculate(input(nodes));
    const sh = shares(result);
    expect(sh.disciplines.get('qa')?.isZero()).toBe(true); // QA без часов: 0 / E работ
    expect(shares(calculate(input([]))).disciplines.get('be')).toBeNull(); // E = 0 → «—»
    expect(sh.phases.get('a')?.lt(100)).toBe(true);
    expect(controlRatio(result, 'qa', ['be'], dec(25), dec(35)).verdict).toBe('below');
    expect(controlRatio(result, 'be', ['be'], dec(25), dec(35)).verdict).toBe('above');
    expect(controlRatio(result, 'be', ['be'], dec(0), dec(100)).verdict).toBe('within');
    expect(controlRatio(result, 'be', ['nope'], dec(0), dec(100)).pct).toBeNull();
    expect(volumesText(volumes(result))).toBe('Функция — 1, Экран — 3, Работа — 1');
    const d = decomposition(result);
    expect(d.large).toEqual(['l1']);
    expect(d.wideForks).toEqual(['l2']);
    expect(d.topBySigmaRatio.map((c) => c.nodeId)).toEqual(['l2', 'l1']);
    expect(decomposition(calculate(input(nodes, { detailLevel: 'coarse' }))).thresholdHours).toBeNull();
  });
});
