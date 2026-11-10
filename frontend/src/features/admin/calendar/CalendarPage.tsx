/**
 * FE-072 · «Производственный календарь» (SPEC 7.5, GAP-03, Q-43): год с 12 месяцами, ручная правка
 * дня щелчком, загрузка CSV data.gov.ru с предпросмотром по месяцам перед сохранением. Года без
 * календаря считаются по Пн–Пт — это видно в шапке.
 */
import { Button, Group, Select } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { AdminLayout } from '../layout/AdminLayout';
import {
  dayLabel,
  dayNumber,
  daysOf,
  exceptionsOf,
  isWeekend,
  isWorking,
  monthName,
  monthWeeks,
  sameExceptions,
  toggle,
  workingDays,
  type Exceptions,
} from './calendar';

type Preview = components['schemas']['CalendarPreview'];

const calendarKey = ['admin', 'calendar'] as const;
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);
const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

export function CalendarPage({ now = new Date() }: { now?: Date }) {
  const { t } = useTranslation();
  const current = now.getFullYear();
  const [year, setYear] = useState(current);
  const [done, setDone] = useState<string | null>(null);
  const calendars = useQuery({
    queryKey: calendarKey,
    queryFn: () => call(() => api.GET('/admin/calendar')),
  });
  const years = new Set([current - 1, current, current + 1, ...(calendars.data?.items ?? []).map((c) => c.year)]);
  const saved = calendars.data?.items.find((c) => c.year === year) ?? null;

  return (
    <AdminLayout active="calendar" title={t('admin.menu.calendar')} subtitle={t('admin.calendar.subtitle')}>
      <ErrorText error={calendars.error} />
      {calendars.data ? (
        <Year
          key={`${year}:${saved ? 'saved' : 'none'}`}
          year={year}
          years={[...years].sort((a, b) => a - b)}
          initial={exceptionsOf(saved?.days ?? [])}
          hasCalendar={saved !== null}
          done={done}
          setDone={setDone}
          onYear={(y) => {
            setDone(null);
            setYear(y);
          }}
        />
      ) : null}
    </AdminLayout>
  );
}

function Year({
  year,
  years,
  initial,
  hasCalendar,
  done,
  setDone,
  onYear,
}: {
  year: number;
  years: number[];
  initial: Exceptions;
  hasCalendar: boolean;
  done: string | null;
  setDone: (s: string | null) => void;
  onYear: (y: number) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [ex, setEx] = useState<Exceptions>(initial);
  const [deleting, setDeleting] = useState(false);
  const [preview, setPreview] = useState<{ file: File; data: Preview } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const dirty = !sameExceptions(ex, initial);
  const refresh = () => qc.invalidateQueries({ queryKey: calendarKey });

  const save = useMutation({
    mutationFn: () =>
      call(() => api.PUT('/admin/calendar/{year}', { params: { path: { year } }, body: { year, days: daysOf(ex) } })),
    onSuccess: async () => {
      await refresh();
      setDone(t('admin.calendar.saved'));
    },
  });
  const remove = useMutation({
    mutationFn: () => call(() => api.DELETE('/admin/calendar/{year}', { params: { path: { year } } })),
    onSuccess: async () => {
      setDeleting(false);
      await refresh();
    },
  });
  const upload = useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) =>
      call(() =>
        api.POST('/admin/calendar', {
          body: { file: file as unknown as string, dry_run: dryRun },
          bodySerializer: (body) => {
            const form = new FormData();
            form.append('file', body.file as unknown as Blob, (body.file as unknown as File).name);
            form.append('dry_run', String(body.dry_run));
            return form;
          },
        }),
      ),
    onSuccess: async (data, { file }) => {
      if (!data.saved) {
        setPreview({ file, data });
        return;
      }
      setPreview(null);
      await refresh();
      onYear(data.year);
      setDone(t('admin.calendar.uploaded', { year: data.year }));
    },
  });

  const pick = (file: File | undefined) => {
    if (!file) return;
    setDone(null);
    upload.mutate({ file, dryRun: true });
  };

  return (
    <>
      <div className="sys-list-head cal-head">
        <Select
          aria-label={t('admin.calendar.year')}
          value={String(year)}
          allowDeselect={false}
          data={years.map((y) => String(y))}
          onChange={(v) => (v ? onYear(Number(v)) : undefined)}
          w={110}
        />
        <span className={`pill ${hasCalendar ? 'ok' : 'warn'}`}>
          {hasCalendar ? t('admin.calendar.loaded') : t('admin.calendar.none')}
        </span>
        <span className="sp" />
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          hidden
          aria-label={t('admin.calendar.file')}
          onChange={(e) => {
            pick(e.currentTarget.files?.[0]);
            e.currentTarget.value = '';
          }}
        />
        <Button size="xs" variant="default" loading={upload.isPending} onClick={() => input.current?.click()}>
          {t('admin.calendar.upload')}
        </Button>
        {hasCalendar ? (
          <Button size="xs" variant="default" color="red" onClick={() => setDeleting(true)}>
            {t('admin.calendar.delete')}
          </Button>
        ) : null}
      </div>
      <p className="sys-sub">{t('admin.calendar.csvHint')}</p>
      <ErrorText error={upload.error ?? save.error ?? remove.error} />
      {done ? (
        <p className="auth-ok" role="status">
          ✓ {done}
        </p>
      ) : null}

      {preview ? (
        <PreviewTable
          preview={preview.data}
          busy={upload.isPending}
          onSave={() => upload.mutate({ file: preview.file, dryRun: false })}
          onCancel={() => setPreview(null)}
        />
      ) : (
        <>
          <div className="cal-legend">
            <span className="cal-day">1</span> {t('admin.calendar.legend.working')}
            <span className="cal-day off">1</span> {t('admin.calendar.legend.off')}
            <span className="cal-day off ex">1</span> {t('admin.calendar.legend.holiday')}
            <span className="cal-day ex">1</span> {t('admin.calendar.legend.workingWeekend')}
          </div>
          <div className="cal-year">
            {MONTHS.map((m) => (
              <Month
                key={m}
                year={year}
                month={m}
                ex={ex}
                onToggle={(date) => {
                  setDone(null);
                  setEx((x) => toggle(x, date));
                }}
              />
            ))}
          </div>
          <div className="sys-actions">
            <Button disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
              {t('admin.calendar.save')}
            </Button>
            {dirty ? (
              <Button variant="default" onClick={() => setEx(initial)}>
                {t('admin.calendar.reset')}
              </Button>
            ) : null}
            <span className="sub">{t('admin.calendar.clickHint')}</span>
          </div>
        </>
      )}
      <ConfirmDialog
        opened={deleting}
        title={t('admin.calendar.deleteTitle', { year })}
        message={t('admin.calendar.deleteText')}
        confirmLabel={t('admin.calendar.delete')}
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setDeleting(false)}
      />
    </>
  );
}

function Month({
  year,
  month,
  ex,
  onToggle,
}: {
  year: number;
  month: number;
  ex: Exceptions;
  onToggle: (date: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="cal-month" aria-label={`${monthName(month)} ${year}`}>
      <h3>
        {monthName(month)}
        <span className="sub">{t('admin.calendar.workingDays', { count: workingDays(ex, year, month) })}</span>
      </h3>
      <table>
        <thead>
          <tr>
            {WEEKDAYS.map((w) => (
              <th key={w}>{w}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthWeeks(year, month).map((week) => (
            <tr key={week.find(Boolean) ?? ''}>
              {week.map((date, i) => {
                if (!date) return <td key={`e${i}`} />;
                const working = isWorking(ex, date);
                const exception = working === isWeekend(date);
                const cls = ['cal-day', working ? '' : 'off', exception ? 'ex' : ''].filter(Boolean).join(' ');
                return (
                  <td key={date}>
                    <button
                      type="button"
                      className={cls}
                      aria-pressed={!working}
                      aria-label={`${dayLabel(date)}, ${working ? t('admin.calendar.working') : t('admin.calendar.off')}`}
                      onClick={() => onToggle(date)}
                    >
                      {dayNumber(date)}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PreviewTable({
  preview,
  busy,
  onSave,
  onCancel,
}: {
  preview: Preview;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const days = (dates: string[]) => dates.map(dayNumber).join(', ') || '—';
  const total = preview.months.reduce((s, m) => s + m.working_days, 0);
  return (
    <section className="sec" aria-label={t('admin.calendar.previewTitle', { year: preview.year })}>
      <h3>{t('admin.calendar.previewTitle', { year: preview.year })}</h3>
      <p className="sys-sub">{t('admin.calendar.previewHint')}</p>
      <table className="t sys-table">
        <thead>
          <tr>
            <th>{t('admin.calendar.month')}</th>
            <th>{t('admin.calendar.workingCount')}</th>
            <th>{t('admin.calendar.holidays')}</th>
            <th>{t('admin.calendar.workingWeekends')}</th>
          </tr>
        </thead>
        <tbody>
          {preview.months.map((m) => (
            <tr key={m.month}>
              <td>{monthName(m.month)}</td>
              <td className="num">{m.working_days}</td>
              <td>{days(m.non_working)}</td>
              <td>{days(m.working_weekends)}</td>
            </tr>
          ))}
          <tr className="cal-total">
            <td>{t('admin.calendar.total')}</td>
            <td className="num">{total}</td>
            <td />
            <td />
          </tr>
        </tbody>
      </table>
      <Group mt="sm">
        <Button loading={busy} onClick={onSave}>
          {t('admin.calendar.savePreview', { year: preview.year })}
        </Button>
        <Button variant="default" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
      </Group>
    </section>
  );
}
