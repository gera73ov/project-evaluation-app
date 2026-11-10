/**
 * FE-070 · новый пользователь. Режим «Приложение»: логин, ФИО, email и роли — ссылка активации
 * уходит письмом (на экране — только если письмо не ушло, FR-AUTH-LOC-01). Режим AD: «Найти в AD»
 * от 3 символов, до 50 записей; учётку вне группы доступа завести нельзя, уже заведённую — открыть.
 */
import { Button, Checkbox, Stack, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { isEmail } from '../../system/settings/settings';
import { ActivationLinkNote } from './UserCard';
import { AD_MIN_QUERY, GRANTABLE, LOGIN_RE, usersKey, type GrantableRole } from './users';

type AdItem = components['schemas']['AdSearchItem'];
type Activation = components['schemas']['ActivationLink'];

export function CreateUser({
  adMode,
  onCreated,
  onCancel,
}: {
  adMode: boolean;
  onCreated: (id: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [login, setLogin] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [roles, setRoles] = useState<GrantableRole[]>([]);
  const [picked, setPicked] = useState<AdItem | null>(null);
  const [done, setDone] = useState<{ id: string; activation: Activation | null } | null>(null);

  const errors = {
    login: !LOGIN_RE.test(login.trim()),
    name: !name.trim(),
    email: email.trim() !== '' && !isEmail(email.trim()),
  };
  const valid = adMode ? picked !== null : !errors.login && !errors.name && !errors.email;

  const create = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/admin/users', {
          body: picked
            ? { login: picked.login, full_name: picked.full_name, roles, ad_object_guid: picked.object_guid }
            : {
                login: login.trim(),
                full_name: name.trim(),
                roles,
                ...(email.trim() ? { email: email.trim() } : {}),
              },
        }),
      ),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: usersKey });
      setDone({ id: res.user.id, activation: res.activation });
    },
  });

  if (done)
    return (
      <Stack gap="sm">
        <h3>{t('admin.users.created')}</h3>
        {done.activation ? <ActivationLinkNote link={done.activation} /> : <p>{t('admin.users.createdAd')}</p>}
        <div className="sys-actions">
          <Button onClick={() => onCreated(done.id)}>{t('admin.users.openCard')}</Button>
          <Button variant="default" onClick={onCancel}>
            {t('common.close')}
          </Button>
        </div>
      </Stack>
    );

  const roleBoxes = (
    <Checkbox.Group label={t('admin.users.roles')} value={roles} onChange={(v) => setRoles(v as GrantableRole[])}>
      <Stack gap={6} mt={4}>
        {GRANTABLE.map((r) => (
          <Checkbox key={r} value={r} label={t(`roles.${r}`)} />
        ))}
      </Stack>
    </Checkbox.Group>
  );

  return (
    <Stack gap="sm">
      <h3>{t('admin.users.new')}</h3>
      {adMode ? (
        picked ? (
          <div className="adm-picked">
            <b>{picked.full_name}</b>
            <div className="sub mono">
              {picked.login}
              {picked.email ? ` · ${picked.email}` : ''}
            </div>
            <button type="button" className="btn-link" onClick={() => setPicked(null)}>
              {t('admin.users.ad.other')}
            </button>
          </div>
        ) : (
          <AdSearch onPick={setPicked} onOpen={onCreated} />
        )
      ) : (
        <>
          <TextInput
            label={t('admin.users.login')}
            required
            value={login}
            maxLength={64}
            error={login && errors.login ? t('admin.users.loginError') : null}
            onChange={(e) => setLogin(e.currentTarget.value)}
          />
          <TextInput
            label={t('admin.users.fullName')}
            required
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.currentTarget.value)}
          />
          <TextInput
            label="Email"
            description={t('admin.users.emailHint')}
            value={email}
            maxLength={254}
            error={errors.email ? t('system.settings.emailError') : null}
            onChange={(e) => setEmail(e.currentTarget.value)}
          />
        </>
      )}
      {!adMode || picked ? roleBoxes : null}
      <ErrorText error={create.error} />
      <div className="sys-actions">
        <Button disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>
          {t('admin.users.create')}
        </Button>
        <Button variant="default" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
      </div>
    </Stack>
  );
}

/**
 * «Найти в AD»: ФИО или логин от 3 символов; до 50 записей (FR-AUTH-AD-10). `system` — поиск
 * раздела «Система» (CR-011, у суперадминистратора нет права ad.search); там уже заведённого
 * пользователя открыть негде — только отметка.
 */
export function AdSearch({
  onPick,
  onOpen,
  system = false,
}: {
  onPick: (item: AdItem) => void;
  onOpen?: (id: string) => void;
  system?: boolean;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [q, setQ] = useState('');
  useEffect(() => {
    const id = setTimeout(() => setQ(text.trim()), 300);
    return () => clearTimeout(id);
  }, [text]);
  const search = useQuery({
    queryKey: [system ? 'system' : 'admin', 'ad-search', q],
    enabled: q.length >= AD_MIN_QUERY,
    queryFn: () =>
      call(() => api.GET(system ? '/system/auth/ad/search' : '/admin/ad/search', { params: { query: { q } } })),
    retry: false,
  });
  const items = search.data?.items ?? [];
  return (
    <Stack gap="xs">
      <TextInput
        label={t('admin.users.ad.search')}
        description={t('admin.users.ad.searchHint')}
        value={text}
        maxLength={100}
        onChange={(e) => setText(e.currentTarget.value)}
      />
      <ErrorText error={search.error} />
      {q.length >= AD_MIN_QUERY && search.data && items.length === 0 ? (
        <p className="sys-empty">{t('admin.users.ad.none')}</p>
      ) : null}
      {items.length > 0 ? (
        <ul className="adm-ad-list" aria-label={t('admin.users.ad.results')}>
          {items.map((i) => (
            <li key={i.object_guid}>
              <div>
                <b>{i.full_name}</b>
                <div className="sub">
                  <span className="mono">{i.login}</span>
                  {i.department ? ` · ${i.department}` : ''}
                </div>
              </div>
              {i.user_id && onOpen ? (
                <button type="button" className="btn-link" onClick={() => onOpen(i.user_id ?? '')}>
                  {t('admin.users.ad.exists')}
                </button>
              ) : i.user_id ? (
                <span className="pill">{t('admin.users.ad.existsHere')}</span>
              ) : i.in_access_group ? (
                <Button size="xs" variant="default" onClick={() => onPick(i)}>
                  {t('admin.users.ad.pick')}
                </Button>
              ) : (
                <span className="pill warn">{t('admin.users.ad.notInGroup')}</span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </Stack>
  );
}
