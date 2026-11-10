/** FE-072 · производственный календарь: исключения из Пн–Пт, ручная правка, CSV с предпросмотром. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { parseCsv, upload } from '../../../shared/api/mocks/demoCalendar';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../../test/render';
import { exceptionsOf, isWorking, monthWeeks, toggle, workingDays } from './calendar';

const CSV = [
  'Год/Месяц,Январь,Февраль,Март,Апрель,Май,Июнь,Июль,Август,Сентябрь,Октябрь,Ноябрь,Декабрь,Всего рабочих дней',
  '2027,"1,2,3,4,5,6,7,8,9,10,16,17,23,24,30,31","6,7,13,14,21,22*,23+,27,28","6,7,8,13,14,20,21,27,28","3,4,10,11,17,18,24,25","1,2,8,9,10,15,16,22,23,29,30","5,6,12,13,14,19,20,26,27","3,4,10,11,17,18,24,25,31","1,7,8,14,15,21,22,28,29","4,5,11,12,18,19,25,26","2,3,9,10,16,17,23,24,30,31","3*,4,6,7,13,14,20,21,27,28","4,5,11,12,18,19,25,26,31",247',
].join('\n');

describe('правила календаря', () => {
  it('исключения из Пн–Пт: праздник в будни, рабочая суббота; щелчок возвращает к норме', () => {
    const ex = exceptionsOf([
      { date: '2026-01-05', is_working: false },
      { date: '2026-01-03', is_working: false }, // суббота и так выходной — не исключение
    ]);
    expect([...ex.keys()]).toEqual(['2026-01-05']);
    expect(isWorking(ex, '2026-01-05')).toBe(false);
    expect(isWorking(ex, '2026-01-12')).toBe(true);
    const sat = toggle(ex, '2026-03-07');
    expect(sat.get('2026-03-07')).toBe(true);
    expect(toggle(sat, '2026-03-07').has('2026-03-07')).toBe(false);
    expect(toggle(ex, '2026-01-05').size).toBe(0);
    expect(workingDays(ex, 2026, 1)).toBe(21);
  });

  it('недели месяца начинаются с понедельника', () => {
    const weeks = monthWeeks(2026, 11); // 1 ноября 2026 — воскресенье
    expect(weeks[0]).toEqual([null, null, null, null, null, null, '2026-11-01']);
    expect(weeks.every((w) => w.length === 7)).toBe(true);
  });

  it('CSV data.gov.ru: «*» — сокращённый рабочий день, «+» — перенесённый выходной', () => {
    const parsed = parseCsv(CSV);
    expect(parsed?.year).toBe(2027);
    const ex = exceptionsOf(parsed?.days ?? []);
    expect(isWorking(ex, '2027-02-22')).toBe(true); // «22*» — сокращённый, рабочий
    expect(isWorking(ex, '2027-02-23')).toBe(false); // «23+»
    expect(isWorking(ex, '2027-11-03')).toBe(true);
    expect(isWorking(ex, '2027-11-04')).toBe(false);
    expect(parseCsv('просто текст')).toBeNull();
    expect(parseCsv('2027,"40"')).toBeNull();
  });
});

describe('экран «Производственный календарь»', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-05T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  it('правка дня щелчком сохраняется', async () => {
    persona.current = PERSONAS.admin;
    renderApp('/admin/calendar');
    expect(await screen.findByText('Календарь загружен')).toBeTruthy();
    const march = screen.getByRole('region', { name: 'Март 2026' });
    expect(within(march).getByText('21 рабочий')).toBeTruthy(); // 9 марта — праздник
    fireEvent.click(within(march).getByRole('button', { name: '7 марта, нерабочий' }));
    expect(within(march).getByText('22 рабочих')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить правки' }));
    expect(await screen.findByText('✓ Правки календаря сохранены')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Сохранить правки' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('CSV: предпросмотр по месяцам, затем сохранение', async () => {
    // jsdom теряет содержимое файла в multipart — ответ строится из демо напрямую
    let call = 0;
    server.use(
      http.post(api('/admin/calendar'), () => {
        call += 1;
        return HttpResponse.json(upload({ file: { file_name: 'cal.csv', text: CSV }, dry_run: call === 1 }));
      }),
    );
    persona.current = PERSONAS.admin;
    renderApp('/admin/calendar');
    await screen.findByText('Календарь загружен');
    fireEvent.change(screen.getByLabelText('Файл CSV календаря'), {
      target: { files: [new File([CSV], 'calendar.csv', { type: 'text/csv' })] },
    });
    const preview = await screen.findByRole('region', { name: 'Предпросмотр календаря 2027 года' });
    const feb = within(preview).getByText('Февраль').closest('tr') as HTMLElement;
    expect(within(feb).getByText('23')).toBeTruthy();
    fireEvent.click(within(preview).getByRole('button', { name: 'Сохранить календарь 2027' }));
    expect(await screen.findByText('✓ Календарь 2027 года сохранён')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('region', { name: 'Февраль 2027' })).toBeTruthy());
    expect(call).toBe(2);
  });
});
