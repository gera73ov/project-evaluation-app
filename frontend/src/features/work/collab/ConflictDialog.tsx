/**
 * FE-026 · конфликт того же поля (FR-TREE-32, G-14; DESIGN.md 9.7): «Значение изменил П. Петров»,
 * «Его: 16», «Ваше: 18»; «Принять» (Esc) снимает своё значение, «Оставить моё» сохраняет его
 * поверх с текущей версией узла.
 */
import { Button, Group, Modal } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import type { CellConflict } from '../cells/useCells';

const FIELD_LABELS = new Map([
  ['o', 'O'],
  ['r', 'R'],
  ['p', 'P'],
  ['multiplier', '×N'],
]);

export function ConflictDialog({
  conflict,
  title,
  onResolve,
}: {
  conflict: CellConflict;
  /** Название узла. */
  title: string;
  onResolve: (choice: 'mine' | 'theirs') => void;
}) {
  const { t } = useTranslation();
  const by = conflict.items.find((i) => i.changedBy)?.changedBy ?? t('collab.someone');
  const label = (field: string) => FIELD_LABELS.get(field) ?? t('tree.col.comment');
  return (
    <Modal
      opened
      onClose={() => onResolve('theirs')}
      title={t('collab.conflictTitle', { name: by })}
      size={440}
      centered
    >
      <p className="conflict-node">{title}</p>
      {conflict.items.map((item) => (
        <div className="conflict-row" key={item.field}>
          <span className="k">{label(item.field)}</span>
          <span>
            {t('collab.theirs')} <b>{item.current ?? '—'}</b>
          </span>
          <span>
            {t('collab.yours')} <b>{item.yours || '—'}</b>
          </span>
        </div>
      ))}
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={() => onResolve('theirs')}>
          {t('collab.accept')}
        </Button>
        <Button onClick={() => onResolve('mine')}>{t('collab.keepMine')}</Button>
      </Group>
    </Modal>
  );
}
