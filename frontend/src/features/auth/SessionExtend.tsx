/**
 * FE-007 · диалог «Продлить сессию?» за 2 минуты до истечения по бездействию (FR-SESS-02).
 *
 * Срок бездействия — `idle_timeout_seconds` из `GET /me`, отсчёт от последнего пользовательского
 * REST-запроса (shared/api/activity.ts). Если раньше наступит абсолютный срок `session_expires_at`,
 * продлевать нечего — диалога нет. По истечении сервер закрывает WebSocket и шлёт `session.ended`,
 * дальше экран входа (FE-020).
 */
import { Button, Group, Modal, Text } from '@mantine/core';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { lastActivityAt, onActivity } from '../../shared/api/activity';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';

export const WARN_BEFORE_MS = 2 * 60_000;

/** Сколько осталось до истечения по бездействию, если пора предупреждать; иначе null. */
export function idleWarning(
  now: number,
  lastActivity: number,
  idleTimeoutSeconds: number,
  sessionExpiresAt: string,
): number | null {
  const idleDeadline = lastActivity + idleTimeoutSeconds * 1000;
  const absolute = Date.parse(sessionExpiresAt);
  if (Number.isFinite(absolute) && absolute <= idleDeadline) return null;
  const left = idleDeadline - now;
  return left <= WARN_BEFORE_MS && left > 0 ? left : null;
}

export function formatLeft(ms: number): string {
  const seconds = Math.ceil(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function SessionExtend({
  idleTimeoutSeconds,
  sessionExpiresAt,
  onLogout,
}: {
  idleTimeoutSeconds: number;
  sessionExpiresAt: string;
  onLogout: () => void;
}) {
  const { t } = useTranslation();
  const [left, setLeft] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const tick = () =>
      setLeft(idleWarning(Date.now(), lastActivityAt(), idleTimeoutSeconds, sessionExpiresAt));
    tick();
    const timer = setInterval(tick, 1000);
    const off = onActivity(tick);
    return () => {
      clearInterval(timer);
      off();
    };
  }, [idleTimeoutSeconds, sessionExpiresAt]);

  async function extend() {
    setBusy(true);
    try {
      // пользовательский запрос без X-Background: сервер продлевает сессию, middleware — таймер
      await call(() => api.GET('/me'));
    } catch {
      // сессия уже истекла: экран входа покажет session.ended / 401
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      opened={left !== null}
      onClose={() => void extend()}
      title={t('sessionExtend.title')}
      centered
      withCloseButton={false}
    >
      <Text mb="md">{t('sessionExtend.text', { time: formatLeft(left ?? 0) })}</Text>
      <Group justify="flex-end">
        <Button variant="default" onClick={onLogout}>
          {t('nav.logout')}
        </Button>
        <Button loading={busy} onClick={() => void extend()}>
          {t('sessionExtend.extend')}
        </Button>
      </Group>
    </Modal>
  );
}
