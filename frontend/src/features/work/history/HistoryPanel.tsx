/**
 * FE-028 · панель истории листа (FR-TREE-25, 11.5 №3; DESIGN.md 9.9).
 *
 * 430 px рядом со строкой: шапка «История: <название> ✕»; запись — аватар 24 px, «O/R/P ~~было~~ →
 * **стало**», под ним «кто · когда»; у текущего значения — серая «текущее», у прошлых — «Вернуть
 * 30–40–60». «Вернуть» записывает значение новой правкой (PATCH): она попадает в историю, в ленту
 * обсуждения и сбрасывает «Проверено», как любая правка. Закрывается ✕, Esc и щелчком мимо.
 */
import { Button, CloseButton } from '@mantine/core';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { useSession } from '../../../app/session';
import { api, type components } from '../../../shared/api/client';
import { call, errorMessage } from '../../../shared/api/problem';
import { formatDateTime } from '../../../shared/format/date';
import { formatFork } from '../../../shared/format/number';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { userColor } from '../../../shared/ui/userColor';
import type { TreeStore } from '../store/treeStore';
import { useTree } from '../store/useProjectTree';
import { historyRows, type Fork, type HistoryRow } from './history';

type ApiNode = components['schemas']['Node'];

export const historyKey = (nodeId: string) => ['node-history', nodeId] as const;

const PANEL_WIDTH = 430;

const fork = (f: Fork) => formatFork(f.o, f.r, f.p);

interface CommentLine {
  tag_id: string | null;
  text: string;
}

export function HistoryPanel({
  nodeId,
  store,
  anchor,
  canRevert,
  onConfirm,
  roleOf,
  typeName,
  tags,
  onClose,
}: {
  nodeId: string;
  store: TreeStore;
  /** Прямоугольник строки узла; null — строка прокручена из вида. */
  anchor: () => DOMRect | null;
  canRevert: boolean;
  onConfirm: (node: ApiNode, projectVersion: number) => void;
  /** «модератор» у участника с этой ролью в проекте. */
  roleOf: (userId: string) => string | null;
  typeName: (typeId: string) => string;
  tags: ReadonlyMap<string, string>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  const client = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number; max: number }>({ top: 80, left: 80, max: 520 });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [shown, setShown] = useState<ReadonlySet<string>>(new Set());
  const node = useTree(store, (s) => s.nodes.get(nodeId));
  const pending = useTree(store, (s) => s.pending.get(nodeId));
  const history = useInfiniteQuery({
    queryKey: historyKey(nodeId),
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/nodes/{id}/history', {
          params: { path: { id: nodeId }, query: pageParam ? { cursor: pageParam } : {} },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });

  // рядом со строкой; при прокрутке дерева панель едет вместе со строкой
  useLayoutEffect(() => {
    const update = () => {
      const rect = anchor();
      if (!rect) return;
      const height = ref.current?.offsetHeight ?? 360;
      const left = Math.max(8, Math.min(rect.left + 360, window.innerWidth - PANEL_WIDTH - 16));
      // снизу строки, если хватает места хотя бы на 300 px; иначе над строкой
      const below = window.innerHeight - rect.bottom - 12;
      const top = below >= Math.min(height, 300) ? rect.bottom + 4 : Math.max(8, rect.top - Math.min(height, 520) - 4);
      const max = Math.min(520, window.innerHeight - top - 8);
      setPlace((prev) => (prev.top === top && prev.left === left && prev.max === max ? prev : { top, left, max }));
    };
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
    };
  }, [anchor, history.data, shown]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const onDown = (e: MouseEvent) => {
      if (ref.current && e.target instanceof Node && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [onClose]);

  if (!node) return null;
  const current: Fork = {
    o: pending?.o !== undefined ? pending.o : node.o,
    r: pending?.r !== undefined ? pending.r : node.r,
    p: pending?.p !== undefined ? pending.p : node.p,
  };
  const entries = history.data?.pages.flatMap((page) => page.items) ?? [];
  const rows = historyRows(entries, current);

  const revert = async (row: HistoryRow, value: Fork) => {
    setBusy(row.entry.id);
    setError(null);
    try {
      const result = await call(() =>
        api.PATCH('/nodes/{id}', {
          params: { path: { id: nodeId } },
          body: { base_version: node.version, changes: { o: value.o, r: value.r, p: value.p } },
        }),
      );
      onConfirm(result.node as ApiNode, result.project_version);
      await client.invalidateQueries({ queryKey: historyKey(nodeId) });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const describe = (row: HistoryRow): ReactNode => {
    switch (row.kind) {
      case 'fork':
        return (
          <>
            {t('history.fork')} <s>{fork(row.before)}</s> → <b>{fork(row.after)}</b>
          </>
        );
      case 'create':
        return row.after.o !== null || row.after.r !== null || row.after.p !== null ? (
          <>
            {t('history.createdWith')} <b>{fork(row.after)}</b>
          </>
        ) : (
          t('history.created')
        );
      case 'title':
        return (
          <>
            {t('history.title')} <s>{String(row.was ?? '')}</s> → <b>{String(row.now ?? '')}</b>
          </>
        );
      case 'multiplier':
        return (
          <>
            ×N <s>{String(row.was ?? 1)}</s> → <b>{String(row.now ?? 1)}</b>
          </>
        );
      case 'type':
        return (
          <>
            {t('history.type')} <s>{row.was ? typeName(String(row.was)) : '—'}</s> →{' '}
            <b>{row.now ? typeName(String(row.now)) : '—'}</b>
          </>
        );
      case 'split':
        return (
          <>
            {t('history.split')} <s>{fork(row.before)}</s>
          </>
        );
      case 'collapse':
        return (
          <>
            {t('history.collapse')} <b>{fork(row.after)}</b>
          </>
        );
      default:
        return t(`history.action.${row.kind}`);
    }
  };

  const comment = (value: unknown) => {
    const lines = Array.isArray(value) ? (value as CommentLine[]) : [];
    if (!lines.length) return <i>{t('history.noComment')}</i>;
    return lines.map((line, i) => (
      <div key={i}>
        {line.tag_id ? <b>{tags.get(line.tag_id) ?? ''} </b> : null}
        {line.text}
      </div>
    ));
  };

  return (
    <div
      ref={ref}
      className="history-panel"
      role="dialog"
      aria-label={t('history.heading', { name: node.title })}
      style={{ top: place.top, left: place.left, width: PANEL_WIDTH, maxHeight: place.max }}
    >
      <div className="hp-head">
        <b>{t('history.heading', { name: node.title })}</b>
        <CloseButton size="sm" aria-label={t('common.close')} onClick={onClose} />
      </div>
      {error ? (
        <div className="hp-error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="hp-list">
        {history.error ? <ErrorText error={history.error} /> : null}
        {history.isPending ? <div className="hp-empty">{t('common.loading')}</div> : null}
        {!history.isPending && !rows.length && !history.error ? (
          <div className="hp-empty">{t('history.empty')}</div>
        ) : null}
        {rows.map((row) => {
          const user = row.entry.user;
          const role = user ? roleOf(user.id) : null;
          const open = shown.has(row.entry.id);
          return (
            <div key={row.entry.id} className="hp-row">
              <span className="av" style={{ background: user ? userColor(user) : 'var(--faint)' }} aria-hidden="true">
                {user?.initials ?? '·'}
              </span>
              <div className="hp-what">
                <div className="hp-change">{row.kind === 'comment' ? t('history.comment') : describe(row)}</div>
                <div className="hp-who">
                  {user ? user.full_name : t('history.system')}
                  {role ? ` (${role})` : ''} · {formatDateTime(row.entry.created_at, timeZone)}
                </div>
                {row.kind === 'comment' && open ? (
                  <div className="hp-comment">
                    <div className="hp-k">{t('history.was')}</div>
                    {comment(row.was)}
                    <div className="hp-k">{t('history.became')}</div>
                    {comment(row.now)}
                  </div>
                ) : null}
              </div>
              <div className="hp-act">
                {row.current ? (
                  <Button size="xs" variant="default" disabled>
                    {t('history.current')}
                  </Button>
                ) : row.revert && canRevert ? (
                  <Button
                    size="xs"
                    variant="default"
                    loading={busy === row.entry.id}
                    disabled={busy !== null}
                    onClick={() => row.revert && void revert(row, row.revert)}
                  >
                    {t('history.revert', { fork: fork(row.revert) })}
                  </Button>
                ) : row.kind === 'comment' ? (
                  <Button
                    size="xs"
                    variant="default"
                    aria-expanded={open}
                    onClick={() =>
                      setShown((prev) => {
                        const next = new Set(prev);
                        if (next.has(row.entry.id)) next.delete(row.entry.id);
                        else next.add(row.entry.id);
                        return next;
                      })
                    }
                  >
                    {open ? t('history.hide') : t('history.show')}
                  </Button>
                ) : null}
              </div>
            </div>
          );
        })}
        {history.hasNextPage ? (
          <Button
            variant="subtle"
            size="xs"
            loading={history.isFetchingNextPage}
            onClick={() => void history.fetchNextPage()}
          >
            {t('history.more')}
          </Button>
        ) : null}
      </div>
      <div className="hp-foot">{t('history.note')}</div>
    </div>
  );
}
