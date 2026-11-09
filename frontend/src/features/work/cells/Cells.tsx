/**
 * FE-025 · ячейки листа: O/R/P, ×N и комментарий из строк с метками (FR-TREE-10, FR-TREE-20…22,
 * FR-TREE-02, R-03, R-09; DESIGN.md 9.4–9.6).
 */
import { Popover } from '@mantine/core';
import { useRef, useState, type FocusEvent, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { formatFork, formatHoursInput } from '../../../shared/format/number';
import { cellKey, type CellField, type CellsApi, type CommentLine, type Direction } from './useCells';

/** Комментарий: до 10 строк по 2 000 символов (NodeChanges.comment_lines). */
export const COMMENT_MAX_LINES = 10;
export const COMMENT_MAX_CHARS = 2000;

const keyDir = (e: KeyboardEvent): Direction => (e.shiftKey ? -1 : 1);

/** Поле ввода ячейки: Enter и уход фокуса сохраняют, Esc отменяет, Tab — следующая ячейка. */
function CellInput({
  initial,
  label,
  className,
  onCommit,
  onCancel,
}: {
  initial: string;
  label: string;
  className: string;
  onCommit: (text: string, dir: Direction | null) => boolean;
  onCancel: () => void;
}) {
  const done = useRef(false);
  const finish = (text: string, dir: Direction | null) => {
    if (done.current) return;
    done.current = true;
    if (!onCommit(text, dir)) done.current = false;
  };
  return (
    <input
      className={className}
      aria-label={label}
      defaultValue={initial}
      autoFocus
      onFocus={(e) => e.currentTarget.select()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          finish(e.currentTarget.value, null);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          done.current = true;
          onCancel();
        } else if (e.key === 'Tab') {
          e.preventDefault();
          finish(e.currentTarget.value, keyDir(e));
        }
      }}
      onBlur={(e) => finish(e.currentTarget.value, null)}
    />
  );
}

/** Подпись под ячейкой: ошибка (красная) или подсказка об округлении. */
function CellNote({ error, hint }: { error: string | undefined; hint: string | undefined }) {
  if (error)
    return (
      <span className="cell-note bad" role="alert">
        {error}
      </span>
    );
  if (hint)
    return (
      <span className="cell-note" role="status">
        {hint}
      </span>
    );
  return null;
}

export function HoursCell({
  nodeId,
  field,
  value,
  classes,
  label,
  pending,
  cells,
  roTitle,
}: {
  nodeId: string;
  field: 'o' | 'r' | 'p';
  value: string | null;
  /** Классы состояния листа: empty, wrong, zero. */
  classes: string[];
  label: string;
  pending: boolean;
  /** Нет — ячейка только для чтения. */
  cells: CellsApi | undefined;
  roTitle: string | undefined;
}) {
  const key = cellKey(nodeId, field);
  const error = cells?.errors.get(key);
  const hint = cells?.hints.get(key);
  const editing = cells?.editing?.nodeId === nodeId && cells.editing.field === field;
  const cls = ['cell', ...classes];
  if (pending) cls.push('saving');
  if (error) cls.push('error');
  let body: ReactNode;
  if (!cells) {
    cls.push('ro');
    body = (
      <span className={cls.join(' ')} {...(roTitle ? { title: roTitle } : {})}>
        {formatHoursInput(value)}
      </span>
    );
  } else if (editing) {
    body = (
      <CellInput
        className={error ? 'cell-in error' : 'cell-in'}
        label={label}
        initial={error?.draft ?? formatHoursInput(value)}
        onCommit={(text, dir) => cells.commit({ nodeId, field }, text, dir)}
        onCancel={cells.cancel}
      />
    );
  } else {
    body = (
      <button
        type="button"
        className={cls.join(' ')}
        aria-label={`${label}: ${error?.draft ?? formatHoursInput(value)}`}
        {...(pending ? { 'aria-busy': true } : {})}
        onClick={() => cells.start({ nodeId, field })}
      >
        {error?.draft ?? formatHoursInput(value)}
      </button>
    );
  }
  return (
    <div className="td num" role="cell">
      {body}
      <CellNote error={error?.message} hint={hint} />
    </div>
  );
}

export function MultiplierCell({
  nodeId,
  value,
  pending,
  cells,
}: {
  nodeId: string;
  value: number;
  pending: boolean;
  cells: CellsApi | undefined;
}) {
  const { t } = useTranslation();
  const field: CellField = 'multiplier';
  const key = cellKey(nodeId, field);
  const error = cells?.errors.get(key);
  const editing = cells?.editing?.nodeId === nodeId && cells.editing.field === field;
  const cls = [value === 1 ? 'mul one' : 'mul'];
  if (pending) cls.push('saving');
  if (error) cls.push('error');
  let body: ReactNode = <span className={cls.join(' ')}>×{error?.draft ?? value}</span>;
  if (cells && editing) {
    body = (
      <CellInput
        className="cell-in mul-in"
        label={t('cells.multiplier')}
        initial={error?.draft ?? String(value)}
        onCommit={(text) => cells.commit({ nodeId, field }, text, null)}
        onCancel={cells.cancel}
      />
    );
  } else if (cells) {
    body = (
      <button
        type="button"
        className={cls.join(' ')}
        aria-label={`${t('cells.multiplier')}: ${error?.draft ?? value}`}
        onClick={() => cells.start({ nodeId, field })}
      >
        ×{error?.draft ?? value}
      </button>
    );
  }
  return (
    <div className="td mul-c" role="cell">
      {body}
      <CellNote error={error?.message} hint={undefined} />
    </div>
  );
}

/** Подсветка совпадения поиска передаётся снаружи, чтобы не тянуть таблицу в ячейки. */
type Highlighter = (text: string) => ReactNode;

/** Комментарий в ячейке: первая строка с меткой (до 2 строк текста), «+N» с метками, «…» (R-03, R-09). */
function CommentView({
  lines,
  tags,
  highlight,
}: {
  lines: CommentLine[];
  tags: ReadonlyMap<string, string>;
  highlight: Highlighter;
}) {
  const { t } = useTranslation();
  const [first, ...rest] = lines;
  if (!first) return null;
  const tagOf = (l: CommentLine) => (l.tag_id ? tags.get(l.tag_id) : undefined);
  const tag = tagOf(first);
  const more = rest.map(tagOf).filter(Boolean);
  return (
    <span className="cm-view">
      <span className="cm-line">
        {tag ? <span className="tag">{tag}</span> : null} {highlight(first.text)}
      </span>
      {rest.length || first.text.length > 90 ? (
        <Popover position="bottom-start" width={420} shadow="md" withinPortal>
          <Popover.Target>
            <button
              type="button"
              className="tag more"
              aria-label={t('cells.commentAll', { count: lines.length })}
              onClick={(e) => e.stopPropagation()}
            >
              {rest.length ? `+${rest.length}${more.length ? ` ${more.join(', ')}` : ''}` : '…'}
            </button>
          </Popover.Target>
          <Popover.Dropdown className="cm-all">
            <ul>
              {lines.map((l, i) => (
                <li key={i}>
                  {tagOf(l) ? <span className="tag">{tagOf(l)}</span> : null} {highlight(l.text)}
                </li>
              ))}
            </ul>
          </Popover.Dropdown>
        </Popover>
      ) : null}
    </span>
  );
}

/** Редактор комментария: строки с меткой на строку, до 10 строк по 2 000 символов. */
function CommentEditor({
  lines: initial,
  tags,
  onSave,
  onCancel,
}: {
  lines: CommentLine[];
  tags: ReadonlyMap<string, string>;
  onSave: (lines: CommentLine[] | null, dir: Direction | null) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [lines, setLines] = useState<CommentLine[]>(initial.length ? initial : [{ tag_id: null, text: '' }]);
  const done = useRef(false);
  const save = (dir: Direction | null) => {
    if (done.current) return;
    done.current = true;
    const kept = lines.map((l) => ({ ...l, text: l.text.trim() })).filter((l) => l.text);
    onSave(kept.length ? kept : null, dir);
  };
  const update = (index: number, patch: Partial<CommentLine>) =>
    setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  const onKey = (e: KeyboardEvent, index: number) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      done.current = true;
      onCancel();
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      save(null);
    } else if (e.key === 'Tab' && !e.shiftKey && index === lines.length - 1 && e.target instanceof HTMLInputElement) {
      e.preventDefault();
      save(1);
    } else if (e.key === 'Tab' && e.shiftKey && index === 0 && e.target instanceof HTMLSelectElement) {
      e.preventDefault();
      save(-1);
    }
  };
  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) save(null);
  };
  return (
    <div className="cm-editor" role="group" aria-label={t('cells.commentEditor')} onBlur={onBlur}>
      {lines.map((line, index) => (
        <div className="cm-row" key={index}>
          <select
            aria-label={t('cells.commentTag', { n: index + 1 })}
            value={line.tag_id ?? ''}
            onChange={(e) => update(index, { tag_id: e.currentTarget.value || null })}
            onKeyDown={(e) => onKey(e, index)}
          >
            <option value="">{t('cells.noTag')}</option>
            {[...tags].map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <input
            aria-label={t('cells.commentLine', { n: index + 1 })}
            value={line.text}
            maxLength={COMMENT_MAX_CHARS}
            autoFocus={index === 0}
            onChange={(e) => update(index, { text: e.currentTarget.value })}
            onKeyDown={(e) => onKey(e, index)}
          />
          {lines.length > 1 ? (
            <button
              type="button"
              className="cm-del"
              aria-label={t('cells.commentRemove', { n: index + 1 })}
              onClick={() => setLines((prev) => prev.filter((_, i) => i !== index))}
            >
              ×
            </button>
          ) : null}
        </div>
      ))}
      <div className="cm-foot">
        {lines.length < COMMENT_MAX_LINES ? (
          <button
            type="button"
            className="btn-sm"
            onClick={() => setLines((prev) => [...prev, { tag_id: null, text: '' }])}
          >
            {t('cells.commentAdd')}
          </button>
        ) : null}
        <span className="cm-keys">{t('cells.commentKeys')}</span>
      </div>
    </div>
  );
}

export interface Norm {
  label: string;
  o: string;
  r: string;
  p: string;
}

export function CommentCell({
  nodeId,
  lines,
  tags,
  cells,
  placeholder,
  norms,
  highlight,
}: {
  nodeId: string;
  lines: CommentLine[];
  tags: ReadonlyMap<string, string>;
  cells: CellsApi | undefined;
  /** Пустой комментарий своего листа — «Нажмите, чтобы добавить комментарий». */
  placeholder: boolean;
  /** Нормы типа для пустого листа (FR-TREE-02): подсказка «Норма: … · подставить». */
  norms: readonly Norm[];
  highlight: Highlighter;
}) {
  const { t } = useTranslation();
  const key = cellKey(nodeId, 'comment');
  const error = cells?.errors.get(key);
  const editing = cells?.editing?.nodeId === nodeId && cells.editing.field === 'comment';
  const saving = cells?.savingComments.has(nodeId) ?? false;
  const norm = norms[0];
  const content = lines.length ? (
    <CommentView lines={lines} tags={tags} highlight={highlight} />
  ) : norm && cells ? (
    <span className="norm">
      {t('cells.norm', { label: norm.label, fork: formatFork(norm.o, norm.r, norm.p) })} ·{' '}
      <button
        type="button"
        className="link"
        onClick={(e) => {
          e.stopPropagation();
          cells.applyNorm(nodeId, norm);
        }}
      >
        {t('cells.normApply')}
      </button>
    </span>
  ) : placeholder ? (
    <span className="cm-empty">{t('tree.commentPlaceholder')}</span>
  ) : null;
  const cls = ['td', 'cm'];
  if (saving) cls.push('saving');
  if (error) cls.push('error');
  return (
    <div className={cls.join(' ')} role="cell">
      {cells ? (
        <div
          className="cm-click"
          role="button"
          tabIndex={0}
          aria-label={t('cells.commentEdit')}
          onClick={() => cells.start({ nodeId, field: 'comment' })}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && e.target === e.currentTarget) cells.start({ nodeId, field: 'comment' });
          }}
        >
          {content}
        </div>
      ) : (
        content
      )}
      {cells && editing ? (
        <CommentEditor
          lines={lines}
          tags={tags}
          onSave={(next, dir) => cells.saveComment(nodeId, next, dir)}
          onCancel={cells.cancel}
        />
      ) : null}
      <CellNote error={error?.message} hint={undefined} />
    </div>
  );
}
