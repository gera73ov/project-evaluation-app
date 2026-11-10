/** FE-072 · «Предложенные типы»: добавить в словарь, объединить, отклонить. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona } from '../../../test/setup';
import { renderApp } from '../../../test/render';

describe('экран «Предложенные типы»', () => {
  it('«Добавить» переносит тип в словарь, «Отклонить» — убирает из списка', async () => {
    persona.current = PERSONAS.admin;
    renderApp('/admin/proposed-types');
    const table = within(await screen.findByRole('table'));
    expect(table.getByText('Шлюз оплаты')).toBeTruthy();
    fireEvent.click(table.getByRole('button', { name: 'Добавить «Шлюз оплаты» в словарь' }));
    expect(await screen.findByText('✓ «Шлюз оплаты» добавлен в словарь типов')).toBeTruthy();
    await waitFor(() => expect(table.queryByText('Шлюз оплаты')).toBeNull());

    fireEvent.click(table.getByRole('button', { name: 'Отклонить «Регламентный отчёт»' }));
    const dialog = await screen.findByRole('dialog', { name: /Отклонить «Регламентный отчёт»/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отклонить' }));
    expect(await screen.findByText('Новых предложенных типов нет')).toBeTruthy();
  });

  it('«Объединить с…»: без выбора типа объединить нельзя', async () => {
    persona.current = PERSONAS.admin;
    renderApp('/admin/proposed-types');
    const table = within(await screen.findByRole('table'));
    fireEvent.click(table.getByRole('button', { name: 'Объединить с типом словаря «Регламентный отчёт»' }));
    const dialog = await screen.findByRole('dialog', { name: 'Объединить «Регламентный отчёт»' });
    expect(within(dialog).getByText('5 узлов проекта получат выбранный тип словаря.')).toBeTruthy();
    expect((within(dialog).getByRole('button', { name: 'Объединить' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole('textbox', { name: 'Тип словаря' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Отчёт' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Объединить' }));
    expect(await screen.findByText('✓ «Регламентный отчёт» объединён с «Отчёт»: 5 узлов перепривязаны')).toBeTruthy();
  });
});
