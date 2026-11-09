/** FE-025 · ввод в ячейки: разбор часов и вилки, Tab-навигация, сохранение, ошибки, комментарий. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, problem, renderApp } from '../../../test/render';
import { parseFork, parseHours, parseMultiplier } from './hours';
import { nextCell, sameHours } from './useCells';

describe('разбор ввода', () => {
  it('часы: запятая и точка, шаг 0,5 по ROUND_HALF_UP, пусто, ошибки', () => {
    expect(parseHours('12')).toEqual({ ok: true, value: '12', rounded: false });
    expect(parseHours('12,5')).toEqual({ ok: true, value: '12.5', rounded: false });
    expect(parseHours('12.3')).toEqual({ ok: true, value: '12.5', rounded: true });
    expect(parseHours('12,25')).toEqual({ ok: true, value: '12.5', rounded: true });
    expect(parseHours('12,2')).toEqual({ ok: true, value: '12', rounded: true });
    expect(parseHours(' ')).toEqual({ ok: true, value: null, rounded: false });
    expect(parseHours('abc')).toEqual({ ok: false, error: 'number' });
    expect(parseHours('1,2,3')).toEqual({ ok: false, error: 'number' });
    expect(parseHours('-1')).toEqual({ ok: false, error: 'number' });
    expect(parseHours('100000')).toEqual({ ok: false, error: 'range' });
    expect(sameHours('12', '12.00')).toBe(true);
    expect(sameHours(null, '0')).toBe(false);
  });

  it('вилка в поле O и множитель', () => {
    expect(parseFork('8-12-20')).toEqual(['8', '12', '20']);
    expect(parseFork('8/12/20')).toEqual(['8', '12', '20']);
    expect(parseFork('8 – 12,5 – 20')).toEqual(['8', '12,5', '20']);
    expect(parseFork('8-12')).toBeNull();
    expect(parseFork('8')).toBeNull();
    expect(parseMultiplier('3')).toEqual({ ok: true, value: 3 });
    expect(parseMultiplier('0').ok).toBe(false);
    expect(parseMultiplier('10001').ok).toBe(false);
    expect(parseMultiplier('2,5').ok).toBe(false);
  });

  it('Tab: O → R → P → Комментарий → O следующего листа, Shift+Tab — назад', () => {
    const leaves = ['a', 'b'];
    expect(nextCell(leaves, { nodeId: 'a', field: 'o' }, 1)).toEqual({ nodeId: 'a', field: 'r' });
    expect(nextCell(leaves, { nodeId: 'a', field: 'p' }, 1)).toEqual({ nodeId: 'a', field: 'comment' });
    expect(nextCell(leaves, { nodeId: 'a', field: 'comment' }, 1)).toEqual({ nodeId: 'b', field: 'o' });
    expect(nextCell(leaves, { nodeId: 'b', field: 'comment' }, 1)).toBeNull();
    expect(nextCell(leaves, { nodeId: 'b', field: 'o' }, -1)).toEqual({ nodeId: 'a', field: 'comment' });
    expect(nextCell(leaves, { nodeId: 'a', field: 'o' }, -1)).toBeNull();
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

async function openTree() {
  persona.current = PERSONAS.expert;
  const patches: { id: string; body: { base_version: number; changes: Record<string, unknown> } }[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method !== 'PATCH') return;
    const nodeId = new URL(request.url).pathname.split('/').at(-1) ?? '';
    void request
      .clone()
      .json()
      .then((body) => patches.push({ id: nodeId, body: body as (typeof patches)[number]['body'] }));
  });
  renderApp(`/projects/${id}`);
  const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
  await within(grid).findByText('Авторизация');
  const row = (title: string) => within(grid).getByText(title).closest('[role="row"]') as HTMLElement;
  return { grid, row, patches };
}

describe('ввод в ячейки на рабочем экране', () => {
  it('полный цикл с клавиатуры: вилка в O, Tab в комментарий, строка с меткой, Tab в O следующего листа', async () => {
    const { row, patches } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'O: 8' }));
    const o = within(row('Авторизация')).getByRole('textbox', { name: 'O' });
    expect(document.activeElement).toBe(o);
    fireEvent.change(o, { target: { value: '8-12-21' } });
    fireEvent.keyDown(o, { key: 'Tab' });
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]?.body.changes).toEqual({ p: '21' });
    expect(patches[0]?.body.base_version).toBeGreaterThan(0);
    await waitFor(() => expect(within(row('Авторизация')).getByRole('button', { name: 'P: 21' })).toBeTruthy());

    const editor = within(row('Авторизация')).getByRole('group', { name: 'Комментарий листа' });
    const text = within(editor).getByRole('textbox', { name: 'Строка комментария 1' });
    fireEvent.change(text, { target: { value: 'OAuth2 через Keycloak' } });
    fireEvent.keyDown(text, { key: 'Tab' });
    await waitFor(() => expect(patches).toHaveLength(2));
    expect(patches[1]?.body.changes).toEqual({ comment_lines: [{ tag_id: null, text: 'OAuth2 через Keycloak' }] });
    const next = await within(row('Профиль дилера')).findByRole('textbox', { name: 'O' });
    expect(document.activeElement).toBe(next);
    fireEvent.keyDown(next, { key: 'Escape' });
    expect(within(row('Профиль дилера')).queryByRole('textbox')).toBeNull();
  });

  it('округление до 0,5 с подсказкой; Esc не сохраняет', async () => {
    const { row, patches } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'R: 12' }));
    const r = within(row('Авторизация')).getByRole('textbox', { name: 'R' });
    fireEvent.change(r, { target: { value: '99' } });
    fireEvent.keyDown(r, { key: 'Escape' });
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'R: 12' }));
    const again = within(row('Авторизация')).getByRole('textbox', { name: 'R' });
    fireEvent.change(again, { target: { value: '12,3' } });
    fireEvent.keyDown(again, { key: 'Enter' });
    expect(within(row('Авторизация')).getByRole('status').textContent).toBe('округлено до 12,5');
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]?.body.changes).toEqual({ r: '12.5' });
  });

  it('ошибка 422 — красная рамка и текст, введённое значение остаётся; неверное число не отправляется', async () => {
    server.use(http.patch(api('/nodes/:id'), () => problem(422, 'VALIDATION_FAILED')));
    const { row, patches } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'O: 8' }));
    const bad = within(row('Авторизация')).getByRole('textbox', { name: 'O' });
    fireEvent.change(bad, { target: { value: 'восемь' } });
    fireEvent.keyDown(bad, { key: 'Enter' });
    expect(within(row('Авторизация')).getByRole('alert').textContent).toMatch(/Введите число/);
    expect(within(row('Авторизация')).getByRole('textbox', { name: 'O' })).toBeTruthy();

    fireEvent.change(bad, { target: { value: '10' } });
    fireEvent.keyDown(bad, { key: 'Enter' });
    const cell = await within(row('Авторизация')).findByRole('button', { name: 'O: 10' });
    await waitFor(() => expect(cell.className).toContain('error'));
    expect(within(row('Авторизация')).getByRole('alert').textContent).toBe('Проверьте выделенные поля.');
    expect(patches).toHaveLength(1);
    // в расчёт значение не вошло: E листа прежнее
    expect(within(row('Авторизация')).getByText('12,7')).toBeTruthy();
    fireEvent.click(cell);
    expect((within(row('Авторизация')).getByRole('textbox', { name: 'O' }) as HTMLInputElement).value).toBe('10');
  });

  it('чужая ветка — без полей ввода', async () => {
    const { grid } = await openTree();
    fireEvent.click(screen.getByRole('button', { name: /Мои ветки/, pressed: true }));
    await within(grid).findByText('Дашборд');
    const foreign = within(grid).getByText('Дашборд').closest('[role="row"]') as HTMLElement;
    expect(within(foreign).queryByRole('button', { name: /^O:/ })).toBeNull();
    expect(within(foreign).queryByRole('button', { name: 'Изменить комментарий' })).toBeNull();
  });

  it('норма типа у пустого листа: «Норма: … · подставить» отправляет вилку', async () => {
    const leaf = PROJECTS.portal.nodes.find((n) => n.title === 'Авторизация');
    if (!leaf) throw new Error('нет листа');
    const saved = { o: leaf.o, r: leaf.r, p: leaf.p };
    Object.assign(leaf, { o: null, r: null, p: null });
    server.use(
      http.get(api('/admin/node-types'), () =>
        HttpResponse.json({
          items: [
            {
              id: leaf.type_id,
              name: 'Функция',
              icon: 'function',
              norms: [{ label: 'средняя функция', o: '5', r: '7', p: '10' }],
              is_system: false,
              is_active: true,
            },
          ],
        }),
      ),
    );
    try {
      const { row, patches } = await openTree();
      expect(await within(row('Авторизация')).findByText(/Норма: средняя функция 5–7–10/)).toBeTruthy();
      fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'подставить' }));
      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]?.body.changes).toEqual({ o: '5', r: '7', p: '10' });
    } finally {
      Object.assign(leaf, saved);
    }
  });
});
