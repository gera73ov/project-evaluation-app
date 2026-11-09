/**
 * FE-063 · «Суперадминистраторы и администраторы» и «Аудиторы ИБ» (SPEC 11.2 №1, FR-SA-05,
 * BR-ROLE-02/03, FR-2FA-03): список слева, форма справа. Создать (ссылка активации — письмом или на
 * экране), заблокировать / разблокировать, разжаловать, сбросить пароль и TOTP — всё со step-up.
 * Последнего активного суперадминистратора заблокировать и разжаловать нельзя (кнопки неактивны,
 * подсказка); четвёртого суперадминистратора создать нельзя.
 */
import { Button, Radio, Stack, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDateTime } from '../../../shared/format/date';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { ListWithForm, SystemLayout, adminsKey } from '../layout/SystemLayout';
import { StepUpCancelled, useStepUp } from '../layout/useStepUp';
import { isEmail } from '../settings/settings';
import { SUPERADMIN_MAX, accountsOf, isLastSuperadmin, type AccountKind, type AdminRole } from './accounts';

type Account = components['schemas']['AdminAccount'];
type Activation = components['schemas']['ActivationLink'];

export function useAdmins() {
  return useQuery({ queryKey: adminsKey, queryFn: () => call(() => api.GET('/system/admins')) });
}

export function AccountsPage({ kind }: { kind: AccountKind }) {
  const { t } = useTranslation();
  const admins = useAdmins();
  const [selected, setSelected] = useState<string | 'new' | null>(null);
  const all = admins.data?.items ?? [];
  const items = accountsOf(all, kind);
  const current = items.find((a) => a.id === selected) ?? null;
  return (
    <SystemLayout active={kind} title={t(`system.menu.${kind}`)} subtitle={t(`system.accounts.${kind}Sub`)}>
      <ErrorText error={admins.error} />
      <ListWithForm
        list={
          <section className="sec">
            <div className="sys-list-head">
              <span className="sub">{t('system.accounts.count', { count: items.length })}</span>
              <span className="sp" />
              <Button size="xs" onClick={() => setSelected('new')}>
                + {t('system.accounts.add')}
              </Button>
            </div>
            <table className="t sys-table">
              <thead>
                <tr>
                  <th>{t('system.accounts.name')}</th>
                  <th>{t('system.accounts.role')}</th>
                  <th>{t('system.accounts.status')}</th>
                  <th>{t('system.accounts.lastLogin')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.id} className={a.id === selected ? 'on' : undefined}>
                    <td>
                      <button type="button" className="link-btn" onClick={() => setSelected(a.id)}>
                        {a.full_name}
                      </button>
                      <div className="sub">{a.login}</div>
                    </td>
                    <td>{a.roles.map((r) => t(`system.accounts.roles.${r}`)).join(', ')}</td>
                    <td>
                      <span
                        className={`pill ${a.status === 'active' ? 'ok' : a.status === 'blocked' ? 'bad' : 'warn'}`}
                      >
                        {t(`system.accounts.st.${a.status}`)}
                      </span>
                      {a.totp_enabled ? null : <span className="sub"> · {t('system.accounts.noTotp')}</span>}
                    </td>
                    <td className="sub">{a.last_login_at ? formatDateTime(a.last_login_at) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        }
        form={
          selected === 'new' ? (
            <CreateForm key="new" kind={kind} all={all} onDone={() => setSelected(null)} />
          ) : current ? (
            <AccountForm key={current.id} account={current} all={all} kind={kind} />
          ) : null
        }
      />
    </SystemLayout>
  );
}

function CreateForm({ kind, all, onDone }: { kind: AccountKind; all: readonly Account[]; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { run, modal } = useStepUp();
  const [login, setLogin] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<AdminRole>(kind === 'auditors' ? 'security_auditor' : 'admin');
  const [link, setLink] = useState<Activation | null>(null);
  const saFull = all.filter((a) => a.status !== 'blocked' && a.roles.includes('superadmin')).length >= SUPERADMIN_MAX;
  const errors = {
    login: login.trim().length < 3,
    name: !name.trim(),
    email: !isEmail(email.trim()),
  };
  const valid = !errors.login && !errors.name && !errors.email && !(role === 'superadmin' && saFull);
  const create = useMutation({
    mutationFn: () =>
      run(() =>
        call(() =>
          api.POST('/system/admins', {
            body: { login: login.trim(), full_name: name.trim(), email: email.trim(), role },
          }),
        ),
      ),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: adminsKey });
      setLink(res);
    },
  });
  if (link)
    return (
      <Stack gap="sm">
        <h3>{t('system.accounts.created')}</h3>
        <ActivationNote link={link} />
        <Button variant="default" onClick={onDone}>
          {t('common.close')}
        </Button>
      </Stack>
    );
  return (
    <Stack gap="sm">
      <h3>{t(`system.accounts.new.${kind}`)}</h3>
      <TextInput
        label={t('system.accounts.login')}
        required
        value={login}
        maxLength={64}
        error={login && errors.login ? t('system.accounts.loginError') : null}
        onChange={(e) => setLogin(e.currentTarget.value)}
      />
      <TextInput
        label={t('system.accounts.fullName')}
        required
        value={name}
        maxLength={200}
        onChange={(e) => setName(e.currentTarget.value)}
      />
      <TextInput
        label="Email"
        required
        value={email}
        maxLength={254}
        error={email && errors.email ? t('system.settings.emailError') : null}
        onChange={(e) => setEmail(e.currentTarget.value)}
      />
      {kind === 'admins' ? (
        <Radio.Group
          label={t('system.accounts.role')}
          value={role}
          onChange={(v) => setRole(v === 'superadmin' ? 'superadmin' : 'admin')}
        >
          <Stack gap={6} mt={4}>
            <Radio value="admin" label={t('system.accounts.roles.admin')} />
            <Radio value="superadmin" label={t('system.accounts.roles.superadmin')} disabled={saFull} />
          </Stack>
        </Radio.Group>
      ) : null}
      {kind === 'admins' && saFull ? <p className="auth-hint">{t('system.accounts.saLimit')}</p> : null}
      {role === 'superadmin' ? <p className="auth-hint">{t('system.accounts.saNotice')}</p> : null}
      <ErrorText error={create.error instanceof StepUpCancelled ? null : create.error} />
      <Button disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>
        {t('system.accounts.create')}
      </Button>
      {modal}
    </Stack>
  );
}

type Action = 'block' | 'unblock' | 'demote' | 'resetPassword' | 'resetTotp';

function AccountForm({ account, all, kind }: { account: Account; all: readonly Account[]; kind: AccountKind }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { run, modal } = useStepUp();
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [link, setLink] = useState<Activation | null>(null);
  const [done, setDone] = useState<Action | null>(null);
  const last = isLastSuperadmin(account, all);
  const id = account.id;
  const act = useMutation({
    mutationFn: (action: Action) =>
      run(async (): Promise<Activation | null> => {
        if (action === 'block' || action === 'unblock') {
          await call(() =>
            api.PATCH('/system/admins/{id}', {
              params: { path: { id } },
              body: { status: action === 'block' ? 'blocked' : 'active' },
            }),
          );
          return null;
        }
        if (action === 'demote') {
          await call(() => api.DELETE('/system/admins/{id}', { params: { path: { id } } }));
          return null;
        }
        if (action === 'resetPassword')
          return call(() => api.POST('/system/users/{id}/reset-password', { params: { path: { id } } }));
        await call(() => api.POST('/system/users/{id}/reset-totp', { params: { path: { id } } }));
        return null;
      }),
    onSuccess: (res, action) => {
      void qc.invalidateQueries({ queryKey: adminsKey });
      setLink(res);
      setDone(action);
    },
  });
  const error = act.error instanceof StepUpCancelled ? null : act.error;
  return (
    <Stack gap="sm">
      <h3>{account.full_name}</h3>
      <dl className="sys-dl">
        <dt>{t('system.accounts.login')}</dt>
        <dd className="mono">{account.login}</dd>
        <dt>Email</dt>
        <dd>{account.email ?? '—'}</dd>
        <dt>{t('system.accounts.role')}</dt>
        <dd>{account.roles.map((r) => t(`system.accounts.roles.${r}`)).join(', ')}</dd>
        <dt>{t('system.accounts.status')}</dt>
        <dd>{t(`system.accounts.st.${account.status}`)}</dd>
        <dt>TOTP</dt>
        <dd>{account.totp_enabled ? t('system.accounts.totpOn') : t('system.accounts.noTotp')}</dd>
      </dl>
      <div className="sys-actions">
        {account.status === 'blocked' ? (
          <Button variant="default" onClick={() => setConfirm('unblock')}>
            {t('system.accounts.unblock')}
          </Button>
        ) : (
          <Button variant="default" color="red" disabled={last} onClick={() => setConfirm('block')}>
            {t('system.accounts.block')}
          </Button>
        )}
        <Button variant="default" disabled={last} onClick={() => setConfirm('demote')}>
          {t('system.accounts.demote')}
        </Button>
        <Button variant="default" onClick={() => setConfirm('resetPassword')}>
          {t('system.accounts.resetPassword')}
        </Button>
        <Button variant="default" onClick={() => setConfirm('resetTotp')}>
          {t('system.accounts.resetTotp')}
        </Button>
      </div>
      {last ? <p className="auth-hint">{t('system.accounts.lastHint')}</p> : null}
      {done ? (
        <p className="auth-ok" role="status">
          ✓ {t(`system.accounts.done.${done}`)}
        </p>
      ) : null}
      {link ? <ActivationNote link={link} /> : null}
      <ErrorText error={error} />
      <ConfirmDialog
        opened={confirm !== null}
        title={confirm ? t(`system.accounts.confirm.${confirm}`, { name: account.full_name }) : ''}
        message={confirm ? t(`system.accounts.confirmText.${confirm}`, { kind: t(`system.menu.${kind}`) }) : ''}
        confirmLabel={confirm ? t(`system.accounts.${confirm}`) : ''}
        danger={confirm === 'block' || confirm === 'demote'}
        busy={act.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          const a = confirm;
          setConfirm(null);
          setDone(null);
          setLink(null);
          if (a) act.mutate(a);
        }}
      />
      {modal}
    </Stack>
  );
}

/** Ссылка активации: на экране — только если письмо не ушло (FR-AUTH-LOC-01). */
function ActivationNote({ link }: { link: Activation }) {
  const { t } = useTranslation();
  return link.emailed || !link.activation_url ? (
    <p className="auth-hint">{t('system.accounts.emailed', { until: formatDateTime(link.expires_at) })}</p>
  ) : (
    <div className="auth-result">
      <span>{t('system.accounts.linkHint', { until: formatDateTime(link.expires_at) })}</span>
      <code className="mono sys-link">{link.activation_url}</code>
    </div>
  );
}
