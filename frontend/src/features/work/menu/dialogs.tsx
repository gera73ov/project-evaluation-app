/**
 * FE-027 · диалоги меню строки (11.5; DESIGN.md 9.9, 16.3): смена типа, свой тип в проекте,
 * профиль ветки, «Свернуть в лист», «Переместить в…», «Скопировать ветку из проекта…».
 */
import { Button, Group, Modal, Select, Text, TextInput } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../../shared/api/client";
import { call } from "../../../shared/api/problem";
import { formatHours } from "../../../shared/format/number";
import { HoursInput } from "../../../shared/ui/HoursInput";
import {
  NODE_TYPE_ICON_KEYS,
  type NodeTypeIcon,
  nodeTypeSymbol,
} from "../../../shared/ui/icons/nodeTypes";
import type { MoveTarget } from "./ops";

export interface MenuType {
  id: string;
  name: string;
  icon: string;
  /** Локальный тип проекта (FR-TREE-03). */
  local?: boolean;
}

/** Название локального типа: 1–50 символов (LocalNodeType.name). */
export const LOCAL_TYPE_MAX = 50;

function Actions({
  busy,
  disabled,
  label,
  onConfirm,
  onClose,
}: {
  busy: boolean;
  disabled: boolean;
  label: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Group justify="flex-end" mt="md">
      <Button variant="default" onClick={onClose}>
        {t("common.cancel")}
      </Button>
      <Button
        color="accent"
        loading={busy}
        disabled={disabled}
        onClick={onConfirm}
      >
        {label}
      </Button>
    </Group>
  );
}

/** «Сменить тип…»: сетка типов в 2 колонки, текущий отмечен. */
export function TypeDialog({
  title,
  types,
  current,
  busy,
  onPick,
  onClose,
}: {
  title: string;
  types: readonly MenuType[];
  current: string | null;
  busy: boolean;
  onPick: (typeId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("menu.changeTypeTitle", { name: title })}
      size={360}
      centered
    >
      <div className="type-grid" role="group" aria-label={t("menu.types")}>
        {types.map((type) => (
          <button
            key={type.id}
            type="button"
            className={type.id === current ? "type-opt sel" : "type-opt"}
            aria-pressed={type.id === current}
            disabled={busy}
            onClick={() => onPick(type.id)}
          >
            <span className="ti" aria-hidden="true">
              {nodeTypeSymbol(type.icon)}
            </span>
            {type.name}
            {type.local ? (
              <span className="type-note">{t("menu.local")}</span>
            ) : null}
          </button>
        ))}
      </div>
    </Modal>
  );
}

/** «+ Свой тип в проекте…»: название и иконка сеткой 6 колонок из курируемого набора. */
export function LocalTypeDialog({
  busy,
  onCreate,
  onClose,
}: {
  busy: boolean;
  onCreate: (name: string, icon: NodeTypeIcon) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [icon, setIcon] = useState<NodeTypeIcon | null>(null);
  const trimmed = name.trim();
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("menu.localTitle")}
      size={560}
      centered
    >
      <TextInput
        label={t("menu.localName")}
        value={name}
        maxLength={LOCAL_TYPE_MAX}
        onChange={(e) => setName(e.currentTarget.value)}
        data-autofocus
      />
      <Text size="sm" fw={600} mt="md" mb={6} id="icon-grid-label">
        {t("menu.localIcon")}
      </Text>
      <div
        className="icon-grid"
        role="radiogroup"
        aria-labelledby="icon-grid-label"
      >
        {NODE_TYPE_ICON_KEYS.map((key) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={icon === key}
            aria-label={t(`menu.icon.${key}`)}
            title={t(`menu.icon.${key}`)}
            className={icon === key ? "icon-opt sel" : "icon-opt"}
            onClick={() => setIcon(key)}
          >
            {nodeTypeSymbol(key)}
          </button>
        ))}
      </div>
      <Text size="xs" c="dimmed" mt="sm">
        {t("menu.localNote")}
      </Text>
      <Actions
        busy={busy}
        disabled={!trimmed || !icon}
        label={t("menu.localCreate")}
        onConfirm={() => icon && onCreate(trimmed, icon)}
        onClose={onClose}
      />
    </Modal>
  );
}

/** «Профиль ветки ▸» (FR-TREE-04): профили дисциплины, текущий отмечен. */
export function ProfileDialog({
  branch,
  profiles,
  current,
  busy,
  onPick,
  onClose,
}: {
  branch: string;
  profiles: readonly { id: string; name: string; chain: string }[];
  current: string | null;
  busy: boolean;
  onPick: (profileId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("menu.profileTitle", { name: branch })}
      size={420}
      centered
    >
      <Text size="sm" c="dimmed" mb="sm">
        {t("menu.profileNote")}
      </Text>
      {profiles.length ? (
        <div className="pick-list" role="group" aria-label={t("menu.profile")}>
          {profiles.map((p) => (
            <button
              key={p.id}
              type="button"
              className={p.id === current ? "pick sel" : "pick"}
              aria-pressed={p.id === current}
              disabled={busy}
              onClick={() => onPick(p.id)}
            >
              <b>{p.name}</b>
              <span className="pick-sub">{p.chain}</span>
            </button>
          ))}
        </div>
      ) : (
        <Text size="sm">{t("menu.noProfiles")}</Text>
      )}
    </Modal>
  );
}

/** «Свернуть в лист» (BR-TREE-03): суммы детей предложены, их можно изменить. */
export function CollapseDialog({
  title,
  childrenCount,
  initial,
  busy,
  onConfirm,
  onClose,
}: {
  title: string;
  childrenCount: number;
  initial: { o: string; r: string; p: string };
  busy: boolean;
  onConfirm: (values: { o: string; r: string; p: string }) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [values, setValues] = useState(initial);
  const field = (key: "o" | "r" | "p") => (
    <HoursInput
      label={key.toUpperCase()}
      value={key === "o" ? values.o : key === "r" ? values.r : values.p}
      onCommit={(value) => setValues((v) => ({ ...v, [key]: value ?? "0" }))}
    />
  );
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("menu.collapseTitle", { name: title })}
      size={420}
      centered
    >
      <Text size="sm" mb="sm">
        {t("menu.collapseNote", {
          count: childrenCount,
          fork: `${formatHours(initial.o)}–${formatHours(initial.r)}–${formatHours(initial.p)}`,
        })}
      </Text>
      <div className="fork-row">
        {field("o")}
        {field("r")}
        {field("p")}
      </div>
      <Actions
        busy={busy}
        disabled={false}
        label={t("menu.collapseConfirm")}
        onConfirm={() => onConfirm(values)}
        onClose={onClose}
      />
    </Modal>
  );
}

/** «Переместить в…»: узел выбирается из списка с поиском; узел встаёт последним ребёнком. */
export function MoveDialog({
  title,
  targets,
  busy,
  onPick,
  onClose,
}: {
  title: string;
  targets: readonly MoveTarget[];
  busy: boolean;
  onPick: (parentId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const q = query.trim().toLocaleLowerCase("ru");
  const shown = q
    ? targets.filter((x) => x.title.toLocaleLowerCase("ru").includes(q))
    : targets;
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("menu.moveTitle", { name: title })}
      size={480}
      centered
    >
      <TextInput
        placeholder={t("menu.moveSearch")}
        aria-label={t("menu.moveSearch")}
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        mb="sm"
        data-autofocus
      />
      {shown.length ? (
        <div
          className="pick-list tall"
          role="radiogroup"
          aria-label={t("menu.moveWhere")}
        >
          {shown.map((target) => (
            <button
              key={target.id}
              type="button"
              role="radio"
              aria-checked={picked === target.id}
              className={picked === target.id ? "pick sel" : "pick"}
              style={{ paddingLeft: 10 + (q ? 0 : target.level * 16) }}
              onClick={() => setPicked(target.id)}
            >
              {target.kind === "discipline" ? (
                <b>{target.title}</b>
              ) : (
                target.title
              )}
            </button>
          ))}
        </div>
      ) : (
        <Text size="sm">{t("menu.moveNothing")}</Text>
      )}
      <Actions
        busy={busy}
        disabled={!picked}
        label={t("menu.moveConfirm")}
        onConfirm={() => picked && onPick(picked)}
        onClose={onClose}
      />
    </Modal>
  );
}

/**
 * «Скопировать ветку из проекта…» (FR-PRJ-03): проект, где пользователь сейчас участник, и узел
 * ветки той же дисциплины; поддерево копируется детьми выбранной строки.
 */
export function CopyBranchDialog({
  title,
  projectId,
  disciplineId,
  busy,
  onPick,
  onClose,
}: {
  title: string;
  projectId: string;
  disciplineId: string | null;
  busy: boolean;
  onPick: (sourceNodeId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [source, setSource] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const projects = useQuery({
    queryKey: ["projects", "copy-source"],
    queryFn: () =>
      call(() => api.GET("/projects", { params: { query: { limit: 200 } } })),
    select: (data) =>
      data.items
        .filter((p) => p.id !== projectId)
        .map((p) => ({ value: p.id, label: p.name })),
  });
  const tree = useQuery({
    queryKey: ["tree", source],
    queryFn: () =>
      call(() =>
        api.GET("/projects/{id}/tree", {
          params: { path: { id: source ?? "" } },
        }),
      ),
    enabled: source !== null,
    select: (data) => sourceRows(data.nodes as SourceNode[], disciplineId),
  });
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("menu.copyTitle", { name: title })}
      size={520}
      centered
    >
      <Select
        label={t("menu.copyProject")}
        placeholder={
          projects.isPending ? t("common.loading") : t("menu.copyProjectPick")
        }
        data={projects.data ?? []}
        value={source}
        onChange={(value) => {
          setSource(value);
          setPicked(null);
        }}
        searchable
        nothingFoundMessage={t("menu.copyNoProjects")}
        comboboxProps={{ withinPortal: true }}
      />
      {source && tree.data ? (
        tree.data.length ? (
          <div
            className="pick-list tall"
            role="radiogroup"
            aria-label={t("menu.copyNode")}
          >
            {tree.data.map((row) => (
              <button
                key={row.id}
                type="button"
                role="radio"
                aria-checked={picked === row.id}
                className={picked === row.id ? "pick sel" : "pick"}
                style={{ paddingLeft: 10 + row.level * 16 }}
                onClick={() => setPicked(row.id)}
              >
                {row.level === 0 ? <b>{row.title}</b> : row.title}
              </button>
            ))}
          </div>
        ) : (
          <Text size="sm" mt="sm">
            {t("menu.copyEmpty")}
          </Text>
        )
      ) : null}
      <Text size="xs" c="dimmed" mt="sm">
        {t("menu.copyNote")}
      </Text>
      <Actions
        busy={busy}
        disabled={!picked}
        label={t("menu.copyConfirm")}
        onConfirm={() => picked && onPick(picked)}
        onClose={onClose}
      />
    </Modal>
  );
}

interface SourceNode {
  id: string;
  parent_id: string | null;
  kind: string;
  title: string;
  position: string;
  discipline_id: string | null;
  phase_id: string;
}

/** Строки дерева проекта-источника той же дисциплины: ветки (с фазой в названии) и их узлы. */
export function sourceRows(
  nodes: readonly SourceNode[],
  disciplineId: string | null,
): { id: string; title: string; level: number }[] {
  const byParent = new Map<string | null, SourceNode[]>();
  for (const n of nodes)
    byParent.set(n.parent_id, [...(byParent.get(n.parent_id) ?? []), n]);
  for (const list of byParent.values())
    list.sort((a, b) => (a.position < b.position ? -1 : 1));
  const phases = new Map(
    nodes.filter((n) => n.kind === "phase").map((n) => [n.id, n.title]),
  );
  const out: { id: string; title: string; level: number }[] = [];
  const walk = (parent: string, level: number) => {
    for (const n of byParent.get(parent) ?? []) {
      out.push({ id: n.id, title: n.title, level });
      walk(n.id, level + 1);
    }
  };
  for (const n of nodes) {
    if (
      n.kind !== "discipline" ||
      n.discipline_id !== disciplineId ||
      !(byParent.get(n.id) ?? []).length
    )
      continue;
    out.push({
      id: n.id,
      title: `${phases.get(n.phase_id) ?? ""} · ${n.title}`,
      level: 0,
    });
    walk(n.id, 1);
  }
  return out;
}
