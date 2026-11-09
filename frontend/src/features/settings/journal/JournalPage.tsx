/**
 * FE-015 · вкладка «Журнал проекта» (SPEC 11.6 №1, 15.2 `GET /projects/{id}/journal`; DESIGN.md 10.5).
 *
 * Лента изменений настроек, команды и статуса: когда, кто («Система» для автоархивации), что и
 * «было → стало». Записи об изменении денег сервер отдаёт только с `money.read` (CORE-032), клиент
 * рисует их денежным цветом и ничего не скрывает сам. Пагинация курсором, «Показать ещё».
 */
import { Button } from '@mantine/core';
import { useInfiniteQuery } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatWhen } from '../../../shared/format/relative';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { SettingsTabs } from '../ProjectSettingsPage';
import { useProject } from '../useProject';

type Entry = components['schemas']['JournalEntry'];

/** Значение поля журнала для показа: пусто — «—», массив — через запятую, логическое — да/нет. */
export function showValue(value: unknown, t: TFunction): string {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return '—';
  if (typeof value === 'boolean') return t(value ? 'journal.yes' : 'journal.no');
  if (Array.isArray(value)) return value.map((v) => showValue(v, t)).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value as string | number);
}

/** Статус проекта — словом, как на плашке (DESIGN.md 7.1); остальное — `showValue`. */
export function fieldValue(field: string, value: unknown, t: TFunction): string {
  if (field === 'status' && typeof value === 'string') return t(`status.project.${value}`, { defaultValue: value });
  return showValue(value, t);
}

/** Пары `{поле: [было, стало]}` → строки; неверные записи пропускаются. */
export function changeRows(changes: object): { field: string; before: unknown; after: unknown }[] {
  return Object.entries(changes).flatMap(([field, pair]) =>
    Array.isArray(pair) && pair.length === 2 ? [{ field, before: pair[0] as unknown, after: pair[1] as unknown }] : [],
  );
}

function Changes({ changes, money }: { changes: object; money?: boolean }) {
  const { t } = useTranslation();
  const rows = changeRows(changes);
  if (!rows.length) return null;
  return (
    <ul className={money ? 'journal-changes money' : 'journal-changes'}>
      {rows.map((row) => (
        <li key={row.field}>
          <span className="journal-field">{t(`journal.field.${row.field}`, { defaultValue: row.field })}:</span>{' '}
          {fieldValue(row.field, row.before, t)} → {fieldValue(row.field, row.after, t)}
        </li>
      ))}
    </ul>
  );
}

function Row({ entry }: { entry: Entry }) {
  const { t } = useTranslation();
  return (
    <li className="journal-row">
      <div className="journal-meta">
        <span className="journal-who">{entry.user ? entry.user.full_name : t('journal.system')}</span>
        <time dateTime={entry.created_at}>{formatWhen(entry.created_at)}</time>
      </div>
      <div className="journal-what">
        <div className="journal-action">{t(`journal.action.${entry.action}`, { defaultValue: entry.action })}</div>
        <Changes changes={entry.changes} />
        {entry.money ? <Changes changes={entry.money.changes} money /> : null}
      </div>
    </li>
  );
}

export function JournalPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const project = useProject(projectId);
  const journal = useInfiniteQuery({
    queryKey: ['journal', projectId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/projects/{id}/journal', {
          params: { path: { id: projectId }, query: { limit: 50, ...(pageParam ? { cursor: pageParam } : {}) } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
  const entries = (journal.data?.pages.flatMap((p) => p.items) ?? []) as Entry[];

  return (
    <div className="settings">
      <div className="crumbs">
        <Link to={`/projects/${projectId}`}>{project.data?.name ?? ''}</Link>
        <span aria-hidden="true"> › </span>
        <h1>{t('settings.title')}</h1>
      </div>
      <SettingsTabs projectId={projectId} active="journal" />
      <section className="sec journal" aria-labelledby="journal-title">
        <h3 id="journal-title">{t('settings.tabs.journal')}</h3>
        <ErrorText error={project.error ?? journal.error} />
        {journal.isSuccess && entries.length === 0 ? <EmptyState title={t('journal.empty')} /> : null}
        {entries.length ? (
          <ol className="journal-list">
            {entries.map((entry) => (
              <Row key={entry.id} entry={entry} />
            ))}
          </ol>
        ) : null}
        {journal.hasNextPage ? (
          <Button
            variant="default"
            size="xs"
            loading={journal.isFetchingNextPage}
            onClick={() => void journal.fetchNextPage()}
          >
            {t('journal.more')}
          </Button>
        ) : null}
      </section>
    </div>
  );
}
