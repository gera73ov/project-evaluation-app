/**
 * FE-020 · клиент WebSocket `/api/v1/ws` (SPEC 15.4, ARCH-02, FR-TREE-33, FR-SESS-02;
 * контракт RT-001: `contracts/ws-events.md`, `ws-events.schema.json`).
 *
 * - Одно соединение на вкладку; личный канал `user:{id}` сервер подписывает сам.
 * - Подписка на проект — команда `subscribe {project_id, since}`; после разрыва клиент
 *   переподключается с экспоненциальной задержкой и подписывается заново с `since` = последней
 *   применённой версии. Сервер досылает пропущенное из `change_log` (ws-events.md «Версии и
 *   догрузка», п. 3) или отвечает `resync: true` и `resync.required` — тогда дерево грузится целиком.
 * - Пропуски номеров версий внутри живого соединения нормальны (события не по правам не приходят).
 *   Отбрасываются только повторы: события с версией меньше уже применённой.
 * - `session.ended` или закрытие 4401 — сессии больше нет, переподключения нет.
 *   `access.revoked` — проект закрывается, подписка снимается.
 * - `heartbeat` каждые 10 с продлевает захваты ячеек (FR-TREE-31) и не продлевает сессию.
 */

/**
 * idle — соединение не нужно (нет сессии); connecting — первое подключение; open — на связи;
 * offline — связь потеряна, идут попытки переподключения; ended — сессия закончилась.
 */
export type WsStatus = 'idle' | 'connecting' | 'open' | 'offline' | 'ended';

export interface WsEvent {
  type: 'event';
  event: string;
  channel: string;
  ts: string;
  project_version?: number;
  data: Record<string, unknown>;
}

export interface SubscribeResult {
  project_version: number;
  channels: string[];
  resync: boolean;
}

export interface LockRef {
  node_id: string;
  field: string;
}

export interface ProjectHandlers {
  /** Событие каналов проекта (`project:{id}`, `:money`, `:notes`). */
  onEvent?: (event: WsEvent) => void;
  /** Клиент слишком отстал (ack с `resync` или `resync.required`): перезагрузить дерево. */
  onResync?: () => void;
  /** Доступ к проекту отозван (`access.revoked`). */
  onRevoked?: (reason: string) => void;
  /** Подписка подтверждена (в том числе повторно после переподключения). */
  onSubscribed?: (result: SubscribeResult) => void;
}

export interface WsClientOptions {
  url: string;
  /** Фабрика сокета: в тестах — имитатор. */
  createSocket?: (url: string) => WebSocket;
  /** Задержка переподключения: 1, 2, 4 … 30 с с разбросом ±20 %. */
  backoff?: (attempt: number) => number;
  heartbeatMs?: number;
  /** Захваты, которые сервер не продлил в ответ на `heartbeat` (истекли или перехвачены). */
  onLocksLost?: (locks: LockRef[]) => void;
  /** Сессии больше нет (`session.ended`, закрытие 4401). */
  onSessionEnded?: (reason: string) => void;
  /** Событие личного канала `user:{id}` (уведомления). */
  onUserEvent?: (event: WsEvent) => void;
}

interface Subscription {
  projectId: string;
  /** Последняя применённая версия проекта; null — ещё не известна. */
  version: number | null;
  handlers: ProjectHandlers;
}

interface Pending {
  resolve: (result: Record<string, unknown>) => void;
  reject: (error: WsCommandError) => void;
}

/** Ответ `{type: "error"}` на команду: код из contracts/errors.yaml и поля ошибки. */
export class WsCommandError extends Error {
  constructor(
    readonly code: string,
    readonly details: Record<string, unknown>,
  ) {
    super(code);
  }
}

const CLOSE_SESSION_ENDED = 4401;
const CLOSE_FORBIDDEN_ORIGIN = 4403;

export function defaultBackoff(attempt: number): number {
  const base = Math.min(30_000, 1000 * 2 ** attempt);
  return Math.round(base * (0.8 + Math.random() * 0.4));
}

export function wsUrl(location: Pick<Location, 'protocol' | 'host'> = window.location): string {
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/ws`;
}

export class WsClient {
  private socket: WebSocket | null = null;
  private status: WsStatus = 'idle';
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = true;
  private reqSeq = 0;
  private readonly subscriptions = new Map<string, Subscription>();
  private readonly statusListeners = new Set<(status: WsStatus) => void>();
  private locks: () => LockRef[] = () => [];
  private readonly pending = new Map<string, Pending>();

  constructor(private options: WsClientOptions) {}

  /** Обновить колбэки (React передаёт свежие после каждого рендера). */
  setCallbacks(callbacks: Pick<WsClientOptions, 'onSessionEnded' | 'onUserEvent' | 'onLocksLost'>): void {
    this.options = { ...this.options, ...callbacks };
  }

  getStatus(): WsStatus {
    return this.status;
  }

  onStatus(listener: (status: WsStatus) => void): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  /** Откуда брать захваты для `heartbeat` (FE-025 передаст ячейки в фокусе). */
  setLockSource(source: () => LockRef[]): void {
    this.locks = source;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000);
    this.rejectPending();
    this.setStatus('idle');
  }

  /** Подписка на проект; возвращает отписку. `since` — версия уже загруженного дерева. */
  subscribe(projectId: string, since: number | null, handlers: ProjectHandlers): () => void {
    const sub: Subscription = { projectId, version: since, handlers };
    this.subscriptions.set(projectId, sub);
    if (this.status === 'open') this.sendSubscribe(sub);
    return () => {
      if (this.subscriptions.get(projectId) !== sub) return;
      this.subscriptions.delete(projectId);
      if (this.status === 'open') this.send({ op: 'unsubscribe', project_id: projectId });
    };
  }

  /** Версия, применённая клиентом (например, после ответа PATCH — FE-021). */
  markApplied(projectId: string, version: number): void {
    const sub = this.subscriptions.get(projectId);
    if (sub && (sub.version === null || version > sub.version)) sub.version = version;
  }

  appliedVersion(projectId: string): number | null {
    return this.subscriptions.get(projectId)?.version ?? null;
  }

  send(command: Record<string, unknown>): boolean {
    if (this.status !== 'open' || !this.socket) return false;
    this.socket.send(JSON.stringify(command));
    return true;
  }

  /** Команда с ответом: `ack.result` или WsCommandError; без соединения — ошибка OFFLINE. */
  request(command: Record<string, unknown>): Promise<Record<string, unknown>> {
    const reqId = this.nextReqId();
    return new Promise((resolve, reject) => {
      if (!this.send({ ...command, req_id: reqId })) {
        reject(new WsCommandError('OFFLINE', {}));
        return;
      }
      this.pending.set(reqId, { resolve, reject });
    });
  }

  private nextReqId(): string {
    this.reqSeq += 1;
    return `r${this.reqSeq}`;
  }

  private open(): void {
    // при переподключении полоса «Нет связи» не мигает: статус остаётся offline до успеха
    if (this.status !== 'offline') this.setStatus('connecting');
    const create = this.options.createSocket ?? ((url: string) => new WebSocket(url));
    const socket = create(this.options.url);
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.attempt = 0;
      this.setStatus('open');
      for (const sub of this.subscriptions.values()) this.sendSubscribe(sub);
      this.startHeartbeat();
    };
    socket.onmessage = (message: MessageEvent) => {
      if (this.socket === socket) this.receive(String(message.data));
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.clearTimers();
      this.rejectPending();
      if (event.code === CLOSE_SESSION_ENDED) {
        this.end('expired');
        return;
      }
      if (this.stopped) return;
      this.setStatus('offline');
      // 4403 — чужой Origin: повтор не поможет, но и тихо молчать нельзя — полоса остаётся
      if (event.code === CLOSE_FORBIDDEN_ORIGIN) return;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = (this.options.backoff ?? defaultBackoff)(this.attempt);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.stopped) this.open();
    }, delay);
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      const locks = this.locks();
      if (locks.length === 0) return;
      this.request({ op: 'heartbeat', locks: locks.slice(0, 20) })
        .then((result) => {
          const lost = (result.lost ?? []) as LockRef[];
          if (lost.length > 0) this.options.onLocksLost?.(lost);
        })
        .catch(() => {}); // разрыв: захваты снимет сервер, полоса «Нет связи» уже видна
    }, this.options.heartbeatMs ?? 10_000);
  }

  private rejectPending(): void {
    for (const pending of this.pending.values()) pending.reject(new WsCommandError('OFFLINE', {}));
    this.pending.clear();
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
  }

  private sendSubscribe(sub: Subscription): void {
    this.request({
      op: 'subscribe',
      project_id: sub.projectId,
      ...(sub.version === null ? {} : { since: sub.version }),
    })
      .then((result) => {
        if (this.subscriptions.get(sub.projectId) !== sub) return;
        const ack = result as unknown as SubscribeResult;
        if (sub.version === null) sub.version = ack.project_version;
        sub.handlers.onSubscribed?.(ack);
        if (ack.resync) sub.handlers.onResync?.();
      })
      .catch((error: unknown) => {
        // NOT_FOUND / FORBIDDEN: проекта нет или доступа нет — как отзыв доступа
        if (!(error instanceof WsCommandError) || error.code === 'OFFLINE') return;
        if (this.subscriptions.get(sub.projectId) !== sub) return;
        this.subscriptions.delete(sub.projectId);
        sub.handlers.onRevoked?.(error.code);
      });
  }

  private end(reason: string): void {
    this.stopped = true;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000);
    this.rejectPending();
    this.setStatus('ended');
    this.options.onSessionEnded?.(reason);
  }

  private receive(raw: string): void {
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    if (message.type === 'ack' || message.type === 'error') {
      const reqId = typeof message.req_id === 'string' ? message.req_id : '';
      const pending = this.pending.get(reqId);
      if (!pending) return;
      this.pending.delete(reqId);
      if (message.type === 'ack') pending.resolve((message.result ?? {}) as Record<string, unknown>);
      else pending.reject(new WsCommandError(String(message.code), message));
      return;
    }
    if (message.type !== 'event') return;
    const event = message as unknown as WsEvent;
    if (event.event === 'session.ended') {
      this.end(String(event.data.reason ?? 'expired'));
      return;
    }
    if (event.channel.startsWith('user:')) {
      this.options.onUserEvent?.(event);
      return;
    }
    const projectId = event.channel.split(':')[1] ?? '';
    const sub = this.subscriptions.get(projectId);
    if (!sub) return;
    switch (event.event) {
      case 'access.revoked':
        this.subscriptions.delete(projectId);
        sub.handlers.onRevoked?.(String(event.data.reason ?? ''));
        return;
      case 'resync.required':
        if (typeof event.data.project_version === 'number') sub.version = event.data.project_version;
        sub.handlers.onResync?.();
        return;
      default:
        break;
    }
    const version = event.project_version;
    if (typeof version === 'number') {
      if (sub.version !== null && version < sub.version) return; // повтор уже применённого
      sub.version = version;
    }
    sub.handlers.onEvent?.(event);
  }

  private setStatus(status: WsStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }
}
