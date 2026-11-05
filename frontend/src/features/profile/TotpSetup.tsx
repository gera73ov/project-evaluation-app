/**
 * FE-006 · подключение TOTP: QR, секрет с «Скопировать», первый код, затем резервные коды.
 * Используется на принудительном экране (`/auth/totp/enroll*`, FR-2FA-04) и в профиле
 * (`/me/totp`). `start` и `confirm` передаёт вызывающий.
 */
import { Button, CopyButton, Loader } from '@mantine/core';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ErrorText } from '../../shared/ui/ErrorText';
import { QrCode } from '../../shared/ui/QrCode';
import { TotpCodeInput } from '../../shared/ui/TotpCodeInput';
import { BackupCodes } from './BackupCodes';

export interface EnrollStart {
  otpauth_uri: string;
  secret: string;
}

export function TotpSetup({
  start,
  confirm,
  onDone,
  doneLabel,
}: {
  start: () => Promise<EnrollStart>;
  confirm: (code: string) => Promise<readonly string[]>;
  onDone: () => void;
  doneLabel: string;
}) {
  const { t } = useTranslation();
  const [enroll, setEnroll] = useState<EnrollStart | null>(null);
  const [codes, setCodes] = useState<readonly string[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    start().then(
      (value) => alive && setEnroll(value),
      (e: unknown) => alive && setError(e),
    );
    return () => {
      alive = false;
    };
  }, [start]);

  async function submit(code: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setCodes(await confirm(code));
    } catch (e) {
      setError(e);
      setAttempt((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }

  if (codes) {
    return (
      <div>
        <BackupCodes codes={codes} />
        <Button fullWidth size="md" mt="md" onClick={onDone}>
          {doneLabel}
        </Button>
      </div>
    );
  }
  if (!enroll) return error ? <ErrorText error={error} /> : <Loader aria-label={t('common.loading')} />;
  return (
    <div>
      <ErrorText error={error} />
      <p>{t('totp.scan')}</p>
      <QrCode value={enroll.otpauth_uri} label={t('totp.qr')} />
      <div className="secret">
        <span aria-label={t('totp.secret')}>{enroll.secret}</span>
        <CopyButton value={enroll.secret}>
          {({ copied, copy }) => (
            <Button size="compact-xs" variant="default" onClick={copy}>
              {copied ? t('common.copied') : t('common.copy')}
            </Button>
          )}
        </CopyButton>
      </div>
      <p>{t('totp.firstCode')}</p>
      <TotpCodeInput key={attempt} autoFocus={false} disabled={busy} onComplete={(code) => void submit(code)} />
    </div>
  );
}
