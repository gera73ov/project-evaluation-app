/**
 * FE-065 · журнал аудита (SPEC SEC-AUD-06, 8.1 «Журнал аудита (аудитор ИБ)», FR-EXP-06): таблица
 * событий с фильтрами (период, пользователь, тип, результат) и детали записи. Аудитор ИБ видит
 * журнал отдельным пунктом меню, суперадминистратор — в разделе «Система», администратор — только
 * категории «Пользователи и роли» и «Справочники». Выгрузка CSV — со step-up, только с правом
 * `audit.export` (не у администратора).
 */
import { Button, Select, TextInput } from '@mantine/core';
import { useInfiniteQuery, useMutation } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { useSession, type Me } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { ExportTimeout, downloadExport } from '../../shared/api/exports';
import { call } from '../../shared/api/problem';
import { formatDateTime } from '../../shared/format/date';
import { ErrorText } from '../../shared/ui/ErrorText';
import { SystemLayout } from '../system/layout/SystemLayout';
import { StepUpCancelled, useStepUp } from '../system/layout/useStepUp';
import {
  RESULTS,
  categoryTitle,
  defaultFilters,
  eventOptions,
  eventTitle,
  periodOf,
  periodValid,
  queryOf,
  type AuditFilters,
  type AuditResult,
} from './audit';

type Entry = components['schemas']['AuditEntry'];

export function AuditPage() {
  const { t } = useTranslation();
  const { session } = useSession();
  if (session.state !== 'ready') return null;
  const me = session.me;
  const body = <AuditJournal me={me} />;
  return me.system_roles.includes('superadmin') ? (
    <SystemLayout active="audit" title={t('audit.title')} subtitle={t('audit.subtitle')}>
      {body}
    </SystemLayout>
  ) : (
    <div className="audit-page">
      <h1 className="sys-title">{t('audit.title')}</h1>
      <p className="sys-sub">
        {me.system_roles.includes('admin') && !me.system_roles.includes('security_auditor')
          ? t('audit.adminScope')
          : t('audit.subtitle')}
      </p>
      {body}
    </div>
  );
}

function AuditJournal({ me }: { me: Me }) {
  const { t } = useTranslation();
  const { run, modal } = useStepUp();
  const [draft, setDraft] = useState<AuditFilters>(() => defaultFilters());
  const [filters, setFilters] = useState<AuditFilters>(draft);
  const [selected, setSelected] = useState<Entry | null>(null);
  const [users, setUsers] = useState<Map<string, string>>(new Map());
  const roles = me.system_roles;
  const canExport = roles.includes('superadmin') || roles.includes('security_auditor');
  const tz = me.timezone ?? undefined;

  const journal = useInfiniteQuery({
    queryKey: ['audit', filters],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const page = await call(() =>
        api.GET('/system/audit', {
          params: { query: { ...queryOf(filters), limit: 50, ...(pageParam ? { cursor: pageParam } : {}) } },
        }),
      );
      // пользователи для фильтра — из уже загруженных записей
      setUsers((prev) => {
        const next = new Map(prev);
        for (const e of page.items) if (e.user_id && e.login) next.set(e.user_id, e.login);
        return next.size === prev.size ? prev : next;
      });
      return page;
    },
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = journal.data?.pages.flatMap((p) => p.items) ?? [];

  const exportCsv = useMutation({
    mutationFn: () =>
      downloadExport(
        () =>
          run(() =>
            call(() =>
              api.POST('/system/audit/export', {
                body: {
                  ...periodOf(filters),
                  user_id: filters.userId,
                  event_type: filters.eventType,
                  result: filters.result,
                },
              }),
            ),
          ),
        { fallbackName: 'audit.csv' },
      ),
  });
  const exportError =
    exportCsv.error instanceof StepUpCancelled
      ? null
      : exportCsv.error instanceof ExportTimeout
        ? new Error(t('audit.exportTimeout'))
        : exportCsv.error;

  const set = (patch: Partial<AuditFilters>) => setDraft((f) => ({ ...f, ...patch }));
  const valid = periodValid(draft);
  const changed = JSON.stringify(draft) !== JSON.stringify(filters);

  return (
    <>
      <section className="sec audit-filters" aria-label={t('audit.filters')}>
        <TextInput
          type="date"
          label={t('audit.from')}
          value={draft.from}
          onChange={(e) => set({ from: e.currentTarget.value })}
        />
        <TextInput
          type="date"
          label={t('audit.to')}
          value={draft.to}
          error={draft.from && draft.to && !valid ? t('audit.periodError') : null}
          onChange={(e) => set({ to: e.currentTarget.value })}
        />
        <Select
          label={t('audit.user')}
          placeholder={t('audit.any')}
          clearable
          searchable
          value={draft.userId}
          data={[...users].map(([value, label]) => ({ value, label }))}
          onChange={(v) => set({ userId: v })}
        />
        <Select
          className="audit-type"
          label={t('audit.eventType')}
          placeholder={t('audit.any')}
          clearable
          searchable
          value={draft.eventType}
          data={eventOptions(roles)}
          onChange={(v) => set({ eventType: v })}
        />
        <Select
          label={t('audit.result')}
          placeholder={t('audit.any')}
          clearable
          value={draft.result}
          data={RESULTS.map((r) => ({ value: r, label: t(`audit.results.${r}`) }))}
          onChange={(v) => set({ result: RESULTS.find((r) => r === v) ?? null })}
        />
        <div className="audit-filter-actions">
          <Button disabled={!valid || !changed} onClick={() => setFilters(draft)}>
            {t('audit.apply')}
          </Button>
          <Button
            variant="default"
            onClick={() => {
              const d = defaultFilters();
              setDraft(d);
              setFilters(d);
            }}
          >
            {t('audit.reset')}
          </Button>
          {canExport ? (
            <Button variant="default" loading={exportCsv.isPending} onClick={() => exportCsv.mutate()}>
              ⇩ {t('audit.export')}
            </Button>
          ) : null}
        </div>
        {canExport ? <p className="auth-hint audit-hint">{t('audit.exportHint')}</p> : null}
        <ErrorText error={exportError} />
      </section>

      <ErrorText error={journal.error} />
      <div className="audit-body">
        <section className="sec">
          {journal.data && items.length === 0 ? <p className="sys-empty">{t('audit.empty')}</p> : null}
          {items.length > 0 ? (
            <table className="t sys-table audit-table">
              <thead>
                <tr>
                  <th>{t('audit.time')}</th>
                  <th>{t('audit.event')}</th>
                  <th>{t('audit.category')}</th>
                  <th>{t('audit.user')}</th>
                  <th>IP</th>
                  <th>{t('audit.result')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id} className={selected?.id === e.id ? 'on' : undefined}>
                    <td className="sub nowrap">{formatDateTime(e.ts, tz)}</td>
                    <td>
                      <button type="button" className="link-btn" onClick={() => setSelected(e)}>
                        {eventTitle(e.event_type)}
                      </button>
                      <div className="sub mono">{e.event_type}</div>
                    </td>
                    <td>{categoryTitle(e.category)}</td>
                    <td className="mono">{e.login ?? '—'}</td>
                    <td className="mono sub">{e.ip ?? '—'}</td>
                    <td>
                      <ResultPill result={e.result} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {journal.hasNextPage ? (
            <Button
              mt="sm"
              variant="default"
              loading={journal.isFetchingNextPage}
              onClick={() => void journal.fetchNextPage()}
            >
              {t('audit.more')}
            </Button>
          ) : null}
        </section>
        {selected ? <EntryDetails entry={selected} tz={tz} onClose={() => setSelected(null)} /> : null}
      </div>
      {modal}
    </>
  );
}

function ResultPill({ result }: { result: AuditResult }) {
  const { t } = useTranslation();
  const tone = result === 'success' ? 'ok' : result === 'denied' ? 'bad' : 'warn';
  return <span className={`pill ${tone}`}>{t(`audit.results.${result}`)}</span>;
}

function EntryDetails({ entry, tz, onClose }: { entry: Entry; tz: string | undefined; onClose: () => void }) {
  const { t } = useTranslation();
  const rows: [string, ReactNode][] = [
    [t('audit.time'), formatDateTime(entry.ts, tz)],
    [
      t('audit.event'),
      <span key="e" className="mono">
        {entry.event_type}
      </span>,
    ],
    [t('audit.category'), categoryTitle(entry.category)],
    [t('audit.result'), <ResultPill key="r" result={entry.result} />],
    [t('audit.user'), entry.login ?? '—'],
    ['IP', entry.ip ?? '—'],
    ['User-Agent', entry.user_agent ?? '—'],
    [t('audit.object'), entry.object_type ? `${entry.object_type} · ${entry.object_id ?? '—'}` : '—'],
  ];
  return (
    <aside className="sec audit-details" aria-label={t('audit.details')}>
      <div className="sys-list-head">
        <h3>{eventTitle(entry.event_type)}</h3>
        <span className="sp" />
        <button type="button" className="icon-btn" aria-label={t('common.close')} onClick={onClose}>
          ×
        </button>
      </div>
      <dl className="sys-dl">
        {rows.map(([k, v]) => (
          <Row key={k} label={k} value={v} />
        ))}
      </dl>
      <span className="auth-label">{t('audit.detailsJson')}</span>
      <pre className="mono audit-json">{JSON.stringify(entry.details, null, 2)}</pre>
      <p className="auth-hint">{t('audit.factOnly')}</p>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}
