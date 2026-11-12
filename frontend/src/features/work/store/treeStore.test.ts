/**
 * FE-021 · хранилище дерева: загрузка, оптимистичная правка, события WS по версиям и главное —
 * 1 000 случайных событий подряд дают то же дерево и те же суммы, что свежая выдача сервера.
 */
import { describe, expect, it } from 'vitest';

import type { components } from '../../../shared/api/client';
import { calculate, parseInput, type RawProjectInput } from '../../../shared/calc';
import portal from '../../../../../contracts/fixtures/calc/portal-dilerov.json';
import { createTreeStore, type CalcSettings, type TreeEvent, type TreeStore } from './treeStore';

type ApiNode = components['schemas']['Node'];
type Tree = components['schemas']['Tree'];
type Status = 'not_started' | 'draft' | 'done' | 'not_needed';

/* ---- генератор: детерминированный, чтобы падение воспроизводилось ---- */

function rng(seed: number) {
  let x = seed >>> 0;
  return () => {
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    return (x >>> 0) / 4294967296;
  };
}

const PHASES = ['ph-a', 'ph-b', 'ph-pm'];
const DISCIPLINES = ['d-1', 'd-2'];

const SETTINGS: CalcSettings = {
  pmPercent: '15',
  quoteFigure: 'p80',
  detailLevel: 'medium',
  phases: [
    { id: 'ph-a', name: 'A', isCrossCutting: false, inPmBase: true, enabled: true },
    { id: 'ph-b', name: 'B', isCrossCutting: false, inPmBase: false, enabled: true },
    { id: 'ph-pm', name: 'УП', isCrossCutting: true, inPmBase: false, enabled: true },
  ],
  disciplines: DISCIPLINES.map((id) => ({ id, name: id })),
};

function node(fields: Partial<ApiNode> & Pick<ApiNode, 'id' | 'kind' | 'phase_id'>): ApiNode {
  return {
    parent_id: null,
    discipline_id: null,
    type_id: null,
    title: fields.id,
    position: 'm',
    o: null,
    r: null,
    p: null,
    multiplier: 1,
    version: 1,
    ...fields,
  } as ApiNode;
}

function baseNodes(): ApiNode[] {
  const nodes: ApiNode[] = [];
  for (const ph of PHASES.slice(0, 2)) {
    nodes.push(node({ id: ph, kind: 'phase', phase_id: ph, position: ph }));
    for (const d of DISCIPLINES) {
      nodes.push(
        node({ id: `${ph}/${d}`, kind: 'discipline', phase_id: ph, discipline_id: d, parent_id: ph, position: d }),
      );
    }
  }
  return nodes;
}

function treeOf(nodes: Iterable<ApiNode>, statuses: Map<string, Status>, version: number): Tree {
  return {
    project_version: version,
    nodes: [...nodes],
    branch_statuses: [...statuses].map(([key, status]) => {
      const [phase_id = '', discipline_id = ''] = key.split('/');
      return {
        phase_id,
        discipline_id,
        status,
        changed_by: null,
        changed_at: '2026-11-09T00:00:00Z',
        open_questions: 0,
        has_expert: true,
      };
    }),
    totals: {},
  } as unknown as Tree;
}

/** Сводка состояния для сравнения: узлы в порядке обхода и суммы каждого. */
function snapshot(store: TreeStore) {
  const { calc, result, children } = store.getState();
  if (!calc || !result) throw new Error('нет расчёта');
  const rows = [...calc.walk()].map((id) => {
    const r = calc.get(id);
    return [
      id,
      r.node.parentId,
      r.isLeaf,
      r.excluded,
      r.totals.e.toString(),
      r.totals.sigmaSq.toFixed(10),
      r.totals.unaccounted,
    ];
  });
  return {
    rows,
    order: [...children].map(([p, ids]) => [p, ids.join(',')]).sort(),
    total: [result.total.e.toString(), result.total.p80.toFixed(6), result.unaccountedLeaves],
  };
}

const LETTERS = 'abcdefghijklmnopqrstuvwxyz';

function randomEvents(count: number, seed: number) {
  const rand = rng(seed);
  const pick = <T>(list: readonly T[]): T => list[Math.floor(rand() * list.length)] as T;
  const server = new Map(baseNodes().map((n) => [n.id, n]));
  const statuses = new Map<string, Status>();
  const trash: ApiNode[][] = [];
  const events: TreeEvent[] = [];
  let version = 1;
  let seq = 0;

  const estimate = (): Pick<ApiNode, 'o' | 'r' | 'p'> => {
    const roll = rand();
    if (roll < 0.1) return { o: null, r: null, p: null } as never;
    const o = Math.floor(rand() * 20);
    const r = o + Math.floor(rand() * 20);
    const p = r + Math.floor(rand() * 40);
    if (roll < 0.15) return { o: String(p + 1), r: String(r), p: String(p) } as never; // неверная
    return { o: String(o), r: `${r}.5`, p: String(p) } as never;
  };
  const descendants = (id: string): Set<string> => {
    const out = new Set([id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const n of server.values()) {
        if (n.parent_id && out.has(n.parent_id) && !out.has(n.id)) {
          out.add(n.id);
          grew = true;
        }
      }
    }
    return out;
  };
  const items = () => [...server.values()].filter((n) => n.kind === 'item');
  const parents = () => [...server.values()].filter((n) => n.kind !== 'phase');

  while (events.length < count) {
    version += 1 + Math.floor(rand() * 2); // пропуски номеров нормальны
    const roll = rand();
    if (roll < 0.35 || items().length < 3) {
      const parent = pick(parents());
      const created = node({
        id: `n${++seq}`,
        kind: 'item',
        phase_id: parent.phase_id,
        discipline_id: parent.discipline_id,
        parent_id: parent.id,
        position: pick([...LETTERS]) + pick([...LETTERS]),
        multiplier: 1 + Math.floor(rand() * 3),
        ...estimate(),
      });
      server.set(created.id, created);
      events.push({ event: 'node.created', project_version: version, data: { node: created } });
    } else if (roll < 0.65) {
      const target = pick(items());
      const updated = { ...target, ...estimate(), title: `t${version}`, version: target.version + 1 };
      if (rand() < 0.3) updated.multiplier = 1 + Math.floor(rand() * 4);
      server.set(updated.id, updated);
      events.push({ event: 'node.updated', project_version: version, data: { node: updated } });
    } else if (roll < 0.75) {
      const target = pick(items());
      const banned = descendants(target.id);
      const options = parents().filter(
        (p) => !banned.has(p.id) && p.phase_id === target.phase_id && p.discipline_id === target.discipline_id,
      );
      const parent = pick(options);
      const moved = { ...target, parent_id: parent.id, position: pick([...LETTERS]), version: target.version + 1 };
      server.set(moved.id, moved);
      events.push({ event: 'node.moved', project_version: version, data: { node: moved } });
    } else if (roll < 0.85) {
      const target = pick(items());
      const ids = descendants(target.id);
      trash.push([...ids].map((id) => server.get(id)).filter((n): n is ApiNode => n !== undefined));
      for (const id of ids) server.delete(id);
      events.push({ event: 'node.deleted', project_version: version, data: { node_ids: [target.id] } });
    } else if (roll < 0.92 && trash.length) {
      const batch = trash.pop() ?? [];
      const restorable = batch.filter(
        (n) => n.parent_id === null || server.has(n.parent_id) || batch.some((b) => b.id === n.parent_id),
      );
      if (!restorable.length || !restorable.some((n) => n.parent_id && server.has(n.parent_id))) continue;
      for (const n of restorable) server.set(n.id, n);
      events.push({ event: 'node.restored', project_version: version, data: { nodes: restorable } });
    } else {
      const phase_id = pick(PHASES.slice(0, 2));
      const discipline_id = pick(DISCIPLINES);
      const status = pick<Status>(['not_started', 'draft', 'done', 'not_needed']);
      statuses.set(`${phase_id}/${discipline_id}`, status);
      events.push({ event: 'branch.status', project_version: version, data: { phase_id, discipline_id, status } });
    }
  }
  return { events, final: treeOf(server.values(), statuses, version) };
}

/* ---- тесты ---- */

describe('хранилище дерева (FE-021)', () => {
  it('загрузка выдачи сервера даёт те же итоги, что расчёт FE-002 по фикстуре', () => {
    const input = (portal as unknown as { input: RawProjectInput }).input;
    const expected = calculate(parseInput(input));
    const store = createTreeStore();
    const settings: CalcSettings = {
      pmPercent: input.project.pm_percent,
      quoteFigure: input.project.quote_figure,
      detailLevel: input.project.detail_level,
      phases: input.phases.map((p) => ({
        id: p.id,
        name: p.name,
        isCrossCutting: p.is_cross_cutting,
        inPmBase: p.in_pm_base,
        enabled: p.enabled,
      })),
      disciplines: input.disciplines,
    };
    const nodes = input.nodes.map((n, i) => ({ ...n, position: String(i).padStart(4, '0'), version: 1 }));
    store.getState().load(
      {
        project_version: 7,
        nodes,
        branch_statuses: (input.branch_status ?? []).map((b) => ({
          ...b,
          changed_by: null,
          changed_at: '',
          open_questions: 0,
          has_expert: true,
        })),
        totals: {},
      } as unknown as Tree,
      settings,
    );
    const result = store.getState().result;
    expect(result?.total.e.toString()).toBe(expected.total.e.toString());
    expect(result?.total.p80.toString()).toBe(expected.total.p80.toString());
    expect(result?.unaccountedLeaves).toBe(expected.unaccountedLeaves);
    expect(store.getState().version).toBe(7);
  });

  it('правка листа: сразу в суммах предков и итоге, ячейка «сохраняется» до ответа сервера', () => {
    const store = createTreeStore();
    const leaf = node({
      id: 'L',
      kind: 'item',
      phase_id: 'ph-a',
      discipline_id: 'd-1',
      parent_id: 'ph-a/d-1',
      o: '1',
      r: '2',
      p: '3',
    } as never);
    store.getState().load(treeOf([...baseNodes(), leaf], new Map(), 5), SETTINGS);
    const before = store.getState().result?.total.e.toString();

    store.getState().edit('L', { r: '10', p: '20' });
    const s = store.getState();
    expect(s.isPending('L', 'r')).toBe(true);
    expect(s.isPending('L', 'o')).toBe(false);
    expect(s.calc?.get('ph-a/d-1').totals.e.toString()).toBe(s.calc?.get('L').totals.e.toString());
    expect(s.calc?.get('ph-a').totals.e.toString()).toBe(s.calc?.get('L').totals.e.toString());
    expect(s.result?.total.e.toString()).not.toBe(before);
    expect(s.effective('L')?.r).toBe('10');
    expect(s.nodes.get('L')?.r).toBe('2');

    store.getState().applyNode({ ...leaf, r: '10', p: '20', version: 2 } as ApiNode, 6);
    expect(store.getState().isPending('L', 'r')).toBe(false);
    expect(store.getState().nodes.get('L')?.r).toBe('10');
    expect(store.getState().version).toBe(6);
  });

  it('QA-020: ответ на раннюю правку снимает только её значения', () => {
    const store = createTreeStore();
    const leaf = node({
      id: 'L',
      kind: 'item',
      phase_id: 'ph-a',
      discipline_id: 'd-1',
      parent_id: 'ph-a/d-1',
      o: '1',
      r: '2',
      p: '3',
    } as never);
    store.getState().load(treeOf([...baseNodes(), leaf], new Map(), 5), SETTINGS);
    store.getState().edit('L', { o: '5' });
    store.getState().edit('L', { o: '6', r: '7' });
    // подтверждена первая правка (O = 5): O = 6 и R = 7 ещё ждут ответа
    store.getState().applyNode({ ...leaf, o: '5', version: 2 } as ApiNode, 6, { o: '5' });
    expect(store.getState().effective('L')?.o).toBe('6');
    expect(store.getState().isPending('L', 'r')).toBe(true);
    // отказ по старому значению не снимает новое
    store.getState().revert('L', ['o'], { o: '5' });
    expect(store.getState().isPending('L', 'o')).toBe(true);
    store.getState().applyNode({ ...leaf, o: '6', r: '7', version: 3 } as ApiNode, 7, { o: '6', r: '7' });
    expect(store.getState().pending.size).toBe(0);
    expect(store.getState().nodes.get('L')?.o).toBe('6');
  });

  it('отказ сервера возвращает значение; повтор старого события пропускается', () => {
    const store = createTreeStore();
    const leaf = node({
      id: 'L',
      kind: 'item',
      phase_id: 'ph-a',
      discipline_id: 'd-1',
      parent_id: 'ph-a/d-1',
      o: '1',
      r: '2',
      p: '3',
    } as never);
    store.getState().load(treeOf([...baseNodes(), leaf], new Map(), 5), SETTINGS);
    const e = store.getState().result?.total.e.toString();
    store.getState().edit('L', { o: '5', r: '6' });
    store.getState().revert('L', ['o', 'r']);
    expect(store.getState().pending.size).toBe(0);
    expect(store.getState().result?.total.e.toString()).toBe(e);

    const stale = { event: 'node.updated', project_version: 5, data: { node: { ...leaf, r: '99' } } } as TreeEvent;
    expect(store.getState().applyEvent(stale)).toBe(false);
    expect(store.getState().nodes.get('L')?.r).toBe('2');
  });

  it('удаление уносит поддерево; «не нужно» исключает ветку из фазы', () => {
    const store = createTreeStore();
    const parent = node({
      id: 'P',
      kind: 'item',
      phase_id: 'ph-a',
      discipline_id: 'd-1',
      parent_id: 'ph-a/d-1',
    } as never);
    const child = node({
      id: 'C',
      kind: 'item',
      phase_id: 'ph-a',
      discipline_id: 'd-1',
      parent_id: 'P',
      o: '1',
      r: '2',
      p: '3',
    } as never);
    store.getState().load(treeOf([...baseNodes(), parent, child], new Map(), 1), SETTINGS);
    expect(store.getState().calc?.get('ph-a').totals.e.isZero()).toBe(false);

    store.getState().applyEvent({
      event: 'branch.status',
      project_version: 2,
      data: { phase_id: 'ph-a', discipline_id: 'd-1', status: 'not_needed' },
    });
    expect(store.getState().calc?.get('ph-a').totals.e.isZero()).toBe(true);

    store.getState().applyEvent({ event: 'node.deleted', project_version: 3, data: { node_ids: ['P'] } });
    expect(store.getState().nodes.has('C')).toBe(false);
    expect(store.getState().calc?.nodes.has('C')).toBe(false);
  });

  it('1 000 событий подряд — то же дерево, что серверная выдача (и повторы не мешают)', () => {
    for (const seed of [1, 42, 2026]) {
      const { events, final } = randomEvents(1000, seed);
      const kinds = new Set(events.map((e) => e.event));
      expect(kinds.size).toBe(6);
      expect(final.nodes.filter((n) => n.kind === 'item').length).toBeGreaterThan(20);
      const live = createTreeStore();
      live.getState().load(treeOf(baseNodes(), new Map(), 1), SETTINGS);
      const started = performance.now();
      events.forEach((event, i) => {
        live.getState().applyEvent(event);
        // повтор уже применённого после переподключения
        if (i % 50 === 49) expect(live.getState().applyEvent(events[i - 10] as TreeEvent)).toBe(false);
      });
      const elapsed = performance.now() - started;

      const fresh = createTreeStore();
      fresh.getState().load(final, SETTINGS);
      expect(snapshot(live)).toEqual(snapshot(fresh));
      expect(live.getState().version).toBe(final.project_version);
      expect(elapsed).toBeLessThan(10_000);
    }
  });
  it('правка листа в дереве из 5 000 узлов пересчитывается быстрее 100 мс (NFR-PERF-03)', () => {
    const nodes = baseNodes();
    const extra = 5000 - nodes.length;
    for (let i = 0; i < extra; i++) {
      const parent = i < 400 ? `ph-a/d-${(i % 2) + 1}` : `g${i % 400}`;
      const ph = 'ph-a';
      const d = parent.startsWith('g') ? `d-${((i % 400) % 2) + 1}` : parent.slice(-3);
      nodes.push(
        node({
          id: `g${i}`,
          kind: 'item',
          phase_id: ph,
          discipline_id: d,
          parent_id: parent,
          position: String(i).padStart(5, '0'),
          o: '1',
          r: '2',
          p: '4',
        } as never),
      );
    }
    const store = createTreeStore();
    store.getState().load(treeOf(nodes, new Map(), 1), SETTINGS);
    expect(store.getState().calc?.nodes.size).toBe(5000);
    const started = performance.now();
    store.getState().edit('g4993', { r: '3' });
    expect(performance.now() - started).toBeLessThan(100);
    expect(store.getState().isPending('g4993', 'r')).toBe(true);
  });
});
