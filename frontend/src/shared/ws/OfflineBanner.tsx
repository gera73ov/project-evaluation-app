/** FE-020 · жёлтая полоса «Нет связи, правки не сохраняются» (FR-TREE-33, DESIGN.md 7). */
import { useTranslation } from 'react-i18next';

import { useWsStatus } from './WsProvider';

export function OfflineBanner() {
  const { t } = useTranslation();
  const status = useWsStatus();
  if (status !== 'offline') return null;
  return (
    <div className="ybar" role="status">
      <span aria-hidden="true">⚠</span> {t('ws.offline')}
    </div>
  );
}
