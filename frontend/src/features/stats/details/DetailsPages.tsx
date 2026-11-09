/**
 * FE-042 · вкладки статистики «Доли и соотношения», «Объёмы по типам», «Кандидаты на
 * декомпозицию», «Допущения и риски» (SPEC 11.10 №1–4; DESIGN.md 10.9). Каждая вкладка — свой
 * маршрут; данные — `GET /projects/{id}/stats` и дерево проекта. Клик по строке кандидата или
 * метки открывает узел на рабочем экране (`?node=`). «⇩ Word» — черновик раздела КП (только с
 * правом выгрузки денег, 3.3).
 */
import { Button, CopyButton, Select } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { api } from '../../../shared/api/client';
import { ExportTimeout, downloadExport } from '../../../shared/api/exports';
import { call, errorMessage } from '../../../shared/api/problem';
import { D } from '../../../shared/calc/decimal';
import { formatFork, formatHours, formatNumber } from '../../../shared/format/number';
import { nodeTypeSymbol } from '../../../shared/ui/icons/nodeTypes';
import { projectTypesKey } from '../../work/menu/useTreeOps';
import { RatioList, useRatioName } from '../grid/RatioList';
import {
  TAG_ORDER,
  largeRows,
  shares,
  tagLines,
  volumeRows,
  volumeSummary,
  wideRows,
  type CandidateRow,
  type TagCategory,
} from './details';
import { StatsShell, useTree } from './StatsShell';

// --- «Доли и соотношения» -----------------------------------------------------------------

export function SharesPage({ projectId }: { projectId: string }) {
  return (
    <StatsShell projectId={projectId} active="shares">
      {({ project, stats }) => <SharesBody projectId={projectId} project={project} stats={stats} />}
    </StatsShell>
  );
}

function SharesBody({
  projectId,
  project,
  stats,
}: {
  projectId: string;
  project: Parameters<typeof shares>[0];
  stats: Parameters<typeof volumeRows>[0];
}) {
  const { t } = useTranslation();
  const tree = useTree(projectId);
  const [phase, setPhase] = useState<string | null>(null);
  const names = new Map(project.disciplines.map((d) => [d.discipline_id, d.name]));
  const ratioName = useRatioName(names);
  const rows = shares(project, tree.data?.nodes ?? [], phase);
  const max = Math.max(1, ...rows.map((r) => r.pct));
  const phases = project.phases.filter((p) => p.is_enabled && !p.is_cross_cutting);
  return (
    <div className="det-grid">
      <section className="card det-card" aria-labelledby="det-shares">
        <div className="card-head">
          <h3 id="det-shares">{t('stats.details.sharesTitle')}</h3>
          <Select
            size="xs"
            className="det-phase"
            aria-label={t('stats.details.phase')}
            allowDeselect={false}
            value={phase ?? 'all'}
            data={[
              { value: 'all', label: t('stats.details.phaseAll') },
              ...phases.map((p) => ({ value: p.phase_id, label: `${t('stats.details.phaseOne')}${p.name}` })),
            ]}
            onChange={(v) => setPhase(v && v !== 'all' ? v : null)}
          />
        </div>
        {rows.length === 0 ? <p className="card-hint">{t('stats.details.sharesEmpty')}</p> : null}
        {rows.map((r) => (
          <div key={r.id} className="hb">
            <span>{r.name}</span>
            <div className="b acc" style={{ width: `${(r.pct / max) * 100}%` }} />
            <span>{formatNumber(String(r.pct), 0)}%</span>
          </div>
        ))}
        <p className="card-hint">{t('stats.details.sharesHint')}</p>
      </section>
      <section className="card det-card" aria-labelledby="det-ratios">
        <h3 id="det-ratios">{t('stats.ratios.title')}</h3>
        <RatioList ratios={stats.ratios} name={ratioName} />
        {phase ? <p className="card-hint">{t('stats.details.ratiosProject')}</p> : null}
      </section>
    </div>
  );
}

// --- «Объёмы по типам» ------------------------------------------------------------------------

export function VolumesPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const tree = useTree(projectId);
  const types = useQuery({
    queryKey: projectTypesKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/node-types', { params: { path: { id: projectId } } })),
    staleTime: 10 * 60_000,
  });
  const icons = new Map((types.data?.items ?? []).map((n) => [n.id, n.icon]));
  return (
    <StatsShell projectId={projectId} active="volumes">
      {({ project, stats }) => {
        const rows = volumeRows(
          stats,
          tree.data?.nodes ?? [],
          project,
          (id, name) => icons.get(id) === 'work' || name === 'Работа',
        );
        const summary = volumeSummary(rows);
        return (
          <div className="det-one">
            <section className="card det-card" aria-labelledby="det-volumes">
              <div className="card-head">
                <h3 id="det-volumes">{t('stats.details.volumesTitle')}</h3>
                <span className="sub">{t('stats.details.withN')}</span>
              </div>
              {rows.length === 0 ? (
                <p className="card-hint">{t('stats.details.volumesEmpty')}</p>
              ) : (
                <table className="t det-table">
                  <thead>
                    <tr>
                      <th>{t('stats.details.type')}</th>
                      <th className="r">{t('stats.details.units')}</th>
                      <th className="r">{t('stats.totals.e')}</th>
                      <th className="r">{t('stats.details.eUnit')}</th>
                      <th>{t('stats.details.disciplines')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.typeId}>
                        <td>
                          <span className="type-ico" aria-hidden="true">
                            {nodeTypeSymbol(icons.get(r.typeId))}
                          </span>{' '}
                          {r.name}
                        </td>
                        <td className="r">{r.count}</td>
                        <td className="r">{formatHours(r.e)}</td>
                        <td className="r">{r.eUnit === null ? '—' : formatHours(r.eUnit)}</td>
                        <td>{r.disciplines.join(', ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {summary ? (
                <div className="det-summary">
                  <span>
                    {t('stats.details.summary')}: «{summary}»
                  </span>
                  <CopyButton value={summary}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="default" onClick={copy}>
                        {copied ? t('common.copied') : t('common.copy')}
                      </Button>
                    )}
                  </CopyButton>
                </div>
              ) : null}
              <p className="card-hint">{t('stats.details.volumesHint')}</p>
            </section>
          </div>
        );
      }}
    </StatsShell>
  );
}

// --- «Кандидаты на декомпозицию» --------------------------------------------------------------

function CandidateButton({ row, onOpen, side }: { row: CandidateRow; onOpen: () => void; side: React.ReactNode }) {
  return (
    <li>
      <button type="button" className="det-row" onClick={onOpen}>
        <span className="det-main">
          <b>
            {row.title}
            {row.multiplier > 1 ? ` ×${row.multiplier}` : ''}
          </b>
          <span className="sub">{row.path}</span>
        </span>
        {side}
      </button>
    </li>
  );
}

export function CandidatesPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const tree = useTree(projectId);
  const method = useQuery({
    queryKey: ['dict', 'method-settings'],
    queryFn: () => call(() => api.GET('/admin/method-settings')),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const open = (nodeId: string) => navigate(`/projects/${projectId}?node=${nodeId}`);
  return (
    <StatsShell projectId={projectId} active="candidates">
      {({ project, stats }) => {
        const level = project.detail_level;
        const limits = method.data?.large_leaf_hours;
        const threshold =
          level === 'coarse' || !limits ? null : new D(String(level === 'detailed' ? limits.detailed : limits.medium));
        const nodes = tree.data?.nodes ?? [];
        const large = largeRows(stats, nodes, threshold);
        const wide = wideRows(stats, nodes);
        const forkLimit = 30;
        return (
          <div className="det-grid">
            <section className="card det-card" aria-labelledby="det-large">
              <div className="card-head">
                <h3 id="det-large">{t('stats.details.largeTitle')}</h3>
                {threshold ? (
                  <span className="sub">
                    {t('stats.details.threshold', {
                      level: t(`stats.details.level.${level}`),
                      hours: formatNumber(threshold, 0),
                    })}
                  </span>
                ) : (
                  <span className="sub">{t('stats.details.noThreshold')}</span>
                )}
              </div>
              <ul className="det-list">
                {large.map((r) => (
                  <CandidateButton
                    key={r.nodeId}
                    row={{
                      ...r,
                      path:
                        r.multiplier > 1
                          ? `${r.path} · ${t('stats.details.perUnit', { hours: formatHours(r.eUnit) })}`
                          : r.path,
                    }}
                    onOpen={() => open(r.nodeId)}
                    side={
                      <span className="det-side">
                        <b>{formatHours(r.e, { unit: true })}</b>
                        {r.mark === 'above' ? (
                          <span className="pill warn">{t('stats.details.above')}</span>
                        ) : r.mark === 'repeating' ? (
                          <span className="pill gray">{t('stats.details.repeating')}</span>
                        ) : (
                          <span className="det-pill-space" />
                        )}
                      </span>
                    }
                  />
                ))}
              </ul>
              {large.length === 0 ? <p className="card-hint">{t('stats.details.largeEmpty')}</p> : null}
            </section>
            <section className="card det-card" aria-labelledby="det-wide">
              <div className="card-head">
                <h3 id="det-wide">{t('stats.details.wideTitle')}</h3>
                <span className="sub">{t('stats.details.forkLimit', { pct: forkLimit })}</span>
              </div>
              <ul className="det-list">
                {wide.map((r) => (
                  <CandidateButton
                    key={r.nodeId}
                    row={{
                      ...r,
                      path: r.fork ? `${r.path} · ${formatFork(r.fork.o, r.fork.r, r.fork.p)}` : r.path,
                    }}
                    onOpen={() => open(r.nodeId)}
                    side={
                      <span className={Number(r.ratio) > forkLimit ? 'det-side warn' : 'det-side'}>
                        σ/E {formatNumber(r.ratio, 0)}%
                      </span>
                    }
                  />
                ))}
              </ul>
              <p className="card-hint">
                {wide.some((r) => Number(r.ratio) > forkLimit)
                  ? t('stats.details.wideHint')
                  : t('stats.details.wideNone', { pct: forkLimit })}
              </p>
            </section>
          </div>
        );
      }}
    </StatsShell>
  );
}

// --- «Допущения и риски» ----------------------------------------------------------------------

const TAG_TONE = new Map<TagCategory, string>([
  ['assumption', 'ok'],
  ['constraint', 'warn'],
  ['risk', 'bad'],
  ['tech', 'acc'],
]);

export function TagsPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<TagCategory | null>(null);
  const exporting = useMutation({
    mutationFn: () =>
      downloadExport(
        () => call(() => api.GET('/projects/{id}/assumptions/export', { params: { path: { id: projectId } } })),
        { fallbackName: 'assumptions.docx' },
      ),
  });
  return (
    <StatsShell projectId={projectId} active="tags">
      {({ project, stats, perms }) => {
        const lines = tagLines(
          stats,
          { pct: formatNumber(project.pm_percent, 0), reason: project.pm_percent_reason ?? '' },
          t('stats.details.projectSettings'),
        ).filter((l) => filter === null || l.category === filter);
        return (
          <div className="det-one">
            <section className="card det-card" aria-labelledby="det-tags">
              <div className="card-head">
                <h3 id="det-tags">{t('stats.details.tagsTitle')}</h3>
                <span className="det-tools">
                  <Select
                    size="xs"
                    aria-label={t('stats.details.tagFilter')}
                    allowDeselect={false}
                    value={filter ?? 'all'}
                    data={[
                      { value: 'all', label: t('stats.details.tagAll') },
                      ...TAG_ORDER.map((c) => ({ value: c, label: t(`stats.details.tag.${c}`) })),
                    ]}
                    onChange={(v) => setFilter(v && v !== 'all' ? (v as TagCategory) : null)}
                  />
                  {perms.includes('export.money') ? (
                    <Button
                      size="xs"
                      variant="default"
                      loading={exporting.isPending}
                      onClick={() => exporting.mutate()}
                    >
                      ⇩ {t('stats.details.word')}
                    </Button>
                  ) : null}
                </span>
              </div>
              {exporting.error ? (
                <div className="err" role="alert">
                  {exporting.error instanceof ExportTimeout ? t('stats.exportTimeout') : errorMessage(exporting.error)}
                </div>
              ) : null}
              {lines.length === 0 ? <p className="card-hint">{t('stats.details.tagsEmpty')}</p> : null}
              <ul className="det-tags">
                {lines.map((l) => {
                  const body = (
                    <>
                      <span className={`pill ${TAG_TONE.get(l.category) ?? 'gray'}`}>
                        {t(`stats.details.tagShort.${l.category}`)}
                      </span>{' '}
                      <span>{l.text}</span>
                      <span className="sub">{l.path}</span>
                    </>
                  );
                  const nodeId = l.nodeId;
                  return (
                    <li key={l.key}>
                      {nodeId ? (
                        <button
                          type="button"
                          className="det-tag"
                          onClick={() => navigate(`/projects/${projectId}?node=${nodeId}`)}
                        >
                          {body}
                        </button>
                      ) : (
                        <div className="det-tag">{body}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
              <p className="card-hint">{t('stats.details.tagsHint')}</p>
            </section>
          </div>
        );
      }}
    </StatsShell>
  );
}
