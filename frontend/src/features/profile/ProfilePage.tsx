/**
 * FE-006 · профиль (SPEC 8.1 «Профиль»): данные и часовой пояс (FR-UI-02), смена пароля для
 * локальных учёток (FR-AUTH-LOC-04), вход по коду — подключить, новые резервные коды, отключить
 * со step-up (FR-2FA-01, SEC-AUTH-05), активные сессии (FR-SESS-04), письма (FR-NOTIF-02).
 */
import { Button, Group, PasswordInput, Select, Switch, Table, Text, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../shared/api/client';
import { ApiError, call } from '../../shared/api/problem';
import { formatDateTime } from '../../shared/format/date';
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../shared/ui/ErrorText';
import { StepUpModal } from '../../shared/ui/StepUpModal';
import { useSession, type Me } from '../../app/session';
import { PASSWORD_MIN } from '../auth/PasswordPages';
import { BackupCodes } from './BackupCodes';
import { TotpSetup, type EnrollStart } from './TotpSetup';

type Session = components['schemas']['Session'];

export function ProfilePage() {
  const { t } = useTranslation();
  const { session } = useSession();
  if (session.state !== 'ready') return null;
  const me = session.me;
  return (
    <div className="main">
      <h1 className="page-title">{t('profile.title')}</h1>
      <AccountSection me={me} />
      {me.source === 'local' ? <PasswordSection /> : null}
      <TotpSection me={me} />
      <SessionsSection timezone={me.timezone ?? undefined} />
      <NotificationsSection />
    </div>
  );
}

function timeZones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone');
  } catch {
    return ['Europe/Moscow'];
  }
}

function AccountSection({ me }: { me: Me }) {
  const { t } = useTranslation();
  const { refresh } = useSession();
  const [fullName, setFullName] = useState(me.full_name);
  const [timezone, setTimezone] = useState<string | null>(me.timezone);
  const save = useMutation({
    mutationFn: () =>
      call(() =>
        api.PATCH('/me', {
          body: me.source === 'local' ? { full_name: fullName.trim(), timezone } : { timezone },
        }),
      ),
    onSuccess: () => refresh(),
  });
  const changed = fullName.trim() !== me.full_name || timezone !== me.timezone;
  return (
    <section className="sec" aria-labelledby="profile-account">
      <h3 id="profile-account">{t('profile.account.title')}</h3>
      <ErrorText error={save.error} />
      <Group grow align="flex-start">
        <TextInput label={t('profile.account.login')} value={me.login} readOnly />
        <TextInput label={t('profile.account.email')} value={me.email ?? '—'} readOnly />
      </Group>
      <TextInput
        mt="sm"
        label={t('profile.account.fullName')}
        value={fullName}
        readOnly={me.source !== 'local'}
        description={me.source !== 'local' ? t('profile.account.fromAd') : undefined}
        onChange={(e) => setFullName(e.currentTarget.value)}
      />
      <Select
        mt="sm"
        searchable
        clearable
        label={t('profile.account.timezone')}
        placeholder={t('profile.account.timezoneDefault')}
        data={timeZones()}
        value={timezone}
        onChange={setTimezone}
      />
      <Button mt="md" onClick={() => save.mutate()} loading={save.isPending} disabled={!changed || fullName.trim() === ''}>
        {t('common.save')}
      </Button>
    </section>
  );
}

function PasswordSection() {
  const { t } = useTranslation();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const change = useMutation({
    mutationFn: () => call(() => api.POST('/me/password', { body: { current_password: current, new_password: next } })),
    onSuccess: () => {
      setCurrent('');
      setNext('');
      setRepeat('');
    },
  });
  const ready = current !== '' && next.length >= PASSWORD_MIN && next === repeat;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (ready && !change.isPending) change.mutate();
  }
  return (
    <section className="sec" aria-labelledby="profile-password">
      <h3 id="profile-password">{t('profile.password.title')}</h3>
      <form onSubmit={submit}>
        <ErrorText error={change.error} />
        {change.isSuccess ? (
          <Text role="status" c="green" mb="sm">
            {t('profile.password.done')}
          </Text>
        ) : null}
        <PasswordInput
          label={t('profile.password.current')}
          value={current}
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
        />
        <Button mt="md" type="submit" loading={change.isPending} disabled={!ready}>
          {t('profile.password.submit')}
        </Button>
      </form>
    </section>
  );
}

function TotpSection({ me }: { me: Me }) {
  const { t } = useTranslation();
  const { refresh } = useSession();
  const [mode, setMode] = useState<'idle' | 'setup'>('idle');
  const [codes, setCodes] = useState<readonly string[] | null>(null);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const start = useCallback(async () => (await call(() => api.POST('/me/totp', { body: {} }))) as EnrollStart, []);
  const confirm = useCallback(async (code: string) => {
    const result = await call(() => api.POST('/me/totp', { body: { code } }));
    return 'backup_codes' in result ? result.backup_codes : [];
  }, []);

  async function regenerate() {
    setError(null);
    try {
      setCodes((await call(() => api.POST('/me/backup-codes'))).backup_codes);
    } catch (e) {
      setError(e);
    }
  }

  async function disable() {
    setError(null);
    try {
      await call(() => api.DELETE('/me/totp'));
      setConfirmDisable(false);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STEP_UP_REQUIRED') {
        setConfirmDisable(false);
        setStepUp(true); // после подтверждения запрос повторяется
        return;
      }
      setConfirmDisable(false);
      setError(e);
    }
  }

  return (
    <section className="sec" aria-labelledby="profile-totp">
      <h3 id="profile-totp">{t('profile.totp.title')}</h3>
      <ErrorText error={error} />
      {me.totp_enabled ? (
        <>
          <Text mb="sm">
            <span className="pill ok">✓ {t('profile.totp.enabled')}</span>
          </Text>
          {codes ? <BackupCodes codes={codes} /> : null}
          <Group mt="sm">
            <Button variant="default" onClick={() => void regenerate()}>
              {t('profile.totp.newCodes')}
            </Button>
            {me.totp_required ? (
              <Text c="dimmed" size="xs">
                {t('profile.totp.required')}
              </Text>
            ) : (
              <Button variant="default" color="red" onClick={() => setConfirmDisable(true)}>
                {t('profile.totp.disable')}
              </Button>
            )}
          </Group>
        </>
      ) : mode === 'setup' ? (
        <TotpSetup
          start={start}
          confirm={confirm}
          doneLabel={t('totp.done')}
          onDone={() => {
            setMode('idle');
            void refresh();
          }}
        />
      ) : (
        <>
          <Text mb="sm">{t('profile.totp.disabled')}</Text>
          <Button onClick={() => setMode('setup')}>{t('profile.totp.enable')}</Button>
        </>
      )}
      <ConfirmDialog
        opened={confirmDisable}
        title={t('profile.totp.disableTitle')}
        message={t('profile.totp.disableText')}
        confirmLabel={t('profile.totp.disable')}
        danger
        onConfirm={() => void disable()}
        onCancel={() => setConfirmDisable(false)}
      />
      <StepUpModal
        opened={stepUp}
        onClose={() => setStepUp(false)}
        onSuccess={() => {
          setStepUp(false);
          void disable();
        }}
      />
    </section>
  );
}

const SESSIONS_KEY = ['me', 'sessions'] as const;

function SessionsSection({ timezone }: { timezone?: string | undefined }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const list = useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: async () => (await call(() => api.GET('/me/sessions'))).items,
  });
  const end = useMutation({
    mutationFn: (id: string | null) =>
      call(() => api.DELETE('/me/sessions', { params: { query: id ? { id } : {} } })),
    onSuccess: () => client.invalidateQueries({ queryKey: SESSIONS_KEY }),
  });
  const sessions: Session[] = list.data ?? [];
  const others = sessions.filter((s) => !s.current).length;
  return (
    <section className="sec" aria-labelledby="profile-sessions">
      <h3 id="profile-sessions">{t('profile.sessions.title')}</h3>
      <ErrorText error={list.error ?? end.error} />
      <Table className="t">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('profile.sessions.browser')}</Table.Th>
            <Table.Th>{t('profile.sessions.ip')}</Table.Th>
            <Table.Th>{t('profile.sessions.created')}</Table.Th>
            <Table.Th>{t('profile.sessions.lastSeen')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {sessions.map((s) => (
            <Table.Tr key={s.id}>
              <Table.Td>{s.user_agent ?? '—'}</Table.Td>
              <Table.Td className="mono">{s.ip}</Table.Td>
              <Table.Td>{formatDateTime(s.created_at, timezone)}</Table.Td>
              <Table.Td>{formatDateTime(s.last_seen_at, timezone)}</Table.Td>
              <Table.Td className="r">
                {s.current ? (
                  <span className="pill acc">{t('profile.sessions.current')}</span>
                ) : (
                  <Button size="compact-xs" variant="default" onClick={() => end.mutate(s.id)}>
                    {t('profile.sessions.end')}
                  </Button>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Button mt="md" variant="default" disabled={others === 0} loading={end.isPending} onClick={() => end.mutate(null)}>
        {t('profile.sessions.endOthers')}
      </Button>
    </section>
  );
}

const NOTIFY_KEY = ['me', 'notification-settings'] as const;

function NotificationsSection() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: NOTIFY_KEY,
    queryFn: () => call(() => api.GET('/me/notification-settings')),
  });
  const save = useMutation({
    mutationFn: (body: components['schemas']['NotificationSettings']) =>
      call(() => api.PUT('/me/notification-settings', { body })),
    onSuccess: (data) => client.setQueryData(NOTIFY_KEY, data),
  });
  const value = query.data;
  return (
    <section className="sec" aria-labelledby="profile-notify">
      <h3 id="profile-notify">{t('profile.notify.title')}</h3>
      <ErrorText error={query.error ?? save.error} />
      {value ? (
        <>
          <Switch
            label={t('profile.notify.questions')}
            checked={value.notify_questions}
            onChange={(e) => save.mutate({ ...value, notify_questions: e.currentTarget.checked })}
          />
          <Switch
            mt="sm"
            label={t('profile.notify.digest')}
            checked={value.notify_digest}
            onChange={(e) => save.mutate({ ...value, notify_digest: e.currentTarget.checked })}
          />
        </>
      ) : null}
    </section>
  );
}
