/**
 * FE-070 · карточка пользователя: данные учётки, роли (свои роли и роли из групп AD менять нельзя),
 * блокировка с причиной, сброс пароля и TOTP со step-up (ссылка на экране — только если письмо не
 * ушло), «Заменить участника…».
 */
import { Button, Checkbox, Group, Modal, Stack, Textarea } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDateTime } from '../../../shared/format/date';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { StepUpCancelled, useStepUp } from '../../system/layout/useStepUp';
import { ReplaceWizard } from './ReplaceWizard';
import { GRANTABLE, manualRoles, mappedByGroups, roleLocked, usersKey, type GrantableRole, type User } from './users';

type Activation = components['schemas']['ActivationLink'];
type Action = 'resetPassword' | 'resetTotp' | 'unblock';

export function UserCard({ user, isSelf }: { user: User; isSelf: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { run, modal } = useStepUp();
  const [roles, setRoles] = useState<GrantableRole[]>(manualRoles(user));
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [blocking, setBlocking] = useState(false);
  const [reason, setReason] = useState('');
  const [replacing, setReplacing] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [link, setLink] = useState<Activation | null>(null);
  const id = user.id;
  const refresh = () => void qc.invalidateQueries({ queryKey: usersKey });
  const changed = JSON.stringify([...roles].sort()) !== JSON.stringify([...manualRoles(user)].sort());

  const saveRoles = useMutation({
    mutationFn: () => call(() => api.PATCH('/admin/users/{id}', { params: { path: { id } }, body: { roles } })),
    onSuccess: () => {
      refresh();
      setDone(t('admin.users.done.roles'));
    },
  });
  const block = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/admin/users/{id}/block', {
          params: { path: { id } },
          body: { reason: reason.trim() || null },
        }),
      ),
    onSuccess: () => {
      setBlocking(false);
      setReason('');
      refresh();
      setDone(t('admin.users.done.block'));
    },
  });
  const act = useMutation({
    mutationFn: (action: Action) =>
      run(async (): Promise<Activation | null> => {
        if (action === 'unblock') {
          await call(() => api.POST('/admin/users/{id}/unblock', { params: { path: { id } } }));
          return null;
        }
        if (action === 'resetPassword')
          return call(() => api.POST('/admin/users/{id}/reset-password', { params: { path: { id } } }));
        await call(() => api.POST('/admin/users/{id}/reset-totp', { params: { path: { id } } }));
        return null;
      }),
    onSuccess: (res, action) => {
      refresh();
      setLink(res);
      setDone(t(`admin.users.done.${action}`));
    },
  });
  const error = act.error instanceof StepUpCancelled ? null : act.error;

  return (
    <Stack gap="sm">
      <h3>{user.full_name}</h3>
      <dl className="sys-dl">
        <dt>{t('admin.users.login')}</dt>
        <dd className="mono">{user.login}</dd>
        <dt>Email</dt>
        <dd>{user.email ?? '—'}</dd>
        <dt>{t('admin.users.source')}</dt>
        <dd>{t(`admin.users.sources.${user.source}`)}</dd>
        <dt>{t('admin.users.status')}</dt>
        <dd>
          {t(`admin.users.st.${user.status}`)}
          {user.block_reason ? ` · ${t(`admin.users.blockReasons.${user.block_reason}`)}` : ''}
        </dd>
        <dt>TOTP</dt>
        <dd>{user.totp_enabled ? t('admin.users.totpOn') : t('admin.users.noTotp')}</dd>
        <dt>{t('admin.users.lastLogin')}</dt>
        <dd>{user.last_login_at ? formatDateTime(user.last_login_at) : '—'}</dd>
      </dl>

      {user.system_roles.some((r) => r.role === 'admin') ? <p className="sub">{t('admin.users.adminRole')}</p> : null}
      <Checkbox.Group label={t('admin.users.roles')} value={roles} onChange={(v) => setRoles(v as GrantableRole[])}>
        <Stack gap={6} mt={4}>
          {GRANTABLE.map((r) => {
            const fromGroup = user.system_roles.some((s) => s.role === r && s.source === 'ad_group');
            return (
              <Checkbox
                key={r}
                value={r}
                disabled={roleLocked(user, r, isSelf)}
                label={fromGroup ? `${t(`roles.${r}`)} · ${t('admin.users.fromGroup')}` : t(`roles.${r}`)}
              />
            );
          })}
        </Stack>
      </Checkbox.Group>
      {isSelf ? <p className="auth-hint">{t('admin.users.selfHint')}</p> : null}
      {mappedByGroups(user) ? <p className="auth-hint">{t('admin.users.groupsHint')}</p> : null}
      {changed ? (
        <div className="sys-actions">
          <Button loading={saveRoles.isPending} onClick={() => saveRoles.mutate()}>
            {t('admin.users.saveRoles')}
          </Button>
          <Button variant="default" onClick={() => setRoles(manualRoles(user))}>
            {t('common.cancel')}
          </Button>
        </div>
      ) : null}
      <ErrorText error={saveRoles.error} />

      <div className="sys-actions">
        {user.status === 'blocked' ? (
          <Button variant="default" onClick={() => setConfirm('unblock')}>
            {t('admin.users.unblock')}
          </Button>
        ) : (
          <Button variant="default" color="red" disabled={isSelf} onClick={() => setBlocking(true)}>
            {t('admin.users.block')}
          </Button>
        )}
        {user.source === 'local' ? (
          <Button variant="default" onClick={() => setConfirm('resetPassword')}>
            {t('admin.users.resetPassword')}
          </Button>
        ) : null}
        <Button variant="default" onClick={() => setConfirm('resetTotp')}>
          {t('admin.users.resetTotp')}
        </Button>
        <Button variant="default" onClick={() => setReplacing(true)}>
          {t('admin.users.replace')}
        </Button>
      </div>
      {done ? (
        <p className="auth-ok" role="status">
          ✓ {done}
        </p>
      ) : null}
      {link ? <ActivationLinkNote link={link} /> : null}
      <ErrorText error={error ?? block.error} />

      <Modal
        opened={blocking}
        onClose={() => setBlocking(false)}
        title={t('admin.users.blockTitle', { name: user.full_name })}
        centered
      >
        <Stack gap="sm">
          <p>{t('admin.users.blockText')}</p>
          <Textarea
            label={t('admin.users.blockReason')}
            value={reason}
            maxLength={500}
            autosize
            minRows={2}
            onChange={(e) => setReason(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setBlocking(false)}>
              {t('common.cancel')}
            </Button>
            <Button color="red" loading={block.isPending} onClick={() => block.mutate()}>
              {t('admin.users.block')}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <ConfirmDialog
        opened={confirm !== null}
        title={confirm ? t(`admin.users.confirm.${confirm}`, { name: user.full_name }) : ''}
        message={confirm ? t(`admin.users.confirmText.${confirm}`) : ''}
        confirmLabel={confirm ? t(`admin.users.${confirm}`) : ''}
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
      <ReplaceWizard user={user} opened={replacing} onClose={() => setReplacing(false)} />
      {modal}
    </Stack>
  );
}

/** Ссылка активации: на экране — только если письмо не ушло (FR-AUTH-LOC-01). */
export function ActivationLinkNote({ link }: { link: Activation }) {
  const { t } = useTranslation();
  return link.emailed || !link.activation_url ? (
    <p className="auth-hint">{t('system.accounts.emailed', { until: formatDateTime(link.expires_at) })}</p>
  ) : (
    <div className="auth-result">
      <span>{t('admin.users.linkHint', { until: formatDateTime(link.expires_at) })}</span>
      <code className="mono sys-link">{link.activation_url}</code>
    </div>
  );
}
