/**
 * FE-027 · кнопки «+» и «⋯» у строки дерева (11.5 №1, №2, №4; FR-TREE-23; DESIGN.md 9.9).
 *
 * «+» (300 px): «Лист рядом», «Дочерний узел» (у листа — «разбить» с подтверждением), сетка типов
 * нового узла с меткой «профиль», «+ Свой тип в проекте…». «⋯» (220 px, или правая кнопка мыши):
 * у ветки дисциплины — «Профиль ветки ▸», у остальных строк — операции с узлом. Недоступные
 * пункты бледные с причиной.
 */
import { Menu } from '@mantine/core';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { nodeTypeSymbol } from '../../../shared/ui/icons/nodeTypes';
import type { BranchStatus } from '../../../shared/calc';
import type { TreeState } from '../store/treeStore';
import type { MenuType } from './dialogs';
import { MAX_DEPTH, depthOf, isLeaf, reorderAfter, suggestType } from './ops';

export interface MenuConfig {
  /** Активные типы словаря и локальные типы проекта. */
  types: readonly MenuType[];
  /** Цепочка типов профиля ветки дисциплины (FR-TREE-04). */
  chainOf: (disciplineId: string | null) => readonly string[];
  can: {
    localType: boolean;
    profile: boolean;
    copyFrom: boolean;
  };
}

export type NodeAction =
  | 'type'
  | 'split'
  | 'collapse'
  | 'move'
  | 'up'
  | 'down'
  | 'duplicate'
  | 'history'
  | 'copy'
  | 'delete'
  | 'profile'
  | 'notNeeded'
  | 'needed';

export interface RowMenuApi {
  config: MenuConfig;
  tree: () => Pick<TreeState, 'nodes' | 'children'>;
  /** Новый узел рядом или ребёнком; `typeId` null — тип по профилю. */
  add: (nodeId: string, where: 'sibling' | 'child', typeId: string | null) => void;
  localType: (nodeId: string) => void;
  act: (nodeId: string, action: NodeAction) => void;
  /** Строка, у которой меню открыто правой кнопкой мыши. */
  context: string | null;
  setContext: (nodeId: string | null) => void;
  /** История листа подключена (FE-028). */
  history: boolean;
  /** Модератор: «Ветка не нужна» / «Ветка снова нужна» (FE-029). */
  canNotNeeded: boolean;
  statusOf: (nodeId: string) => BranchStatus | undefined;
}

function Reason({ children }: { children: ReactNode }) {
  return <span className="menu-why">{children}</span>;
}

export function AddMenu({ nodeId, api }: { nodeId: string; api: RowMenuApi }) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const tree = api.tree();
  const node = tree.nodes.get(nodeId);
  if (!node) return null;
  const branch = node.kind === 'discipline';
  const leaf = isLeaf(tree, nodeId);
  const splits = leaf && (!branch || node.o !== null);
  const tooDeep = depthOf(tree, nodeId) >= MAX_DEPTH;
  const chain = api.config.chainOf(node.discipline_id);
  const profileType = suggestType(tree, branch ? nodeId : (node.parent_id ?? nodeId), chain);
  const shown = picked ?? profileType;
  return (
    <Menu
      opened={open}
      onChange={(next) => {
        setOpen(next);
        if (!next) setPicked(null);
      }}
      width={300}
      position="bottom-start"
      shadow="md"
      withinPortal
    >
      <Menu.Target>
        <button
          type="button"
          className={open ? 'row-btn add open' : 'row-btn add'}
          aria-label={t('menu.addFor', { name: node.title })}
        >
          +
        </button>
      </Menu.Target>
      <Menu.Dropdown className="row-menu add-menu">
        <Menu.Label>{t('menu.add')}</Menu.Label>
        <Menu.Item
          disabled={branch}
          rightSection={
            <Reason>{branch ? t('menu.siblingBranch') : t('menu.siblingUnder', { name: node.title })}</Reason>
          }
          onClick={() => api.add(nodeId, 'sibling', picked)}
        >
          {t('menu.sibling')}
        </Menu.Item>
        <Menu.Item
          disabled={tooDeep}
          rightSection={
            tooDeep ? (
              <Reason>{t('menu.depth', { max: MAX_DEPTH })}</Reason>
            ) : splits ? (
              <Reason>{t('menu.childSplits')}</Reason>
            ) : null
          }
          onClick={() => (splits ? api.act(nodeId, 'split') : api.add(nodeId, 'child', picked))}
        >
          {t('menu.child')}
        </Menu.Item>
        <Menu.Label>{t('menu.newType')}</Menu.Label>
        <div className="type-grid" role="group" aria-label={t('menu.types')}>
          {api.config.types.map((type) => (
            <Menu.Item
              key={type.id}
              closeMenuOnClick={false}
              className={type.id === shown ? 'type-opt sel' : 'type-opt'}
              aria-pressed={type.id === shown}
              onClick={() => setPicked(type.id)}
            >
              <span className="ti" aria-hidden="true">
                {nodeTypeSymbol(type.icon)}
              </span>
              {type.name}
              {type.id === profileType ? <span className="type-note">{t('menu.byProfile')}</span> : null}
            </Menu.Item>
          ))}
        </div>
        {api.config.can.localType ? (
          <Menu.Item
            className="local-type"
            rightSection={<Reason>{t('menu.localHint')}</Reason>}
            onClick={() => api.localType(nodeId)}
          >
            {t('menu.localType')}
          </Menu.Item>
        ) : null}
      </Menu.Dropdown>
    </Menu>
  );
}

export function NodeMenu({ nodeId, api }: { nodeId: string; api: RowMenuApi }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const tree = api.tree();
  const node = tree.nodes.get(nodeId);
  if (!node) return null;
  const opened = open || api.context === nodeId;
  const onChange = (next: boolean) => {
    setOpen(next);
    if (!next && api.context === nodeId) api.setContext(null);
  };
  const branch = node.kind === 'discipline';
  const leaf = isLeaf(tree, nodeId);
  const item = (action: NodeAction, label: string, why: string | null = null, className?: string) => (
    <Menu.Item
      key={action}
      disabled={why !== null}
      {...(className ? { className } : {})}
      rightSection={why ? <Reason>{why}</Reason> : null}
      onClick={() => api.act(nodeId, action)}
    >
      {label}
    </Menu.Item>
  );
  const history = api.history ? null : t('menu.soon');
  const copy = api.config.can.copyFrom ? null : t('menu.noRight');
  let items: ReactNode;
  if (branch) {
    items = (
      <>
        {item('profile', t('menu.profile'), api.config.can.profile ? null : t('menu.noRight'))}
        <Menu.Divider />
        {item('copy', t('menu.copy'), copy)}
        {api.canNotNeeded ? (
          <>
            <Menu.Divider />
            {api.statusOf(nodeId) === 'not_needed'
              ? item('needed', t('menu.needed'))
              : item(
                  'notNeeded',
                  t('menu.notNeeded'),
                  !leaf ? t('menu.notEmpty') : api.statusOf(nodeId) === 'done' ? t('menu.branchDone') : null,
                )}
          </>
        ) : null}
      </>
    );
  } else {
    const deep = depthOf(tree, nodeId) >= MAX_DEPTH;
    const up = reorderAfter(tree, nodeId, -1);
    const down = reorderAfter(tree, nodeId, 1);
    items = (
      <>
        {item('type', t('menu.changeType'))}
        {item(
          'split',
          t('menu.split'),
          !leaf ? t('menu.hasChildren') : deep ? t('menu.depth', { max: MAX_DEPTH }) : null,
        )}
        {item('collapse', t('menu.collapse'), leaf ? t('menu.noChildren') : null)}
        {item('move', t('menu.move'))}
        <div className="menu-pair">
          {item('up', t('menu.up'), up ? null : t('menu.first'))}
          {item('down', t('menu.down'), down ? null : t('menu.last'))}
        </div>
        {item('duplicate', t('menu.duplicate'))}
        {item('profile', t('menu.profile'), t('menu.profileBranchOnly'))}
        <Menu.Divider />
        {item('history', t('menu.history'), leaf ? history : t('menu.leafOnly'))}
        {item('copy', t('menu.copy'), copy)}
        <Menu.Divider />
        {item('delete', t('menu.delete'), null, 'danger')}
      </>
    );
  }
  return (
    <Menu opened={opened} onChange={onChange} width={220} position="bottom-start" shadow="md" withinPortal>
      <Menu.Target>
        <button
          type="button"
          className={opened ? 'row-btn more open' : 'row-btn more'}
          aria-label={t('menu.moreFor', { name: node.title })}
        >
          ⋯
        </button>
      </Menu.Target>
      <Menu.Dropdown className="row-menu node-menu">{items}</Menu.Dropdown>
    </Menu>
  );
}
