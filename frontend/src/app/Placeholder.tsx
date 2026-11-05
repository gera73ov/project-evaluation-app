/** FE-003 · заглушка экрана, который делает следующая задача плана. */
import { useTranslation } from 'react-i18next';

import { EmptyState } from '../shared/ui/EmptyState';

export function Placeholder({ title, task }: { title: string; task: string }) {
  const { t } = useTranslation();
  return (
    <div className="main">
      <h1 className="page-title">{title}</h1>
      <EmptyState title={t('placeholder.title')} hint={t('placeholder.hint', { task })} />
    </div>
  );
}

export function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="main">
      <EmptyState title={t('errors.NOT_FOUND')} hint={t('placeholder.notFound')} />
    </div>
  );
}
