/**
 * FE-010 · «Мои оценки» (SPEC 11.3 №1–5, №7; FR-HOME-01…04; DESIGN.md 10.3).
 *
 * Список — `GET /projects` с фильтрами статуса и роли и поиском с 2 символов; без фильтра
 * статуса сервер отдаёт всё, кроме архива (FR-HOME-02, Q-44). Фильтры запоминаются для
 * пользователя в браузере. Порядок — сначала проекты с «Мне» > 0, затем по дедлайну.
 * Деньги под часами — только если сервер их прислал (право `money.read`, FR-HOME-04).
 */
import { Button, Select, TextInput } from '@mantine/core';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { Link, useNavigate } from '../../app/router';
import { hasRole, type Me } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { formatDate } from '../../shared/format/date';
import { formatHours, formatMoney } from '../../shared/format/number';
import { formatWhen } from '../../shared/format/relative';
import { EmptyState } from '../../shared/ui/EmptyState';
import { ErrorText } from '../../shared/ui/ErrorText';
import { StatusBadge } from '../../shared/ui/StatusBadge';

export type ProjectItem = components['schemas']['ProjectListItem'];
type ProjectStatus = components['schemas']['ProjectStatus'];
type ProjectRole = components['schemas']['ProjectRole'];

const STATUSES: readonly ProjectStatus[] = ['preparation', 'estimation', 'consolidation', 'completed', 'archived'];
const ROLES: readonly ProjectRole[] = ['moderator', 'expert', 'presale'];
const SEARCH_MIN = 2;

export interface HomeFilters {
  status: ProjectStatus | null;
  role: ProjectRole | null;
  q: string;
}

const EMPTY_FILTERS: HomeFilters = { status: null, role: null, q: '' };

function storageKey(userId: string): string {
  return `home.filters.${userId}`;
}

/** Фильтры из браузера; повреждённое или недоступное хранилище — значения по умолчанию. */
export function loadFilters(userId: string): HomeFilters {
  try {
    const raw = window.localStorage.getItem(storageKey(userId));
    if (!raw) return EMPTY_FILTERS;
    const value = JSON.parse(raw) as Partial<HomeFilters>;
    return {
      status: STATUSES.includes(value.status as ProjectStatus) ? (value.status as ProjectStatus) : null,
      role: ROLES.includes(value.role as ProjectRole) ? (value.role as ProjectRole) : null,
      q: typeof value.q === 'string' ? value.q.slice(0, 200) : '',
    };
  } catch {
    return EMPTY_FILTERS;
  }
}

function saveFilters(userId: string, filters: HomeFilters): void {
  try {
    window.localStorage.setItem(storageKey(userId), JSON.stringify(filters));
  } catch {
    // приватный режим или запрет хранилища: фильтры просто не запомнятся
  }
}

/** FR-HOME-02: сначала с «Мне» > 0, затем по дедлайну по возрастанию, без дедлайна — в конце. */
export function sortProjects(items: readonly ProjectItem[]): ProjectItem[] {
  return [...items].sort((a, b) => {
    const toMe = Number(b.questions_to_me > 0) - Number(a.questions_to_me > 0);
    if (toMe !== 0) return toMe;
    if (a.deadline === b.deadline) return 0;
    if (a.deadline === null) return 1;
    if (b.deadline === null) return -1;
    return a.deadline < b.deadline ? -1 : 1;
  });
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/** Названия дисциплин для «Эксперт: Бэкенд» (`dict.read` есть у роли «Пользователь»). */
function useDisciplineNames(): Map<string, string> {
  const query = useQuery({
    queryKey: ['dict', 'disciplines'],
    queryFn: () => call(() => api.GET('/admin/disciplines')),
    staleTime: 10 * 60_000,
  });
  return useMemo(() => new Map((query.data?.items ?? []).map((d) => [d.id, d.name])), [query.data]);
}

export function HomePage({ me }: { me: Me }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [filters, setFilters] = useState<HomeFilters>(() => loadFilters(me.id));
  const q = useDebounced(filters.q.trim(), 300);
  const search = q.length >= SEARCH_MIN ? q : '';
  const disciplines = useDisciplineNames();
  const timeZone = me.timezone ?? undefined;

  useEffect(() => saveFilters(me.id, filters), [me.id, filters]);

  const projects = useInfiniteQuery({
    queryKey: ['projects', 'mine', filters.status, filters.role, search],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/projects', {
          params: {
            query: {
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
              ...(filters.status ? { status: filters.status } : {}),
              ...(filters.role ? { role: filters.role } : {}),
              ...(search ? { q: search } : {}),
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
  });

  const items = useMemo(
    () => sortProjects((projects.data?.pages.flatMap((page) => page.items) ?? []) as ProjectItem[]),
    [projects.data],
  );
  const filtered = filters.status !== null || filters.role !== null || search !== '';
  const canCreate = hasRole(me, ['moderator']);

  function roleText(item: ProjectItem): string {
    const parts: string[] = [];
    const expert = item.my_roles.filter((r) => r.role === 'expert');
    if (item.my_roles.some((r) => r.role === 'moderator')) parts.push(t('home.roles.moderator'));
    if (expert.length > 0) {
      const names = expert.map((r) => (r.discipline_id ? (disciplines.get(r.discipline_id) ?? '…') : '…'));
      const reviewer = expert.some((r) => r.is_reviewer) ? ` · ${t('home.reviewer')}` : '';
      parts.push(`${t('home.roles.expert')}: ${names.join(', ')}${reviewer}`);
    }
    if (item.my_roles.some((r) => r.role === 'presale')) parts.push(t('home.roles.presale'));
    return parts.join(', ');
  }

  function open(item: ProjectItem) {
    navigate(`/projects/${item.id}`);
  }

  function onRowKey(event: KeyboardEvent<HTMLTableRowElement>, item: ProjectItem) {
    if (event.key === 'Enter' && event.target === event.currentTarget) open(item);
  }

  return (
    <div className="home">
      <div className="home-bar">
        <h1>{t('home.title')}</h1>
        <TextInput
          className="home-search"
          aria-label={t('home.search')}
          placeholder={t('home.search')}
          leftSection={<span aria-hidden="true">🔍</span>}
          value={filters.q}
          maxLength={200}
          onChange={(e) => setFilters({ ...filters, q: e.currentTarget.value })}
        />
        <Select
          className="home-filter"
          radius="xl"
          aria-label={t('home.statusFilter')}
          allowDeselect={false}
          value={filters.status ?? 'default'}
          data={[
            { value: 'default', label: t('home.statusDefault') },
            ...STATUSES.map((s) => ({ value: s, label: t('home.statusOne', { status: t(`status.project.${s}`) }) })),
          ]}
          onChange={(value) =>
            setFilters({ ...filters, status: value && value !== 'default' ? (value as ProjectStatus) : null })
          }
        />
        <Select
          className="home-filter narrow"
          radius="xl"
          aria-label={t('home.roleFilter')}
          allowDeselect={false}
          value={filters.role ?? 'all'}
          data={[
            { value: 'all', label: t('home.roleAll') },
            ...ROLES.map((r) => ({ value: r, label: t('home.roleOne', { role: t(`home.roles.${r}`) }) })),
          ]}
          onChange={(value) => setFilters({ ...filters, role: value && value !== 'all' ? (value as ProjectRole) : null })}
        />
        <span className="sp" />
        {canCreate ? (
          <Link to="/projects/new" className="btn-primary">
            {t('home.create')}
          </Link>
        ) : null}
      </div>

      <ErrorText error={projects.error} />

      {projects.isSuccess && items.length === 0 ? (
        filtered ? (
          <EmptyState title={t('home.notFound')} />
        ) : (
          <EmptyState
            title={t('home.emptyTitle')}
            hint={t('home.emptyHint')}
            action={
              canCreate ? (
                <Link to="/projects/new" className="btn-primary">
                  {t('home.create')}
                </Link>
              ) : undefined
            }
          />
        )
      ) : null}

      {items.length > 0 ? (
        <table className="t home-table">
          <thead>
            <tr>
              <th>{t('home.col.project')}</th>
              <th>{t('home.col.status')}</th>
              <th>{t('home.col.role')}</th>
              <th>{t('home.col.progress')}</th>
              <th>{t('home.col.deadline')}</th>
              <th>{t('home.col.me')}</th>
              <th className="r">{t('home.col.total')}</th>
              <th>{t('home.col.updated')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="click" tabIndex={0} onClick={(e) => {
                  // ссылка с названием переходит сама
                  if (!(e.target as HTMLElement).closest('a')) open(item);
                }}
                onKeyDown={(e) => onRowKey(e, item)}>
                <td>
                  <Link to={`/projects/${item.id}`} className="home-name">
                    {item.name}
                  </Link>
                  <div className="sub">{item.customer}</div>
                </td>
                <td>
                  <StatusBadge kind="project" status={item.status} />
                </td>
                <td>{roleText(item)}</td>
                <td>
                  <Progress item={item} />
                </td>
                <td>
                  {item.deadline === null ? (
                    t('common.empty')
                  ) : item.deadline_alert ? (
                    <span className="deadline-alert" title={t('home.deadlineAlert')}>
                      {formatDate(item.deadline)} <span aria-hidden="true">⚠</span>
                      <span className="sr-only">{t('home.deadlineAlert')}</span>
                    </span>
                  ) : (
                    formatDate(item.deadline)
                  )}
                </td>
                <td>
                  {item.questions_to_me > 0 ? (
                    <span className="count-bad" title={t('home.toMe', { count: item.questions_to_me })}>
                      {item.questions_to_me}
                    </span>
                  ) : (
                    <span className="faint">{t('common.empty')}</span>
                  )}
                </td>
                <td className="r">
                  <Total item={item} />
                </td>
                <td>{formatWhen(item.updated_at, { timeZone })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {items.length > 0 ? (
        <div className="home-foot">
          <span>{t('home.shown', { count: items.length })}</span>
          {projects.hasNextPage ? (
            <Button variant="default" size="xs" loading={projects.isFetchingNextPage} onClick={() => void projects.fetchNextPage()}>
              {t('home.more')}
            </Button>
          ) : null}
          <span className="sp" />
          <span>{t('home.sortNote')}</span>
        </div>
      ) : null}
    </div>
  );
}

function Progress({ item }: { item: ProjectItem }) {
  const { t } = useTranslation();
  const progress = item.my_progress ?? null;
  if (!progress || progress.total === 0) {
    return <span className="faint">{item.status === 'preparation' ? t('home.noTeam') : t('common.empty')}</span>;
  }
  const share = Math.round((progress.done / progress.total) * 100);
  return (
    <span className="progress">
      <span className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={progress.total} aria-valuenow={progress.done}>
        <i style={{ width: `${share}%` }} />
      </span>
      {t('home.progress', { done: progress.done, total: progress.total })}
    </span>
  );
}

function Total({ item }: { item: ProjectItem }) {
  const { t } = useTranslation();
  if (item.quote_hours === null) return <>{t('common.empty')}</>;
  const money = item.money;
  return (
    <>
      <div>
        {formatHours(item.quote_hours)} <span className="figure">{t(`home.figure.${item.quote_figure}`)}</span>
      </div>
      {money ? (
        <div className="lock">
          <span aria-hidden="true">🔒</span>
          {money.quote_cur === null ? t('home.ratesMissing') : formatMoney(money.quote_cur, money.currency)}
        </div>
      ) : null}
    </>
  );
}
