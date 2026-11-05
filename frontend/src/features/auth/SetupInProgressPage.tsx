/** FE-005 · «Приложение настраивается» (FR-SA-02): мастер первичной настройки не завершён. */
import { useTranslation } from 'react-i18next';

import { Link } from '../../app/router';
import { AuthCard } from './AuthCard';

export function SetupInProgressPage() {
  const { t } = useTranslation();
  return (
    <AuthCard title={t('errors.APP_SETUP_IN_PROGRESS')} subtitle={t('auth.setup.subtitle')}>
      <Link to="/login" className="link center">
        {t('auth.setup.retry')}
      </Link>
    </AuthCard>
  );
}
