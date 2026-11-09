/**
 * FE-045 · выгрузка проекта в Excel «Часы» или «С деньгами» (FR-EXP-01…05): задание
 * `POST /projects/{id}/exports` из текущего состояния или снимка, ожидание и автоскачивание. Если
 * файл готовится дольше 3 секунд — уведомление «Готовим файл…», по готовности — «Файл готов»
 * (DESIGN.md 13: долгий экспорт).
 */
import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../shared/api/client';
import { ExportTimeout, downloadExport } from '../../shared/api/exports';
import { call, errorMessage } from '../../shared/api/problem';

export type ExportKind = 'hours_xlsx' | 'money_xlsx';

/** Через сколько миллисекунд ожидания показывается «Готовим файл…». */
export const SLOW_EXPORT_MS = 3000;
const DONE_VISIBLE_MS = 3000;

type Phase = 'idle' | 'slow' | 'done';

export function useProjectExport(projectId: string) {
  const [phase, setPhase] = useState<Phase>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const slow = useRef(false);
  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => clear, []);
  const mutation = useMutation({
    mutationFn: ({ kind, snapshotId }: { kind: ExportKind; snapshotId: string | null }) => {
      clear();
      slow.current = false;
      setPhase('idle');
      timer.current = setTimeout(() => {
        slow.current = true;
        setPhase('slow');
      }, SLOW_EXPORT_MS);
      return downloadExport(
        () =>
          call(() =>
            api.POST('/projects/{id}/exports', {
              params: { path: { id: projectId } },
              body: { kind, snapshot_id: snapshotId },
            }),
          ),
        { fallbackName: kind === 'money_xlsx' ? 'money.xlsx' : 'hours.xlsx' },
      );
    },
    onSuccess: () => {
      clear();
      if (slow.current) {
        setPhase('done');
        timer.current = setTimeout(() => setPhase('idle'), DONE_VISIBLE_MS);
      } else setPhase('idle');
    },
    onError: () => {
      clear();
      setPhase('idle');
    },
  });
  return { ...mutation, phase };
}

/** Уведомление о долгом экспорте внизу экрана и ошибка выгрузки. */
export function ExportToast({ phase, error }: { phase: Phase; error: unknown }) {
  const { t } = useTranslation();
  if (error)
    return (
      <div className="toast bad" role="alert">
        {error instanceof ExportTimeout ? t('stats.exportTimeout') : errorMessage(error)}
      </div>
    );
  if (phase === 'idle') return null;
  return (
    <div className="toast" role="status">
      {phase === 'slow' ? (
        <>
          <span className="spinner" aria-hidden="true" /> {t('exports.preparing')}
        </>
      ) : (
        t('exports.ready')
      )}
    </div>
  );
}
