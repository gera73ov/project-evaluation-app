/** FE-006 · 10 резервных кодов сеткой 2 × 5 и «Скачать» текстовым файлом (FR-2FA-04, DESIGN.md 10.1). */
import { Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { saveBlob } from '../../shared/api/saveBlob';

export function backupCodesText(codes: readonly string[], title: string): string {
  return [title, '', ...codes, ''].join('\n');
}

export function BackupCodes({ codes }: { codes: readonly string[] }) {
  const { t } = useTranslation();
  function download() {
    const blob = new Blob([backupCodesText(codes, t('totp.backupFileTitle'))], { type: 'text/plain;charset=utf-8' });
    saveBlob(blob, 'backup-codes.txt');
  }
  return (
    <div>
      <p>{t('totp.backupHint')}</p>
      <div className="codes" aria-label={t('totp.backupTitle')}>
        {codes.map((code) => (
          <span key={code}>{code}</span>
        ))}
      </div>
      <Button variant="default" onClick={download}>
        ⇩ {t('common.download')}
      </Button>
    </div>
  );
}
