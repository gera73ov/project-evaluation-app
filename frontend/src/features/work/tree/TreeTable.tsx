/**
 * FE-022 · таблица-дерево рабочего экрана (FR-TREE-10, FR-TREE-13, FR-TREE-15, 11.4 №7, №9–11, №15,
 * «Чужие ветки», FR-UI-03; DESIGN.md 9.4–9.6, 9.11).
 *
 * Строки виртуализированы (@tanstack/react-virtual): в DOM не больше ~150 строк при 5 000 узлах.
 * Строки фазы и дисциплины прилипают под шапкой столбцов, пока видны их узлы: поверх прокрутки
 * рисуются копии ближайших сверху строк фазы и дисциплины. Ячейки пока только показывают значения;
 * ввод — FE-025, кнопки «+» и «⋯» — FE-027, статус ветки и «Проверено» — FE-029.
 */
import { Tooltip } from '@mantine/core';
import { useVirtualizer } from '@tanstack/react-virtual';
import { memo, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import {
  DEFAULT_LARGE_LEAF_HOURS,
  branchKey,
  candidate,
  largeLeafThreshold,
  sigmaOf,
  totalsP80,
  type BranchStatus,
  type Dec,
  type NodeResult,
} from '../../../shared/calc';
import { formatHours, formatHoursInput, formatNumber, formatPercent } from '../../../shared/format/number';
import { StatusBadge } from '../../../shared/ui/StatusBadge';
import { nodeTypeSymbol } from '../../../shared/ui/icons/nodeTypes';
import type { TreeNode, TreeStore } from '../store/treeStore';
import { useTree } from '../store/useProjectTree';
import { MAX_INDENT_DEPTH, buildRows, indentOf, type TreeRow } from './rows';

export const ROW_HEIGHT = 38;

export interface TreeContext {
  /** Может ли пользователь править узлы ветки этой дисциплины (своя ветка или модератор). */
  canEdit: (disciplineId: string | null) => boolean;
  /** Дисциплины без эксперта (11.6 №6). */
  withoutExpert: ReadonlySet<string>;
  disciplineNames: ReadonlyMap<string, string>;
  nodeTypes: ReadonlyMap<string, { name: string; icon: string }>;
  tags: ReadonlyMap<string, string>;
  pmPercent: string;
  pmReason: string;
  /** Модератор: строка УП ведёт в настройки. */
  settingsHref: string | null;
}

interface CommentLine {
  tag_id: string | null;
  text: string;
}

function extra<T>(node: TreeNode | undefined, key: string): T | undefined {
  if (!node) return undefined;
  return new Map(Object.entries(node.extra)).get(key) as T | undefined;
}

/** Причина «неверного» листа для Σ E: «O > R» или «R > P». */
export function invalidReason(o: Dec | null, r: Dec | null): string {
  return o !== null && r !== null && o.gt(r) ? 'O > R' : 'R > P';
}

function SumTooltip({ result, children }: { result: NodeResult; children: ReactNode }) {
  const { t } = useTranslation();
  const leaf = result.isLeaf ? result.leaf : null;
  const label = leaf ? (
    <>
      <span className="tip-k">{t('tree.tip.fork')}</span> {formatHoursInput(result.node.o)}–
      {formatHoursInput(result.node.r)}–{formatHoursInput(result.node.p)}
      {result.node.multiplier > 1 ? ` × ${result.node.multiplier}` : ''} · <span className="tip-k">σ</span>{' '}
      {formatNumber(leaf.sigma, 1)} · <span className="tip-k">P80</span> {formatHours(totalsP80(result.totals))}
    </>
  ) : (
    <>
      <span className="tip-k">Σ O–R–P</span> {formatHours(result.totals.sumO)}–{formatHours(result.totals.sumR)}–
      {formatHours(result.totals.sumP)} · <span className="tip-k">σ</span> {formatNumber(sigmaOf(result.totals), 1)} ·{' '}
      <span className="tip-k">P80</span> {formatHours(totalsP80(result.totals))}
    </>
  );
  return (
    <Tooltip label={label} openDelay={300} position="top-end" withinPortal>
      <span className="e-tip" tabIndex={0}>
        {children}
      </span>
    </Tooltip>
  );
}

function Comment({ lines, ctx, placeholder }: { lines: CommentLine[]; ctx: TreeContext; placeholder: boolean }) {
  const { t } = useTranslation();
  const [first, ...rest] = lines;
  if (!first) return placeholder ? <span className="cm-empty">{t('tree.commentPlaceholder')}</span> : null;
  const tag = first.tag_id ? ctx.tags.get(first.tag_id) : undefined;
  const more = rest.map((l) => (l.tag_id ? ctx.tags.get(l.tag_id) : undefined)).filter(Boolean);
  return (
    <span className="cm-line">
      {tag ? <span className="tag">{tag}</span> : null} {first.text}
      {rest.length ? (
        <span className="tag more">
          +{rest.length}
          {more.length ? ` ${more.join(', ')}` : ''}
        </span>
      ) : null}
    </span>
  );
}

function Discussion({ node }: { node: TreeNode | undefined }) {
  const { t } = useTranslation();
  const count = extra<number>(node, 'messages_count') ?? 0;
  if (!count) return null;
  const open = (extra<number>(node, 'open_questions') ?? 0) > 0;
  const mine = (extra<number>(node, 'questions_to_me') ?? 0) > 0;
  return (
    <span
      className={open ? 'disc open' : 'disc'}
      aria-label={t('tree.discussion', { count }) + (mine ? `, ${t('tree.questionToMe')}` : '')}
    >
      💬 {count}
      {mine ? <span className="dot" aria-hidden="true" /> : null}
    </span>
  );
}

interface RowProps {
  row: TreeRow;
  result: NodeResult | undefined;
  node: TreeNode | undefined;
  status: BranchStatus | undefined;
  ctx: TreeContext;
  pmE: Dec | null;
  largeThreshold: Dec | null;
  onToggle: (id: string) => void;
}

const Row = memo(function Row({ row, result, node, status, ctx, pmE, largeThreshold, onToggle }: RowProps) {
  const { t } = useTranslation();
  if (row.kind === 'pm') {
    return (
      <div className="tr pm" role="row">
        <div className="td node" role="cell" style={{ paddingLeft: indentOf(0) + 14 + 6 }}>
          <span className="title">{t('tree.pm')}</span>
          {ctx.settingsHref ? (
            <Link to={ctx.settingsHref} className="pill gray">
              {t('tree.pmShare', { percent: formatPercent(ctx.pmPercent) })}
            </Link>
          ) : (
            <span className="pill gray">{t('tree.pmShare', { percent: formatPercent(ctx.pmPercent) })}</span>
          )}
        </div>
        <div className="td" role="cell" />
        <div className="td cm" role="cell">
          {ctx.pmReason ? t('tree.pmReason', { reason: ctx.pmReason }) : null}
        </div>
        <div className="td" role="cell" />
        <div className="td" role="cell" />
        <div className="td" role="cell" />
        <div className="td e" role="cell">
          {pmE ? formatHours(pmE) : '—'}
        </div>
        <div className="td" role="cell" />
      </div>
    );
  }
  if (!result || !row.id) return null;
  const id = row.id;
  const editable = ctx.canEdit(row.disciplineId);
  const notNeeded = status === 'not_needed';
  const leaf = row.kind === 'leaf' ? result.leaf : null;
  const state = leaf?.state;
  const errorRow = state === 'empty' || state === 'invalid';
  const classes = ['tr', row.kind];
  if (errorRow) classes.push('err');
  if (notNeeded) classes.push('not-needed');
  const toggle = row.hasChildren ? (
    <button
      type="button"
      className="tg"
      aria-expanded={!row.collapsed}
      aria-label={t(row.collapsed ? 'tree.expand' : 'tree.collapse', { name: result.node.title })}
      onClick={() => onToggle(id)}
    >
      {row.collapsed ? '▸' : '▾'}
    </button>
  ) : (
    <span className="tg" aria-hidden="true" />
  );
  const type = node?.type_id ? ctx.nodeTypes.get(node.type_id) : undefined;
  const big = leaf && largeThreshold ? candidate(result.node, leaf, largeThreshold).large : false;
  const comments = extra<CommentLine[] | null>(node, 'comment_lines') ?? [];
  const reviewed = extra<unknown>(node, 'reviewed_by');
  const self = extra<boolean>(node, 'self_review');
  const foreign = row.kind === 'discipline' && !editable;
  const roTitle = editable
    ? undefined
    : t('tree.foreignHint', { name: (row.disciplineId && ctx.disciplineNames.get(row.disciplineId)) ?? '' });

  let sum: ReactNode = formatHours(result.totals.e);
  if (state === 'empty') sum = <span className="bad-note">{t('tree.unaccounted')}</span>;
  else if (state === 'invalid') sum = <span className="bad-note">{invalidReason(result.node.o, result.node.r)}</span>;

  const fork = (field: 'o' | 'r' | 'p') => {
    const { o, r, p } = result.node;
    const value = field === 'o' ? o : field === 'r' ? r : p;
    const wrong =
      state === 'invalid' &&
      ((field === 'o' && result.node.o !== null && result.node.r !== null && result.node.o.gt(result.node.r)) ||
        (field === 'r' &&
          result.node.r !== null &&
          ((result.node.o !== null && result.node.o.gt(result.node.r)) ||
            (result.node.p !== null && result.node.r.gt(result.node.p)))) ||
        (field === 'p' && result.node.p !== null && result.node.r !== null && result.node.r.gt(result.node.p)));
    const cls = ['cell'];
    if (!editable) cls.push('ro');
    if (state === 'empty') cls.push('empty');
    if (wrong) cls.push('wrong');
    if (state === 'zero') cls.push('zero');
    return (
      <div className="td num" role="cell">
        <span className={cls.join(' ')} {...(roTitle ? { title: roTitle } : {})}>
          {formatHoursInput(value)}
        </span>
      </div>
    );
  };

  return (
    <div className={classes.join(' ')} role="row" aria-level={row.depth + 1} data-node={id}>
      <div className="td node" role="cell" style={{ paddingLeft: indentOf(row.depth) }}>
        {toggle}
        {row.kind === 'node' || row.kind === 'leaf' ? (
          <span className="ic" title={type?.name}>
            {nodeTypeSymbol(type?.icon)}
            {row.depth > MAX_INDENT_DEPTH ? <span className="lvl">{row.depth}</span> : null}
          </span>
        ) : null}
        <span className="title" title={result.node.title}>
          {result.node.title}
        </span>
        {big ? (
          <span
            className="big"
            title={t('tree.large', {
              e: formatHours(leaf?.eUnit ?? '0'),
              limit: formatNumber(largeThreshold ?? '0', 0),
            })}
          >
            ◆
          </span>
        ) : null}
        {row.kind === 'discipline' && status ? <StatusBadge kind="branch" status={status} /> : null}
        {foreign ? <span className="foreign">· {t('tree.foreign')}</span> : null}
        {row.kind === 'discipline' && row.disciplineId && ctx.withoutExpert.has(row.disciplineId) ? (
          <span className="pill warn">⚠ {t('tree.noExpert')}</span>
        ) : null}
        <Discussion node={node} />
      </div>
      <div className="td mul-c" role="cell">
        {row.kind === 'leaf' ? (
          <span className={result.node.multiplier === 1 ? 'mul one' : 'mul'}>×{result.node.multiplier}</span>
        ) : null}
      </div>
      <div className="td cm" role="cell">
        {row.kind === 'discipline' && !row.hasChildren ? (
          <span className="cm-empty">{t('tree.emptyBranch')}</span>
        ) : row.kind === 'leaf' || row.kind === 'node' ? (
          <Comment lines={comments} ctx={ctx} placeholder={editable && row.kind === 'leaf'} />
        ) : null}
      </div>
      {row.kind === 'leaf' ? (
        <>
          {fork('o')}
          {fork('r')}
          {fork('p')}
        </>
      ) : (
        <>
          <div className="td" role="cell" />
          <div className="td" role="cell" />
          <div className="td" role="cell" />
        </>
      )}
      <div className={state === 'zero' ? 'td e zero' : 'td e'} role="cell">
        {state === 'empty' || state === 'invalid' ? sum : <SumTooltip result={result}>{sum}</SumTooltip>}
      </div>
      <div className="td rv" role="cell">
        {reviewed ? (
          self ? (
            <span className="half" title={t('tree.selfReview')} aria-label={t('tree.selfReview')} />
          ) : (
            <span className="ok-mark" aria-label={t('tree.reviewed')}>
              ✓
            </span>
          )
        ) : null}
      </div>
    </div>
  );
});

export function TreeTable({ store, ctx, height }: { store: TreeStore; ctx: TreeContext; height?: number | string }) {
  const { t } = useTranslation();
  const revision = useTree(store, (s) => s.revision);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [scrollTop, setScrollTop] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const state = store.getState();
  const { calc, children, settings, nodes, pending, branchStatus, result } = state;
  const rows = useMemo(
    () => (calc && settings ? buildRows(calc, children, settings, collapsed) : []),
    // revision меняется при каждом изменении расчёта
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [revision, collapsed],
  );
  // виртуализатор не мемоизируется компилятором React — строки перерисовываются по revision
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    initialRect: { width: 1366, height: 900 },
  });
  const largeThreshold = settings ? largeLeafThreshold(settings.detailLevel, DEFAULT_LARGE_LEAF_HOURS) : null;

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (!calc || !settings) return null;
  const items = virtualizer.getVirtualItems();
  const rowProps = (row: TreeRow): RowProps => {
    const base = row.id ? nodes.get(row.id) : undefined;
    const edit = row.id ? pending.get(row.id) : undefined;
    return {
      row,
      result: row.id ? calc.nodes.get(row.id) : undefined,
      node: base && edit ? { ...base, ...edit } : base,
      status: row.disciplineId ? branchStatus.get(branchKey(row.phaseId, row.disciplineId)) : undefined,
      ctx,
      pmE: result?.pm.e ?? null,
      largeThreshold,
      onToggle: toggle,
    };
  };

  // прилипающие строки фазы и дисциплины первой видимой строки (FR-TREE-13)
  const top = scrollTop;
  // строка под прилипшими фазой и дисциплиной (их не больше двух)
  const firstIndex = items.find((i) => i.end > top + 2 * ROW_HEIGHT)?.index ?? 0;
  const sticky: TreeRow[] = [];
  if (top > 0) {
    let phase: TreeRow | undefined;
    let discipline: TreeRow | undefined;
    for (let i = firstIndex; i >= 0 && !phase; i--) {
      const r = rows.at(i);
      if (!r) continue;
      if (r.kind === 'discipline' && !discipline) discipline = r;
      if (r.kind === 'phase') phase = r;
    }
    if (phase && rows.indexOf(phase) < firstIndex) sticky.push(phase);
    if (discipline && discipline.phaseId === phase?.phaseId && rows.indexOf(discipline) < firstIndex) {
      sticky.push(discipline);
    }
  }

  return (
    <div className="tree" role="treegrid" aria-label={t('tree.label')} aria-rowcount={rows.length}>
      <div className="tr th" role="row">
        <div className="td node" role="columnheader">
          {t('tree.col.node')}
        </div>
        <div className="td mul-c" role="columnheader">
          ×N
        </div>
        <div className="td cm" role="columnheader">
          {t('tree.col.comment')}
        </div>
        <div className="td num" role="columnheader">
          O
        </div>
        <div className="td num" role="columnheader">
          R
        </div>
        <div className="td num" role="columnheader">
          P
        </div>
        <div className="td e" role="columnheader">
          {t('tree.col.sum')}
        </div>
        <div className="td rv" role="columnheader" aria-label={t('tree.col.reviewed')}>
          ✓
        </div>
      </div>
      <div
        className="tree-scroll"
        ref={scrollRef}
        style={{ height: height ?? 'calc(100vh - 230px)' }}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        {sticky.length ? (
          <div className="tree-sticky">
            {sticky.map((r) => (
              <Row key={`sticky-${r.key}`} {...rowProps(r)} />
            ))}
          </div>
        ) : null}
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {items.map((item) => {
            const row = rows.at(item.index);
            if (!row) return null;
            return (
              <div
                key={row.key}
                className="vrow"
                style={{ position: 'absolute', top: 0, left: 0, right: 0, transform: `translateY(${item.start}px)` }}
              >
                <Row {...rowProps(row)} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
