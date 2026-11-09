/**
 * FE-001 · демо-данные моков: «Портал дилеров» (SPEC 5.1, 6.5, макеты 11) и «Интеграция
 * с ФНС» (11.3). Дерево, часы и деньги «Портала» берутся из эталонной фикстуры CORE-001
 * `contracts/fixtures/calc/portal-dilerov.json`, поэтому совпадают с таблицами 6.5.
 * Цифры «Интеграции с ФНС» — демонстрационные, считаются упрощённо (без правил 6.4).
 */
import Decimal from 'decimal.js';

import portalFixture from '../../../../../contracts/fixtures/calc/portal-dilerov.json';
import { NOW, TODAY, minutesAgo, uuidFrom } from './ids';
import { PERSONAS, personaId, type Persona } from './personas';

type Json = Record<string, unknown>;
type FixtureNode = {
  id: string;
  parent_id: string | null;
  kind: 'phase' | 'discipline' | 'item';
  phase_id: string;
  discipline_id: string | null;
  type: string | null;
  title: string;
  multiplier?: number;
  o?: string;
  r?: string;
  p?: string;
};
type HoursRow = { e: string; sigma: string; p80?: string; p90?: string };

const fx = portalFixture as unknown as {
  input: {
    nodes: FixtureNode[];
    branch_status: { phase_id: string; discipline_id: string; status: string }[];
  };
  expected: {
    leaves: { values: Record<string, HoursRow> };
    nodes: { values: Record<string, HoursRow & { sum_o: string; sum_r: string; sum_p: string }> };
    disciplines: { values: Record<string, HoursRow> };
    phases: { values: Record<string, HoursRow> };
    works: { values: HoursRow };
    pm: { values: HoursRow };
    total: { values: HoursRow };
    money: { by_figure: Record<'e' | 'p80' | 'p90', MoneyFixture> };
  };
};
type MoneyFixture = {
  k: string;
  rows_rub: Record<string, string>;
  rows_cur: Record<string, string>;
  total_rub: string;
  vat_rub: string;
  total_with_vat_rub: string;
  total_cur: string;
  vat_cur: string;
  total_with_vat_cur: string;
};

/** Часы в формате HoursString: 2 знака, ROUND_HALF_UP. */
export const hours = (v: Decimal.Value) =>
  new Decimal(v).toDecimalPlaces(2, Decimal.ROUND_HALF_UP).toFixed(2);

// --- справочники ---------------------------------------------------------------------------

export const PHASES = [
  { key: 'ph-analysis', name: 'Анализ и проектирование', cross: false },
  { key: 'ph-dev', name: 'Разработка', cross: false },
  { key: 'ph-test', name: 'Тестирование', cross: false },
  { key: 'ph-pm', name: 'Управление проектом', cross: true },
];
export const DISCIPLINES = [
  { key: 'd-analytics', name: 'Аналитика', short: 'Анал', color: '#7b61c9', profile: 'Лист' },
  { key: 'd-arch', name: 'Архитектура', short: 'Арх', color: '#3e8ed0', profile: 'Работа' },
  { key: 'd-backend', name: 'Бэкенд', short: 'BE', color: '#2f9e6e', profile: 'Модуль → Функция' },
  { key: 'd-frontend', name: 'Фронтенд', short: 'FE', color: '#d08a2f', profile: 'Экран' },
  { key: 'd-qa', name: 'QA', short: 'QA', color: '#c0504d', profile: 'Тест-набор' },
];
/** Типы словаря SPEC 5.2 в порядке сетки меню «+» (tree-menu.png). */
export const NODE_TYPES = [
  'Функция',
  'Экран',
  'Интеграция',
  'Сущность',
  'Отчёт',
  'Работа',
  'Модуль',
  'Сервис',
  'Тест-набор',
  'Документ',
];

export const phaseId = (key: string) => uuidFrom('phase', key);
export const disciplineId = (key: string) => uuidFrom('discipline', key);
export const profileId = (key: string) => uuidFrom('profile', key);
export const typeId = (name: string) => uuidFrom('node-type', name);
export const userRef = (p: Persona | { login: string; fullName: string; initials: string }) => ({
  id: uuidFrom('user', p.login),
  full_name: p.fullName,
  initials: p.initials,
  is_active: true,
});

/** Участники макетов, которых нет в переключателе ролей. */
export const PEOPLE = {
  kuznetsova: { login: 'o.kuznetsova', fullName: 'О. Кузнецова', initials: 'ОК' },
  morozov: { login: 'd.morozov', fullName: 'Д. Морозов', initials: 'ДМ' },
  petrov: { login: 'p.petrov', fullName: 'П. Петров', initials: 'ПП' },
  orlova: { login: 'm.orlova', fullName: 'М. Орлова', initials: 'МО' },
  novikov: { login: 'n.novikov', fullName: 'Н. Новиков', initials: 'НН' },
};

// --- проекты -------------------------------------------------------------------------------

export type DemoProject = {
  key: 'portal' | 'fns';
  id: string;
  name: string;
  customer: string;
  description: string;
  deadline: string;
  phases: string[];
  disciplines: string[];
  nodes: Json[];
  branchStatuses: Json[];
  totals: {
    works: HoursRow;
    pm: HoursRow;
    total: HoursRow;
    byDiscipline: Record<string, HoursRow>;
    byPhase: Record<string, HoursRow>;
  };
  members: Json[];
  money: {
    currency: string;
    exchangeRate: string;
    vatPercent: string;
    rates: Record<string, string>;
    figures: Record<'e' | 'p80' | 'p90', MoneyFixture>;
  };
};

const hoursTotals = (row: HoursRow) => ({
  e: hours(row.e),
  sigma: hours(row.sigma),
  p80: hours(row.p80 ?? row.e),
  p90: hours(row.p90 ?? row.e),
});
export { hoursTotals };

function nodeOf(
  project: string,
  n: FixtureNode,
  index: number,
  calc: (HoursRow & Partial<Record<'sum_o' | 'sum_r' | 'sum_p', string>>) | undefined,
  isLeaf: boolean,
): Json {
  return {
    id: uuidFrom('node', project, n.id),
    parent_id: n.parent_id ? uuidFrom('node', project, n.parent_id) : null,
    kind: n.kind,
    phase_id: phaseId(n.phase_id),
    discipline_id: n.discipline_id ? disciplineId(n.discipline_id) : null,
    type_id: n.type ? typeId(n.type) : null,
    title: n.title,
    position: String(index + 1).padStart(4, '0'),
    o: isLeaf ? (n.o ?? null) : null,
    r: isLeaf ? (n.r ?? null) : null,
    p: isLeaf ? (n.p ?? null) : null,
    multiplier: n.multiplier ?? 1,
    comment_lines: isLeaf ? [] : null,
    reviewed_by: null,
    reviewed_at: null,
    self_review: false,
    version: 3,
    field_versions: {},
    e: calc ? hours(calc.e) : null,
    sigma: calc ? hours(calc.sigma) : null,
    p80: calc?.p80 ? hours(calc.p80) : null,
    p90: calc?.p90 ? hours(calc.p90) : null,
    sum_o: calc?.sum_o ? hours(calc.sum_o) : null,
    sum_r: calc?.sum_r ? hours(calc.sum_r) : null,
    sum_p: calc?.sum_p ? hours(calc.sum_p) : null,
    leaf_state: isLeaf ? 'valid' : null,
    is_large: n.id === 'n-analytics-whole',
    is_repeating: (n.multiplier ?? 1) > 1,
    unaccounted_leaves: 0,
    messages_count: n.id === 'n-1c' ? 3 : 0,
    open_questions: n.id === 'n-1c' ? 1 : 0,
    questions_to_me: 0,
  };
}

function buildPortal(): DemoProject {
  const nodes = fx.input.nodes;
  const parents = new Set(nodes.map((n) => n.parent_id));
  const values = { ...fx.expected.nodes.values, ...fx.expected.leaves.values };
  const pm = fx.expected.pm.values;
  const treeNodes = nodes.map((n, i) => {
    const calc = n.id === 'n-ph-pm' ? pm : values[n.id];
    return nodeOf('portal', n, i, calc, n.kind === 'item' && !parents.has(n.id));
  });
  const done = new Set(['ph-analysis/d-analytics', 'ph-analysis/d-arch', 'ph-dev/d-frontend']);
  const expertOf: Record<string, Json> = {
    'd-analytics': userRef(PEOPLE.kuznetsova),
    'd-arch': userRef(PEOPLE.morozov),
    'd-backend': userRef(PERSONAS.expert),
    'd-frontend': userRef(PEOPLE.petrov),
    'd-qa': userRef(PEOPLE.orlova),
  };
  const branchStatuses = fx.input.branch_status.map((b, i) => ({
    phase_id: phaseId(b.phase_id),
    discipline_id: disciplineId(b.discipline_id),
    status: done.has(`${b.phase_id}/${b.discipline_id}`) ? 'done' : 'draft',
    changed_by: expertOf[b.discipline_id] ?? null,
    changed_at: minutesAgo(60 * (i + 1)),
    open_questions: b.discipline_id === 'd-backend' || b.discipline_id === 'd-qa' ? 1 : 0,
    has_expert: true,
  }));
  const member = (
    person: Persona | (typeof PEOPLE)[keyof typeof PEOPLE],
    role: string,
    discipline: string | null,
    extra: Json = {},
  ) => ({
    user: userRef(person),
    role,
    discipline_id: discipline ? disciplineId(discipline) : null,
    is_reviewer: false,
    status: 'active',
    added_by_admin_self: false,
    ...extra,
  });
  const money = fx.expected.money.by_figure;
  return {
    key: 'portal',
    id: uuidFrom('project', 'portal'),
    name: 'Портал дилеров',
    customer: 'ООО «Пример»',
    description: 'Портал для дилеров: ЛК, обмен с 1С. ТЗ — https://wiki.corp/dealers',
    deadline: TODAY,
    phases: PHASES.map((p) => p.key),
    disciplines: DISCIPLINES.map((d) => d.key),
    nodes: treeNodes,
    branchStatuses,
    totals: {
      works: fx.expected.works.values,
      pm,
      total: fx.expected.total.values,
      byDiscipline: fx.expected.disciplines.values,
      byPhase: fx.expected.phases.values,
    },
    members: [
      member(PERSONAS.moderator, 'moderator', null),
      member(PERSONAS.presale, 'presale', null),
      member(PEOPLE.kuznetsova, 'expert', 'd-analytics'),
      member(PEOPLE.morozov, 'expert', 'd-arch'),
      member(PERSONAS.expert, 'expert', 'd-backend', { is_reviewer: true }),
      member(PEOPLE.novikov, 'expert', 'd-backend', {
        status: 'blocked',
        user: { ...userRef(PEOPLE.novikov), is_active: false },
      }),
      member(PEOPLE.petrov, 'expert', 'd-frontend'),
      member(PEOPLE.orlova, 'expert', 'd-qa'),
    ],
    money: {
      currency: 'USD',
      exchangeRate: '92.5',
      vatPercent: '20',
      rates: {
        'd-analytics': '2500',
        'd-arch': '3500',
        'd-backend': '3000',
        'd-frontend': '2800',
        'd-qa': '2200',
        pm: '3200',
      },
      figures: money,
    },
  };
}

/** «Интеграция с ФНС»: две дисциплины в трёх фазах (6 веток), всё в черновике (SPEC 11.3). */
function buildFns(): DemoProject {
  const leaves: [string, string, string, string, number, [string, string, string]][] = [
    ['n-req', 'ph-analysis', 'd-analytics', 'Требования к обмену с ФНС', 1, ['8', '12', '20']],
    ['n-api', 'ph-dev', 'd-backend', 'Клиент API ФНС', 1, ['16', '24', '40']],
    ['n-sign', 'ph-dev', 'd-backend', 'Подпись запросов', 1, ['8', '12', '24']],
    ['n-tests', 'ph-test', 'd-backend', 'Интеграционные тесты', 1, ['6', '10', '16']],
  ];
  const nodes: FixtureNode[] = [];
  const phasesUsed = ['ph-analysis', 'ph-dev', 'ph-test', 'ph-pm'];
  const discs = ['d-analytics', 'd-backend'];
  for (const ph of phasesUsed) {
    nodes.push({
      id: `n-${ph}`,
      parent_id: null,
      kind: 'phase',
      phase_id: ph,
      discipline_id: null,
      type: null,
      title: PHASES.find((p) => p.key === ph)?.name ?? ph,
    });
    if (ph === 'ph-pm') continue;
    for (const d of discs) {
      nodes.push({
        id: `n-${ph}-${d}`,
        parent_id: `n-${ph}`,
        kind: 'discipline',
        phase_id: ph,
        discipline_id: d,
        type: null,
        title: DISCIPLINES.find((x) => x.key === d)?.name ?? d,
      });
    }
  }
  const calc: Record<string, HoursRow> = {};
  const add = (id: string, e: Decimal, s2: Decimal) => {
    const prev = calc[id];
    const pe = prev ? new Decimal(prev.e).plus(e) : e;
    const ps2 = prev ? new Decimal(prev.sigma).pow(2).plus(s2) : s2;
    calc[id] = { e: pe.toString(), sigma: ps2.sqrt().toString() };
  };
  for (const [id, ph, d, title, mult, [o, r, p]] of leaves) {
    nodes.push({
      id,
      parent_id: `n-${ph}-${d}`,
      kind: 'item',
      phase_id: ph,
      discipline_id: d,
      type: 'Работа',
      title,
      multiplier: mult,
      o,
      r,
      p,
    });
    const e = new Decimal(o).plus(new Decimal(r).times(4)).plus(p).div(6).times(mult);
    const s = new Decimal(p).minus(o).div(6).times(mult);
    calc[id] = { e: e.toString(), sigma: s.toString() };
    add(`n-${ph}-${d}`, e, s.pow(2));
    add(`n-${ph}`, e, s.pow(2));
    add(`disc:${d}`, e, s.pow(2));
    add('works', e, s.pow(2));
  }
  const pmK = new Decimal('0.15');
  const works = calc.works ?? { e: '0', sigma: '0' };
  const pm = {
    e: new Decimal(works.e).times(pmK).toString(),
    sigma: new Decimal(works.sigma).times(pmK).toString(),
  };
  calc['n-ph-pm'] = pm;
  const withP = (row: HoursRow): HoursRow => ({
    ...row,
    p80: new Decimal(row.e).plus(new Decimal(row.sigma).times('0.8416')).toString(),
    p90: new Decimal(row.e).plus(new Decimal(row.sigma).times('1.2816')).toString(),
  });
  const total = withP({
    e: new Decimal(works.e).plus(pm.e).toString(),
    sigma: new Decimal(works.sigma).pow(2).plus(new Decimal(pm.sigma).pow(2)).sqrt().toString(),
  });
  const parents = new Set(nodes.map((n) => n.parent_id));
  const treeNodes = nodes.map((n, i) => {
    const row = calc[n.id];
    return nodeOf(
      'fns',
      n,
      i,
      row ? withP(row) : undefined,
      n.kind === 'item' && !parents.has(n.id),
    );
  });
  const branchStatuses = phasesUsed
    .filter((ph) => ph !== 'ph-pm')
    .flatMap((ph) =>
      discs.map((d) => ({
        phase_id: phaseId(ph),
        discipline_id: disciplineId(d),
        status: 'draft',
        changed_by: null,
        changed_at: minutesAgo(60 * 26),
        open_questions: 0,
        has_expert: d === 'd-backend',
      })),
    );
  // деньги: одна ставка 3 000 ₽ на всё, валюта КП — рубли
  const rate = new Decimal(3000);
  const rowsFor = (k: Decimal) => {
    const rows: Record<string, string> = {};
    for (const d of discs)
      rows[d] = new Decimal(calc[`disc:${d}`]?.e ?? 0).times(k).times(rate).toFixed(0);
    rows.pm = new Decimal(pm.e).times(k).times(rate).toFixed(0);
    const sum = Object.values(rows).reduce((a, v) => a.plus(v), new Decimal(0));
    const vat = sum.times('0.2').toDecimalPlaces(0, Decimal.ROUND_HALF_UP);
    return {
      k: k.toFixed(6),
      rows_rub: rows,
      rows_cur: rows,
      total_rub: sum.toFixed(0),
      vat_rub: vat.toFixed(0),
      total_with_vat_rub: sum.plus(vat).toFixed(0),
      total_cur: sum.toFixed(0),
      vat_cur: vat.toFixed(0),
      total_with_vat_cur: sum.plus(vat).toFixed(0),
    };
  };
  const e = new Decimal(total.e);
  return {
    key: 'fns',
    id: uuidFrom('project', 'fns'),
    name: 'Интеграция с ФНС',
    customer: 'ИП Юг',
    description: 'Обмен с сервисами ФНС: требования, клиент API, подпись запросов.',
    deadline: '2026-11-20',
    phases: phasesUsed,
    disciplines: discs,
    nodes: treeNodes,
    branchStatuses,
    totals: {
      works: withP(works),
      pm: withP(pm),
      total,
      byDiscipline: Object.fromEntries(
        discs.map((d) => [d, withP(calc[`disc:${d}`] ?? { e: '0', sigma: '0' })]),
      ),
      byPhase: Object.fromEntries(
        phasesUsed
          .filter((p) => p !== 'ph-pm')
          .map((p) => [p, withP(calc[`n-${p}`] ?? { e: '0', sigma: '0' })]),
      ),
    },
    members: [
      {
        user: userRef(PERSONAS.expert),
        role: 'moderator',
        discipline_id: null,
        is_reviewer: false,
        status: 'active',
        added_by_admin_self: false,
      },
      {
        user: userRef(PERSONAS.presale),
        role: 'presale',
        discipline_id: null,
        is_reviewer: false,
        status: 'active',
        added_by_admin_self: false,
      },
      {
        user: userRef(PERSONAS.expert),
        role: 'expert',
        discipline_id: disciplineId('d-backend'),
        is_reviewer: false,
        status: 'active',
        added_by_admin_self: false,
      },
    ],
    money: {
      currency: 'RUB',
      exchangeRate: '1',
      vatPercent: '20',
      rates: { 'd-analytics': '3000', 'd-backend': '3000', pm: '3000' },
      figures: {
        e: rowsFor(new Decimal(1)),
        p80: rowsFor(new Decimal(total.p80 ?? total.e).div(e)),
        p90: rowsFor(new Decimal(total.p90 ?? total.e).div(e)),
      },
    },
  };
}

export const PROJECTS: Record<'portal' | 'fns', DemoProject> = {
  portal: buildPortal(),
  fns: buildFns(),
};

/** Ключ проекта демо-данных по UUID проекта, узла, треда… (неизвестный UUID → null). */
export function projectKeyOf(id: string | undefined): 'portal' | 'fns' | null {
  if (!id) return null;
  for (const p of Object.values(PROJECTS)) {
    if (p.id === id || p.nodes.some((n) => n.id === id)) return p.key;
  }
  return null;
}

export const SNAPSHOT_TIME = minutesAgo(60 * 24 * 3);
export { NOW, personaId };
