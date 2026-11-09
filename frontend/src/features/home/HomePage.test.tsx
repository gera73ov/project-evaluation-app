/** FE-010 · «Мои оценки» и колокольчик на моках (SPEC 11.3 №1–7, FR-HOME-01…04, FR-NOTIF-01). */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../test/render';
import { sortProjects, type ProjectItem } from './HomePage';

beforeEach(() => {
  window.localStorage.clear();
});

async function openHome() {
  renderApp('/');
  return screen.findByRole('heading', { name: 'Мои оценки', level: 1 });
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByRole('link', { name }).closest('tr');
  if (!row) throw new Error(`нет строки ${name}`);
  return row;
}

describe('«Мои оценки»', () => {
  it('№3, №5, №7: роли, прогресс, «Мне», «Итог, ч»; деньги — только где модератор', async () => {
    await openHome();
    await screen.findByRole('link', { name: 'Портал дилеров' });
    const portal = rowOf('Портал дилеров');
    await waitFor(() => expect(within(portal).getByText('Эксперт: Бэкенд · ревьюер')).toBeTruthy());
    expect(within(portal).getByText('2 из 3')).toBeTruthy();
    expect(within(portal).getByText('P80')).toBeTruthy();
    expect(portal.querySelector('.lock')).toBeNull(); // эксперт денег не видит

    const fns = rowOf('Интеграция с ФНС');
    expect(within(fns).getByText('Модератор')).toBeTruthy();
    expect(fns.querySelector('.lock')).not.toBeNull();
    expect(screen.getByText(/Сортировка: сначала с вопросами мне/)).toBeTruthy();
  });

  it('№2: «+ Создать проект» только с системной ролью «Модератор»', async () => {
    await openHome();
    expect(await screen.findByRole('link', { name: '+ Создать проект' })).toBeTruthy();
  });

  it('у пресейла без системной роли «Модератор» кнопки создания нет совсем', async () => {
    persona.current = PERSONAS.presale;
    await openHome();
    await screen.findByRole('link', { name: 'Портал дилеров' });
    expect(screen.queryByRole('link', { name: '+ Создать проект' })).toBeNull();
  });

  it('№1: поиск с 2 символов; фильтры запоминаются', async () => {
    const queries: (string | null)[] = [];
    const statuses: (string | null)[] = [];
    server.events.on('request:start', ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith('/api/v1/projects') && request.method === 'GET' && url.searchParams.get('limit') === '50') {
        queries.push(url.searchParams.get('q'));
        statuses.push(url.searchParams.get('status'));
      }
    });
    await openHome();
    const search = screen.getByLabelText('Поиск по названию и заказчику');
    fireEvent.change(search, { target: { value: 'П' } });
    await new Promise((r) => setTimeout(r, 400));
    expect(queries.every((q) => q === null)).toBe(true);
    fireEvent.change(search, { target: { value: 'По' } });
    await waitFor(() => expect(queries).toContain('По'));

    fireEvent.click(screen.getByRole('textbox', { name: 'Статус' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Статус: Архив' }));
    await waitFor(() => expect(statuses).toContain('archived'));
    server.events.removeAllListeners();

    const key = Object.keys(window.localStorage).find((k) => k.startsWith('home.filters.')) ?? '';
    expect(JSON.parse(window.localStorage.getItem(key) ?? 'null')).toMatchObject({ status: 'archived', q: 'По' });
  });

  it('клик по строке открывает рабочий экран', async () => {
    await openHome();
    await screen.findByRole('link', { name: 'Портал дилеров' });
    fireEvent.click(within(rowOf('Портал дилеров')).getByText('Эксперт: Бэкенд · ревьюер'));
    await waitFor(() => expect(window.location.pathname).toMatch(/^\/projects\/[0-9a-f-]+$/));
  });

  it('проектов нет — «Вас пока не добавили ни в один проект»', async () => {
    server.use(http.get(api('/projects'), () => HttpResponse.json({ items: [], next_cursor: null })));
    await openHome();
    expect(await screen.findByText('Вас пока не добавили ни в один проект')).toBeTruthy();
  });
});

describe('колокольчик (11.3 №6)', () => {
  it('счётчик; список с метками видов; клик — прочитано и переход к строке', async () => {
    let readBody: unknown = null;
    server.use(
      http.post(api('/notifications/read'), async ({ request }) => {
        readBody = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await openHome();
    const bell = await screen.findByRole('button', { name: 'Уведомления, непрочитанных: 3' });
    fireEvent.click(bell);
    const list = await screen.findByRole('region', { name: 'Мне' });
    expect(within(list).getByText('Вопрос вам')).toBeTruthy();
    expect(within(list).getByText('Изменение модератора')).toBeTruthy();
    await waitFor(() => expect(within(list).getAllByText(/Портал дилеров/).length).toBeGreaterThan(0));
    fireEvent.click(within(list).getByText('Вопрос вам'));
    await waitFor(() => expect(window.location.pathname).toMatch(/^\/projects\//));
    expect(window.location.search).toMatch(/^\?node=/);
    await waitFor(() => expect(readBody).toMatchObject({ ids: [expect.any(String)] }));
  });
});

describe('sortProjects (FR-HOME-02)', () => {
  const item = (id: string, toMe: number, deadline: string | null) =>
    ({ id, questions_to_me: toMe, deadline }) as unknown as ProjectItem;
  it('сначала «Мне» > 0, затем дедлайн по возрастанию, без дедлайна — в конце', () => {
    const sorted = sortProjects([
      item('a', 0, null),
      item('b', 0, '2026-11-07'),
      item('c', 2, '2026-11-20'),
      item('d', 1, '2026-11-05'),
      item('e', 0, '2026-10-12'),
    ]);
    expect(sorted.map((p) => p.id)).toEqual(['d', 'c', 'e', 'b', 'a']);
  });
});
