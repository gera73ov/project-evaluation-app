/** FE-015 · «Журнал проекта» (11.6 №1): кто, когда, что, «было → стало», «Система», денежные записи. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import i18n from 'i18next';
import { describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../../test/render';
import { changeRows, showValue } from './JournalPage';

const id = PROJECTS.portal.id;
const t = i18n.t.bind(i18n);
const user = { id: '0190c0de-0000-7000-8000-000000000001', full_name: 'А. Смирнова', initials: 'АС' };

function entry(n: number, fields: Record<string, unknown>) {
  return {
    id: `0190c0de-0000-7000-8000-0000000001${String(n).padStart(2, '0')}`,
    created_at: '2026-11-09T09:00:00Z',
    user,
    action: 'project.settings',
    changes: {},
    ...fields,
  };
}

describe('журнал: значения', () => {
  it('пусто — «—», логическое — да/нет, список — через запятую', () => {
    expect(showValue(null, t)).toBe('—');
    expect(showValue([], t)).toBe('—');
    expect(showValue(true, t)).toBe('да');
    expect(showValue(['a', 'b'], t)).toBe('a, b');
    expect(showValue('18', t)).toBe('18');
  });

  it('пары без двух значений пропускаются', () => {
    expect(changeRows({ name: ['А', 'Б'], bad: 'x', short: [1] })).toEqual([
      { field: 'name', before: 'А', after: 'Б' },
    ]);
  });
});

describe('вкладка «Журнал проекта»', () => {
  it('записи с автором, «Система», полями и денежными изменениями; «Показать ещё»', async () => {
    persona.current = PERSONAS.moderator;
    server.use(
      http.get(api('/projects/:id/journal'), ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        if (cursor === 'p2') {
          return HttpResponse.json({ items: [entry(3, { action: 'project.created' })], next_cursor: null });
        }
        return HttpResponse.json({
          items: [
            entry(1, { changes: { pm_percent: ['15', '18'], deadline: [null, '2026-11-20'] } }),
            entry(2, {
              user: null,
              action: 'project.status',
              changes: { status: ['completed', 'archived'] },
              money: { changes: { rate_rub: ['2800', '3000'] } },
            }),
          ],
          next_cursor: 'p2',
        });
      }),
    );
    renderApp(`/projects/${id}/log`);
    const section = await screen.findByRole('region', { name: 'Журнал проекта' });
    await within(section).findByText('Изменены настройки');
    expect(within(section).getByText('Управление проектом, %:')).toBeTruthy();
    expect(within(section).getByText(/15 → 18/)).toBeTruthy();
    expect(within(section).getByText(/— → 2026-11-20/)).toBeTruthy();
    expect(within(section).getByText('Система')).toBeTruthy();
    expect(within(section).getByText(/Завершена → Архив/)).toBeTruthy();
    expect(
      within(section)
        .getByText(/2800 → 3000/)
        .closest('.journal-changes')?.className,
    ).toContain('money');
    expect(screen.getByRole('link', { name: 'Журнал проекта' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(within(section).getByRole('button', { name: 'Показать ещё' }));
    await within(section).findByText('Проект создан');
    await waitFor(() => expect(within(section).queryByRole('button', { name: 'Показать ещё' })).toBeNull());
  });

  it('пустой журнал — подсказка', async () => {
    persona.current = PERSONAS.expert;
    server.use(http.get(api('/projects/:id/journal'), () => HttpResponse.json({ items: [], next_cursor: null })));
    renderApp(`/projects/${id}/log`);
    await screen.findByText('Изменений пока нет');
  });
});
