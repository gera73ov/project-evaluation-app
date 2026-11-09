/** FE-018 · корзина: срок, видимость по ролям, «Восстановить», выбор места при недоступном (G-15). */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { PROJECTS, disciplineId, phaseId } from '../../shared/api/mocks/data';
import { uuidFrom } from '../../shared/api/mocks/ids';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { renderApp } from '../../test/render';
import { daysLeft, restoreTargets } from './trash';

describe('правила корзины', () => {
  it('дни до очистки: неполный день считается', () => {
    const now = Date.parse('2026-11-09T12:00:00Z');
    expect(daysLeft('2026-11-11T11:00:00Z', now)).toBe(2);
    expect(daysLeft('2026-11-09T13:00:00Z', now)).toBe(1);
    expect(daysLeft('2026-11-01T00:00:00Z', now)).toBe(0);
  });

  it('место восстановления: та же дисциплина, без «не нужно», без листьев', () => {
    const n = (
      id: string,
      parent: string | null,
      kind: 'phase' | 'discipline' | 'item',
      ph: string,
      d: string | null,
    ) => ({
      id,
      parent_id: parent,
      kind,
      phase_id: ph,
      discipline_id: d,
      title: id,
      position: id,
      o: null,
    });
    const tree = {
      nodes: [
        n('A', null, 'phase', 'A', null),
        n('B', null, 'phase', 'B', null),
        n('A-be', 'A', 'discipline', 'A', 'be'),
        n('A-be-x', 'A-be', 'item', 'A', 'be'),
        n('A-be-x-1', 'A-be-x', 'item', 'A', 'be'),
        n('A-fe', 'A', 'discipline', 'A', 'fe'),
        n('B-be', 'B', 'discipline', 'B', 'be'),
      ],
      branch_statuses: [{ phase_id: 'B', discipline_id: 'be', status: 'not_needed' }],
    };
    expect(restoreTargets(tree, 'be').map((x) => [x.title, x.level])).toEqual([
      ['A › A-be', 0],
      ['A-be-x', 1],
    ]);
  });
});

const portal = PROJECTS.portal;

afterEach(() => server.events.removeAllListeners());

function track() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET') return;
    const entry = { method: request.method, path: new URL(request.url).pathname, body: null as unknown };
    calls.push(entry);
    void request
      .clone()
      .json()
      .then((b) => (entry.body = b))
      .catch(() => undefined);
  });
  return calls;
}

const WHO = { moderator: PERSONAS.moderator, expert: PERSONAS.expert, presale: PERSONAS.presale };

async function openTrash(who: keyof typeof WHO = 'moderator') {
  persona.current = new Map(Object.entries(WHO)).get(who) ?? PERSONAS.moderator;
  const calls = track();
  renderApp(`/projects/${portal.id}/trash`);
  await screen.findByRole('heading', { name: 'Корзина' });
  const row = async (name: string) => (await screen.findByText(name)).closest('tr') as HTMLElement;
  return { calls, row };
}

describe('вкладка «Корзина»', () => {
  it('модератор видит узлы и документы; срок в последние 3 дня — плашкой', async () => {
    const { row } = await openTrash();
    const reports = await row('Отчёты');
    expect(reports.textContent).toContain('Бэкенд ›');
    expect(reports.textContent).toContain('3 узла');
    expect(reports.textContent).toContain('И. Иванов');
    expect(reports.textContent).toContain('ещё 28 дней');
    const old = await row('Старый дашборд');
    expect(within(old).getByText('будет удалён через 2 дн.').className).toContain('pill warn');
    expect((await row('ТЗ_v1.pdf')).textContent).toContain('Документы заказчика ›');
    expect(screen.getByText('В корзине 3 элемента')).toBeTruthy();
  });

  it('эксперт видит только свои ветки', async () => {
    const view = await openTrash('expert');
    await view.row('Отчёты');
    expect(screen.queryByText('Старый дашборд')).toBeNull();
    expect(screen.queryByText('ТЗ_v1.pdf')).toBeNull();
  });

  it('пресейл видит только документы и восстанавливает их', async () => {
    const view = await openTrash('presale');
    within(await view.row('ТЗ_v1.pdf')).getByRole('button', { name: 'Восстановить «ТЗ_v1.pdf»' });
    expect(screen.queryByText('Отчёты')).toBeNull();
  });

  it('«Восстановить» возвращает пакет на прежнее место и убирает строку', async () => {
    const { calls, row } = await openTrash();
    fireEvent.click(within(await row('Отчёты')).getByRole('button', { name: 'Восстановить «Отчёты»' }));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/restore'))?.body).toEqual({}));
    expect(calls[0]?.path).toBe(`/api/v1/trash/${uuidFrom('trash', 'portal', 'reports')}/restore`);
    expect(await screen.findByText('«Отчёты» восстановлен')).toBeTruthy();
    await waitFor(() => expect(screen.queryByText('Отчёты')).toBeNull());
  });

  it('документ восстанавливается через документы', async () => {
    const { calls, row } = await openTrash();
    fireEvent.click(within(await row('ТЗ_v1.pdf')).getByRole('button', { name: /^Восстановить/ }));
    await waitFor(() =>
      expect(calls.at(-1)?.path).toBe(`/api/v1/documents/${uuidFrom('document', 'portal', 'tz-v1')}/restore`),
    );
    await waitFor(() => expect(screen.queryByText('ТЗ_v1.pdf')).toBeNull());
  });
});

describe('G-15: восстановление в ветку «не нужно»', () => {
  const status = () =>
    portal.branchStatuses.find(
      (b) => b.phase_id === phaseId('ph-dev') && b.discipline_id === disciplineId('d-backend'),
    ) as { status: string };

  it('система предлагает выбрать другое место в дисциплине Бэкенд', async () => {
    const was = status().status;
    status().status = 'not_needed';
    // вторая ветка Бэкенда — в фазе «Тестирование», чтобы было куда восстановить
    const phase = portal.nodes.find((n) => n.kind === 'phase' && n.phase_id === phaseId('ph-test')) as
      | { id: string }
      | undefined;
    const sample = portal.nodes.find((n) => n.kind === 'discipline') as Record<string, unknown>;
    const extra = {
      ...sample,
      id: uuidFrom('node', 'test', 'qa-backend'),
      parent_id: phase?.id ?? null,
      phase_id: phaseId('ph-test'),
      discipline_id: disciplineId('d-backend'),
      title: 'Бэкенд',
      position: 'zz',
      o: null,
      r: null,
      p: null,
    };
    portal.nodes.push(extra as never);
    try {
      const { calls, row } = await openTrash();
      fireEvent.click(within(await row('Отчёты')).getByRole('button', { name: 'Восстановить «Отчёты»' }));
      const dialog = await screen.findByRole('dialog', { name: 'Восстановить «Отчёты»' });
      expect(dialog.textContent).toContain('ветка в статусе «не нужно»');
      const options = await within(dialog).findAllByRole('radio');
      expect(options.map((o) => o.textContent)).toEqual(['Тестирование › Бэкенд']);
      fireEvent.click(options[0] as HTMLElement);
      fireEvent.click(within(dialog).getByRole('button', { name: 'Восстановить' }));
      await waitFor(() =>
        expect(calls.filter((c) => c.path.endsWith('/restore')).at(-1)?.body).toEqual({ target_parent_id: extra.id }),
      );
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(screen.getByText('«Отчёты» восстановлен')).toBeTruthy();
    } finally {
      status().status = was;
      portal.nodes.splice(portal.nodes.indexOf(extra as never), 1);
    }
  });
});

it('без пакетов — «Корзина пуста»', async () => {
  persona.current = PERSONAS.expert;
  renderApp(`/projects/${PROJECTS.fns.id}/trash`);
  expect(await screen.findByText('Корзина пуста')).toBeTruthy();
});
