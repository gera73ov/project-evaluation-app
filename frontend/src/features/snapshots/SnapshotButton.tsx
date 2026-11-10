/**
 * FE-045 · «📷 Снимок» в верхней полосе (SPEC 11.4 №17, FR-SNAP-01): только с `snapshot.create`
 * (модератор). Окно с полями «Название» (обязательно, до 100 символов) и «Описание» (до 1 000).
 * После сохранения список снимков перечитывается, внизу — «Снимок «…» сохранён».
 */
import { Button, Group, Modal, TextInput, Textarea } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';
import { snapshotsKey } from './keys';

export const SNAPSHOT_NAME_MAX = 100;
export const SNAPSHOT_DESCRIPTION_MAX = 1000;

export function SnapshotButton({ projectId, perms }: { projectId: string; perms: readonly string[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saved, setSaved] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/projects/{id}/snapshots', {
          params: { path: { id: projectId } },
          body: { name: name.trim(), ...(description.trim() ? { description: description.trim() } : {}) },
        }),
      ),
    onSuccess: (snap) => {
      void qc.invalidateQueries({ queryKey: snapshotsKey(projectId) });
      setSaved(snap.name);
      close();
    },
  });
  useEffect(() => {
    if (!saved) return;
    const id = setTimeout(() => setSaved(null), 4000);
    return () => clearTimeout(id);
  }, [saved]);
  if (!perms.includes('snapshot.create')) return null;
  function close() {
    setOpen(false);
    setName('');
    setDescription('');
    save.reset();
  }
  return (
    <>
      <button type="button" className="btn-link" onClick={() => setOpen(true)}>
        📷 {t('snapshot.button')}
      </button>
      <Modal opened={open} onClose={close} title={t('snapshot.title')} centered>
        <TextInput
          label={t('snapshot.name')}
          placeholder={t('snapshot.namePlaceholder')}
          required
          value={name}
          maxLength={SNAPSHOT_NAME_MAX}
          data-autofocus
          description={`${name.length} / ${SNAPSHOT_NAME_MAX}`}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Textarea
          mt="sm"
          label={t('snapshot.description')}
          value={description}
          maxLength={SNAPSHOT_DESCRIPTION_MAX}
          autosize
          minRows={3}
          description={`${description.length} / ${SNAPSHOT_DESCRIPTION_MAX}`}
          onChange={(e) => setDescription(e.currentTarget.value)}
        />
        <p className="sub">{t('snapshot.hint')}</p>
        <ErrorText error={save.error} />
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={close}>
            {t('common.cancel')}
          </Button>
          <Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>
            {t('snapshot.save')}
          </Button>
        </Group>
      </Modal>
      {saved ? (
        <div className="toast" role="status">
          {t('snapshot.saved', { name: saved })}
        </div>
      ) : null}
    </>
  );
}
