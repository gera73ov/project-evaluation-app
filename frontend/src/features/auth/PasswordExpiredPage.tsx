/**
 * Смена истёкшего пароля при входе (FR-AUTH-LOC-02, CR-003; решение владельца 06.11.2026).
 * Вход вернул `step=password_change`: сессия ограничена, до смены доступны только этот экран и
 * выход (гард в app/Routes.tsx). После смены сервер выдаёт новую сессию; если TOTP обязателен и
 * не подключён, гард дальше ведёт на подключение.
 */
import { Button, PasswordInput } from '@mantine/core';
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';
import { useNavigate } from '../../app/router';
import { useSession } from '../../app/session';
import { AuthCard } from './AuthCard';
import { PASSWORD_MIN } from './PasswordPages';

export function PasswordExpiredPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refresh, clear } = useSession();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const ready = current !== '' && next.length >= PASSWORD_MIN && next === repeat;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await call(() => api.POST('/me/password', { body: { current_password: current, new_password: next } }));
      await refresh();
      navigate('/', { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await call(() => api.POST('/auth/logout'));
    } finally {
      clear();
      navigate('/login', { replace: true });
    }
  }

  return (
    <AuthCard title={t('auth.expired.title')} subtitle={t('auth.expired.subtitle')}>
      <form onSubmit={(e) => void submit(e)}>
        <ErrorText error={error} />
        <PasswordInput
          label={t('auth.expired.current')}
          value={current}
          autoFocus
          autoComplete="current-password"
          onChange={(e) => setCurrent(e.currentTarget.value)}
        />
        <PasswordInput
          mt="sm"
          label={t('auth.newPassword.label')}
          description={t('auth.newPassword.rule', { min: PASSWORD_MIN })}
          value={next}
          autoComplete="new-password"
          onChange={(e) => setNext(e.currentTarget.value)}
        />
        <PasswordInput
          mt="sm"
          label={t('auth.newPassword.repeat')}
          value={repeat}
          autoComplete="new-password"
          error={repeat !== '' && repeat !== next ? t('auth.newPassword.mismatch') : null}
          onChange={(e) => setRepeat(e.currentTarget.value)}
          mb="md"
        />
        <Button type="submit" fullWidth size="md" loading={busy} disabled={!ready}>
          {t('auth.expired.submit')}
        </Button>
      </form>
      <button type="button" className="link muted center" onClick={() => void logout()}>
        {t('nav.logout')}
      </button>
    </AuthCard>
  );
}
