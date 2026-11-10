/** FE-073 · реестр проектов администратора, «Передать / добавить модератора», режим поддержки. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { canModerate, minutesLeft, reasonValid } from './registry';

async function open() {
  persona.current = PERSONAS.admin;
  renderApp('/admin/registry');
  await screen.findByRole('table');
  return () => within(screen.getByRole('table'));
}

const rowOf = (table: () => ReturnType<typeof within>, name: string) =>
  table().getByText(name).closest('tr') as HTMLElement;

describe('правила реестра', () => {
  it('модератором — активный «Модератор» или «Руководитель пресейла»; причина 10–500; минуты сессии', () => {
    const roles = (r: string) => [{ role: r as 'moderator', source: 'manual' as const }];
    expect(canModerate({ status: 'active', system_roles: roles('moderator') })).toBe(true);
    expect(canModerate({ status: 'active', system_roles: roles('presale_head') })).toBe(true);
    expect(canModerate({ status: 'active', system_roles: roles('presale') })).toBe(false);
    expect(canModerate({ status: 'blocked', system_roles: roles('moderator') })).toBe(false);
    expect(reasonValid('коротко')).toBe(false);
    expect(reasonValid('  Проверка расчёта P80  ')).toBe(true);
    expect(reasonValid('я'.repeat(501))).toBe(false);
    const now = Date.parse('2026-11-05T12:00:00Z');
    expect(minutesLeft('2026-11-05T12:59:00Z', now)).toBe(59);
    expect(minutesLeft('2026-11-05T12:00:30Z', now)).toBe(1);
    expect(minutesLeft('2026-11-05T11:59:00Z', now)).toBe(0);
  });
});

describe('экран «Реестр проектов»', () => {
  it('фильтр «Проекты без модератора» и назначение модератора', async () => {
    const table = await open();
    expect(within(rowOf(table, 'Миграция CRM')).getByText('без модератора 12 дней')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Проекты без модератора' }));
    await waitFor(() => expect(table().queryByText('Портал дилеров')).toBeNull());
    expect(table().getAllByRole('row')).toHaveLength(3); // шапка и два проекта

    fireEvent.click(screen.getByRole('button', { name: 'Передать или добавить модератора «Миграция CRM»' }));
    const dialog = await screen.findByRole('dialog', { name: /Модераторы проекта «Миграция CRM»/ });
    expect(within(dialog).getByText('Проект нельзя оставить без модератора.')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('textbox', { name: /Добавить модератора/ }));
    expect(screen.queryByRole('option', { name: /П\. Сидоров/ })).toBeNull(); // пресейл без роли модератора
    fireEvent.click(await screen.findByRole('option', { name: /А\. Смирнова/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(table().queryByText('Миграция CRM')).toBeNull());
  });

  it('снять единственного модератора без замены нельзя', async () => {
    const table = await open();
    fireEvent.click(screen.getByRole('button', { name: 'Передать или добавить модератора «Портал дилеров»' }));
    const dialog = await screen.findByRole('dialog', { name: /Модераторы проекта «Портал дилеров»/ });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'А. Смирнова' }));
    expect(within(dialog).getByText('Проект нельзя оставить без модератора.')).toBeTruthy();
    expect((within(dialog).getByRole('button', { name: 'Сохранить' }) as HTMLButtonElement).disabled).toBe(true);
    expect(rowOf(table, 'Портал дилеров')).toBeTruthy();
  });

  it('режим поддержки: причина обязательна, проект открывается на чтение с жёлтой полосой и без денег', async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть «Портал дилеров» в режиме поддержки' }));
    const dialog = await screen.findByRole('dialog', { name: /Режим поддержки: «Портал дилеров»/ });
    const button = within(dialog).getByRole('button', { name: 'Открыть проект' }) as HTMLButtonElement;
    fireEvent.change(within(dialog).getByRole('textbox', { name: /Причина/ }), { target: { value: 'Проверка' } });
    expect(button.disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole('textbox', { name: /Причина/ }), {
      target: { value: 'Заказчик не видит итог P80' },
    });
    fireEvent.click(button);
    const bar = await screen.findByText(/Режим поддержки · только чтение/, {}, { timeout: 5000 });
    expect(bar.textContent).toMatch(/осталось 60 мин · причина: Заказчик не видит итог P80/);
    expect(window.location.pathname).toBe(`/projects/${PROJECTS.portal.id}`);
    expect(document.querySelector('.money')).toBeNull();
    expect(screen.queryByRole('tab', { name: /Заметки/ })).toBeNull();
  });

  it('без сессии поддержки чужой проект администратору не открывается', async () => {
    persona.current = PERSONAS.admin;
    renderApp(`/projects/${PROJECTS.portal.id}`);
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.queryByText(/Режим поддержки/)).toBeNull();
  });
});
