/** FE-005 · установка пароля по ссылке активации (FR-AUTH-LOC-01, FR-SA-01; срок ссылки 72 часа). */
import { useTranslation } from 'react-i18next';

import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { NewPasswordForm } from './PasswordPages';

export function ActivatePage() {
  const { t } = useTranslation();
  return (
    <NewPasswordForm
      title={t('auth.activate.title')}
      subtitle={t('auth.activate.subtitle')}
      doneText={t('auth.activate.done')}
      submitLabel={t('auth.activate.submit')}
      send={async (token, password) => {
        await call(() => api.POST('/auth/activate', { body: { token, password } }));
      }}
    />
  );
}
