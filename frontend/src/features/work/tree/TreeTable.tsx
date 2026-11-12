/**
 * FE-022 · таблица-дерево рабочего экрана (FR-TREE-10, FR-TREE-13, FR-TREE-15, 11.4 №7, №9–11, №15,
 * «Чужие ветки», FR-UI-03; DESIGN.md 9.4–9.6, 9.11).
 *
 * Строки виртуализированы (@tanstack/react-virtual): в DOM не больше ~150 строк при 5 000 узлах.
 * Строки фазы и дисциплины прилипают под шапкой столбцов, пока видны их узлы: поверх прокрутки
 * рисуются копии ближайших сверху строк фазы и дисциплины. Ввод в ячейки своих листов — FE-025
 * (`cells/*`, включается пропсом `onConfirm`); кнопки «+» и «⋯» — FE-027, статус ветки и
 * «Проверено» — FE-029.
 *
 * Свёртку и набор видимых узлов может вести экран (FE-024: фильтры, поиск, сохранение вида);
 * без них таблица хранит свёртку сама.
 */
import { Tooltip } from '@mantine/core';
import { useVirtualizer } from '@tanstack/react-virtual';
import {
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import type { components } from '../../../shared/api/client';
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
import { CommentCell, HoursCell, MultiplierCell, TitleCell, type Norm } from '../cells/Cells';
import { cellKey, useCells, type CellRef, type CellsApi, type CommentLine, type LockResult } from '../cells/useCells';
import type { CellLock, CellMark } from '../collab/collabStore';
import { BranchControls, ReviewCell } from '../branch/BranchControls';
import { branchReadiness, type BranchReadiness } from '../branch/branch';
import { useBranch, type BranchApi, type BranchSetup } from '../branch/useBranch';
import { DiscussionPanel, type DiscussionSetup } from '../../discussions/DiscussionPanel';
import { HistoryPanel } from '../history/HistoryPanel';
import { AddMenu, NodeMenu, type RowMenuApi } from '../menu/RowMenus';
import { useRowMenus, type MenuSetup } from '../menu/useRowMenus';
import { ConflictDialog } from '../collab/ConflictDialog';
import { userColor } from '../../../shared/ui/userColor';
import { extraOf, type NodeEdit, type TreeNode, type TreeStore } from '../store/treeStore';
import { useTree } from '../store/useProjectTree';
import { sameSignature, useFresh } from './fresh';
import { MAX_INDENT_DEPTH, ancestorsOf, buildRows, indentOf, type TreeRow } from './rows';

export const ROW_HEIGHT = 38;
/** Колонок в шапке дерева: узел, ×N, комментарий, O, R, P, E, ✓. */
const COLUMNS = 8;

export interface TreeContext {
  /** Может ли пользователь править узлы ветки этой дисциплины (своя ветка или модератор). */
  canEdit: (disciplineId: string | null) => boolean;
  /** Дисциплины без эксперта (11.6 №6). */
  withoutExpert: ReadonlySet<string>;
  disciplineNames: ReadonlyMap<string, string>;
  nodeTypes: ReadonlyMap<string, { name: string; icon: string; norms?: readonly Norm[] }>;
  tags: ReadonlyMap<string, string>;
  pmPercent: string;
  pmReason: string;
  /** Модератор: строка УП ведёт в настройки. */
  settingsHref: string | null;
  /** Строка поиска для подсветки совпадений (FE-024); пусто — без подсветки. */
  highlight?: string;
  /** Чужие захваты ячеек и метки чужих правок (FE-026). */
  collab?: {
    locks: ReadonlyMap<string, CellLock>;
    marks: ReadonlyMap<string, CellMark>;
    /** Модератор: «Всё равно править». */
    canForce: boolean;
  };
  /** Роль участника для подписи в истории («модератор»), FE-028. */
  roleOf?: (userId: string) => string | null;
  /** Обсуждения под строкой (FE-030); нет — значок без раскрытия. */
  discussion?: DiscussionSetup | undefined;
}

/** Подсветка совпадений поиска тегом `<mark>` (DESIGN.md 9.3). */
export function Highlight({ text, query }: { text: string; query: string | undefined }) {
  const q = query?.trim().toLocaleLowerCase('ru') ?? '';
  if (q.length < 2) return <>{text}</>;
  const lower = text.toLocaleLowerCase('ru');
  const parts: ReactNode[] = [];
  let from = 0;
  for (let at = lower.indexOf(q); at >= 0; at = lower.indexOf(q, from)) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(<mark key={at}>{text.slice(at, at + q.length)}</mark>);
    from = at + q.length;
  }
  if (!parts.length) return <>{text}</>;
  parts.push(text.slice(from));
  return <>{parts}</>;
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

/** Значок 💬 (11.4 №13): число сообщений, оранжевый — открытый вопрос, точка — вопрос мне. */
function Discussion({
  node,
  expanded,
  onToggle,
}: {
  node: TreeNode | undefined;
  /** Обсуждение раскрыто под строкой. */
  expanded?: boolean | undefined;
  /** Есть — значок кнопка (FE-030); у строки без сообщений — бледный при наведении. */
  onToggle?: (() => void) | undefined;
}) {
  const { t } = useTranslation();
  const count = extraOf(node).messages_count ?? 0;
  if (!count && !onToggle) return null;
  const open = (extraOf(node).open_questions ?? 0) > 0;
  const mine = (extraOf(node).questions_to_me ?? 0) > 0;
  const label = t('tree.discussion', { count }) + (mine ? `, ${t('tree.questionToMe')}` : '');
  const className = ['disc', open ? 'open' : '', !count ? 'ghost' : '', expanded ? 'on' : ''].filter(Boolean).join(' ');
  if (!onToggle)
    return (
      <span className={className} aria-label={label}>
        💬 {count}
        {mine ? <span className="dot" aria-hidden="true" /> : null}
      </span>
    );
  return (
    <button
      type="button"
      className={className}
      aria-label={count ? label : t('discussion.start', { name: node?.title ?? '' })}
      aria-expanded={Boolean(expanded)}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
    >
      💬{count ? ` ${count}` : ''}
      {mine ? <span className="dot" aria-hidden="true" /> : null}
    </button>
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
  target?: boolean;
  /** Ввод в ячейки (FE-025); нет — только просмотр. */
  cells?: CellsApi | undefined;
  /** Поля, ожидающие ответа сервера. */
  pendingFields?: ReadonlySet<string> | undefined;
  /** Кнопки «+» и «⋯» (FE-027); нет — строка без операций. */
  menu?: RowMenuApi | undefined;
  /** Статус ветки и «Проверено» (FE-029). */
  branch?: BranchApi | undefined;
  /** Обсуждение раскрыто под строкой; есть `onDiscussion` — значок кнопка (FE-030). */
  discOpen?: boolean | undefined;
  onDiscussion?: ((nodeId: string) => void) | undefined;
  /** Готовность ветки (только у строки дисциплины). */
  readiness?: BranchReadiness | undefined;
  /**
   * FE-081 · всё, что показывает строка, плоским списком: строка перерисовывается, только когда он
   * изменился. Объекты действий приходят через `useFresh` и в сравнении не участвуют.
   */
  sig: readonly unknown[];
}

const CELL_FIELDS = ['title', 'o', 'r', 'p', 'multiplier', 'comment'] as const;

const sameRow = (a: RowProps, b: RowProps) => sameSignature(a.sig, b.sig);

const Row = memo(function Row({
  row,
  result,
  node,
  status,
  ctx,
  pmE,
  largeThreshold,
  onToggle,
  target,
  cells: cellsApi,
  pendingFields,
  menu: menuApi,
  branch: branchApi,
  readiness,
  discOpen,
  onDiscussion,
}: RowProps) {
  const { t } = useTranslation();
  const [dropAt, setDropAt] = useState<'above' | 'below' | null>(null);
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
  const cells = editable ? cellsApi : undefined;
  const menu = editable && row.kind !== 'phase' ? menuApi : undefined;
  const notNeeded = status === 'not_needed';
  const leaf = row.kind === 'leaf' ? result.leaf : null;
  const state = leaf?.state;
  const errorRow = state === 'empty' || state === 'invalid';
  const classes = ['tr', row.kind];
  if (errorRow) classes.push('err');
  if (notNeeded) classes.push('not-needed');
  if (target) classes.push('target');
  const mark = ctx.collab?.marks.get(id);
  if (mark) classes.push('changed');
  if (dropAt) classes.push(`drop-${dropAt}`);
  const movable = menu && (row.kind === 'node' || row.kind === 'leaf');
  const below = (e: DragEvent) => {
    const box = e.currentTarget.getBoundingClientRect();
    return e.clientY > box.top + box.height / 2;
  };
  const lockOf = (field: 'title' | 'o' | 'r' | 'p' | 'multiplier' | 'comment') =>
    ctx.collab?.locks.get(cellKey(id, field));
  const canForce = ctx.collab?.canForce ?? false;
  const toggle =
    row.hasChildren && !row.filtered ? (
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
  const comments: CommentLine[] = extraOf(node).comment_lines ?? [];
  const reviewed = extraOf(node).reviewed_by;
  const self = extraOf(node).self_review;
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
      ((field === 'o' && o !== null && r !== null && o.gt(r)) ||
        (field === 'r' && r !== null && ((o !== null && o.gt(r)) || (p !== null && r.gt(p)))) ||
        (field === 'p' && p !== null && r !== null && r.gt(p)));
    const cls: string[] = [];
    if (state === 'empty') cls.push('empty');
    if (wrong) cls.push('wrong');
    if (state === 'zero') cls.push('zero');
    return (
      <HoursCell
        nodeId={id}
        field={field}
        value={value === null ? null : value.toFixed()}
        classes={cls}
        label={field.toUpperCase()}
        pending={pendingFields?.has(field) ?? false}
        cells={cells}
        roTitle={roTitle}
        lock={lockOf(field)}
        canForce={canForce}
      />
    );
  };
  const typeNorms = type?.norms ?? [];
  const highlight = (text: string) => <Highlight text={text} query={ctx.highlight} />;

  return (
    <div
      className={classes.join(' ')}
      role="row"
      aria-level={row.depth + 1}
      data-node={id}
      {...(menu
        ? {
            onContextMenu: (e: MouseEvent) => {
              e.preventDefault();
              menu.setContext(id);
            },
          }
        : {})}
      {...(movable
        ? {
            onDragOver: (e: DragEvent) => {
              if (!menu.drag.canDrop(id)) return;
              e.preventDefault();
              e.dataTransfer.dropEffect = 'move';
              const at = below(e) ? 'below' : 'above';
              if (at !== dropAt) setDropAt(at);
            },
            onDragLeave: () => setDropAt(null),
            onDrop: (e: DragEvent) => {
              e.preventDefault();
              setDropAt(null);
              menu.drag.drop(id, below(e));
            },
          }
        : {})}
    >
      <div className="td node" role="cell" style={{ paddingLeft: indentOf(row.depth) }}>
        {movable ? (
          <span
            className="drag"
            draggable
            title={t('menu.drag')}
            aria-hidden="true"
            data-testid={`drag-${id}`}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'move';
              e.dataTransfer.setData('text/plain', id);
              menu.drag.start(id);
            }}
            onDragEnd={() => menu.drag.end()}
          >
            ⋮⋮
          </span>
        ) : null}
        {toggle}
        {row.kind === 'node' || row.kind === 'leaf' ? (
          <span className="ic" title={type?.name}>
            {nodeTypeSymbol(type?.icon)}
            {row.depth > MAX_INDENT_DEPTH ? <span className="lvl">{row.depth}</span> : null}
          </span>
        ) : null}
        <TitleCell nodeId={id} title={result.node.title} cells={cells} lock={lockOf('title')}>
          <Highlight text={result.node.title} query={ctx.highlight} />
        </TitleCell>
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
        {row.kind === 'discipline' && readiness && branchApi ? (
          <BranchControls
            status={status}
            readiness={readiness}
            canDone={branchApi.setup.canDone(row.disciplineId)}
            busy={branchApi.busy === `status:${id}`}
            onDone={() => void branchApi.setStatus(id, 'done')}
          />
        ) : null}
        {foreign ? <span className="foreign">· {t('tree.foreign')}</span> : null}
        {row.kind === 'discipline' && row.disciplineId && ctx.withoutExpert.has(row.disciplineId) ? (
          <span className="pill warn">⚠ {t('tree.noExpert')}</span>
        ) : null}
        <Discussion
          node={node}
          expanded={discOpen}
          onToggle={onDiscussion && row.id ? () => onDiscussion(row.id as string) : undefined}
        />
        {mark ? (
          <span
            key={mark.at}
            className="author-mark"
            style={{ background: userColor(mark.user) }}
            title={mark.user.full_name}
          >
            {t('collab.changed', { initials: mark.user.initials })}
          </span>
        ) : null}
        {menu ? (
          <span className={menu.context === id ? 'row-btns open' : 'row-btns'}>
            <AddMenu nodeId={id} api={menu} />
            <NodeMenu nodeId={id} api={menu} />
          </span>
        ) : null}
      </div>
      {row.kind === 'leaf' ? (
        <MultiplierCell
          nodeId={id}
          value={result.node.multiplier}
          pending={pendingFields?.has('multiplier') ?? false}
          cells={cells}
          lock={lockOf('multiplier')}
          canForce={canForce}
        />
      ) : (
        <div className="td mul-c" role="cell" />
      )}
      {row.kind === 'leaf' || row.kind === 'node' ? (
        <CommentCell
          nodeId={id}
          lines={comments}
          tags={ctx.tags}
          cells={cells}
          placeholder={editable && row.kind === 'leaf'}
          norms={state === 'empty' ? typeNorms : []}
          highlight={highlight}
          lock={lockOf('comment')}
          canForce={canForce}
        />
      ) : (
        <div className="td cm" role="cell">
          {row.kind === 'discipline' && !row.hasChildren ? (
            <span className="cm-empty">{t('tree.emptyBranch')}</span>
          ) : null}
        </div>
      )}
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
      <ReviewCell
        title={result.node.title}
        reviewed={Boolean(reviewed)}
        self={Boolean(self)}
        canReview={Boolean(branchApi?.setup.canReview(row.disciplineId)) && !notNeeded}
        busy={branchApi?.busy === `review:${id}`}
        onToggle={(next) => void branchApi?.review(id, next)}
      />
    </div>
  );
}, sameRow);

/**
 * Ключ данных контекста, которые показывают строки: справочники, подписи, права, поиск. Меняется —
 * перерисовываются все строки; иначе строки сравнивают только свои данные.
 */
function contextKey(ctx: TreeContext, menu: RowMenuApi | undefined): string {
  return [
    ctx.pmPercent,
    ctx.pmReason,
    ctx.settingsHref ?? '',
    ctx.highlight ?? '',
    String(ctx.collab?.canForce ?? false),
    String(Boolean(ctx.discussion)),
    JSON.stringify([...ctx.nodeTypes]),
    JSON.stringify([...ctx.tags]),
    JSON.stringify([...ctx.disciplineNames]),
    [...ctx.withoutExpert].join(),
    menu ? JSON.stringify([menu.history, menu.canNotNeeded, menu.config.types, menu.config.can]) : '',
  ].join('\n');
}

/** Управление таблицей снаружи: показать строку узла (раскрыть предков и прокрутить к ней). */
export interface TreeTableApi {
  show: (nodeId: string) => void;
}

export function TreeTable({
  store,
  ctx,
  height,
  apiRef,
  collapsed: collapsedProp,
  onCollapsedChange,
  visible = null,
  onConfirm,
  locking,
  menus: menuSetup,
  branchSetup,
}: {
  store: TreeStore;
  ctx: TreeContext;
  height?: number | string;
  apiRef?: Ref<TreeTableApi>;
  /** Свёрнутые узлы, если их ведёт экран. */
  collapsed?: ReadonlySet<string>;
  onCollapsedChange?: (next: ReadonlySet<string>) => void;
  /** Видимые узлы под фильтром; null — без фильтра. */
  visible?: ReadonlySet<string> | null;
  /** Подтверждение правки сервером (`useProjectTree().confirm`); есть — ячейки редактируются. */
  onConfirm?: (node: components['schemas']['Node'], projectVersion: number, sent?: NodeEdit) => void;
  /** Захват ячеек при вводе (FE-026). */
  locking?: {
    lock: (cell: CellRef, force?: boolean) => Promise<LockResult>;
    unlock: (cell: CellRef) => void;
  };
  /** Меню строки и «+» (FE-027). */
  menus?: MenuSetup | undefined;
  /** Статус ветки, «Проверено» и предупреждение о правке готовой ветки (FE-029). */
  branchSetup?: BranchSetup | undefined;
}) {
  const { t } = useTranslation();
  const revision = useTree(store, (s) => s.revision);
  const [ownCollapsed, setOwnCollapsed] = useState<ReadonlySet<string>>(new Set());
  const collapsed = collapsedProp ?? ownCollapsed;
  const setCollapsed = (update: (prev: ReadonlySet<string>) => ReadonlySet<string>) => {
    if (onCollapsedChange) onCollapsedChange(update(collapsed));
    else setOwnCollapsed(update);
  };
  const [scrollTop, setScrollTop] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  /** Шапка вне прокрутки строк: уже 1366 px её сдвигаем вслед за горизонтальной прокруткой (FR-UI-03). */
  const headRef = useRef<HTMLDivElement>(null);

  const state = store.getState();
  const { calc, children, settings, nodes, pending, branchStatus, result } = state;
  const rows = useMemo(
    () => (calc && settings ? buildRows(calc, children, settings, collapsed, visible) : []),
    // revision меняется при каждом изменении расчёта
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [revision, collapsed, visible],
  );
  // виртуализатор не мемоизируется компилятором React — строки перерисовываются по revision
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => {
      const id = rows.at(index)?.id;
      return id && discOpen.has(id) ? ROW_HEIGHT + 260 : ROW_HEIGHT;
    },
    getItemKey: (index) => rows.at(index)?.key ?? index,
    overscan: 12,
    initialRect: { width: 1366, height: 900 },
  });
  const [target, setTarget] = useState<string | null>(null);
  const editableLeaves = useMemo(
    () => rows.filter((r) => r.kind === 'leaf' && r.id && ctx.canEdit(r.disciplineId)).map((r) => r.id as string),
    [rows, ctx],
  );
  const branch = useBranch(onConfirm ? branchSetup : undefined, store);
  const cells = useCells({
    store,
    ...(branch ? { guard: branch.guard } : {}),
    confirm: onConfirm ?? (() => undefined),
    leaves: editableLeaves,
    ...(locking ? { lock: locking.lock, unlock: locking.unlock } : {}),
    onMove: (cell: CellRef) => {
      const index = rows.findIndex((r) => r.id === cell.nodeId);
      if (index >= 0) virtualizer.scrollToIndex(index, { align: 'auto' });
    },
  });
  const show = (nodeId: string) => {
    const calcNow = store.getState().calc;
    if (!calcNow?.nodes.has(nodeId)) return;
    const up = new Set(ancestorsOf(calcNow, nodeId));
    setCollapsed((prev) => new Set([...prev].filter((id) => !up.has(id))));
    setTarget(nodeId);
  };
  useImperativeHandle(apiRef, () => ({ show }));
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  // раскрытые обсуждения под строками (FE-030)
  const [discOpen, setDiscOpen] = useState<ReadonlySet<string>>(new Set());
  /** «Обмен с 1С · Разработка › Бэкенд»: узел, фаза и дисциплина (11.4 №18). */
  const pathOf = (nodeId: string) => {
    const all = store.getState().nodes;
    const node = all.get(nodeId);
    if (!node) return '';
    const phase = [...all.values()].find((n) => n.kind === 'phase' && n.phase_id === node.phase_id);
    const discipline = node.discipline_id ? ctx.disciplineNames.get(node.discipline_id) : undefined;
    const where = [phase?.title, discipline].filter(Boolean).join(' › ');
    return where && node.kind === 'item' ? `${node.title} · ${where}` : node.title;
  };
  const toggleDiscussion = (nodeId: string) => {
    const closing = discOpen.has(nodeId);
    setDiscOpen((prev) => {
      const next = new Set(prev);
      if (closing) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
    // закрытая панель больше не измеряется — вернуть строке обычную высоту
    const index = rows.findIndex((r) => r.id === nodeId);
    if (closing && index >= 0) virtualizer.resizeItem(index, ROW_HEIGHT);
  };
  const closeHistory = useCallback(() => setHistoryFor(null), []);
  // строка узла в прокручиваемой области (без прилипших копий)
  const historyAnchor = useMemo(
    () => () =>
      historyFor
        ? (scrollRef.current?.querySelector(`.vrow [data-node="${CSS.escape(historyFor)}"]`)?.getBoundingClientRect() ??
          null)
        : null,
    [historyFor],
  );
  const menus = useRowMenus({
    setup:
      onConfirm && menuSetup
        ? {
            ...menuSetup,
            onHistory: setHistoryFor,
            ...(branch
              ? {
                  guard: branch.guard,
                  setBranchStatus: (nodeId: string, status: BranchStatus) => void branch.setStatus(nodeId, status),
                  canNotNeeded: branch.setup.canNotNeeded,
                }
              : {}),
          }
        : undefined,
    store,
    canEdit: ctx.canEdit,
    onShow: show,
    onCreated: (nodeId) => {
      show(nodeId);
      cells.start({ nodeId, field: 'title' });
    },
  });
  // прокрутка после того, как раскрытые предки попали в список строк
  useEffect(() => {
    if (!target) return;
    const index = rows.findIndex((r) => r.id === target);
    if (index >= 0) virtualizer.scrollToIndex(index, { align: 'center' });
  }, [target, rows, virtualizer]);
  const largeThreshold = settings ? largeLeafThreshold(settings.detailLevel, DEFAULT_LARGE_LEAF_HOURS) : null;

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  // FE-081: строки получают постоянные обёртки действий и перерисовываются по своей подписи
  const actions = useFresh({ toggle, toggleDiscussion });
  const rowCells = useFresh(onConfirm ? cells : undefined);
  const rowMenu = useFresh(menus.api);
  const rowBranch = useFresh(branch);
  const thresholdKey = largeThreshold?.toString() ?? null;
  const ctxKey = contextKey(ctx, menus.api);

  if (!calc || !settings || !actions) return null;
  const items = virtualizer.getVirtualItems();
  /** `sticky` — копия строки поверх прокрутки, без меню. */
  const rowProps = (row: TreeRow, sticky = false): RowProps => {
    const id = row.id;
    const base = id ? nodes.get(id) : undefined;
    const edit = id ? pending.get(id) : undefined;
    const res = id ? calc.nodes.get(id) : undefined;
    const status = row.disciplineId ? branchStatus.get(branchKey(row.phaseId, row.disciplineId)) : undefined;
    const pmE = row.kind === 'pm' ? (result?.pm.e ?? null) : null;
    const readiness = row.kind === 'discipline' && id && rowBranch ? branchReadiness(state, id) : undefined;
    const isTarget = id !== null && id === target;
    const open = id !== null && discOpen.has(id);
    const sig: unknown[] = [
      ctxKey,
      thresholdKey,
      row.key,
      row.kind,
      row.depth,
      row.hasChildren,
      row.collapsed,
      row.filtered,
      res?.node,
      res?.leaf,
      res?.totals,
      res?.excluded,
      base,
      edit,
      status,
      pmE?.toString(),
      isTarget,
      open,
      readiness ? `${readiness.empty}/${readiness.invalid}/${readiness.open}/${readiness.hasNodes}` : null,
      sticky,
    ];
    if (id) {
      sig.push(
        ctx.canEdit(row.disciplineId),
        ctx.collab?.marks.get(id),
        rowMenu?.context === id,
        rowMenu ? rowMenu.config.chainOf(row.disciplineId).join() : null,
        rowBranch?.busy === `status:${id}` || rowBranch?.busy === `review:${id}`,
        rowBranch?.setup.canDone(row.disciplineId),
        rowBranch?.setup.canReview(row.disciplineId),
        rowCells?.editing?.nodeId === id ? rowCells.editing.field : null,
        rowCells?.savingComments.has(id),
      );
      for (const field of CELL_FIELDS) {
        const key = cellKey(id, field);
        sig.push(ctx.collab?.locks.get(key), rowCells?.errors.get(key), rowCells?.hints.get(key));
      }
    }
    return {
      row,
      result: res,
      node: base && edit ? { ...base, ...edit } : base,
      status,
      ctx,
      pmE,
      largeThreshold,
      onToggle: actions.toggle,
      target: isTarget,
      cells: rowCells,
      pendingFields: edit ? new Set(Object.keys(edit)) : undefined,
      menu: sticky ? undefined : rowMenu,
      branch: rowBranch,
      readiness,
      discOpen: open,
      onDiscussion: ctx.discussion ? actions.toggleDiscussion : undefined,
      sig,
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

  const conflictNode = cells.conflict ? nodes.get(cells.conflict.nodeId) : undefined;
  return (
    <div className="tree" role="treegrid" aria-label={t('tree.label')} aria-rowcount={rows.length}>
      {menus.dialogs}
      {branch?.dialogs}
      {historyFor && onConfirm ? (
        <HistoryPanel
          key={historyFor}
          nodeId={historyFor}
          store={store}
          anchor={historyAnchor}
          canRevert={ctx.canEdit(nodes.get(historyFor)?.discipline_id ?? null)}
          onConfirm={onConfirm}
          roleOf={ctx.roleOf ?? (() => null)}
          typeName={(id) => ctx.nodeTypes.get(id)?.name ?? '—'}
          tags={ctx.tags}
          onClose={closeHistory}
        />
      ) : null}
      {cells.conflict ? (
        <ConflictDialog conflict={cells.conflict} title={conflictNode?.title ?? ''} onResolve={cells.resolveConflict} />
      ) : null}
      <div className="tree-head" ref={headRef}>
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
      </div>
      <div
        className="tree-scroll"
        ref={scrollRef}
        style={{ height: height ?? 'calc(100vh - 230px)' }}
        onScroll={(e) => {
          setScrollTop(e.currentTarget.scrollTop);
          if (headRef.current) headRef.current.scrollLeft = e.currentTarget.scrollLeft;
        }}
      >
        {sticky.length ? (
          <div className="tree-sticky">
            {sticky.map((r) => (
              <Row key={`sticky-${r.key}`} {...rowProps(r, true)} />
            ))}
          </div>
        ) : null}
        <div className="tree-body" style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {items.map((item) => {
            const row = rows.at(item.index);
            if (!row) return null;
            const disc = row.id && ctx.discussion && discOpen.has(row.id) ? row.id : null;
            return (
              <div
                key={row.key}
                data-index={item.index}
                ref={disc ? virtualizer.measureElement : undefined}
                className={cells.editing && cells.editing.nodeId === row.id ? 'vrow editing' : 'vrow'}
                style={{ position: 'absolute', top: 0, left: 0, right: 0, transform: `translateY(${item.start}px)` }}
              >
                <Row {...rowProps(row)} />
                {disc && ctx.discussion ? (
                  // в treegrid допустимы только строки: панель — строка с одной ячейкой на все колонки
                  <div className="disc-wrap" role="row" style={{ paddingLeft: indentOf(row.depth) + 40 }}>
                    <div role="gridcell" aria-colspan={COLUMNS}>
                      <DiscussionPanel
                        nodeId={disc}
                        title={nodes.get(disc)?.title ?? ''}
                        path={pathOf(disc)}
                        setup={ctx.discussion}
                      />
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
