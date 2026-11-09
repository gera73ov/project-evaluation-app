/**
 * FE-040 · шапка экрана статистики (SPEC 11.8 №1, 10.1; DESIGN.md 5.6): «Проект › Статистика»,
 * «← К оценке» и вкладки-маршруты. На «Вопросах заказчику» — счётчик новых вопросов.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Link } from '../../app/router';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';

export const STATS_TABS = [
  { key: 'readiness', path: '/stats' },
  { key: 'totals', path: '/stats/totals' },
  { key: 'shares', path: '/stats/shares' },
  { key: 'volumes', path: '/stats/volumes' },
  { key: 'candidates', path: '/stats/candidates' },
  { key: 'tags', path: '/stats/tags' },
  { key: 'discussions', path: '/stats/discussions' },
  { key: 'questions', path: '/stats/questions' },
  { key: 'snapshots', path: '/stats/snapshots' },
] as const;

export type StatsTab = (typeof STATS_TABS)[number]['key'];

/** Новые вопросы заказчику (статус «новый»): число для вкладки; без права `cq.read` — ничего. */
function useNewQuestions(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['cq', projectId, 'new-count'],
    queryFn: () =>
      call(() =>
        api.GET('/projects/{id}/customer-questions', {
          params: { path: { id: projectId }, query: { status: 'new', limit: 200 } },
        }),
      ),
    select: (data) => data.items.length,
    enabled,
    retry: false,
  });
}

export function StatsHeader({
  projectId,
  projectName,
  active,
  canReadQuestions,
}: {
  projectId: string;
  projectName: string;
  active: StatsTab;
  canReadQuestions: boolean;
}) {
  const { t } = useTranslation();
  const fresh = useNewQuestions(projectId, canReadQuestions);
  return (
    <>
      <div className="crumbs">
        <Link to={`/projects/${projectId}`}>{projectName}</Link>
        <span aria-hidden="true"> › </span>
        <h1>{t('stats.title')}</h1>
        <span className="sp" />
        <Link to={`/projects/${projectId}`} className="btn-link">
          ← {t('stats.back')}
        </Link>
      </div>
      <nav className="tabs set-tabs" aria-label={t('stats.title')}>
        {STATS_TABS.map((tab) => (
          <Link
            key={tab.key}
            to={`/projects/${projectId}${tab.path}`}
            className={tab.key === active ? 'on' : undefined}
            {...(tab.key === active ? { 'aria-current': 'page' as const } : {})}
          >
            {t(`stats.tabs.${tab.key}`)}
            {tab.key === 'questions' && fresh.data ? (
              <span className="pill warn">{t('stats.newQuestions', { count: fresh.data })}</span>
            ) : null}
          </Link>
        ))}
      </nav>
    </>
  );
}
