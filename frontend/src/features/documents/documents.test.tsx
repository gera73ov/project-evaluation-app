/** FE-017 · документы заказчика (11.7): правила файла, права, «проверяется», «заражён», загрузка, удаление, WS. */
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { PROJECTS, userRef } from '../../shared/api/mocks/data';
import { uploadDocument } from '../../shared/api/mocks/demoDocuments';
import { uuidFrom } from '../../shared/api/mocks/ids';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { FakeSocket } from '../../test/fakeSocket';
import { persona, server } from '../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../test/render';
import { checkFile, docLabels, fileKind, formatSize } from './DocumentsPage';

const portal = PROJECTS.portal;

describe('правила вкладки', () => {
  it('формат по расширению; макросы не принимаются', () => {
    expect(fileKind('ТЗ.PDF')).toBe('pdf');
    expect(fileKind('Реестр.xlsx')).toBe('xlsx');
    expect(fileKind('Макрос.docm')).toBeNull();
    expect(fileKind('без расширения')).toBeNull();
  });

  it('до отправки: тип, пустой файл, больше 50 МБ', () => {
    expect(checkFile({ name: 'a.xlsm', size: 10 })).toBe('type');
    expect(checkFile({ name: 'a.pdf', size: 0 })).toBe('empty');
    expect(checkFile({ name: 'a.pdf', size: 50 * 1024 * 1024 + 1 })).toBe('size');
    expect(checkFile({ name: 'a.pdf', size: 50 * 1024 * 1024 })).toBeNull();
  });

  it('размер в МБ с одним знаком, лимит в ГБ; ссылки #doc-N по порядку загрузки', () => {
    const plain = (s: string) => s.replace(/\s/g, ' ');
    expect(plain(formatSize(Math.round(4.2 * 1024 * 1024)))).toBe('4,2 МБ');
    expect(plain(formatSize(300 * 1024))).toBe('0,3 МБ');
    expect(plain(formatSize(1024 * 1024 * 1024))).toBe('1 ГБ');
    const doc = (id: string, at: string) => ({ id, uploaded_at: at }) as Parameters<typeof docLabels>[0][number];
    expect([...docLabels([doc('b', '2026-11-02'), doc('a', '2026-11-01')])]).toEqual([
      ['a', '#doc-1'],
      ['b', '#doc-2'],
    ]);
  });
});

const calls: { method: string; path: string }[] = [];
afterEach(() => {
  server.events.removeAllListeners();
  calls.length = 0;
});

async function openDocs(who: 'expert' | 'moderator' | 'presale_head', ws = false) {
  persona.current = new Map(Object.entries(PERSONAS)).get(who) ?? PERSONAS.expert;
  server.events.on('request:start', ({ request }) => {
    if (request.method !== 'GET') calls.push({ method: request.method, path: new URL(request.url).pathname });
  });
  FakeSocket.all = [];
  renderApp(
    `/projects/${portal.id}/settings/documents`,
    ws ? { createSocket: FakeSocket.factory, backoff: () => 10 } : undefined,
  );
  const table = await screen.findByRole('table');
  await within(table).findByText('ТЗ_портал_дилеров_v3.pdf');
  return table;
}

const rowOf = (table: HTMLElement, name: string) => within(table).getByText(name).closest('tr') as HTMLElement;

describe('вкладка «Документы заказчика»', () => {
  it('эксперт: скачивает проверенное, не загружает и не удаляет', async () => {
    const table = await openDocs('expert');
    expect(screen.queryByText(/Перетащите файл сюда/)).toBeNull();
    expect(screen.queryByRole('button', { name: /^Удалить / })).toBeNull();
    const clean = rowOf(table, 'ТЗ_портал_дилеров_v3.pdf');
    expect((within(clean).getByRole('button', { name: /^Скачать/ }) as HTMLButtonElement).disabled).toBe(false);
    expect(within(clean).getByText('#doc-1')).toBeTruthy();
    const pending = rowOf(table, 'Требования_ИБ_заказчика.docx');
    expect(within(pending).getByText('⟳ проверяется')).toBeTruthy();
    expect((within(pending).getByRole('button', { name: /^Скачать/ }) as HTMLButtonElement).disabled).toBe(true);
    const infected = rowOf(table, 'Презентация_заказчика.docx');
    expect(infected.className).toContain('row-error');
    expect(within(infected).getByText('недоступен')).toBeTruthy();
    expect(within(infected).queryByRole('button')).toBeNull();
    expect(screen.getByText('Кто что может')).toBeTruthy();
    // заражённый файл не занимает место: 4,2 + 0,3 + 1,1 МБ
    expect(screen.getByRole('progressbar').parentElement?.textContent?.replace(/\s/g, ' ')).toContain('5,6 МБ из 1 ГБ');
  });

  it('руководитель пресейла только скачивает', async () => {
    await openDocs('presale_head');
    expect(screen.queryByText(/Перетащите файл сюда/)).toBeNull();
    expect(screen.queryByRole('button', { name: /^Удалить / })).toBeNull();
  });

  it('модератор: неверный файл не уходит, PDF загружается и «проверяется»', async () => {
    const table = await openDocs('moderator');
    const input = screen.getByLabelText('Файл для загрузки');
    fireEvent.change(input, { target: { files: [new File(['x'], 'Смета.xlsm')] } });
    expect(await screen.findByText('Можно загрузить только PDF, DOCX или XLSX без макросов.')).toBeTruthy();
    expect(calls).toHaveLength(0);
    // jsdom теряет имя файла в multipart (undici видит Blob), поэтому ответ загрузки — из демо напрямую
    server.use(
      http.post(api('/projects/:id/documents'), () =>
        HttpResponse.json(
          uploadDocument(
            portal,
            { file: { file_name: 'Протокол встречи.pdf', size_bytes: 8 } },
            userRef(PERSONAS.moderator),
          ),
          { status: 201 },
        ),
      ),
    );
    fireEvent.change(input, { target: { files: [new File(['%PDF-1.4'], 'Протокол встречи.pdf')] } });
    await waitFor(() => expect(within(rowOf(table, 'Протокол встречи.pdf')).getByText('⟳ проверяется')).toBeTruthy());
    expect(calls).toEqual([{ method: 'POST', path: `/api/v1/projects/${portal.id}/documents` }]);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('модератор: удаление через подтверждение — в корзину', async () => {
    const table = await openDocs('moderator');
    fireEvent.click(within(table).getByRole('button', { name: 'Удалить Реестр_интеграций.xlsx' }));
    const dialog = await screen.findByRole('dialog', { name: 'Удалить документ?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }));
    await waitFor(() => expect(within(table).queryByText('Реестр_интеграций.xlsx')).toBeNull());
    expect(calls.at(-1)).toEqual({
      method: 'DELETE',
      path: `/api/v1/documents/${uuidFrom('document', 'portal', 'registry')}`,
    });
    expect(screen.getByRole('status').textContent).toContain('в корзине');
  });

  it('document.scanned перечитывает список', async () => {
    let lists = 0;
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'GET' && new URL(request.url).pathname.endsWith('/documents')) lists += 1;
    });
    await openDocs('expert', true);
    const before = lists;
    await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0));
    act(() => FakeSocket.last().open());
    await waitFor(() => expect(FakeSocket.last().sent.some((c) => c.op === 'subscribe')).toBe(true));
    act(() => FakeSocket.last().ack('subscribe', { project_version: 1, channels: [], resync: false }));
    act(() =>
      FakeSocket.last().push({
        type: 'event',
        event: 'document.scanned',
        channel: `project:${portal.id}`,
        ts: new Date().toISOString(),
        data: { document_id: uuidFrom('document', 'portal', 'sec-req'), scan_status: 'clean' },
      }),
    );
    await waitFor(() => expect(lists).toBeGreaterThan(before));
  });
});
