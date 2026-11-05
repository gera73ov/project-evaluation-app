/** FE-004 · подтверждение необратимого действия (DESIGN.md 6.12): заголовок, последствия, две кнопки. */
import { Button, Group, Modal, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function ConfirmDialog({
  opened,
  title,
  message,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  opened: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal opened={opened} onClose={onCancel} title={title} centered>
      <Text mb="md">{message}</Text>
      <Group justify="flex-end">
        <Button variant="default" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button color={danger ? 'red' : 'accent'} loading={busy} onClick={onConfirm} data-autofocus>
          {confirmLabel}
        </Button>
      </Group>
    </Modal>
  );
}
