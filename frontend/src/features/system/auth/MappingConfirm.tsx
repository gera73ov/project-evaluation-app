/**
 * FE-061 · отчёт перед включением ролей по группам AD (SPEC 11.2 №4, FR-AUTH-AD-07, CR-009):
 * у каких пользователей AD роли «Модератор» и «Пресейл» снимутся или добавятся, если сохранить
 * сопоставление с этими группами. Отчёт строит сервер без записи; без групп — только последствия.
 */
import { Button, Group, Modal, Stack } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import type { RoleMapping } from './auth';

export function MappingConfirm({
  mapping,
  onConfirm,
  onCancel,
}: {
  /** Сопоставление, которое будет сохранено; null — окно закрыто. */
  mapping: RoleMapping | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const groups = mapping?.mappings ?? [];
  const preview = useQuery({
    queryKey: ['system', 'auth', 'role-mapping-preview', groups],
    enabled: mapping !== null && groups.length > 0,
    staleTime: 0,
    gcTime: 0,
    queryFn: () =>
      call(() =>
        api.POST('/system/auth/role-mapping/preview', {
          body: { values: { 'auth.ad.role_mapping': { enabled: true, mappings: groups } as never } },
        }),
      ),
  });
  const items = preview.data?.items ?? [];
  const role = (r: string) => `«${t(`system.roles.${r}`)}»`;
  const waiting = groups.length > 0 && !preview.data;

  return (
    <Modal opened={mapping !== null} onClose={onCancel} title={t('system.auth.roles.confirmTitle')} size="lg" centered>
      <Stack gap="sm">
        <p>{t('system.auth.roles.confirmText')}</p>
        {groups.length === 0 ? (
          <p className="sys-sub">{t('system.auth.roles.previewNoGroups')}</p>
        ) : preview.data ? (
          items.length === 0 ? (
            <p className="auth-ok" role="status">
              ✓ {t('system.auth.roles.previewNone')}
            </p>
          ) : (
            <table className="t sys-table" aria-label={t('system.auth.roles.previewTitle')}>
              <thead>
                <tr>
                  <th>{t('system.auth.roles.previewUser')}</th>
                  <th>{t('system.auth.roles.previewRemoved')}</th>
                  <th>{t('system.auth.roles.previewAdded')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.user.id}>
                    <td>
                      {i.user.full_name}
                      <div className="sub">{i.login}</div>
                    </td>
                    <td className={i.removed.length ? 'bad-ink' : 'sub'}>{i.removed.map(role).join(', ') || '—'}</td>
                    <td className="sub">{i.added.map(role).join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}
        <ErrorText error={preview.error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button
            loading={waiting && preview.isFetching}
            disabled={waiting || preview.isError}
            onClick={onConfirm}
            data-autofocus
          >
            {t('system.auth.roles.confirmButton')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
