/**
 * FE-027 · операции с узлами из меню «+» и «⋯» (FR-TREE-01, FR-TREE-03, FR-TREE-04, FR-TREE-23,
 * FR-TREE-24, FR-PRJ-03, BR-TREE-02, BR-TREE-03).
 *
 * Каждая операция — запрос к API и применение ответа к дереву (`NodeMutation` / `NodesMutation`).
 * Ошибка сервера показывается одной строкой над таблицей; дерево не меняется до ответа.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type components } from "../../../shared/api/client";
import { call, errorMessage } from "../../../shared/api/problem";
import { dec } from "../../../shared/calc";
import { projectKey } from "../../settings/useProject";
import type { TreeMutation, TreeStore } from "../store/treeStore";
import { createdIds } from "./ops";

const canon = (value: string) => dec(value).toFixed();

type ApiNode = components["schemas"]["Node"];
type NodeType = components["schemas"]["NodeType"];

/** Локальные типы, созданные в проекте за эту сессию (до CR-006 их нельзя прочитать списком). */
export const localTypesKey = (projectId: string) =>
  ["dict", "node-types", "local", projectId] as const;

export interface TreeOps {
  busy: boolean;
  error: string | null;
  clearError: () => void;
  /** Новый узел; возвращает его id. */
  create: (
    parentId: string,
    afterId: string | null,
    typeId: string | null,
    title: string,
  ) => Promise<string | null>;
  /** «Разбить лист» (BR-TREE-02); возвращает id нового листа-ребёнка. */
  split: (id: string) => Promise<string | null>;
  collapseSuggestion: (
    id: string,
  ) => Promise<{ o: string; r: string; p: string } | null>;
  collapse: (
    id: string,
    values: { o: string; r: string; p: string },
  ) => Promise<boolean>;
  move: (
    id: string,
    parentId: string,
    afterId: string | null,
  ) => Promise<boolean>;
  duplicate: (id: string) => Promise<string | null>;
  remove: (id: string) => Promise<boolean>;
  copyFrom: (id: string, sourceNodeId: string) => Promise<boolean>;
  changeType: (id: string, typeId: string) => Promise<boolean>;
  setProfile: (disciplineId: string, profileId: string) => Promise<boolean>;
  createLocalType: (
    name: string,
    icon: components["schemas"]["NodeTypeIcon"],
  ) => Promise<NodeType | null>;
}

export function useTreeOps({
  projectId,
  store,
  confirmMutation,
}: {
  projectId: string;
  store: TreeStore;
  confirmMutation: (mutation: TreeMutation) => void;
}): TreeOps {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async <T>(request: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await request();
    } catch (e) {
      setError(errorMessage(e));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const version = (id: string) => store.getState().nodes.get(id)?.version ?? 1;
  /** Ответ `NodesMutation`: применить и вернуть новые узлы. */
  const apply = (
    result: {
      nodes: unknown[];
      deleted_ids?: string[];
      project_version: number;
    } & object,
  ) => {
    const nodes = result.nodes as ApiNode[];
    const created = createdIds(store.getState(), nodes);
    confirmMutation({ ...result, nodes } as TreeMutation);
    return { nodes, created };
  };
  const single = (result: { node: unknown; project_version: number }) =>
    apply({ nodes: [result.node], project_version: result.project_version });

  return {
    busy,
    error,
    clearError: () => setError(null),

    create: async (parentId, afterId, typeId, title) =>
      run(async () => {
        const result = await call(() =>
          api.POST("/projects/{id}/nodes", {
            params: { path: { id: projectId } },
            body: {
              parent_id: parentId,
              after_id: afterId,
              type_id: typeId,
              title,
            },
          }),
        );
        single(result);
        return String((result.node as ApiNode).id);
      }),

    split: async (id) =>
      run(async () => {
        const result = await call(() =>
          api.POST("/nodes/{id}/split", {
            params: { path: { id } },
            body: { base_version: version(id) },
          }),
        );
        const { nodes, created } = apply(result);
        return (
          created.at(0) ?? nodes.find((n) => n.parent_id === id)?.id ?? null
        );
      }),

    collapseSuggestion: async (id) =>
      run(async () => {
        const s = await call(() =>
          api.GET("/nodes/{id}/collapse", { params: { path: { id } } }),
        );
        return { o: String(s.o), r: String(s.r), p: String(s.p) };
      }),

    collapse: async (id, values) =>
      (await run(async () => {
        const result = await call(() =>
          api.POST("/nodes/{id}/collapse", {
            params: { path: { id } },
            // суммы — каноническими строками: «20», а не «20.00»
            body: {
              base_version: version(id),
              o: canon(values.o),
              r: canon(values.r),
              p: canon(values.p),
            },
          }),
        );
        apply(result);
        return true;
      })) ?? false,

    move: async (id, parentId, afterId) =>
      (await run(async () => {
        const result = await call(() =>
          api.POST("/nodes/{id}/move", {
            params: { path: { id } },
            body: {
              base_version: version(id),
              new_parent_id: parentId,
              after_id: afterId,
            },
          }),
        );
        apply(result);
        return true;
      })) ?? false,

    duplicate: async (id) =>
      run(async () => {
        const parent = store.getState().nodes.get(id)?.parent_id ?? null;
        const result = await call(() =>
          api.POST("/nodes/{id}/duplicate", { params: { path: { id } } }),
        );
        const { nodes, created } = apply(result);
        // копия — новый узел под тем же родителем
        return (
          nodes.find((n) => created.includes(n.id) && n.parent_id === parent)
            ?.id ??
          created.at(0) ??
          null
        );
      }),

    remove: async (id) =>
      (await run(async () => {
        const result = await call(() =>
          api.DELETE("/nodes/{id}", { params: { path: { id } } }),
        );
        apply({ ...result, deleted_ids: result.deleted_ids ?? [id] });
        return true;
      })) ?? false,

    copyFrom: async (id, sourceNodeId) =>
      (await run(async () => {
        const result = await call(() =>
          api.POST("/nodes/{id}/copy-from", {
            params: { path: { id } },
            body: { source_node_id: sourceNodeId },
          }),
        );
        apply(result);
        return true;
      })) ?? false,

    changeType: async (id, typeId) =>
      (await run(async () => {
        const result = await call(() =>
          api.PATCH("/nodes/{id}", {
            params: { path: { id } },
            body: { base_version: version(id), changes: { type_id: typeId } },
          }),
        );
        single(result);
        return true;
      })) ?? false,

    setProfile: async (disciplineId, profileId) =>
      (await run(async () => {
        await call(() =>
          api.PATCH("/projects/{id}/disciplines/{discipline_id}", {
            params: { path: { id: projectId, discipline_id: disciplineId } },
            body: { profile_id: profileId },
          }),
        );
        await client.invalidateQueries({ queryKey: projectKey(projectId) });
        return true;
      })) ?? false,

    createLocalType: async (name, icon) =>
      run(async () => {
        const type = (await call(() =>
          api.POST("/projects/{id}/node-types", {
            params: { path: { id: projectId } },
            body: { name, icon },
          }),
        )) as NodeType;
        client.setQueryData<NodeType[]>(localTypesKey(projectId), (prev) => [
          ...(prev ?? []),
          type,
        ]);
        return type;
      }),
  };
}
