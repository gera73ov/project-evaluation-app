/** FE-030 · обсуждения под строкой: лента, «Показать всё», @, «нужен ответ», правка, отзыв, «Решено». */
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS, disciplineId } from '../../shared/api/mocks/data';
import { uuidFrom } from '../../shared/api/mocks/ids';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { renderApp } from '../../test/render';
import { canEditMessage, eventParts, feedEntries, keptAddressees, mentionAt, type Message, type Thread } from './feed';

const msg = (id: string, fields: Partial<Message> = {}): Message => ({
  id,
  thread_id: null,
  node_id: 'n',
  author: { id: 'u1', full_name: 'А', initials: 'А', is_active: true },
  kind: 'message',
  body: id,
  event: null,
  needs_answer: false,
  addressees: [],
  created_at: `2026-11-01T10:0${id.length}:00Z`,
  edited_at: null,
  revoked: false,
  ...fields,
});

describe('правила ленты', () => {
  it('закрытый вопрос сворачивается в одну строку на месте первого сообщения', () => {
    const q = msg('q', { thread_id: 't', needs_answer: true });
    const a = msg('a', { thread_id: 't', body: 'вывод' });
    const thread = { id: 't', status: 'resolved', first_message: q } as unknown as Thread;
    const entries = feedEntries([msg('x'), q, msg('e', { kind: 'event' }), a], [thread]);
    expect(entries.map((e) => e.kind)).toEqual(['message', 'resolved', 'event']);
    expect(entries[1]?.kind === 'resolved' && entries[1].last?.body).toBe('вывод');
  });

  it('своё сообщение правится, пока после него не написал другой', () => {
    const mine = msg('m');
    const other = msg('o', { author: { id: 'u2', full_name: 'Б', initials: 'Б', is_active: true } });
    expect(canEditMessage(mine, [mine, msg('e', { kind: 'event', author: other.author })], 'u1')).toBe(true);
    expect(canEditMessage(mine, [mine, other], 'u1')).toBe(false);
    expect(canEditMessage(mine, [mine], 'u2')).toBe(false);
  });

  it('событие: вилка O/R/P целиком и частично, ×N, комментарий', () => {
    const ev = (changes: object) =>
      msg('e', { kind: 'event', event: { action: 'update', changes } as unknown as Message['event'] });
    expect(eventParts(ev({ o: ['30', '40'], r: ['40', '60'], p: ['60', '100'] }))).toEqual([
      { label: 'orp', before: '30–40–60', after: '40–60–100' },
    ]);
    expect(eventParts(ev({ r: ['12', '16'] }))[0]).toEqual({ label: 'orp', before: '·–12–·', after: '·–16–·' });
    expect(eventParts(ev({ multiplier: [1, 3], comment: ['', 'x'] })).map((p) => p.label)).toEqual([
      'multiplier',
      'comment',
    ]);
  });

  it('@ перед курсором и адресаты, оставшиеся в тексте', () => {
    expect(mentionAt('Вопрос @Бэк', 11)).toEqual({ query: 'Бэк', from: 7 });
    expect(mentionAt('почта a@b', 9)).toBeNull();
    expect(mentionAt('@Бэкенд готово', 14)).toBeNull();
    const backend = { addressee: { target_type: 'discipline' as const, target_id: 'd' }, label: 'Бэкенд' };
    const customer = { addressee: { target_type: 'customer' as const, target_id: null }, label: 'заказчик' };
    expect(keptAddressees('@Бэкенд, глянь', [backend, customer, backend])).toEqual([backend.addressee]);
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

const portal = PROJECTS.portal;

async function openDiscussion(who: 'expert' | 'moderator' = 'expert', title = 'Обмен с 1С') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  const calls: { method: string; path: string; body: unknown }[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET') return;
    const entry = { method: request.method, path: new URL(request.url).pathname, body: null as unknown };
    calls.push(entry);
    void request
      .clone()
      .json()
      .then((b) => (entry.body = b))
      .catch(() => undefined);
  });
  renderApp(`/projects/${portal.id}`);
  const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
  const row = (await within(grid).findByText(title)).closest('[role="row"]') as HTMLElement;
  fireEvent.click(within(row).getByRole('button', { name: /^(Обсуждение|Начать обсуждение)/ }));
  const panel = await screen.findByRole('region', { name: `Обсуждение: ${title}` });
  return { panel, calls, input: within(panel).getByRole('combobox', { name: 'Сообщение' }) };
}

describe('обсуждение под строкой', () => {
  it('шапка вопроса, последние 3 записи и «Показать всё (5)»', async () => {
    const { panel } = await openDiscussion();
    await within(panel).findByText('Открытый вопрос');
    expect(panel.textContent).toContain('адресат @заказчик');
    expect(panel.textContent).toContain('статус «отвечен»');
    const feed = within(panel).getByRole('list');
    expect(within(feed).getAllByRole('listitem')).toHaveLength(3);
    expect(feed.textContent).toContain('изменено: O/R/P 30–40–60 → 40–60–100');
    expect(within(feed).getByText('Ответ заказчика')).toBeTruthy();
    fireEvent.click(within(panel).getByRole('button', { name: 'Показать всё (5)' }));
    await waitFor(() => expect(within(feed).getAllByRole('listitem')).toHaveLength(5));
    expect(feed.textContent).toContain('Есть ли у заказчика готовый API');
  });

  it('ответ по Ctrl+Enter уходит в открытый вопрос; HTML показывается как текст', async () => {
    const { panel, calls, input } = await openDiscussion();
    await within(panel).findByText('Открытый вопрос');
    fireEvent.change(input, { target: { value: 'Ок, <b>берём</b> REST' } });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    await waitFor(() =>
      expect(calls.at(-1)).toEqual({
        method: 'POST',
        path: `/api/v1/threads/${uuidFrom('thread', 'portal', '1c-protocol')}/messages`,
        body: { body: 'Ок, <b>берём</b> REST', needs_answer: false, addressees: [] },
      }),
    );
    expect(await within(panel).findByText('Ок, <b>берём</b> REST')).toBeTruthy();
    expect(panel.querySelector('b b, .msg-body b')).toBeNull();
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('@ с автодополнением и «нужен ответ» открывают вопрос дисциплине', async () => {
    const { panel, calls, input } = await openDiscussion('expert', 'Авторизация');
    await within(panel).findByText(/Сообщений пока нет/);
    fireEvent.change(input, { target: { value: 'Проверьте @Бэ', selectionStart: 13 } });
    const list = await screen.findByRole('listbox', { name: 'Адресаты' });
    expect(within(list).getByRole('option', { name: /@Бэкенд/ })).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe('Проверьте @Бэкенд '));
    fireEvent.click(within(panel).getByRole('checkbox', { name: 'нужен ответ' }));
    fireEvent.click(within(panel).getByRole('button', { name: 'Отправить' }));
    await waitFor(() =>
      expect(calls.at(-1)?.body).toEqual({
        body: 'Проверьте @Бэкенд',
        needs_answer: true,
        addressees: [{ target_type: 'discipline', target_id: disciplineId('d-backend') }],
      }),
    );
    expect(calls.at(-1)?.path).toMatch(/^\/api\/v1\/nodes\/.+\/messages$/);
    await within(panel).findByText('Открытый вопрос');
    expect(panel.textContent).toContain('адресат @Бэкенд');
  });

  it('своё сообщение: правка с меткой «изменено», отзыв с пометкой', async () => {
    const { panel, calls, input } = await openDiscussion('expert', 'Авторизация');
    fireEvent.change(input, { target: { value: 'черновик' } });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    await within(panel).findByText('черновик');
    fireEvent.click(within(panel).getByRole('button', { name: 'Изменить' }));
    const edit = within(panel).getByRole('textbox', { name: 'Текст сообщения' });
    fireEvent.change(edit, { target: { value: 'чистовик' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Сохранить' }));
    await within(panel).findByText('чистовик');
    expect(calls.at(-1)?.method).toBe('PATCH');
    expect(panel.textContent).toContain('изменено');
    fireEvent.click(within(panel).getByRole('button', { name: 'Отозвать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Отозвать сообщение?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отозвать' }));
    await within(panel).findByText('Сообщение отозвано автором');
    expect(calls.at(-1)?.path).toMatch(/\/revoke$/);
    expect(within(panel).queryByText('чистовик')).toBeNull();
  });

  it('модератор: «Решено ▾» → вывод в комментарий с последним сообщением; вопрос сворачивается', async () => {
    const { panel, calls } = await openDiscussion('moderator');
    await within(panel).findByText('Открытый вопрос');
    fireEvent.click(within(panel).getByRole('button', { name: 'Решено ▾' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /Решено и добавить вывод/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Вывод в комментарий листа' });
    const text = within(dialog).getByRole('textbox', { name: 'Текст вывода' });
    expect((text as HTMLTextAreaElement).value).toBe('REST. Спецификации пока нет, обещают в декабре.');
    await act(async () => {
      fireEvent.click(within(dialog).getByRole('button', { name: 'Решено' }));
    });
    await waitFor(() =>
      expect(calls.at(-1)).toEqual({
        method: 'POST',
        path: `/api/v1/threads/${uuidFrom('thread', 'portal', '1c-protocol')}/resolve`,
        body: { conclusion: { text: 'REST. Спецификации пока нет, обещают в декабре.', tag_id: null } },
      }),
    );
    await within(panel).findByText(/Решено:/);
    expect(within(panel).queryByText('Открытый вопрос')).toBeNull();
    expect(within(panel).getByRole('button', { name: 'Открыть снова' })).toBeTruthy();
  });

  it('обсуждение проекта в шапке: лента проекта и сообщение в неё (CR-007)', async () => {
    persona.current = PERSONAS.expert;
    const calls: { path: string; body: unknown }[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.method !== 'POST') return;
      const entry = { path: new URL(request.url).pathname, body: null as unknown };
      calls.push(entry);
      void request
        .clone()
        .json()
        .then((b) => (entry.body = b))
        .catch(() => undefined);
    });
    renderApp(`/projects/${portal.id}`);
    await screen.findByRole('treegrid', { name: 'Дерево оценки' });
    const toggle = screen.getByRole('button', { name: /Обсуждение проекта/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    const panel = await screen.findByRole('region', { name: `Обсуждение: ${portal.name}` });
    await within(panel).findByText(/Сообщений пока нет/);
    const input = within(panel).getByRole('combobox', { name: 'Сообщение' });
    fireEvent.change(input, { target: { value: 'Созвон с заказчиком в четверг' } });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    await within(panel).findByText('Созвон с заказчиком в четверг');
    expect(calls.at(-1)).toEqual({
      path: `/api/v1/projects/${portal.id}/messages`,
      body: { body: 'Созвон с заказчиком в четверг', needs_answer: false, addressees: [] },
    });
    fireEvent.click(toggle);
    expect(screen.queryByRole('region', { name: `Обсуждение: ${portal.name}` })).toBeNull();
  });
});
