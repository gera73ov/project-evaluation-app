/**
 * FE-029 · статус ветки и «Проверено» (4.3, BR-BR-01…03, FR-REV-01…04, GAP-10).
 *
 * - «Отметить «Готово»» и «не нужно» — `PUT /projects/{id}/branches/{phase}/{discipline}/status`.
 * - «Проверено» на листе или узле (тогда на всех листьях поддерева) — `POST /nodes/{id}/review`.
 * - В «Сведении» перед первой правкой «готовой» ветки — диалог «Ветка вернётся в черновик.
 *   Продолжить?»; после «Продолжить» правки в этой ветке идут без вопросов (GAP-10).
 */
import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../../shared/api/client';
import { call, errorMessage } from '../../../shared/api/problem';
import { branchKey, type BranchStatus } from '../../../shared/calc';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import type { TreeMutation, TreeStore } from '../store/treeStore';

export interface BranchSetup {
  projectId: string;
  confirmMutation: (mutation: TreeMutation) => void;
  /** Проект в «Сведении»: правка готовой ветки спрашивает подтверждение (GAP-10). */
  consolidation: boolean;
  /** «Отметить «Готово»»: эксперт своей дисциплины или модератор (`branch.status.draft_done`). */
  canDone: (disciplineId: string | null) => boolean;
  /** «не нужно» и возврат (`branch.status.not_needed`, модератор). */
  canNotNeeded: boolean;
  /** «Проверено»: ревьюер дисциплины или модератор (`review.mark`). */
  canReview: (disciplineId: string | null) => boolean;
}

export interface BranchApi {
  setup: BranchSetup;
  busy: string | null;
  setStatus: (branchNodeId: string, status: BranchStatus) => Promise<boolean>;
  review: (nodeId: string, reviewed: boolean) => Promise<boolean>;
  /** Можно ли сразу править узел; обещание — после ответа в диалоге GAP-10. */
  guard: (nodeId: string) => boolean | Promise<boolean>;
  dialogs: ReactNode;
}

export function useBranch(setup: BranchSetup | undefined, store: TreeStore): BranchApi | undefined {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ask, setAsk] = useState<{ name: string; resolve: (ok: boolean) => void } | null>(null);
  /** Готовые ветки, правку которых пользователь уже подтвердил. */
  const confirmed = useRef(new Set<string>());
  if (!setup) return undefined;

  const branchOf = (nodeId: string) => {
    const state = store.getState();
    let node = state.nodes.get(nodeId);
    while (node && node.kind !== 'discipline') node = node.parent_id ? state.nodes.get(node.parent_id) : undefined;
    return node;
  };

  const run = async (key: string, request: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await request();
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(null);
    }
  };

  const guard = (nodeId: string): boolean | Promise<boolean> => {
    if (!setup.consolidation) return true;
    const branch = branchOf(nodeId);
    if (!branch?.discipline_id) return true;
    const key = branchKey(branch.phase_id, branch.discipline_id);
    if (store.getState().branchStatus.get(key) !== 'done' || confirmed.current.has(key)) return true;
    return new Promise<boolean>((resolve) =>
      setAsk({
        name: branch.title,
        resolve: (ok) => {
          if (ok) confirmed.current.add(key);
          setAsk(null);
          resolve(ok);
        },
      }),
    );
  };

  return {
    setup,
    busy,
    guard,
    setStatus: (branchNodeId, status) =>
      run(`status:${branchNodeId}`, async () => {
        const branch = store.getState().nodes.get(branchNodeId);
        if (!branch?.discipline_id) return;
        const change = await call(() =>
          api.PUT('/projects/{id}/branches/{phase}/{discipline}/status', {
            params: {
              path: { id: setup.projectId, phase: branch.phase_id, discipline: branch.discipline_id ?? '' },
            },
            body: { status },
          }),
        );
        const key = branchKey(change.phase_id, change.discipline_id);
        // новая «готовность» — снова спросить перед первой правкой
        if (change.status === 'done') confirmed.current.delete(key);
        store.getState().applyMutation({
          nodes: [],
          project_version: store.getState().version,
          branch_statuses: [change],
        });
      }),
    review: (nodeId, reviewed) =>
      run(`review:${nodeId}`, async () => {
        const result = await call(() =>
          api.POST('/nodes/{id}/review', { params: { path: { id: nodeId } }, body: { reviewed } }),
        );
        setup.confirmMutation(result as unknown as TreeMutation);
      }),
    dialogs: (
      <>
        {error ? (
          <div className="ops-error" role="alert">
            <span>{error}</span>
            <button type="button" className="btn-sm" onClick={() => setError(null)}>
              {t('common.close')}
            </button>
          </div>
        ) : null}
        <ConfirmDialog
          opened={ask !== null}
          title={t('branch.doneEditTitle', { name: ask?.name ?? '' })}
          message={t('branch.doneEditMessage')}
          confirmLabel={t('branch.doneEditConfirm')}
          onConfirm={() => ask?.resolve(true)}
          onCancel={() => ask?.resolve(false)}
        />
      </>
    ),
  };
}
