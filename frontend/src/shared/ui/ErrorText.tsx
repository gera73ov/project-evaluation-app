/** FE-003 · текст ошибки API по коду и `error_id` для 5xx (errors.yaml, api-conventions 5). */
import { useTranslation } from 'react-i18next';

import { errorMessage, showsErrorId, ApiError } from '../api/problem';

export function ErrorText({ error, variant }: { error: unknown; variant?: 'ad' | undefined }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <div className="err" role="alert">
      {errorMessage(error, variant)}
      {showsErrorId(error) ? (
        <div className="err-id">{t('common.error_id', { error_id: (error as ApiError).errorId })}</div>
      ) : null}
    </div>
  );
}
