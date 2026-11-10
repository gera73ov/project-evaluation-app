/** FE-071 · «Справочники»: правила неудаляемых записей, сквозная фаза, ставка по умолчанию, пороги. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import {
  currencyLocks,
  hoursValid,
  nodeTypeLocks,
  pctValid,
  phaseLocks,
  profileLocks,
  vatLocks,
  type Discipline,
  type NodeType,
  type Phase,
  type Profile,
  type VatRate,
} from './dictionaries';
import { methodErrors } from './MethodForm';
import { normValid, ratioValid } from './kinds';

async function open(path = '/admin/dictionaries') {
  persona.current = PERSONAS.admin;
  renderApp(path);
  await screen.findAllByRole('table');
  // первая таблица — список; в форме типа узла есть ещё таблица норм
  return () => within(screen.getAllByRole('table')[0]!);
}

const form = () => screen.getByRole('heading', { level: 3 }).closest('.adm-dict-form') as HTMLElement;
const button = (name: string | RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement;
const checkbox = (name: string | RegExp) => screen.getByRole('checkbox', { name }) as HTMLInputElement;

describe('правила справочников', () => {
  it('сквозная фаза, «Работа», RUB, «Без НДС», ставка и профиль по умолчанию — не удаляются', () => {
    expect(phaseLocks({ is_cross_cutting: true } as Phase).noDelete).toBe('crossCutting');
    expect(phaseLocks({ is_cross_cutting: false } as Phase).noDelete).toBeNull();
    expect(nodeTypeLocks({ is_system: true } as NodeType).pill).toBe('system');
    expect(currencyLocks({ code: 'RUB', symbol: '₽', is_active: true }).noDeactivate).toBe('rub');
    expect(currencyLocks({ code: 'USD', symbol: '$', is_active: true }).noDelete).toBeNull();
    expect(vatLocks({ percent: null, is_default: false } as VatRate).noDelete).toBe('noVat');
    expect(vatLocks({ percent: '22', is_default: true } as VatRate).noDelete).toBe('defaultVat');
    expect(vatLocks({ percent: '10', is_default: false } as VatRate).pill).toBeNull();
    const d = [{ id: 'd', default_profile_id: 'p1' }] as Discipline[];
    expect(profileLocks({ id: 'p1' } as Profile, d).pill).toBe('default');
    expect(profileLocks({ id: 'p2' } as Profile, d).noDelete).toBeNull();
  });

  it('проценты, часы, нормы O ≤ R ≤ P и соотношения', () => {
    expect(pctValid('25')).toBe(true);
    expect(pctValid('12,5')).toBe(true);
    expect(pctValid('100.01')).toBe(false);
    expect(pctValid('1e2')).toBe(false);
    expect(hoursValid('99999.5')).toBe(true);
    expect(hoursValid('100000')).toBe(false);
    expect(normValid({ label: 'Простой', o: '2', r: '4', p: '8' })).toBe(true);
    expect(normValid({ label: 'Простой', o: '8', r: '4', p: '2' })).toBe(false);
    expect(normValid({ label: ' ', o: '2', r: '4', p: '8' })).toBe(false);
    expect(ratioValid({ a: 'qa', b: ['be'], min: '25', max: '35' })).toBe(true);
    expect(ratioValid({ a: 'qa', b: ['qa'], min: '25', max: '35' })).toBe(false);
    expect(ratioValid({ a: 'qa', b: ['be'], min: '40', max: '35' })).toBe(false);
  });

  it('пороги: УП шагом 0,5 до 50, единицы «от» ≤ «до»', () => {
    const ok = { medium: '80', detailed: '40', min: '5', max: '15', pm: '18', archive: '180' };
    expect(Object.values(methodErrors(ok)).some(Boolean)).toBe(false);
    expect(methodErrors({ ...ok, pm: '17.3' }).pm).toBe(true);
    expect(methodErrors({ ...ok, pm: '50.5' }).pm).toBe(true);
    expect(methodErrors({ ...ok, pm: '12,5' }).pm).toBe(false);
    expect(methodErrors({ ...ok, min: '20' }).max).toBe(true);
    expect(methodErrors({ ...ok, archive: '0' }).archive).toBe(false);
    expect(methodErrors({ ...ok, medium: '0' }).medium).toBe(true);
  });
});

describe('экран «Справочники»', () => {
  it('сквозная фаза: без «Удалить», признак переносится отметкой у другой фазы', async () => {
    const table = await open();
    fireEvent.click(table().getByRole('button', { name: 'Управление проектом' }));
    expect(within(form()).getByText('сквозная')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull();
    expect(checkbox(/^Сквозная/).disabled).toBe(true);
    expect(checkbox('Активна').disabled).toBe(true);
    expect(screen.getByText(/Сквозная фаза одна/)).toBeTruthy();

    fireEvent.click(table().getByRole('button', { name: 'Разработка' }));
    fireEvent.click(checkbox(/^Сквозная/));
    fireEvent.click(button('Сохранить'));
    expect(await screen.findByText('✓ Сохранено')).toBeTruthy();
    await waitFor(() => expect(table().getAllByText('сквозная')).toHaveLength(1));
    const row = table().getByRole('button', { name: 'Разработка' }).closest('tr') as HTMLElement;
    expect(within(row).getByText('сквозная')).toBeTruthy();
  });

  it('новая фаза удаляется, фаза из проектов — нет: сервер отвечает «используется»', async () => {
    const table = await open();
    fireEvent.click(button('+ Добавить'));
    fireEvent.change(screen.getByRole('textbox', { name: /^Название/ }), { target: { value: 'Опытная эксплуатация' } });
    fireEvent.click(button('Создать'));
    expect(await screen.findByText('✓ Сохранено')).toBeTruthy();
    expect(await table().findByRole('button', { name: 'Опытная эксплуатация' })).toBeTruthy();
    fireEvent.click(button('Удалить'));
    const dialog = await screen.findByRole('dialog', { name: /^Удалить «Опытная эксплуатация»/ });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }));
    await waitFor(() => expect(table().queryByRole('button', { name: 'Опытная эксплуатация' })).toBeNull());

    fireEvent.click(table().getByRole('button', { name: 'Тестирование' }));
    fireEvent.click(button('Удалить'));
    const again = await screen.findByRole('dialog', { name: /^Удалить «Тестирование»/ });
    fireEvent.click(within(again).getByRole('button', { name: 'Удалить' }));
    expect(await screen.findByText('Запись используется. Её можно только сделать неактивной.')).toBeTruthy();
  });

  it('тип «Работа» — системный; новый тип с нормой', async () => {
    const table = await open('/admin/dictionaries/node-types');
    fireEvent.click(table().getByRole('button', { name: /Работа/ }));
    expect(within(form()).getByText('системная')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull();
    expect(checkbox('Активна').disabled).toBe(true);

    fireEvent.click(button('+ Добавить'));
    fireEvent.change(screen.getByRole('textbox', { name: /^Название/ }), { target: { value: 'Отчёт BI' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Отчёт' }));
    fireEvent.click(button('+ Норма'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Вариант 1' }), { target: { value: 'Простой' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'O 1' }), { target: { value: '8' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'R 1' }), { target: { value: '4' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'P 1' }), { target: { value: '16' } });
    expect(button('Создать').disabled).toBe(true); // O > R
    fireEvent.change(screen.getByRole('textbox', { name: 'R 1' }), { target: { value: '12' } });
    fireEvent.click(button('Создать'));
    expect(await screen.findByText('✓ Сохранено')).toBeTruthy();
    expect(await table().findByText('Простой 8–12–16')).toBeTruthy();
  });

  it('ставки НДС: «Без НДС» не удалить, ставка по умолчанию переходит к другой', async () => {
    const table = await open('/admin/dictionaries/vat-rates');
    fireEvent.click(table().getByRole('button', { name: 'Без НДС' }));
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull();
    expect(screen.queryByRole('textbox', { name: /Процент/ })).toBeNull();
    expect(screen.getByText('«Без НДС» нельзя удалить или отключить.')).toBeTruthy();

    fireEvent.click(table().getByRole('button', { name: 'НДС 20%' }));
    fireEvent.click(checkbox(/^По умолчанию/));
    fireEvent.click(button('Сохранить'));
    expect(await screen.findByText('✓ Сохранено')).toBeTruthy();
    await waitFor(() => {
      const row = table().getByRole('button', { name: 'НДС 22%' }).closest('tr') as HTMLElement;
      expect(within(row).queryByText('по умолчанию')).toBeNull();
    });
    expect(checkbox(/^По умолчанию/).disabled).toBe(true);
  });

  it('валюты: RUB системная, код повторить нельзя', async () => {
    const table = await open('/admin/dictionaries/currencies');
    fireEvent.click(table().getByRole('button', { name: 'RUB' }));
    expect(within(form()).getByText('системная')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull();
    fireEvent.click(button('+ Добавить'));
    const code = screen.getByRole('textbox', { name: /^Код/ });
    fireEvent.change(code, { target: { value: 'usd' } });
    expect((code as HTMLInputElement).value).toBe('USD');
    fireEvent.click(button('Создать'));
    expect(await screen.findByRole('alert')).toBeTruthy();
    fireEvent.change(code, { target: { value: 'GBP' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Символ' }), { target: { value: '£' } });
    fireEvent.click(button('Создать'));
    expect(await table().findByRole('button', { name: 'GBP' })).toBeTruthy();
  });

  it('пороги и проценты: неверный % УП не сохранить, верный — сохраняется', async () => {
    persona.current = PERSONAS.admin;
    renderApp('/admin/dictionaries/method');
    const pm = await screen.findByRole('textbox', { name: /% УП по умолчанию/ });
    expect((pm as HTMLInputElement).value).toBe('18');
    fireEvent.change(pm, { target: { value: '17,3' } });
    expect(screen.getByText('От 0 до 50 с шагом 0,5')).toBeTruthy();
    expect(button('Сохранить').disabled).toBe(true);
    fireEvent.change(pm, { target: { value: '12,5' } });
    fireEvent.click(button('Сохранить'));
    expect(await screen.findByText('✓ Сохранено')).toBeTruthy();
    await waitFor(() => expect((screen.getByRole('textbox', { name: /% УП/ }) as HTMLInputElement).value).toBe('12,5'));
  });
});
