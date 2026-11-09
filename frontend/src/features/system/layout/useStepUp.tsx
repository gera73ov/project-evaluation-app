/**
 * FE-060 · step-up на критичных действиях раздела «Система» (SEC-AUTH-05): действие выполняется
 * сразу; если сервер ответил 403 STEP_UP_REQUIRED, открывается окно «пароль + код TOTP», после
 * подтверждения действие повторяется. Подтверждение действует 5 минут — следующие действия в
 * это время проходят без окна (решает сервер).
 */
import { useCallback, useRef, useState } from 'react';

import { ApiError } from '../../../shared/api/problem';
import { StepUpModal } from '../../../shared/ui/StepUpModal';

export function isStepUpRequired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.code === 'STEP_UP_REQUIRED';
}

export function useStepUp() {
  const pending = useRef<{
    action: () => Promise<unknown>;
    resolve: (v: unknown) => void;
    reject: (e: unknown) => void;
  } | null>(null);
  const [open, setOpen] = useState(false);

  /** Выполнить действие; при STEP_UP_REQUIRED — после подтверждения ещё раз. */
  const run = useCallback(<T,>(action: () => Promise<T>): Promise<T> => {
    return action().catch((error: unknown) => {
      if (!isStepUpRequired(error)) throw error;
      return new Promise<T>((resolve, reject) => {
        pending.current = {
          action,
          resolve: (v) => resolve(v as T),
          reject,
        };
        setOpen(true);
      });
    });
  }, []);

  const modal = (
    <StepUpModal
      opened={open}
      onClose={() => {
        setOpen(false);
        pending.current?.reject(new StepUpCancelled());
        pending.current = null;
      }}
      onSuccess={() => {
        setOpen(false);
        const p = pending.current;
        pending.current = null;
        if (p) p.action().then(p.resolve, p.reject);
      }}
    />
  );
  return { run, modal };
}

/** Пользователь закрыл окно подтверждения — ошибку не показываем. */
export class StepUpCancelled extends Error {
  constructor() {
    super('step-up cancelled');
  }
}
