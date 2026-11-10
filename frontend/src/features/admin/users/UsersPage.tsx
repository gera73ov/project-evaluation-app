/**
 * FE-070 · «Пользователи» админки администратора (SPEC 7.5, 11 «по аналогии»): список с поиском и
 * фильтрами слева, карточка справа. Создание: в режиме «Приложение» — логин, ФИО, email; в режиме
 * AD — «Найти в AD» (FR-AUTH-AD-10). Карточка: роли, блокировка, сбросы (step-up), «Заменить
 * участника» (FR-ADM-05).
 */
import { Button, Select, TextInput } from '@mantine/core';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useSession } from '../../../app/session';
import { api } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDateTime } from '../../../shared/format/date';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { ListWithForm } from '../../system/layout/SystemLayout';
import { AdminLayout } from '../layout/AdminLayout';
import { CreateUser } from './CreateUser';
import { UserCard } from './UserCard';
import { GRANTABLE, usersKey, type User } from './users';

const STATUSES = ['active', 'blocked', 'pending_password'] as const;

export function UsersPage() {
  const { t } = useTranslation();
  const { session } = useSession();
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | 'new' | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  const users = useInfiniteQuery({
    queryKey: [...usersKey, { q, status, role }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/admin/users', {
          params: {
            query: {
              limit: 50,
              ...(q ? { q } : {}),
              ...(status ? { status: status as User['status'] } : {}),
              ...(role ? { role: role as 'moderator' } : {}),
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
  if (session.state !== 'ready') return null;
  const me = session.me;
  const items = users.data?.pages.flatMap((p) => p.items) ?? [];
  const current = items.find((u) => u.id === selected) ?? null;
  const adMode = me.auth_mode === 'ad';

  return (
    <AdminLayout active="users" title={t('admin.menu.users')} subtitle={t(`admin.users.subtitle.${me.auth_mode}`)}>
      <ErrorText error={users.error} />
      <ListWithForm
        list={
          <section className="sec">
            <div className="sys-list-head adm-filters">
              <TextInput
                className="adm-search"
                aria-label={t('admin.users.search')}
                placeholder={t('admin.users.search')}
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
              />
              <Select
                aria-label={t('admin.users.status')}
                placeholder={t('admin.users.anyStatus')}
                clearable
                value={status}
                data={STATUSES.map((s) => ({ value: s, label: t(`admin.users.st.${s}`) }))}
                onChange={setStatus}
              />
              <Select
                aria-label={t('admin.users.role')}
                placeholder={t('admin.users.anyRole')}
                clearable
                value={role}
                data={['admin', ...GRANTABLE].map((r) => ({ value: r, label: t(`roles.${r}`) }))}
                onChange={setRole}
              />
              <span className="sp" />
              <Button size="xs" onClick={() => setSelected('new')}>
                + {t('admin.users.add')}
              </Button>
            </div>
            {users.data && items.length === 0 ? <p className="sys-empty">{t('admin.users.empty')}</p> : null}
            {items.length > 0 ? (
              <table className="t sys-table">
                <thead>
                  <tr>
                    <th>{t('admin.users.name')}</th>
                    <th>{t('admin.users.roles')}</th>
                    <th>{t('admin.users.status')}</th>
                    <th>{t('admin.users.lastLogin')}</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((u) => (
                    <tr key={u.id} className={u.id === selected ? 'on' : undefined}>
                      <td>
                        <button type="button" className="link-btn" onClick={() => setSelected(u.id)}>
                          {u.full_name}
                        </button>
                        <div className="sub mono">{u.login}</div>
                      </td>
                      <td>{u.system_roles.map((r) => t(`roles.${r.role}`)).join(', ') || '—'}</td>
                      <td>
                        <StatusPill user={u} />
                        {u.totp_enabled ? null : <span className="sub"> · {t('admin.users.noTotp')}</span>}
                      </td>
                      <td className="sub">{u.last_login_at ? formatDateTime(u.last_login_at) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {users.hasNextPage ? (
              <Button
                mt="sm"
                variant="default"
                loading={users.isFetchingNextPage}
                onClick={() => void users.fetchNextPage()}
              >
                {t('admin.users.more')}
              </Button>
            ) : null}
          </section>
        }
        form={
          selected === 'new' ? (
            <CreateUser
              key="new"
              adMode={adMode}
              onCreated={(id) => setSelected(id)}
              onCancel={() => setSelected(null)}
            />
          ) : current ? (
            <UserCard key={current.id} user={current} isSelf={current.id === me.id} />
          ) : null
        }
      />
    </AdminLayout>
  );
}

export function StatusPill({ user }: { user: User }) {
  const { t } = useTranslation();
  const tone = user.status === 'active' ? 'ok' : user.status === 'blocked' ? 'bad' : 'warn';
  return <span className={`pill ${tone}`}>{t(`admin.users.st.${user.status}`)}</span>;
}
