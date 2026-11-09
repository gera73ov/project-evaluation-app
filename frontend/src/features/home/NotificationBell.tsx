/**
 * FE-010 · колокольчик и список «Мне» (SPEC 11.3 №6, FR-NOTIF-01).
 *
 * Счётчик — `unread` из `GET /notifications`; новое `notification.created` по WebSocket
 * перечитывает список. Пункт — цветная метка вида, проект и время; клик отмечает прочитанным и
 * открывает рабочий экран на строке с раскрытым обсуждением. payload содержит только
 * идентификаторы (N-INAPP-PAYLOAD), названия берутся из списка проектов.
 */
import { Popover, UnstyledButton } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../app/router';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { formatWhen } from '../../shared/format/relative';

type Notification = components['schemas']['Notification'];

export const NOTIFICATIONS_KEY = ['notifications'] as const;

const TONES = new Map<string, string>(Object.entries({
  question_to_me: 'bad',
  answer_to_my_question: 'acc',
  moderator_change: 'warn',
  branch_back_to_draft: 'warn',
  cell_taken_over: 'warn',
  member_blocked: 'bad',
  project_without_moderator: 'bad',
}));

const KNOWN = new Set([
  'question_to_me',
  'answer_to_my_question',
  'moderator_change',
  'branch_back_to_draft',
  'assigned_to_project',
  'member_replaced',
  'question_redirected',
  'cell_taken_over',
  'project_without_moderator',
  'support_session_opened',
  'presale_head_joined',
  'member_blocked',
]);

function payloadValue(item: Notification, key: 'is_customer' | 'thread_id'): unknown {
  return new Map(Object.entries(item.payload as Record<string, unknown>)).get(key);
}

export function kindLabelKey(item: Notification): string {
  if (item.kind === 'answer_to_my_question' && payloadValue(item, 'is_customer') === true) {
    return 'bell.kind.answer_customer';
  }
  return KNOWN.has(item.kind) ? `bell.kind.${item.kind}` : 'bell.kind.other';
}

/** Куда ведёт пункт: рабочий экран на строке и обсуждении (11.3 №6). */
export function notificationTarget(item: Notification): string | null {
  if (!item.project_id) return null;
  const params = new URLSearchParams();
  if (item.node_id) params.set('node', item.node_id);
  const thread = payloadValue(item, 'thread_id');
  if (typeof thread === 'string') params.set('thread', thread);
  const query = params.toString();
  return `/projects/${item.project_id}${query ? `?${query}` : ''}`;
}

export function NotificationBell({ timeZone }: { timeZone?: string | undefined }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [opened, setOpened] = useState(false);

  const list = useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: () => call(() => api.GET('/notifications', { params: { query: { limit: 30, unread: true } } })),
    staleTime: 30_000,
  });
  const names = useQuery({
    queryKey: ['projects', 'names'],
    queryFn: () => call(() => api.GET('/projects', { params: { query: { limit: 200 } } })),
    enabled: opened,
    staleTime: 60_000,
    select: (data) => new Map(data.items.map((p) => [p.id, p.name])),
  });
  const markRead = useMutation({
    mutationFn: (body: components['schemas']['NotificationsRead']) =>
      call(() => api.POST('/notifications/read', { body })),
    onSettled: () => client.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
  });

  const unread = list.data?.unread ?? 0;
  const items = list.data?.items ?? [];

  function openItem(item: Notification) {
    markRead.mutate({ ids: [item.id], all: false });
    setOpened(false);
    const target = notificationTarget(item);
    if (target) navigate(target);
  }

  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-end" width={420} shadow="md">
      <Popover.Target>
        <UnstyledButton
          className="bell"
          aria-label={t('bell.open', { count: unread })}
          aria-expanded={opened}
          onClick={() => setOpened((o) => !o)}
        >
          <span aria-hidden="true">🔔</span>
          {unread > 0 ? <span className="bell-count">{unread > 99 ? '99+' : unread}</span> : null}
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown p={0}>
        <section className="bell-list" aria-label={t('bell.title')}>
          <header>
            <b>{t('bell.title')}</b>
            {items.length > 0 ? (
              <button type="button" className="link" onClick={() => markRead.mutate({ all: true })}>
                {t('bell.readAll')}
              </button>
            ) : null}
          </header>
          {items.length === 0 ? <p className="bell-empty">{t('bell.empty')}</p> : null}
          <ul>
            {items.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => openItem(item)}>
                  <span className={`bell-kind ${TONES.get(item.kind) ?? 'acc'}`}>{t(kindLabelKey(item))}</span>
                  <span className="bell-meta">
                    {[item.project_id ? names.data?.get(item.project_id) : undefined, formatWhen(item.created_at, { timeZone, minutes: true })]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </Popover.Dropdown>
    </Popover>
  );
}
