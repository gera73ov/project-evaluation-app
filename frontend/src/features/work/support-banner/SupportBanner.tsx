/**
 * FE-073 · жёлтая полоса режима поддержки (FR-ADM-06, DESIGN.md 6.13): «Режим поддержки · только
 * чтение · осталось N мин · причина: …». По истечении 60 минут — «Сессия закончилась» и путь
 * обратно в реестр; правок, денег и заметок в этом режиме нет (права сессии их не дают).
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import { minutesLeft, supportReason } from '../../admin/registry/registry';

export function SupportBanner({ projectId, expiresAt }: { projectId: string; expiresAt: string | null }) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, []);
  const left = expiresAt ? minutesLeft(expiresAt, now) : 0;
  const reason = supportReason(projectId);
  return (
    <div className="ybar support-bar" role="status">
      <span aria-hidden="true">⚠</span>
      <span>
        {t('support.title')} · {t('support.readOnly')} ·{' '}
        {left > 0 ? t('support.left', { count: left }) : t('support.expired')}
        {reason ? ` · ${t('support.reason', { reason })}` : ''}
      </span>
      <span className="sp" />
      <Link to="/admin/registry">{t('support.exit')}</Link>
    </div>
  );
}
