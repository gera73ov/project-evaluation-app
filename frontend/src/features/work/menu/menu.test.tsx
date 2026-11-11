/** FE-027 · меню строки: правила операций, «+» с типом по профилю, разбиение, свёртка, удаление, перенос. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS, typeId } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import type { TreeNode } from '../store/treeStore';
import { sourceRows } from './dialogs';
import { depthOf, dropAfter, moveTargets, needsDeleteConfirm, reorderAfter, suggestType } from './ops';

function tree(list: [id: string, parent: string | null, kind: TreeNode['kind'], type?: string, extra?: object][]) {
  const nodes = new Map<string, TreeNode>();
  const children = new Map<string | null, string[]>();
  for (const [id, parent, kind, type, extra] of list) {
    nodes.set(id, {
      id,
      parent_id: parent,
      kind,
      phase_id: kind === 'phase' ? id : (list.find((x) => x[2] === 'phase')?.[0] ?? ''),
      discipline_id: kind === 'phase' ? null : id.startsWith('b') ? 'd2' : 'd1',
      type_id: type ?? null,
      title: id,
      position: id,
      o: null,
      r: null,
      p: null,
      multiplier: 1,
      version: 1,
      extra: { ...extra },
    });
    children.set(parent, [...(children.get(parent) ?? []), id]);
  }
  return { nodes, children };
}

describe('правила меню', () => {
  const t = tree([
    ['ph', null, 'phase'],
    ['d', 'ph', 'discipline'],
    ['m', 'd', 'item', 'module'],
    ['f1', 'm', 'item', 'function'],
    ['f2', 'm', 'item', 'function', { messages_count: 2 }],
    ['f3', 'm', 'item', 'function'],
    ['b', 'ph', 'discipline'],
    ['bm', 'b', 'item', 'module'],
    ['bx', 'bm', 'item', 'work'],
  ]);

  it('тип нового узла по профилю: ветка — первый тип, N-й — (N+1)-й, иначе тип родителя', () => {
    const chain = ['module', 'function'];
    expect(suggestType(t, 'd', chain)).toBe('module');
    expect(suggestType(t, 'm', chain)).toBe('function');
    expect(suggestType(t, 'f1', chain)).toBe('function');
    expect(suggestType(t, 'm', [])).toBe('module');
  });

  it('вверх и вниз, глубина, подтверждение удаления', () => {
    expect(reorderAfter(t, 'f1', -1)).toBeNull();
    expect(reorderAfter(t, 'f2', -1)).toEqual({ afterId: null });
    expect(reorderAfter(t, 'f3', -1)).toEqual({ afterId: 'f1' });
    expect(reorderAfter(t, 'f1', 1)).toEqual({ afterId: 'f2' });
    expect(reorderAfter(t, 'f3', 1)).toBeNull();
    // перетаскивание: только внутри родителя, «на своё место» — ничего
    expect(dropAfter(t, 'f3', 'f1', false)).toEqual({ afterId: null });
    expect(dropAfter(t, 'f1', 'f2', true)).toEqual({ afterId: 'f2' });
    expect(dropAfter(t, 'f1', 'f3', false)).toEqual({ afterId: 'f2' });
    expect(dropAfter(t, 'f2', 'f1', true)).toBeNull();
    expect(dropAfter(t, 'f1', 'f1', true)).toBeNull();
    expect(dropAfter(t, 'f1', 'bx', true)).toBeNull();
    expect(dropAfter(t, 'd', 'b', true)).toBeNull();
    expect(depthOf(t, 'f1')).toBe(2);
    expect(depthOf(t, 'd')).toBe(0);
    expect(needsDeleteConfirm(t, 'm')).toBe(true);
    expect(needsDeleteConfirm(t, 'f2')).toBe(true);
    expect(needsDeleteConfirm(t, 'f1')).toBe(false);
  });

  it('перенос: эксперту — своя ветка, модератору — проект; без себя, потомков и нынешнего родителя', () => {
    const all = () => true;
    expect(moveTargets(t, 'f1', { sameBranch: true, canEdit: all }).map((x) => x.id)).toEqual(['d']);
    expect(moveTargets(t, 'f1', { sameBranch: false, canEdit: all }).map((x) => x.id)).toEqual(['d', 'b', 'bm']);
    expect(moveTargets(t, 'm', { sameBranch: false, canEdit: (d) => d === 'd1' }).map((x) => x.id)).toEqual([]);
  });

  it('источник копирования: ветки той же дисциплины с фазой и их узлы', () => {
    const rows = sourceRows(
      [
        {
          id: 'p',
          parent_id: null,
          kind: 'phase',
          title: 'Разработка',
          position: '1',
          discipline_id: null,
          phase_id: 'p',
        },
        {
          id: 'd',
          parent_id: 'p',
          kind: 'discipline',
          title: 'Бэкенд',
          position: '1',
          discipline_id: 'x',
          phase_id: 'p',
        },
        { id: 'a', parent_id: 'd', kind: 'item', title: 'ЛК', position: '1', discipline_id: 'x', phase_id: 'p' },
        { id: 'e', parent_id: 'p', kind: 'discipline', title: 'QA', position: '2', discipline_id: 'y', phase_id: 'p' },
      ],
      'x',
    );
    expect(rows).toEqual([
      { id: 'd', title: 'Разработка · Бэкенд', level: 0 },
      { id: 'a', title: 'ЛК', level: 1 },
    ]);
  });
});

const realHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains('tree-scroll') ? 900 : 0;
    },
  });
});
afterEach(() => server.events.removeAllListeners());
afterAll(() => {
  if (realHeight) Object.defineProperty(HTMLElement.prototype, 'clientHeight', realHeight);
});

const id = PROJECTS.portal.id;
const nodeId = (title: string) => String(PROJECTS.portal.nodes.find((n) => n.title === title)?.id);

async function openTree(who: 'expert' | 'moderator' = 'expert') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  const calls: { method: string; path: string; body: unknown }[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET') return;
    const path = new URL(request.url).pathname.replace(/^\/api\/v1/, '');
    const entry = { method: request.method, path, body: null as unknown };
    calls.push(entry);
    void request
      .clone()
      .json()
      .then((body) => (entry.body = body))
      .catch(() => undefined);
  });
  renderApp(`/projects/${id}`);
  const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
  await within(grid).findByText('Авторизация');
  const row = (title: string) => within(grid).getByText(title).closest('[role="row"]') as HTMLElement;
  return { grid, row, calls };
}

describe('меню строки на рабочем экране', () => {
  it('«+» → «Лист рядом»: тип по профилю, новый лист под строкой, курсор в названии', async () => {
    const { grid, row, calls } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'Добавить рядом с «Авторизация»' }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByText('под «Авторизация»')).toBeTruthy();
    const profile = within(menu).getByRole('menuitem', { name: /Функция/ });
    expect(profile.textContent).toContain('профиль');
    expect(within(menu).getByRole('menuitem', { name: /Дочерний узел/ }).textContent).toContain('= разбить лист');
    fireEvent.click(within(menu).getByRole('menuitem', { name: /Лист рядом/ }));
    await waitFor(() => expect(calls.some((c) => c.path === `/projects/${id}/nodes`)).toBe(true));
    await waitFor(() =>
      expect(calls.find((c) => c.path === `/projects/${id}/nodes`)?.body).toEqual({
        parent_id: nodeId('Личный кабинет'),
        after_id: nodeId('Авторизация'),
        type_id: typeId('Функция'),
        title: 'Новый узел',
      }),
    );
    const title = await within(grid).findByRole('textbox', { name: 'Название' });
    expect(document.activeElement).toBe(title);
    // новый лист стоит сразу под «Авторизацией»
    const rows = within(grid).getAllByRole('row');
    const at = rows.indexOf(row('Авторизация'));
    expect(rows.at(at + 1)?.contains(title)).toBe(true);
    fireEvent.change(title, { target: { value: 'Восстановление пароля' } });
    fireEvent.keyDown(title, { key: 'Enter' });
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
        changes: { title: 'Восстановление пароля' },
      }),
    );
    expect(await within(grid).findByText('Восстановление пароля')).toBeTruthy();
  });

  it('выбранный в сетке тип уходит в запрос; «Дочерний узел» у листа — разбить с подтверждением', async () => {
    const { grid, row, calls } = await openTree();
    fireEvent.click(within(row('Профиль дилера')).getByRole('button', { name: /^Добавить/ }));
    const menu = await screen.findByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: /Дочерний узел/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Разбить лист «Профиль дилера»?' });
    expect(dialog.textContent).toContain('12–16–24');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Разбить' }));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/split'))?.body).toMatchObject({ base_version: 3 }));
    const part = await within(grid).findByRole('textbox', { name: 'Название' });
    expect((part as HTMLInputElement).value).toBe('Профиль дилера — часть 1');
    fireEvent.keyDown(part, { key: 'Escape' });
    expect(within(row('Профиль дилера — часть 1')).getByRole('button', { name: 'O: 12' })).toBeTruthy();
    expect(within(row('Профиль дилера')).queryByRole('button', { name: /^O:/ })).toBeNull();
  });

  it('«⋯»: недоступные пункты с причиной; «Свернуть в лист» с суммами детей', async () => {
    const { row, calls } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: /^Действия/ }));
    let menu = await screen.findByRole('menu');
    const collapse = within(menu).getByRole('menuitem', { name: /Свернуть в лист/ });
    expect(collapse.hasAttribute('data-disabled')).toBe(true);
    expect(collapse.textContent).toContain('нет детей');
    expect(within(menu).getByRole('menuitem', { name: /Вверх/ }).textContent).toContain('первый');
    expect(within(menu).getByRole('menuitem', { name: /Профиль ветки/ }).textContent).toContain('у строки дисциплины');
    fireEvent.keyDown(menu, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());

    fireEvent.contextMenu(row('Личный кабинет'));
    menu = await screen.findByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Свернуть в лист' }));
    const dialog = await screen.findByRole('dialog', { name: 'Свернуть «Личный кабинет» в лист' });
    expect(dialog.textContent).toMatch(/2 дочерних узла/);
    expect((within(dialog).getByRole('textbox', { name: 'O' }) as HTMLInputElement).value).toBe('20');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Свернуть' }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/collapse'))?.body).toMatchObject({ o: '20', r: '28', p: '44' }),
    );
    await waitFor(() => expect(screen.queryByText('Авторизация')).toBeNull());
    expect(within(row('Личный кабинет')).getByRole('button', { name: 'P: 44' })).toBeTruthy();
  });

  it('удаление: лист без обсуждения — сразу, с обсуждением — после подтверждения', async () => {
    const { row, calls } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: /^Действия/ }));
    fireEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Удалить в корзину' }));
    await waitFor(() => expect(screen.queryByText('Авторизация')).toBeNull());
    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(1);

    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
    fireEvent.click(within(row('Обмен с 1С')).getByRole('button', { name: /^Действия/ }));
    fireEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Удалить в корзину' }));
    const dialog = await screen.findByRole('dialog', { name: 'Удалить «Обмен с 1С» в корзину?' });
    expect(dialog.textContent).toContain('есть обсуждение');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить в корзину' }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(2));
  });

  it('«Переместить в…» и «Вниз»: запрос move с новым родителем и порядком', async () => {
    const { grid, row, calls } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: /^Действия/ }));
    fireEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: /Вниз/ }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/move'))?.body).toMatchObject({
        new_parent_id: nodeId('Личный кабинет'),
        after_id: nodeId('Профиль дилера'),
      }),
    );
    await waitFor(() => {
      const titles = within(grid)
        .getAllByRole('row')
        .map((r) => r.textContent ?? '');
      expect(titles.findIndex((x) => x.includes('Профиль дилера'))).toBeLessThan(
        titles.findIndex((x) => x.includes('Авторизация')),
      );
    });

    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
    fireEvent.click(within(row('Обмен с 1С')).getByRole('button', { name: /^Действия/ }));
    fireEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Переместить в…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Переместить «Обмен с 1С»' });
    // эксперт: только своя ветка; нынешний родитель (ветка «Бэкенд») не предлагается
    const options = within(dialog).getAllByRole('radio');
    expect(options.map((o) => o.textContent)).toEqual(['Личный кабинет']);
    fireEvent.click(options[0] as HTMLElement);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Переместить' }));
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith('/move')).at(-1)?.body).toMatchObject({
        new_parent_id: nodeId('Личный кабинет'),
        after_id: nodeId('Авторизация'),
      }),
    );
  });

  it('перетаскивание строки меняет порядок внутри родителя; в чужого родителя не бросить', async () => {
    const { grid, row, calls } = await openTree();
    const transfer = { setData: () => undefined, effectAllowed: '', dropEffect: '' };
    const handle = within(grid).getByTestId(`drag-${nodeId('Профиль дилера')}`);
    fireEvent.dragStart(handle, { dataTransfer: transfer });
    // другой родитель: бросить нельзя — dragover не отменён
    expect(fireEvent.dragOver(row('Обмен с 1С'), { dataTransfer: transfer })).toBe(true);
    expect(fireEvent.dragOver(row('Авторизация'), { dataTransfer: transfer })).toBe(false);
    expect(row('Авторизация').className).toContain('drop-above');
    fireEvent.drop(row('Авторизация'), { dataTransfer: transfer });
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/move'))?.body).toMatchObject({
        new_parent_id: nodeId('Личный кабинет'),
        after_id: null,
      }),
    );
    await waitFor(() => {
      const titles = within(grid)
        .getAllByRole('row')
        .map((r) => r.textContent ?? '');
      expect(titles.findIndex((x) => x.includes('Профиль дилера'))).toBeLessThan(
        titles.findIndex((x) => x.includes('Авторизация')),
      );
    });
  });

  it('свой тип в проекте: иконка сеткой, тип сразу работает — лист этого типа рядом', async () => {
    const { grid, row, calls } = await openTree();
    fireEvent.click(within(row('Обмен с 1С')).getByRole('button', { name: /^Добавить/ }));
    fireEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: /Свой тип в проекте/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Свой тип в проекте' });
    expect(within(dialog).getAllByRole('radio')).toHaveLength(30);
    const create = within(dialog).getByRole('button', { name: 'Создать тип и лист' });
    expect((create as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Название типа' }), {
      target: { value: 'Шлюз' },
    });
    fireEvent.click(within(dialog).getByRole('radio', { name: 'API' }));
    fireEvent.click(create);
    await waitFor(() => expect(calls.some((c) => c.path === `/projects/${id}/nodes`)).toBe(true));
    expect(calls.find((c) => c.path === `/projects/${id}/node-types`)?.body).toEqual({ name: 'Шлюз', icon: 'api' });
    await within(grid).findByRole('textbox', { name: 'Название' });
    const created = calls.find((c) => c.path === `/projects/${id}/nodes`)?.body as { type_id: string };
    expect(created.type_id).toBeTruthy();
    fireEvent.keyDown(within(grid).getByRole('textbox', { name: 'Название' }), { key: 'Escape' });
    expect(within(row('Новый узел')).getByTitle('Шлюз').textContent).toBe('⟨⟩');
  });

  it('ветка дисциплины: «Профиль ветки ▸» меняет профиль; чужая ветка без кнопок', async () => {
    const { grid, row, calls } = await openTree();
    fireEvent.click(within(row('Бэкенд')).getByRole('button', { name: /^Действия/ }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).queryByRole('menuitem', { name: /Сменить тип/ })).toBeNull();
    fireEvent.click(within(menu).getByRole('menuitem', { name: /Профиль ветки/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Профиль ветки «Бэкенд»' });
    expect(within(dialog).getByRole('button', { name: /Модуль → Функция/, pressed: true })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: /Модуль → Работа/ }));
    await waitFor(() => expect(calls.find((c) => c.path.includes('/disciplines/'))?.body).toBeTruthy());
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: /Мои ветки/, pressed: true }));
    await within(grid).findByText('Дашборд');
    expect(within(row('Дашборд')).queryByRole('button', { name: /^Действия/ })).toBeNull();
  });
});
