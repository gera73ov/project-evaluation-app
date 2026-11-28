/** FE-098 · окно «О программе» из меню пользователя (SPEC FR-UI-06, CR-020). */
import { Button, Group, Modal } from '@mantine/core';
import { useTranslation } from 'react-i18next';

/** Версия фронтенда из package.json, её подставляет сборка (vite.config.ts, `define`). */
export const APP_VERSION: string = __APP_VERSION__;

export function AboutDialog({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Modal opened={opened} onClose={onClose} title={t('about.menu')} centered>
      <div className="about">
        <div className="logo">
          <i aria-hidden="true" />
          {t('app.title')}
        </div>
        <dl className="about-list">
          <dt>{t('about.version')}</dt>
          <dd>{APP_VERSION}</dd>
          <dt>{t('about.author')}</dt>
          <dd>{t('about.authorName')}</dd>
          <dt>{t('about.owner')}</dt>
          <dd>{t('about.ownerName')}</dd>
        </dl>
        <p className="about-rights">{t('about.rights')}</p>
      </div>
      <Group justify="flex-end">
        <Button onClick={onClose}>{t('about.close')}</Button>
      </Group>
    </Modal>
  );
}
