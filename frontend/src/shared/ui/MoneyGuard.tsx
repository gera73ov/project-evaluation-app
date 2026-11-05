/**
 * FE-004 · заглушка денежного блока без второго фактора (FR-2FA-05, DESIGN.md 8.4). На 403
 * `TOTP_REQUIRED` вместо блока — «🔒 Подтвердите вход кодом» и step-up «только код»; после успеха
 * `onUnlocked` перезапрашивает деньги без перезагрузки страницы. Без подключённого TOTP — ссылка
 * на подключение в профиле.
 */
import { Button } from '@mantine/core';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '../api/problem';
import { StepUpModal } from './StepUpModal';

export function isTotpRequired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.code === 'TOTP_REQUIRED';
}

export function MoneyGuard({
  error,
  totpEnabled,
  onUnlocked,
  onEnroll,
  children,
}: {
  /** Ошибка запроса денег; не TOTP_REQUIRED — блок рисуется как обычно */
  error: unknown;
  totpEnabled: boolean;
  onUnlocked: () => void;
  onEnroll: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!isTotpRequired(error)) return <>{children}</>;
  return (
    <div className="money-guard">
      <span className="lock">
        {t(totpEnabled ? 'money.guard.confirm' : 'money.guard.enroll')}{' '}
        <Button size="compact-xs" variant="default" onClick={() => (totpEnabled ? setOpen(true) : onEnroll())}>
          {t(totpEnabled ? 'money.guard.enterCode' : 'money.guard.enrollButton')}
        </Button>
      </span>
      <StepUpModal
        opened={open}
        totpOnly
        onClose={() => setOpen(false)}
        onSuccess={() => {
          setOpen(false);
          onUnlocked();
        }}
      />
    </div>
  );
}
