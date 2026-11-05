/**
 * FE-004 · подтверждение действия (SEC-AUTH-05, FR-2FA-05): пароль + код TOTP или, для денег,
 * только код. Сессия не завершается: при успехе вызывается `onSuccess`, вызывающий повторяет запрос.
 */
import { Button, Modal, PasswordInput, Stack, Text } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../api/client';
import { call } from '../api/problem';
import { ErrorText } from './ErrorText';
import { TotpCodeInput } from './TotpCodeInput';

export function StepUpModal({
  opened,
  totpOnly = false,
  onClose,
  onSuccess,
}: {
  opened: boolean;
  totpOnly?: boolean;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  async function submit(finalCode = code) {
    if (busy || finalCode.length !== 6 || (!totpOnly && password === '')) return;
    setBusy(true);
    setError(null);
    try {
      await call(() =>
        api.POST('/auth/step-up', {
          body: totpOnly
            ? { code: finalCode, totp_only: true }
            : { code: finalCode, password, totp_only: false },
        }),
      );
      setPassword('');
      onSuccess();
    } catch (e) {
      setError(e);
      setAttempt((n) => n + 1); // новые пустые клетки
      setCode('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal opened={opened} onClose={onClose} title={t(totpOnly ? 'stepUp.titleTotp' : 'stepUp.title')} centered>
      <Stack gap="sm">
        <Text c="dimmed">{t(totpOnly ? 'stepUp.hintTotp' : 'stepUp.hint')}</Text>
        <ErrorText error={error} />
        {totpOnly ? null : (
          <PasswordInput
            label={t('auth.password')}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            autoComplete="current-password"
            data-autofocus
          />
        )}
        <TotpCodeInput
          key={attempt}
          autoFocus={totpOnly}
          disabled={busy}
          onChange={setCode}
          onComplete={(c) => {
            setCode(c);
            if (totpOnly || password !== '') void submit(c);
          }}
        />
        <Button
          onClick={() => void submit()}
          loading={busy}
          disabled={code.length !== 6 || (!totpOnly && password === '')}
        >
          {t('common.confirm')}
        </Button>
      </Stack>
    </Modal>
  );
}
