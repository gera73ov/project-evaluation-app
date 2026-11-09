/** FE-011 · создание проекта на моках: проверки FR-PRJ-01, тело запроса, переход в настройки. */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../test/render';
import { todayIso, validate, type CreateForm } from './ProjectCreatePage';

const base: CreateForm = {
  name: 'ООО «Пример». Портал. Оценка',
  customer: 'ООО «Пример»',
  description: '',
  phaseIds: ['p1'],
  detailLevel: 'medium',
  deadline: '',
};

describe('validate (FR-PRJ-01)', () => {
  it('название 3–200, заказчик 1–200, описание ≤ 10 000, ≥ 1 фаза, дедлайн не в прошлом', () => {
    expect(validate(base, '2026-11-09')).toEqual({});
    expect(
      Object.keys(
        validate(
          { ...base, name: ' ab ', customer: '  ', description: 'x'.repeat(10_001), phaseIds: [], deadline: '2026-11-08' },
          '2026-11-09',
        ),
      ).sort(),
    ).toEqual(['customer', 'deadline', 'description', 'name', 'phases']);
    expect(validate({ ...base, deadline: '2026-11-09' }, '2026-11-09')).toEqual({});
  });
  it('todayIso по часам браузера', () => {
    expect(todayIso(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});

describe('страница /projects/new', () => {
  it('все фазы включены, «Управление проектом» — всегда; «Создать» → настройки проекта', async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(api('/projects'), async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { project: { id: '11111111-2222-4333-8444-555555555555' }, project_version: 1 },
          { status: 201 },
        );
      }),
    );
    renderApp('/projects/new');
    await screen.findByRole('heading', { name: 'Новый проект' });
    const pm = await screen.findByRole('checkbox', { name: /Управление проектом/ });
    expect((pm as HTMLInputElement).checked).toBe(true);
    expect((pm as HTMLInputElement).disabled).toBe(true);
    const testing = screen.getByRole('checkbox', { name: 'Тестирование' });
    fireEvent.click(testing);

    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));
    expect(await screen.findByText('От 3 до 200 символов')).toBeTruthy();
    expect(body).toBeNull();

    fireEvent.change(screen.getByRole('textbox', { name: /Название/ }), { target: { value: 'Пример. Портал. Оценка' } });
    fireEvent.change(screen.getByRole('textbox', { name: /Заказчик/ }), { target: { value: 'ООО «Пример»' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Детально' }));
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(window.location.pathname).toBe('/projects/11111111-2222-4333-8444-555555555555/settings'));
    expect(body).toMatchObject({ name: 'Пример. Портал. Оценка', customer: 'ООО «Пример»', detail_level: 'detailed', deadline: null });
    expect((body as unknown as { phase_ids: string[] }).phase_ids).toHaveLength(3); // 4 фазы минус «Тестирование»
  });

  it('без системной роли «Модератор» страница недоступна', async () => {
    persona.current = PERSONAS.presale;
    renderApp('/projects/new');
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Новый проект' })).toBeNull());
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Создать' })).toBeNull());
  });
});
