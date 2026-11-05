/**
 * FE-006 · принудительное подключение TOTP (FR-2FA-04): после пароля, если TOTP обязателен и не
 * подключён. До подключения доступны только этот экран и выход (гард в app/Routes.tsx).
 */
import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { useNavigate } from '../../app/router';
import { useSession } from '../../app/session';
import { AuthCard } from '../auth/AuthCard';
import { TotpSetup } from './TotpSetup';

export function TotpEnrollPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refresh, clear } = useSession();
  const start = useCallback(() => call(() => api.POST('/auth/totp/enroll')), []);
  const confirm = useCallback(
    async (code: string) => (await call(() => api.POST('/auth/totp/enroll/confirm', { body: { code } }))).backup_codes,
    [],
  );

  async function logout() {
    try {
      await call(() => api.POST('/auth/logout'));
    } finally {
      clear();
      navigate('/login', { replace: true });
    }
  }

  return (
    <AuthCard title={t('totp.enrollTitle')} subtitle={t('totp.enrollSubtitle')} wide>
      <TotpSetup
        start={start}
        confirm={confirm}
        doneLabel={t('totp.continue')}
        onDone={() => {
          void refresh().then(() => navigate('/', { replace: true }));
        }}
      />
      <button type="button" className="link muted center" onClick={() => void logout()}>
        {t('nav.logout')}
      </button>
    </AuthCard>
  );
}
