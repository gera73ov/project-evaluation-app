/**
 * FE-030 · обсуждение под строкой (11.4 №13–14, FR-DISC-01…09, FR-CQ-03; DESIGN.md 7.4).
 *
 * Шапка — открытые вопросы узла («Открытый вопрос · адресат @заказчик · статус «отвечен»»), лента —
 * последние 3 записи и «Показать всё (N)», серые события, зелёный ответ заказчика, закрытые
 * вопросы одной строкой. Внизу поле ответа (Composer). Своё сообщение правится, пока на него не
 * ответили, и отзывается (FR-DISC-06). Всё — только как текст (SEC-WEB-02).
 */
import { Modal, Select, Textarea } from '@mantine/core';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useSession } from '../../app/session';
import { api } from '../../shared/api/client';
import { call, errorMessage } from '../../shared/api/problem';
import { formatDateTime } from '../../shared/format/date';
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog';
import { Composer, type SendRequest } from './Composer';
import {
  canEditMessage,
  defaultThread,
  entryKey,
  eventParts,
  feedEntries,
  type Addressee,
  type Entry,
  type Message,
  type Thread,
} from './feed';
import { Linkify } from './Linkify';

/** Что нужно обсуждению от рабочего экрана. */
export interface DiscussionSetup {
  projectId: string;
  me: string | null;
  /** `discussion.write` и проект не только для чтения. */
  canWrite: boolean;
  /** Модератор проекта: закрывает любой вопрос (FR-DISC-05). */
  moderator: boolean;
  /** Пресейл или модератор: закрывает отвеченный вопрос заказчику (C-05). */
  presale: boolean;
  /** Дисциплины пользователя: «@Бэкенд» — вопрос мне. */
  myDisciplines: ReadonlySet<string>;
  disciplineNames: ReadonlyMap<string, string>;
  userNames: ReadonlyMap<string, string>;
  /** Подпись роли рядом с именем: «пресейл», «модератор». */
  roleOf: (userId: string) => string | null;
  /** Метки комментария для «Добавить вывод в комментарий». */
  tags: ReadonlyMap<string, string>;
  isLeaf: (nodeId: string) => boolean;
}

export const feedKey = (nodeId: string) => ['feed', nodeId] as const;
const SHOWN = 3;

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .map((w) => w.replace(/[.]/g, '').charAt(0))
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

function useAddresseeLabel(setup: DiscussionSetup) {
  const { t } = useTranslation();
  return (a: Addressee) => {
    if (a.target_type === 'customer') return `@${t('discussion.target.customerName')}`;
    if (a.target_type === 'moderators') return `@${t('discussion.target.moderatorName')}`;
    const id = a.target_id ?? '';
    const name = a.target_type === 'discipline' ? setup.disciplineNames.get(id) : setup.userNames.get(id);
    return `@${name ?? '?'}`;
  };
}

/** Вопрос адресован пользователю или он автор / модератор — может закрыть (FR-DISC-05, C-05). */
function canResolve(thread: Thread, setup: DiscussionSetup): boolean {
  if (!setup.canWrite) return false;
  if (setup.moderator || thread.opened_by.id === setup.me) return true;
  if (thread.is_customer) return setup.presale && thread.customer_status === 'answered';
  return thread.first_message.addressees.some(
    (a) =>
      (a.target_type === 'user' && a.target_id === setup.me) ||
      (a.target_type === 'discipline' && a.target_id !== null && setup.myDisciplines.has(a.target_id)),
  );
}

export function DiscussionPanel({ nodeId, title, setup }: { nodeId: string; title: string; setup: DiscussionSetup }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  const label = useAddresseeLabel(setup);
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null | undefined>(undefined);
  const [editing, setEditing] = useState<{ id: string; body: string } | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [conclude, setConclude] = useState<{ thread: Thread; text: string; tag: string | null } | null>(null);

  const feed = useInfiniteQuery({
    queryKey: feedKey(nodeId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/nodes/{id}/messages', {
          params: { path: { id: nodeId }, query: { limit: 100, ...(pageParam ? { cursor: pageParam } : {}) } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = (feed.data?.pages.flatMap((p) => p.items) ?? []) as Message[];
  const threadMap = new Map<string, Thread>();
  for (const page of feed.data?.pages ?? []) for (const th of page.threads as Thread[]) threadMap.set(th.id, th);
  const threads = [...threadMap.values()];
  const entries = feedEntries(items, threads);
  const open = threads.filter((th) => th.status === 'open');
  // «Показать всё» догружает остальные страницы
  const { hasNextPage, fetchNextPage, isFetchingNextPage } = feed;
  useEffect(() => {
    if (all && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [all, hasNextPage, isFetchingNextPage, fetchNextPage]);
  const shown = all ? entries : entries.slice(-SHOWN);
  const hidden = entries.length - shown.length;

  const target = targetId === undefined ? defaultThread(threads) : targetId ? threadMap.get(targetId) : undefined;

  const run = async (request: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await request();
      await client.invalidateQueries({ queryKey: feedKey(nodeId) });
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const send = ({ body, needsAnswer, addressees }: SendRequest) =>
    run(async () => {
      if (!needsAnswer && target)
        await call(() =>
          api.POST('/threads/{id}/messages', {
            params: { path: { id: target.id } },
            body: { body, needs_answer: false, addressees },
          }),
        );
      else
        await call(() =>
          api.POST('/nodes/{id}/messages', {
            params: { path: { id: nodeId } },
            body: { body, needs_answer: needsAnswer, addressees },
          }),
        );
      // новый вопрос — ответы по умолчанию в него
      if (needsAnswer) setTargetId(undefined);
    });

  const resolve = (thread: Thread, conclusion: { text: string; tag_id: string | null } | null) =>
    run(() =>
      call(() => api.POST('/threads/{id}/resolve', { params: { path: { id: thread.id } }, body: { conclusion } })),
    ).then((ok) => {
      if (ok) {
        setConclude(null);
        setTargetId(undefined);
      }
    });

  const reopen = (thread: Thread) =>
    void run(() => call(() => api.POST('/threads/{id}/reopen', { params: { path: { id: thread.id } } })));

  const author = (m: Message) => {
    const name = m.author?.full_name ?? t('journal.system');
    const role = m.author ? setup.roleOf(m.author.id) : null;
    return (
      <>
        <b>{name}</b>
        {role ? <span className="msg-role"> ({role})</span> : null}
      </>
    );
  };

  const renderEntry = (entry: Entry) => {
    if (entry.kind === 'event') {
      const m = entry.message;
      return (
        <li key={entryKey(entry)} className="ev">
          ⟲ {t('discussion.ev.changed')}:{' '}
          {eventParts(m)
            .map((part) =>
              part.before !== undefined
                ? `${t(`discussion.ev.${part.label}`)} ${part.before} → ${part.after ?? ''}`
                : t(`discussion.ev.${part.label}`),
            )
            .join(', ')}{' '}
          · {m.author?.full_name ?? t('journal.system')} · {formatDateTime(m.created_at, timeZone, true)}
        </li>
      );
    }
    if (entry.kind === 'resolved') {
      const { thread, last } = entry;
      const text = last?.body ?? '';
      return (
        <li key={entryKey(entry)} className="resolved-line">
          <span className="ok-mark">✓</span> {t('discussion.resolvedLine')}:{' '}
          <span className="resolved-text">{text.length > 80 ? `${text.slice(0, 80)}…` : text}</span> ·{' '}
          {thread.resolved_by?.full_name ?? ''}
          {thread.resolved_at ? `, ${formatDateTime(thread.resolved_at, timeZone, true)}` : ''}
          {setup.canWrite && (setup.moderator || (thread.is_customer && setup.presale)) ? (
            <button type="button" className="link" disabled={busy} onClick={() => reopen(thread)}>
              {t('discussion.reopen')}
            </button>
          ) : null}
        </li>
      );
    }
    const m = entry.message;
    const customer = m.kind === 'customer_answer';
    const own = canEditMessage(m, items, setup.me);
    const mine = setup.me !== null && m.author?.id === setup.me && !m.revoked && m.kind === 'message';
    return (
      <li key={entryKey(entry)} className={customer ? 'msg customer' : 'msg'}>
        <span className="msg-ava" aria-hidden="true">
          {m.author?.initials ?? initialsOf(m.author?.full_name ?? '')}
        </span>
        <div className="msg-main">
          <div className="msg-meta">
            {author(m)}
            {m.addressees.length ? (
              <>
                {' → '}
                {m.addressees.map((a) => (
                  <span key={`${a.target_type}/${a.target_id ?? ''}`} className="pill warn">
                    {label(a)}
                  </span>
                ))}
              </>
            ) : null}
            {customer ? <span className="pill ok">{t('discussion.customerAnswer')}</span> : null}
            {m.needs_answer ? <span> · {t('discussion.needsAnswer')}</span> : null}
            <span> · {formatDateTime(m.created_at, timeZone, true)}</span>
            {m.edited_at && !m.revoked ? <span className="msg-edited"> · {t('discussion.edited')}</span> : null}
            {mine && setup.canWrite && editing?.id !== m.id ? (
              <span className="msg-acts">
                {own ? (
                  <button type="button" className="link" onClick={() => setEditing({ id: m.id, body: m.body })}>
                    {t('discussion.edit')}
                  </button>
                ) : null}
                <button type="button" className="link" onClick={() => setRevoking(m.id)}>
                  {t('discussion.revoke')}
                </button>
              </span>
            ) : null}
            {entry.thread?.status === 'open' &&
            open.length > 1 &&
            setup.canWrite &&
            m.id === entry.thread.first_message.id ? (
              <button type="button" className="link" onClick={() => setTargetId(entry.thread?.id ?? null)}>
                {t('discussion.answerThis')}
              </button>
            ) : null}
          </div>
          {m.revoked ? (
            <div className="msg-body revoked">{t('discussion.revoked')}</div>
          ) : editing?.id === m.id ? (
            <div className="msg-edit">
              <Textarea
                autosize
                minRows={1}
                maxLength={4000}
                aria-label={t('discussion.editLabel')}
                value={editing.body}
                onChange={(e) => setEditing({ id: m.id, body: e.currentTarget.value })}
                data-autofocus
              />
              <button
                type="button"
                className="btn-sm primary"
                disabled={busy || !editing.body.trim()}
                onClick={() =>
                  void run(() =>
                    call(() =>
                      api.PATCH('/messages/{id}', {
                        params: { path: { id: m.id } },
                        body: { body: editing.body.trim() },
                      }),
                    ),
                  ).then((ok) => ok && setEditing(null))
                }
              >
                {t('common.save')}
              </button>
              <button type="button" className="btn-sm" onClick={() => setEditing(null)}>
                {t('common.cancel')}
              </button>
            </div>
          ) : (
            <div className="msg-body">
              <Linkify text={m.body} />
            </div>
          )}
        </div>
      </li>
    );
  };

  const statusOf = (th: Thread) =>
    th.is_customer && th.customer_status ? t(`discussion.cq.${th.customer_status}`) : null;
  const revokeTarget = revoking ? items.find((m) => m.id === revoking) : undefined;

  return (
    <div className="disc-panel" role="region" aria-label={t('discussion.region', { name: title })}>
      <div className="disc-head">
        <div className="disc-qs">
          {open.length ? (
            open.map((th) => (
              <div key={th.id} className={target?.id === th.id ? 'disc-q on' : 'disc-q'}>
                <b className="q-open">{t('discussion.openQuestion')}</b>
                {th.first_message.addressees.length ? (
                  <span>
                    {' · '}
                    {t('discussion.addressee')} {th.first_message.addressees.map(label).join(', ')}
                  </span>
                ) : null}
                {statusOf(th) ? <span> · {t('discussion.status', { status: statusOf(th) })}</span> : null}
              </div>
            ))
          ) : (
            <span className="disc-title">{t('discussion.title')}</span>
          )}
        </div>
        {hidden > 0 ? (
          <button type="button" className="link" onClick={() => setAll(true)}>
            {t('discussion.showAll', { count: entries.length })}
          </button>
        ) : all && entries.length > SHOWN ? (
          <button type="button" className="link" onClick={() => setAll(false)}>
            {t('discussion.showLast')}
          </button>
        ) : null}
      </div>
      {feed.isPending ? <div className="disc-empty">{t('common.loading')}</div> : null}
      {feed.isError ? (
        <div className="err" role="alert">
          {errorMessage(feed.error)}
        </div>
      ) : null}
      {feed.isSuccess && !entries.length ? <div className="disc-empty">{t('discussion.empty')}</div> : null}
      {shown.length ? <ol className="disc-feed">{shown.map(renderEntry)}</ol> : null}
      {error ? (
        <div className="err" role="alert">
          {error}
        </div>
      ) : null}
      {setup.canWrite ? (
        <Composer
          projectId={setup.projectId}
          busy={busy}
          target={
            target && open.length > 1
              ? {
                  label: target.first_message.body.slice(0, 40),
                  onClear: () => setTargetId(null),
                }
              : null
          }
          canResolve={target ? canResolve(target, setup) : false}
          canConclude={setup.isLeaf(nodeId)}
          onSend={send}
          onResolve={(withConclusion) => {
            if (!target) return;
            if (!withConclusion) {
              void resolve(target, null);
              return;
            }
            const last = items.filter((m) => m.thread_id === target.id && m.kind !== 'event' && !m.revoked).at(-1);
            setConclude({ thread: target, text: last?.body ?? '', tag: null });
          }}
        />
      ) : null}
      <ConfirmDialog
        opened={revoking !== null}
        title={t('discussion.revokeTitle')}
        message={t('discussion.revokeMessage', { text: (revokeTarget?.body ?? '').slice(0, 80) })}
        confirmLabel={t('discussion.revoke')}
        danger
        busy={busy}
        onConfirm={() => {
          const id = revoking;
          if (!id) return;
          void run(() => call(() => api.POST('/messages/{id}/revoke', { params: { path: { id } } }))).then(() =>
            setRevoking(null),
          );
        }}
        onCancel={() => setRevoking(null)}
      />
      {conclude ? (
        <Modal opened onClose={() => setConclude(null)} title={t('discussion.concludeTitle')} size={520} centered>
          <Textarea
            label={t('discussion.concludeText')}
            autosize
            minRows={3}
            maxLength={2000}
            value={conclude.text}
            onChange={(e) => setConclude({ ...conclude, text: e.currentTarget.value })}
            data-autofocus
          />
          <Select
            mt="sm"
            label={t('discussion.concludeTag')}
            data={[
              { value: '', label: t('discussion.noTag') },
              ...[...setup.tags].map(([value, name]) => ({ value, label: name })),
            ]}
            value={conclude.tag ?? ''}
            onChange={(value) => setConclude({ ...conclude, tag: value || null })}
            allowDeselect={false}
            comboboxProps={{ withinPortal: true }}
          />
          <div className="dlg-actions">
            <button type="button" className="btn-sm" onClick={() => setConclude(null)}>
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className="btn-sm primary"
              disabled={busy || !conclude.text.trim()}
              onClick={() => void resolve(conclude.thread, { text: conclude.text.trim(), tag_id: conclude.tag })}
            >
              {t('discussion.resolveOnly')}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
