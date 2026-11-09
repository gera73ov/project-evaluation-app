/**
 * FE-005 · вход и второй фактор (SPEC 11.1 №1–7, FR-LOCK-05, FR-AUTH-AD-13, FR-AUTH-LOC-03, R-04).
 *
 * Шаги: логин и пароль → (код TOTP | резервный код) → вход; `step=enroll` ведёт на подключение
 * TOTP (FR-2FA-04), `step=password_change` — на смену истёкшего пароля (CR-003). Тексты ошибок — дословно из errors.yaml; пароль после ошибки очищается.
 */
import { Button, PasswordInput, TextInput } from '@mantine/core';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../shared/api/client';
import { ApiError, call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';
import { TotpCodeInput } from '../../shared/ui/TotpCodeInput';
import { Link, useNavigate, useSearchParam } from '../../app/router';
import { safeNext } from '../../app/Routes';
import { useSession } from '../../app/session';
import { AuthCard } from './AuthCard';
import { isAuthMode, loadAuthMode, type AuthMode } from './authMode';

type LoginResponse = components['schemas']['LoginResponse'];
type Step = { kind: 'credentials' } | { kind: 'totp'; ticket: string } | { kind: 'backup'; ticket: string };

const BACKUP_RE = /^\d{8}$/;
const TOTP_RE = /^\d{6}$/;

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const next = safeNext(useSearchParam('next'));
  const { refresh, session } = useSession();
  const [mode, setMode] = useState<AuthMode>('app');
  const [step, setStep] = useState<Step>({ kind: 'credentials' });
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [backup, setBackup] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const busyRef = useRef(false);
  const modeFromServer = useRef(false);
  /** Куда перейти после входа: ждём, пока сессия в контексте обновится, иначе гард вернёт на вход. */
  const [target, setTarget] = useState<string | null>(null);
  const navigated = useRef(false);

  useEffect(() => {
    const signedIn = ['ready', 'enroll', 'password_change'].includes(session.state);
    if (!target || navigated.current || !signedIn) return;
    navigated.current = true; // переход один раз, даже если next указывает на сам вход
    navigate(target, { replace: true });
  }, [target, session.state, navigate]);

  useEffect(() => {
    let alive = true;
    // режим из ответа сервера на вход точнее предварительного: поздний ответ его не перетирает
    void loadAuthMode().then((m) => alive && !modeFromServer.current && setMode(m));
    return () => {
      alive = false;
    };
  }, []);

  async function finish(result: LoginResponse) {
    const ticket = result.login_token;
    if (result.step === 'totp' && ticket) {
      setStep({ kind: 'totp', ticket });
      return;
    }
    await refresh();
    if (result.step === 'password_change') setTarget('/change-password');
    else setTarget(result.step === 'enroll' ? '/enroll-totp' : next);
  }

  /** Один запрос за раз: повторное нажатие во время проверки игнорируется (11.1 №2). */
  async function run(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'APP_SETUP_IN_PROGRESS') {
        navigate('/setup-in-progress', { replace: true });
        return;
      }
      setError(e);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function submitCredentials(e?: FormEvent) {
    e?.preventDefault();
    if (login.trim() === '' || password === '') return;
    void run(async () => {
      try {
        await finish(await call(() => api.POST('/auth/login', { body: { login, password } })));
      } catch (err) {
        setPassword(''); // 11.1 №4
        if (err instanceof ApiError) {
          const reported = err.extension('auth_mode');
          if (isAuthMode(reported)) {
            modeFromServer.current = true;
            setMode(reported);
          }
        }
        throw err;
      }
    });
  }

  function submitCode(token: string, body: { code: string } | { backup_code: string }) {
    void run(async () => {
      try {
        await finish(await call(() => api.POST('/auth/totp', { body: { login_token: token, ...body } })));
      } catch (err) {
        if (err instanceof ApiError && err.code === 'LOGIN_STEP_EXPIRED') backToLogin();
        setAttempt((n) => n + 1);
        setCode('');
        throw err;
      }
    });
  }

  function backToLogin() {
    setStep({ kind: 'credentials' });
    setPassword('');
    setBackup('');
    setCode('');
  }

  if (step.kind !== 'credentials') {
    return (
      <AuthCard
        title={t('auth.totp.title')}
        subtitle={step.kind === 'totp' ? t('auth.totp.subtitle') : t('auth.backup.subtitle')}
      >
        <ErrorText error={error} />
        {step.kind === 'totp' ? (
          <>
            <TotpCodeInput
              key={attempt}
              disabled={busy}
              onChange={setCode}
              onComplete={(value) => submitCode(step.ticket, { code: value })}
            />
            <Button
              fullWidth
              size="md"
              loading={busy}
              disabled={!TOTP_RE.test(code)}
              onClick={() => submitCode(step.ticket, { code })}
            >
              {t('auth.totp.submit')}
            </Button>
          </>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (BACKUP_RE.test(backup)) submitCode(step.ticket, { backup_code: backup });
            }}
          >
            <TextInput
              label={t('auth.backup.label')}
              value={backup}
              inputMode="numeric"
              maxLength={8}
              autoFocus
              autoComplete="one-time-code"
              onChange={(e) => setBackup(e.currentTarget.value.replace(/\D/g, ''))}
              mb="md"
            />
            <Button type="submit" fullWidth size="md" loading={busy} disabled={!BACKUP_RE.test(backup)}>
              {t('auth.totp.submit')}
            </Button>
          </form>
        )}
        <div className="link-row">
          {step.kind === 'totp' ? (
            <button type="button" className="link" onClick={() => setStep({ kind: 'backup', ticket: step.ticket })}>
              {t('auth.totp.useBackup')}
            </button>
          ) : (
            <button type="button" className="link" onClick={() => setStep({ kind: 'totp', ticket: step.ticket })}>
              {t('auth.backup.useTotp')}
            </button>
          )}
          <button type="button" className="link muted" onClick={backToLogin}>
            {t('common.back')}
          </button>
        </div>
        {step.kind === 'totp' ? <div className="hint">{t('auth.totp.refresh')}</div> : null}
      </AuthCard>
    );
  }

  const empty = login.trim() === '' || password === '';
  return (
    <AuthCard
      title={t('auth.login.title')}
      subtitle={mode === 'ad' ? t('auth.login.subtitleAd') : t('auth.login.subtitleApp')}
    >
      <form onSubmit={submitCredentials} noValidate>
        <ErrorText error={error} variant={mode === 'ad' ? 'ad' : undefined} />
        <TextInput
          label={t('auth.login.login')}
          value={login}
          autoFocus
          autoComplete="username"
          onChange={(e) => setLogin(e.currentTarget.value)}
          mb="sm"
        />
        <PasswordInput
          label={t('auth.password')}
          value={password}
          autoComplete="current-password"
          placeholder={t('auth.login.passwordPlaceholder')}
          onChange={(e) => setPassword(e.currentTarget.value)}
          mb="md"
        />
        <Button type="submit" fullWidth size="md" loading={busy} disabled={empty}>
          {t('auth.login.submit')}
        </Button>
      </form>
      {mode === 'ad' ? (
        <div className="hint">🔒 {t('auth.login.adHint')}</div>
      ) : (
        <Link to="/password/forgot" className="link center">
          {t('auth.login.forgot')}
        </Link>
      )}
    </AuthCard>
  );
}
