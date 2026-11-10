/** FE-020 · клиент WS на имитаторе сокета: подписка, разрыв, догрузка, resync, отзыв, конец сессии. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeSocket } from '../../test/fakeSocket';
import { WsClient, defaultBackoff, wsUrl, type WsEvent, type WsStatus } from './client';

/** Дождаться цепочек промисов (ack → then → catch). */
async function flush() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

const P = '7d0f6c8e-0000-4000-8000-000000000001';

function event(name: string, version?: number, data: Record<string, unknown> = {}, channel = `project:${P}`) {
  return {
    type: 'event',
    event: name,
    channel,
    ts: '2026-11-09T10:00:00Z',
    ...(version === undefined ? {} : { project_version: version }),
    data,
  };
}

function setup(extra: Partial<ConstructorParameters<typeof WsClient>[0]> = {}) {
  const statuses: WsStatus[] = [];
  const client = new WsClient({
    url: 'ws://test/api/v1/ws',
    createSocket: FakeSocket.factory,
    backoff: (attempt) => 1000 * 2 ** attempt,
    ...extra,
  });
  client.onStatus((s) => statuses.push(s));
  return { client, statuses };
}

beforeEach(() => {
  FakeSocket.all = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe('WsClient (FR-TREE-33, ARCH-02)', () => {
  it('подписка с since; события применяются, повторы старых версий отбрасываются', async () => {
    const { client } = setup();
    const seen: WsEvent[] = [];
    client.start();
    client.subscribe(P, 20, { onEvent: (e) => seen.push(e) });
    FakeSocket.last().open();
    expect(FakeSocket.last().sent[0]).toMatchObject({ op: 'subscribe', project_id: P, since: 20 });
    FakeSocket.last().ack('subscribe', { project_version: 22, channels: [`project:${P}`], resync: false });
    await flush();
    FakeSocket.last().push(event('node.updated', 21));
    FakeSocket.last().push(event('presence'));
    FakeSocket.last().push(event('node.updated', 23));
    FakeSocket.last().push(event('node.updated', 22)); // повтор: уже применена 23
    expect(seen.map((e) => [e.event, e.project_version])).toEqual([
      ['node.updated', 21],
      ['presence', undefined],
      ['node.updated', 23],
    ]);
    expect(client.appliedVersion(P)).toBe(23);
  });

  it('разрыв → offline; переподключение с задержкой 1, 2 с; повторная подписка с since', () => {
    const { client, statuses } = setup();
    client.start();
    client.subscribe(P, 5, {});
    FakeSocket.last().open();
    FakeSocket.last().push(event('node.created', 9));
    FakeSocket.last().drop();
    expect(client.getStatus()).toBe('offline');

    vi.advanceTimersByTime(999);
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.all).toHaveLength(2);
    FakeSocket.last().drop(); // сервер ещё не поднялся
    vi.advanceTimersByTime(2000);
    expect(FakeSocket.all).toHaveLength(3);
    expect(client.getStatus()).toBe('offline'); // полоса не мигает между попытками

    FakeSocket.last().open();
    expect(client.getStatus()).toBe('open');
    expect(FakeSocket.last().sent[0]).toMatchObject({ op: 'subscribe', since: 9 });
    expect(statuses).toEqual(['connecting', 'open', 'offline', 'open']);
  });

  it('после восстановления сервер досылает пропущенное — оно применяется по порядку', async () => {
    const { client } = setup();
    const versions: (number | undefined)[] = [];
    client.start();
    client.subscribe(P, 10, { onEvent: (e) => versions.push(e.project_version) });
    FakeSocket.last().open();
    FakeSocket.last().drop();
    vi.advanceTimersByTime(1000);
    FakeSocket.last().open();
    FakeSocket.last().ack('subscribe', { project_version: 12, channels: [`project:${P}`], resync: false });
    await flush();
    FakeSocket.last().push(event('node.updated', 11));
    FakeSocket.last().push(event('branch.status', 12));
    expect(versions).toEqual([11, 12]);
  });

  it('resync: true в ответе и resync.required → перезагрузка дерева', async () => {
    const { client } = setup();
    const onResync = vi.fn();
    client.start();
    client.subscribe(P, 1, { onResync });
    FakeSocket.last().open();
    FakeSocket.last().ack('subscribe', { project_version: 900, channels: [`project:${P}`], resync: true });
    await flush();
    expect(onResync).toHaveBeenCalledTimes(1);
    FakeSocket.last().push(event('resync.required', undefined, { project_id: P, project_version: 901 }));
    expect(onResync).toHaveBeenCalledTimes(2);
    expect(client.appliedVersion(P)).toBe(901);
  });

  it('access.revoked и ошибка подписки снимают подписку и сообщают об отзыве', async () => {
    const { client } = setup();
    const onRevoked = vi.fn();
    const onEvent = vi.fn();
    client.start();
    client.subscribe(P, 1, { onRevoked, onEvent });
    FakeSocket.last().open();
    FakeSocket.last().push(event('access.revoked', undefined, { project_id: P, reason: 'removed' }));
    expect(onRevoked).toHaveBeenCalledWith('removed');
    FakeSocket.last().push(event('node.updated', 2));
    expect(onEvent).not.toHaveBeenCalled();

    const other = '7d0f6c8e-0000-4000-8000-000000000002';
    const onOther = vi.fn();
    client.subscribe(other, null, { onRevoked: onOther });
    const command = FakeSocket.last().sent.at(-1);
    FakeSocket.last().push({ type: 'error', op: 'subscribe', req_id: command?.req_id, code: 'NOT_FOUND' });
    await flush();
    expect(onOther).toHaveBeenCalledWith('NOT_FOUND');
  });

  it('две подписки на проект (дерево и настройки) — одна команда subscribe, события обеим (FE-091)', async () => {
    const { client } = setup();
    const tree = vi.fn();
    const settings = vi.fn();
    const revoked = vi.fn();
    client.start();
    FakeSocket.last().open();
    const offTree = client.subscribe(P, 5, { onEvent: tree, onRevoked: revoked });
    const offSettings = client.subscribe(P, null, { onEvent: settings, onRevoked: revoked });
    const subscribes = () => FakeSocket.last().sent.filter((c) => c.op === 'subscribe');
    const unsubscribes = () => FakeSocket.last().sent.filter((c) => c.op === 'unsubscribe');
    expect(subscribes()).toHaveLength(1);
    FakeSocket.last().ack('subscribe', { project_version: 5, channels: [`project:${P}`], resync: false });
    await flush();
    FakeSocket.last().push(event('node.updated', 6));
    expect(tree).toHaveBeenCalledTimes(1);
    expect(settings).toHaveBeenCalledTimes(1);

    offSettings();
    expect(unsubscribes()).toHaveLength(0);
    FakeSocket.last().push(event('node.updated', 7));
    expect(tree).toHaveBeenCalledTimes(2);
    expect(settings).toHaveBeenCalledTimes(1);

    client.subscribe(P, null, { onEvent: settings, onRevoked: revoked });
    FakeSocket.last().push(event('access.revoked', undefined, { project_id: P, reason: 'removed_from_team' }));
    expect(revoked).toHaveBeenCalledTimes(2);
    offTree();
  });

  it('последний отписавшийся снимает подписку на сервере', () => {
    const { client } = setup();
    client.start();
    FakeSocket.last().open();
    const a = client.subscribe(P, 1, {});
    const b = client.subscribe(P, 1, {});
    a();
    expect(FakeSocket.last().sent.filter((c) => c.op === 'unsubscribe')).toHaveLength(0);
    b();
    expect(FakeSocket.last().sent.filter((c) => c.op === 'unsubscribe')).toHaveLength(1);
  });

  it('session.ended и закрытие 4401 — конец сессии без переподключения (FR-SESS-02)', () => {
    const onSessionEnded = vi.fn();
    const { client } = setup({ onSessionEnded });
    client.start();
    FakeSocket.last().open();
    FakeSocket.last().push(event('session.ended', undefined, { reason: 'revoked' }, 'user:u1'));
    expect(onSessionEnded).toHaveBeenCalledWith('revoked');
    expect(client.getStatus()).toBe('ended');
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(1);

    const second = setup({ onSessionEnded });
    second.client.start();
    FakeSocket.last().open();
    FakeSocket.last().drop(4401);
    expect(onSessionEnded).toHaveBeenLastCalledWith('expired');
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it('личный канал — в onUserEvent; heartbeat каждые 10 с только с захватами, потерянные — наружу', async () => {
    const onUserEvent = vi.fn();
    const onLocksLost = vi.fn();
    const { client } = setup({ onUserEvent, onLocksLost });
    client.start();
    FakeSocket.last().open();
    FakeSocket.last().push(event('notification.created', undefined, { unread_count: 3 }, 'user:u1'));
    expect(onUserEvent).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(10_000);
    expect(FakeSocket.last().sent.filter((c) => c.op === 'heartbeat')).toHaveLength(0);
    const lock = { node_id: 'n1', field: 'r' };
    client.setLockSource(() => [lock]);
    vi.advanceTimersByTime(10_000);
    expect(FakeSocket.last().sent.at(-1)).toMatchObject({ op: 'heartbeat', locks: [lock] });
    FakeSocket.last().ack('heartbeat', { extended: [], lost: [lock] });
    await flush();
    expect(onLocksLost).toHaveBeenCalledWith([lock]);
  });

  it('команда без связи отклоняется OFFLINE; stop — idle и без переподключения', async () => {
    const { client } = setup();
    await expect(client.request({ op: 'lock' })).rejects.toMatchObject({ code: 'OFFLINE' });
    client.start();
    FakeSocket.last().open();
    const pending = client.request({ op: 'lock', project_id: P, node_id: 'n1', field: 'o' });
    client.stop();
    await expect(pending).rejects.toMatchObject({ code: 'OFFLINE' });
    expect(client.getStatus()).toBe('idle');
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(1);
  });
});

describe('вспомогательное', () => {
  it('адрес wss для https; задержка растёт до 30 с с разбросом', () => {
    expect(wsUrl({ protocol: 'https:', host: 'est.local' })).toBe('wss://est.local/api/v1/ws');
    expect(wsUrl({ protocol: 'http:', host: 'localhost:5173' })).toBe('ws://localhost:5173/api/v1/ws');
    for (let i = 0; i < 50; i += 1) {
      expect(defaultBackoff(0)).toBeGreaterThanOrEqual(800);
      expect(defaultBackoff(0)).toBeLessThanOrEqual(1200);
      expect(defaultBackoff(20)).toBeLessThanOrEqual(36_000);
    }
  });
});
