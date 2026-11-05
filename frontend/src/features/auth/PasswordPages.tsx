/**
 * FE-005 · «Забыли пароль?» (FR-AUTH-LOC-03: ответ всегда одинаковый) и сброс пароля по ссылке
 * (`?token=`, срок 60 минут, после сброса все сессии завершаются).
 */
import { Button, PasswordInput, TextInput } from '@mantine/core';
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';
import { Link, useSearchParam } from '../../app/router';
import { AuthCard } from './AuthCard';

export const PASSWORD_MIN = 12;

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [value, setValue] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || value.trim() === '') return;
    setBusy(true);
    setError(null);
    try {
      await call(() =>
        api.POST('/auth/password/forgot', {
          body: { login_or_email: value.trim() },
        }),
      );
      setSent(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title={t('auth.forgot.title')} subtitle={sent ? undefined : t('auth.forgot.subtitle')}>
      {sent ? (
        <p role="status">{t('auth.forgot.sent')}</p>
      ) : (
        <form onSubmit={(e) => void submit(e)}>
          <ErrorText error={error} />
          <TextInput
            label={t('auth.forgot.label')}
            value={value}
            autoFocus
            onChange={(e) => setValue(e.currentTarget.value)}
            mb="md"
          />
          <Button type="submit" fullWidth size="md" loading={busy} disabled={value.trim() === ''}>
            {t('auth.forgot.submit')}
          </Button>
        </form>
      )}
      <Link to="/login" className="link center">
        {t('auth.toLogin')}
      </Link>
    </AuthCard>
  );
}

/** Общая форма «новый пароль + повтор» для активации и сброса (SEC-AUTH-03: ≥ 12 символов). */
export function NewPasswordForm({
  title,
  subtitle,
  doneText,
  submitLabel,
  send,
}: {
  title: string;
  subtitle: string;
  doneText: string;
  submitLabel: string;
  send: (token: string, password: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const token = useSearchParam('token') ?? '';
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [done, setDone] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const tooShort = password.length > 0 && password.length < PASSWORD_MIN;
  const mismatch = repeat.length > 0 && repeat !== password;
  const ready = password.length >= PASSWORD_MIN && repeat === password && token !== '';

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !ready) return;
    setBusy(true);
    setError(null);
    try {
      await send(token, password);
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title={title} subtitle={done ? undefined : subtitle}>
      {done ? (
        <p role="status">{doneText}</p>
      ) : token === '' ? (
        <div className="err" role="alert">
          {t('errors.TOKEN_INVALID')}
        </div>
      ) : (
        <form onSubmit={(e) => void submit(e)}>
          <ErrorText error={error} />
          <PasswordInput
            label={t('auth.newPassword.label')}
            description={t('auth.newPassword.rule', { min: PASSWORD_MIN })}
            value={password}
            autoFocus
            autoComplete="new-password"
            error={tooShort ? t('auth.newPassword.short', { min: PASSWORD_MIN }) : null}
            onChange={(e) => setPassword(e.currentTarget.value)}
            mb="sm"
          />
          <PasswordInput
            label={t('auth.newPassword.repeat')}
            value={repeat}
            autoComplete="new-password"
            error={mismatch ? t('auth.newPassword.mismatch') : null}
            onChange={(e) => setRepeat(e.currentTarget.value)}
            mb="md"
          />
          <Button type="submit" fullWidth size="md" loading={busy} disabled={!ready}>
            {submitLabel}
          </Button>
        </form>
      )}
      <Link to="/login" className="link center">
        {t('auth.toLogin')}
      </Link>
    </AuthCard>
  );
}

export function ResetPasswordPage() {
  const { t } = useTranslation();
  return (
    <NewPasswordForm
      title={t('auth.reset.title')}
      subtitle={t('auth.reset.subtitle')}
      doneText={t('auth.reset.done')}
      submitLabel={t('auth.reset.submit')}
      send={async (token, password) => {
        await call(() => api.POST('/auth/password/reset', { body: { token, password } }));
      }}
    />
  );
}
