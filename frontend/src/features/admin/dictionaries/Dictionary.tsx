/**
 * FE-071 · шаблон «список + форма справа» для справочника (DESIGN.md 5.3, 10.13): таблица с
 * поиском слева, форма выбранной записи справа. Неудаляемые записи — без кнопки «Удалить» и с
 * плашкой «системная» (или «сквозная», «по умолчанию»); причина запрета — подсказкой под формой.
 */
import { Button, Checkbox, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { ListWithForm } from '../../system/layout/SystemLayout';
import { dictKey, type DictKey, type Locks } from './dictionaries';

type Base = { name?: string; is_active: boolean };

export type DictConfig<T extends Base, D> = {
  kind: DictKey;
  load: () => Promise<{ items: T[] }>;
  keyOf: (r: T) => string;
  nameOf: (r: T) => string;
  headers: string[];
  cells: (r: T) => ReactNode[];
  empty: D;
  toDraft: (r: T) => D;
  /** Можно ли сохранить черновик. */
  valid: (d: D) => boolean;
  Fields: (p: { draft: D; set: (patch: Partial<D>) => void; record: T | null; locks: Locks }) => ReactNode;
  save: (d: D & { is_active: boolean }, r: T | null) => Promise<T>;
  remove: (r: T) => Promise<unknown>;
  locks?: (r: T) => Locks;
};

const NONE: Locks = { pill: null, noDelete: null, noDeactivate: null };

export function Dictionary<T extends Base, D>({ config }: { config: DictConfig<T, D> }) {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<string | 'new' | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const items = useQuery({ queryKey: dictKey(config.kind), queryFn: config.load });
  const all = items.data?.items ?? [];
  const s = q.trim().toLocaleLowerCase('ru');
  const shown = s ? all.filter((r) => config.nameOf(r).toLocaleLowerCase('ru').includes(s)) : all;
  const current = all.find((r) => config.keyOf(r) === selected) ?? null;
  const locksOf = (r: T) => config.locks?.(r) ?? NONE;

  return (
    <>
      <ErrorText error={items.error} />
      <ListWithForm
        list={
          <section className="sec">
            <div className="sys-list-head adm-filters">
              <TextInput
                className="adm-search"
                aria-label={t('admin.dict.search')}
                placeholder={t('admin.dict.search')}
                value={q}
                onChange={(e) => setQ(e.currentTarget.value)}
              />
              <span className="sp" />
              <Button size="xs" onClick={() => setSelected('new')}>
                + {t('admin.users.add')}
              </Button>
            </div>
            {items.data && shown.length === 0 ? <p className="sys-empty">{t('admin.dict.empty')}</p> : null}
            {shown.length > 0 ? (
              <table className="t sys-table">
                <thead>
                  <tr>
                    {config.headers.map((h) => (
                      <th key={h}>{t(h)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const key = config.keyOf(r);
                    const [first, ...rest] = config.cells(r);
                    const pill = locksOf(r).pill;
                    return (
                      <tr key={key} className={[key === selected ? 'on' : '', r.is_active ? '' : 'off'].join(' ')}>
                        <td>
                          <button type="button" className="link-btn" onClick={() => setSelected(key)}>
                            {first}
                          </button>
                          {pill ? <span className="pill gray adm-pill">{t(`admin.dict.pill.${pill}`)}</span> : null}
                          {r.is_active ? null : <span className="pill warn adm-pill">{t('admin.dict.inactive')}</span>}
                        </td>
                        {rest.map((cell, i) => (
                          <td key={config.headers[i + 1] ?? i}>{cell}</td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </section>
        }
        form={
          selected === 'new' ? (
            <Form
              key="new"
              config={config}
              record={null}
              locks={NONE}
              justSaved={false}
              onEdit={() => setSaved(null)}
              onSaved={(key) => {
                setSaved(key);
                setSelected(key);
              }}
            />
          ) : current ? (
            <Form
              key={config.keyOf(current)}
              config={config}
              record={current}
              locks={locksOf(current)}
              justSaved={saved === config.keyOf(current)}
              onEdit={() => setSaved(null)}
              onSaved={setSaved}
              onDeleted={() => setSelected(null)}
            />
          ) : null
        }
      />
    </>
  );
}

function Form<T extends Base, D>({
  config,
  record,
  locks,
  justSaved,
  onEdit,
  onSaved,
  onDeleted,
}: {
  config: DictConfig<T, D>;
  record: T | null;
  locks: Locks;
  justSaved: boolean;
  onEdit: () => void;
  onSaved: (key: string) => void;
  onDeleted?: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<D>(record ? config.toDraft(record) : config.empty);
  const [active, setActive] = useState(record?.is_active ?? true);
  const [deleting, setDeleting] = useState(false);
  const set = (patch: Partial<D>) => {
    onEdit();
    setDraft((d) => ({ ...d, ...patch }));
  };
  // справочники читают и другие экраны (настройки проекта, дерево) — их кэш тоже сбрасывается
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['admin', 'dict'] });
    void qc.invalidateQueries({ queryKey: ['dict'] });
  };

  const save = useMutation({
    mutationFn: () => config.save({ ...draft, is_active: active }, record),
    onSuccess: (r) => {
      refresh();
      onSaved(config.keyOf(r));
    },
  });
  const remove = useMutation({
    mutationFn: () => (record ? config.remove(record) : Promise.resolve(null)),
    onSuccess: () => {
      setDeleting(false);
      refresh();
      onDeleted?.();
    },
  });

  const hint = locks.noDelete ?? locks.noDeactivate;
  return (
    <div className="adm-dict-form">
      <h3>
        {record ? config.nameOf(record) : t('admin.dict.new')}
        {locks.pill ? <span className="pill gray adm-pill">{t(`admin.dict.pill.${locks.pill}`)}</span> : null}
      </h3>
      <config.Fields draft={draft} set={set} record={record} locks={locks} />
      <Checkbox
        mt="sm"
        label={t('admin.dict.active')}
        checked={active}
        disabled={Boolean(locks.noDeactivate)}
        onChange={(e) => {
          onEdit();
          setActive(e.currentTarget.checked);
        }}
      />
      {hint ? <p className="auth-hint adm-lock">{t(`admin.dict.lock.${hint}`)}</p> : null}
      <ErrorText error={save.error ?? remove.error} />
      {justSaved ? (
        <p className="auth-ok" role="status">
          ✓ {t('admin.dict.saved')}
        </p>
      ) : null}
      <div className="sys-actions">
        <Button disabled={!config.valid(draft)} loading={save.isPending} onClick={() => save.mutate()}>
          {record ? t('common.save') : t('admin.users.create')}
        </Button>
        {record && !locks.noDelete ? (
          <Button variant="default" color="red" onClick={() => setDeleting(true)}>
            {t('admin.dict.delete')}
          </Button>
        ) : null}
      </div>
      {record ? (
        <ConfirmDialog
          opened={deleting}
          title={t('admin.dict.deleteTitle', { name: config.nameOf(record) })}
          message={t('admin.dict.deleteText')}
          confirmLabel={t('admin.dict.delete')}
          danger
          busy={remove.isPending}
          onConfirm={() => remove.mutate()}
          onCancel={() => setDeleting(false)}
        />
      ) : null}
    </div>
  );
}
