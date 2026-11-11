/**
 * FE-027 · что делают пункты меню строки: запуск операций, подтверждения и диалоги.
 *
 * Хук живёт в таблице дерева: после создания узла таблица раскрывает предков, прокручивает к
 * новой строке и ставит курсор в название (`onCreated`).
 */
import { CloseButton } from '@mantine/core';
import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { formatHoursInput } from '../../../shared/format/number';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { branchKey, type BranchStatus } from '../../../shared/calc';
import type { TreeStore } from '../store/treeStore';
import { CollapseDialog, CopyBranchDialog, LocalTypeDialog, MoveDialog, ProfileDialog, TypeDialog } from './dialogs';
import { childrenOf, dropAfter, isLeaf, moveTargets, needsDeleteConfirm, reorderAfter, suggestType } from './ops';
import type { MenuConfig, NodeAction, RowMenuApi } from './RowMenus';
import type { TreeOps } from './useTreeOps';

export interface MenuSetup {
  projectId: string;
  ops: TreeOps;
  config: MenuConfig;
  /** Модератор: перенос по всему проекту (`tree.move.cross_branch`). */
  crossBranch: boolean;
  /** Профили дисциплины для «Профиль ветки ▸» и текущий профиль ветки. */
  profilesOf: (disciplineId: string) => { id: string; name: string; chain: string }[];
  profileOf: (disciplineId: string) => string | null;
  /** История листа (FE-028); нет — пункт бледный. */
  onHistory?: (nodeId: string) => void;
  /** Правка структуры «готовой» ветки в «Сведении» спрашивает подтверждение (FE-029, GAP-10). */
  guard?: (nodeId: string) => boolean | Promise<boolean>;
  /** «Ветка не нужна» / «снова нужна» (FE-029, модератор). */
  setBranchStatus?: (branchNodeId: string, status: BranchStatus) => void;
  canNotNeeded?: boolean;
}

/** Действия, которые меняют структуру или цифры ветки (BR-BR-02). */
const STRUCTURE: ReadonlySet<NodeAction> = new Set(['split', 'collapse', 'up', 'down', 'duplicate', 'delete', 'copy']);

type Dialog =
  | { kind: 'type' | 'local' | 'profile' | 'move' | 'copy' | 'split' | 'delete'; nodeId: string }
  | { kind: 'collapse'; nodeId: string; values: { o: string; r: string; p: string } };

export function useRowMenus({
  setup,
  store,
  canEdit,
  onCreated,
  onShow,
}: {
  setup: MenuSetup | undefined;
  store: TreeStore;
  canEdit: (disciplineId: string | null) => boolean;
  /** Новый узел: показать строку и поставить курсор в название. */
  onCreated: (nodeId: string) => void;
  /** Показать строку (после дублирования и переноса). */
  onShow: (nodeId: string) => void;
}): { api: RowMenuApi | undefined; dialogs: ReactNode } {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const dragging = useRef<string | null>(null);
  if (!setup) return { api: undefined, dialogs: null };
  const { ops, config } = setup;
  const tree = () => store.getState();
  const close = () => setDialog(null);

  /** Правка структуры вернёт «готовую» ветку в черновик: в «Сведении» сначала спросить. */
  const allowed = async (nodeId: string) => (setup.guard ? await setup.guard(nodeId) : true);

  const add = async (nodeId: string, where: 'sibling' | 'child', typeId: string | null) => {
    const node = tree().nodes.get(nodeId);
    if (!node || !(await allowed(nodeId))) return;
    const parent = where === 'sibling' ? node.parent_id : nodeId;
    if (!parent) return;
    const after = where === 'sibling' ? nodeId : (childrenOf(tree(), nodeId).at(-1) ?? null);
    const type = typeId ?? suggestType(tree(), parent, config.chainOf(node.discipline_id));
    const id = await ops.create(parent, after, type, t('menu.newTitle'));
    if (id) onCreated(id);
  };

  const drop = async (nodeId: string, targetId: string, below: boolean) => {
    const node = tree().nodes.get(nodeId);
    const to = dropAfter(tree(), nodeId, targetId, below);
    if (!node?.parent_id || !to || !(await allowed(nodeId))) return;
    if (await ops.move(nodeId, node.parent_id, to.afterId)) onShow(nodeId);
  };

  const act = async (nodeId: string, action: NodeAction) => {
    const node = tree().nodes.get(nodeId);
    if (!node) return;
    if (STRUCTURE.has(action) && !(await allowed(nodeId))) return;
    switch (action) {
      case 'notNeeded':
      case 'needed':
        setup.setBranchStatus?.(nodeId, action === 'notNeeded' ? 'not_needed' : 'not_started');
        return;
      case 'up':
      case 'down': {
        const to = reorderAfter(tree(), nodeId, action === 'up' ? -1 : 1);
        if (to && node.parent_id && (await ops.move(nodeId, node.parent_id, to.afterId))) onShow(nodeId);
        return;
      }
      case 'duplicate': {
        const id = await ops.duplicate(nodeId);
        if (id) onShow(id);
        return;
      }
      case 'collapse': {
        const values = await ops.collapseSuggestion(nodeId);
        if (values) setDialog({ kind: 'collapse', nodeId, values });
        return;
      }
      case 'delete':
        if (needsDeleteConfirm(tree(), nodeId)) setDialog({ kind: 'delete', nodeId });
        else await ops.remove(nodeId);
        return;
      case 'history':
        setup.onHistory?.(nodeId);
        return;
      default:
        setDialog({ kind: action as Exclude<Dialog['kind'], 'collapse'>, nodeId });
    }
  };

  const api: RowMenuApi = {
    config,
    tree,
    add: (nodeId, where, typeId) => void add(nodeId, where, typeId),
    localType: (nodeId) => setDialog({ kind: 'local', nodeId }),
    act: (nodeId, action) => void act(nodeId, action),
    context,
    setContext,
    history: Boolean(setup.onHistory),
    canNotNeeded: Boolean(setup.canNotNeeded && setup.setBranchStatus),
    drag: {
      start: (nodeId) => {
        dragging.current = nodeId;
      },
      end: () => {
        dragging.current = null;
      },
      canDrop: (targetId) => {
        const id = dragging.current;
        if (!id || id === targetId) return false;
        const a = tree().nodes.get(id);
        const b = tree().nodes.get(targetId);
        return Boolean(a && b && a.kind === 'item' && a.parent_id === b.parent_id);
      },
      drop: (targetId, below) => {
        const id = dragging.current;
        dragging.current = null;
        if (id) void drop(id, targetId, below);
      },
    },
    statusOf: (nodeId) => {
      const node = tree().nodes.get(nodeId);
      return node?.discipline_id ? tree().branchStatus.get(branchKey(node.phase_id, node.discipline_id)) : undefined;
    },
  };

  const node = dialog ? tree().nodes.get(dialog.nodeId) : undefined;
  let dialogs: ReactNode = null;
  if (dialog && node) {
    const id = dialog.nodeId;
    const title = node.title;
    switch (dialog.kind) {
      case 'type':
        dialogs = (
          <TypeDialog
            title={title}
            types={config.types}
            current={node.type_id}
            busy={ops.busy}
            onPick={(typeId) => void ops.changeType(id, typeId).then((ok) => ok && close())}
            onClose={close}
          />
        );
        break;
      case 'local':
        dialogs = (
          <LocalTypeDialog
            busy={ops.busy}
            onClose={close}
            onCreate={(name, icon) =>
              void ops.createLocalType(name, icon).then(async (type) => {
                if (!type) return;
                close();
                // новый тип сразу работает: лист этого типа рядом (у ветки — внутри)
                await add(id, node.kind === 'discipline' ? 'child' : 'sibling', type.id);
              })
            }
          />
        );
        break;
      case 'profile':
        dialogs = node.discipline_id ? (
          <ProfileDialog
            branch={title}
            profiles={setup.profilesOf(node.discipline_id)}
            current={setup.profileOf(node.discipline_id)}
            busy={ops.busy}
            onPick={(profileId) => void ops.setProfile(node.discipline_id ?? '', profileId).then((ok) => ok && close())}
            onClose={close}
          />
        ) : null;
        break;
      case 'collapse':
        dialogs = (
          <CollapseDialog
            title={title}
            childrenCount={childrenOf(tree(), id).length}
            initial={dialog.values}
            busy={ops.busy}
            onConfirm={(values) => void ops.collapse(id, values).then((ok) => ok && close())}
            onClose={close}
          />
        );
        break;
      case 'move':
        dialogs = (
          <MoveDialog
            title={title}
            targets={moveTargets(tree(), id, { sameBranch: !setup.crossBranch, canEdit })}
            busy={ops.busy}
            onPick={(parentId) => {
              const last = childrenOf(tree(), parentId).at(-1) ?? null;
              // ветка, куда переносят, тоже может быть «готовой»
              void Promise.resolve(allowed(parentId))
                .then((go) => (go ? ops.move(id, parentId, last) : false))
                .then((ok) => {
                  if (!ok) return;
                  close();
                  onShow(id);
                });
            }}
            onClose={close}
          />
        );
        break;
      case 'copy':
        dialogs = (
          <CopyBranchDialog
            title={title}
            projectId={setup.projectId}
            disciplineId={node.discipline_id}
            busy={ops.busy}
            onPick={(source) => void ops.copyFrom(id, source).then((ok) => ok && close())}
            onClose={close}
          />
        );
        break;
      case 'split': {
        const fork = isLeaf(tree(), id) && node.o !== null;
        dialogs = (
          <ConfirmDialog
            opened
            title={t('menu.splitTitle', { name: title })}
            message={
              fork
                ? t('menu.splitMessage', {
                    name: title,
                    fork: `${formatHoursInput(node.o)}–${formatHoursInput(node.r)}–${formatHoursInput(node.p)}`,
                  })
                : t('menu.splitMessageEmpty', { name: title })
            }
            confirmLabel={t('menu.splitConfirm')}
            busy={ops.busy}
            onConfirm={() =>
              void ops.split(id).then((child) => {
                close();
                if (child) onCreated(child);
              })
            }
            onCancel={close}
          />
        );
        break;
      }
      case 'delete': {
        const count = childrenOf(tree(), id).length;
        dialogs = (
          <ConfirmDialog
            opened
            danger
            title={t('menu.deleteTitle', { name: title })}
            message={count ? t('menu.deleteChildren', { count }) : t('menu.deleteDiscussion')}
            confirmLabel={t('menu.delete')}
            busy={ops.busy}
            onConfirm={() => void ops.remove(id).then(close)}
            onCancel={close}
          />
        );
        break;
      }
    }
  }
  const error = ops.error ? (
    <div className="ops-error" role="alert">
      <span>{ops.error}</span>
      <CloseButton size="sm" aria-label={t('common.close')} onClick={ops.clearError} />
    </div>
  ) : null;
  return {
    api,
    dialogs: (
      <>
        {error}
        {dialogs}
      </>
    ),
  };
}
