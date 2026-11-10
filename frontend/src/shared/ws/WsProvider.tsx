/**
 * FE-020 · соединение WebSocket для React: одно на вкладку, пока сессия активна (FR-SESS-02).
 * `session.ended` → забыть сессию и перейти на вход; `notification.created` → колокольчик (FE-010).
 */
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import { WsClient, wsUrl, type ProjectHandlers, type WsClientOptions, type WsEvent, type WsStatus } from './client';

const WsContext = createContext<WsClient | null>(null);

export interface WsProviderProps {
  /** Соединение открыто, только пока true (сессия «ready»). */
  enabled: boolean;
  /** `restart` — открыть соединение снова, если сессия на деле жива (её id сменил step-up). */
  onSessionEnded: (reason: string, restart: () => void) => void;
  onUserEvent?: (event: WsEvent) => void;
  /** Тесты подставляют фабрику сокета и задержки. */
  options?: Partial<WsClientOptions>;
  children: ReactNode;
}

export function WsProvider({ enabled, onSessionEnded, onUserEvent, options, children }: WsProviderProps) {
  const [client] = useState(
    () =>
      new WsClient({
        url: options?.url ?? (typeof window === 'undefined' ? 'ws://localhost/api/v1/ws' : wsUrl()),
        ...options,
      }),
  );
  // колбэки меняются между рендерами; клиент живёт всё время провайдера
  useLayoutEffect(() => {
    client.setCallbacks({
      onSessionEnded: (reason) => onSessionEnded(reason, () => client.start()),
      ...(onUserEvent ? { onUserEvent } : {}),
    });
  });
  useEffect(() => {
    if (!enabled) return undefined;
    client.start();
    return () => client.stop();
  }, [client, enabled]);
  return <WsContext.Provider value={client}>{children}</WsContext.Provider>;
}

export function useWsClient(): WsClient | null {
  return useContext(WsContext);
}

/** Состояние соединения; вне провайдера — «idle». */
export function useWsStatus(): WsStatus {
  const client = useWsClient();
  return useSyncExternalStore(
    (listener) => (client ? client.onStatus(listener) : () => {}),
    () => client?.getStatus() ?? 'idle',
  );
}

/**
 * Поля только для чтения, пока нет связи (FR-TREE-33): офлайн-правки не копятся,
 * ввод просто недоступен до восстановления соединения.
 */
export function useReadOnlyOffline(): boolean {
  const status = useWsStatus();
  return status === 'connecting' || status === 'offline' || status === 'ended';
}

/** Подписка на проект на время жизни компонента; `since` — версия загруженного дерева. */
export function useProjectChannel(projectId: string | null, since: number | null, handlers: ProjectHandlers): void {
  const client = useWsClient();
  const ref = useRef(handlers);
  const sinceRef = useRef(since);
  useLayoutEffect(() => {
    ref.current = handlers;
    sinceRef.current = since;
  });
  useEffect(() => {
    if (!client || !projectId) return undefined;
    return client.subscribe(projectId, sinceRef.current, {
      onEvent: (event) => ref.current.onEvent?.(event),
      onResync: () => ref.current.onResync?.(),
      onRevoked: (reason) => ref.current.onRevoked?.(reason),
      onSubscribed: (result) => ref.current.onSubscribed?.(result),
    });
  }, [client, projectId]);
}
