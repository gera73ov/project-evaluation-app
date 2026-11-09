/**
 * FE-023 · верхняя полоса рабочего экрана (FR-TREE-11, 11.4 №1–4, №6, №16–17, №21, BR-MONEY-02,
 * BR-MONEY-06; DESIGN.md 9.2).
 *
 * Итоги часов — из локального расчёта по всему дереву, независимо от фильтров. Деньги — только
 * из `GET /projects/{id}/money` (сервер считает суммы, 6.4) и только с правом `money.read`: без
 * него денежного блока нет в разметке и запрос не делается. «Открыто» и «Риски» считаются по узлам
 * дерева; клик по «Риски» включает фильтр «Риски» (FE-024). «📷 Снимок» и «Экспорт ▾» — FE-045 (`features/snapshots`, `features/exports`). Аватары присутствия (FE-026, 11.4 №4; DESIGN.md 6.14) — до 5
 * внахлёст, дальше «+N».
 */
import { Popover } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import type { components } from '../../../shared/api/client';
import { formatDate } from '../../../shared/format/date';
import { formatHours, formatMoney, formatPercent } from '../../../shared/format/number';
import { isTotpRequired } from '../../../shared/ui/MoneyGuard';
import { ExportMenu } from '../../exports/ExportMenu';
import { StatusControl } from '../../settings/status/StatusControl';
import { SnapshotButton } from '../../snapshots/SnapshotButton';
import type { Project } from '../../settings/useProject';
import { userColor } from '../../../shared/ui/userColor';
import type { Peer } from '../collab/collabStore';
import type { TreeStore } from '../store/treeStore';
import { useTree } from '../store/useProjectTree';

type Money = components['schemas']['ProjectMoney'];
type Figure = components['schemas']['MoneyFigure'];

export interface OpenQuestion {
  nodeId: string;
  title: string;
  open: number;
  toMe: number;
}

/** Рабочие дни (Пн–Пт, BR-PRJ-08 без календаря) от сегодня до дедлайна; прошедший — отрицательно. */
export function workingDaysLeft(deadline: string, today: Date = new Date()): number {
  const end = new Date(`${deadline}T00:00:00`);
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const step = end >= start ? 1 : -1;
  let days = 0;
  for (const d = new Date(start); d.getTime() !== end.getTime(); d.setDate(d.getDate() + step)) {
    const next = new Date(d);
    next.setDate(d.getDate() + step);
    const day = (step > 0 ? next : d).getDay();
    if (day !== 0 && day !== 6) days += step;
  }
  return days;
}

/** Аватаров присутствия больше 5 — последний кружок «+N» (DESIGN.md 6.14). */
const PRESENCE_MAX = 5;

/** Дедлайн близко: осталось не больше 2 рабочих дней или он прошёл (11.3 №4). */
export const DEADLINE_ALERT_DAYS = 2;

function figureOf(money: Money, key: 'e' | 'p80' | 'p90'): Figure | undefined {
  return new Map(Object.entries(money.figures)).get(key);
}

function MoneyBlock({
  money,
  quote,
  names,
}: {
  money: Money;
  quote: 'e' | 'p80' | 'p90';
  names: (id: string) => string;
}) {
  const { t } = useTranslation();
  const figure = figureOf(money, quote);
  const rub = money.currency === 'RUB';
  const noVat = rub ? figure?.total_rub : figure?.total_cur;
  const withVat = rub ? figure?.total_with_vat_rub : figure?.total_with_vat_cur;
  const missing = money.rates_missing ?? [];
  return (
    <div className="tot money" aria-label={t('top.money')}>
      {noVat === null && missing.length ? (
        <span className="money-missing">{t('top.ratesMissing', { names: missing.map(names).join(', ') })}</span>
      ) : (
        <>
          <span>
            <span className="k">{t('top.noVat')}</span> <b>{formatMoney(noVat ?? null, money.currency)}</b>
          </span>
          {money.vat_percent !== null ? (
            <span>
              <span className="k">{t('top.withVat', { percent: formatPercent(String(money.vat_percent)) })}</span>{' '}
              <b>{formatMoney(withVat ?? null, money.currency)}</b>
            </span>
          ) : null}
        </>
      )}
      <span aria-hidden="true">🔒</span>
    </div>
  );
}

export function TopBar({
  project,
  store,
  money,
  moneyError,
  questions,
  risks,
  onShowNode,
  onRiskFilter,
  presence = [],
  readOnly,
  discussionOpen = false,
  onDiscussion,
}: {
  project: Project;
  store: TreeStore;
  money: Money | undefined;
  moneyError: Error | null;
  questions: OpenQuestion[];
  risks: number;
  onShowNode: (nodeId: string) => void;
  onRiskFilter: () => void;
  /** Кто сейчас в проекте, кроме меня. */
  presence?: readonly Peer[];
  readOnly: boolean;
  /** Обсуждение проекта целиком (FR-DISC-01, CR-007): кнопка раскрывает ленту под полосой. */
  discussionOpen?: boolean;
  onDiscussion?: () => void;
}) {
  const { t } = useTranslation();
  const [openList, setOpenList] = useState(false);
  const total = useTree(store, (s) => s.result?.total ?? null);
  const quote = project.quote_figure;
  const canMoney = project.my_permissions.includes('money.read');
  const names = new Map(project.disciplines.map((d) => [d.discipline_id, d.name]));
  const nameOf = (id: string) => (id === 'pm' ? t('tree.pm') : (names.get(id) ?? id));
  const deadline = project.deadline ?? null;
  const left = deadline ? workingDaysLeft(deadline) : null;
  const alert = left !== null && left <= DEADLINE_ALERT_DAYS;
  const openTotal = questions.reduce((sum, q) => sum + q.open, 0);
  const toMe = questions.reduce((sum, q) => sum + q.toMe, 0);

  const figure = (key: 'e' | 'p80' | 'p90', label: string) => {
    const value = total ? (key === 'e' ? total.e : key === 'p80' ? total.p80 : total.p90) : null;
    return (
      <span className={key === quote ? 'fig quote' : 'fig'}>
        <span className="k">{label}</span> <b>{value ? formatHours(value) : '—'}</b>
        {key === quote ? (
          <>
            {' '}
            {t('top.hours')} <span className="pill acc-strong">{t('top.inQuote')}</span>
          </>
        ) : null}
      </span>
    );
  };

  return (
    <header className="top" aria-label={t('top.label')}>
      <Link to="/" className="back" aria-label={t('top.back')}>
        ←
      </Link>
      <div className="top-name">
        <h1>{project.name}</h1>
        <div className="sub">
          {project.customer} · {t('top.level', { level: t(`projectCreate.detailLevel.${project.detail_level}`) })}
          {deadline ? (
            <>
              {' · '}
              <span
                className={alert ? 'deadline alert' : 'deadline'}
                {...(alert ? { title: t('top.deadlineLeft', { count: Math.max(left ?? 0, 0) }) } : {})}
              >
                {t('top.deadline', { date: formatDate(deadline, undefined, true) })}
                {alert ? ' ⚠' : ''}
              </span>
            </>
          ) : null}
        </div>
      </div>
      <StatusControl project={project} readOnly={readOnly} label={false} />
      <div className="tot" aria-label={t('top.hoursTotal')}>
        {figure('e', 'E')}
        {figure('p80', 'P80')}
        {figure('p90', 'P90')}
      </div>
      {canMoney && money ? <MoneyBlock money={money} quote={quote} names={nameOf} /> : null}
      {canMoney && isTotpRequired(moneyError) ? (
        <Link to={`/projects/${project.id}/settings`} className="tot money locked">
          🔒 {t('top.moneyLocked')}
        </Link>
      ) : null}
      <Popover opened={openList} onChange={setOpenList} position="bottom-start" width={330} shadow="md">
        <Popover.Target>
          <button type="button" className="open-btn" onClick={() => setOpenList((v) => !v)} aria-expanded={openList}>
            💬 {t('top.open')} <span className="pill warn">{t('top.openCount', { me: toMe, total: openTotal })}</span>
          </button>
        </Popover.Target>
        <Popover.Dropdown className="open-list">
          <div className="open-head">{t('top.openTitle')}</div>
          {questions.length ? (
            <ul>
              {questions.map((q) => (
                <li key={q.nodeId}>
                  <button
                    type="button"
                    onClick={() => {
                      setOpenList(false);
                      onShowNode(q.nodeId);
                    }}
                  >
                    <span className="title">{q.title}</span>
                    <span className={q.toMe ? 'pill bad' : 'pill warn'}>
                      {q.toMe ? t('top.toMe', { count: q.toMe }) : t('top.openN', { count: q.open })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="open-empty">{t('top.noOpen')}</div>
          )}
        </Popover.Dropdown>
      </Popover>
      <button type="button" className="risk-cnt" onClick={onRiskFilter} title={t('top.risksFilter')}>
        ⚠ {t('top.risks')} <span className="pill bad">{risks}</span>
      </button>
      <span className="sp" />
      {presence.length ? (
        <span className="presence" aria-label={t('collab.presence', { count: presence.length })}>
          {presence.slice(0, PRESENCE_MAX).map((p) => (
            <span
              key={p.id}
              className="av pr"
              style={{ background: userColor(p) }}
              title={`${p.full_name} — ${t('collab.inProject')}`}
            >
              {p.initials}
            </span>
          ))}
          {presence.length > PRESENCE_MAX ? (
            <span
              className="av pr more"
              title={presence
                .slice(PRESENCE_MAX)
                .map((p) => p.full_name)
                .join(', ')}
            >
              +{presence.length - PRESENCE_MAX}
            </span>
          ) : null}
        </span>
      ) : null}
      {onDiscussion ? (
        <button
          type="button"
          className={discussionOpen ? 'btn-link disc-toggle on' : 'btn-link disc-toggle'}
          aria-expanded={discussionOpen}
          onClick={onDiscussion}
        >
          💬 {t('top.discussion')}
        </button>
      ) : null}
      <Link to={`/projects/${project.id}/stats`} className="btn-link">
        {t('top.stats')}
      </Link>
      <SnapshotButton projectId={project.id} perms={project.my_permissions} />
      <ExportMenu projectId={project.id} perms={project.my_permissions} />
      <Link to={`/projects/${project.id}/settings`} className="btn-link ghost">
        ⚙ {t('top.settings')}
      </Link>
    </header>
  );
}
