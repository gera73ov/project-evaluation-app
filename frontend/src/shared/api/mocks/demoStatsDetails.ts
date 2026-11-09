/**
 * FE-042 · данные вкладок статистики в демо (11.10): объёмы по типам с учётом ×N, кандидаты на
 * декомпозицию (топ-10 по E и по σ/E) и списки меток «Допущения и риски». Объёмы и кандидаты
 * считаются по дереву проекта, метки — строки макета `stats-details.png`.
 */
import Decimal from "decimal.js";

import { type DemoProject, hours } from "./data";
import { uuidFrom } from "./ids";

type Node = {
  id: string;
  parent_id: string | null;
  kind: string;
  type_id: string | null;
  title: string;
  multiplier: number;
  e: string | null;
  sigma: string | null;
};

const nodesOf = (p: DemoProject) => p.nodes as unknown as Node[];

function leaves(p: DemoProject): Node[] {
  const nodes = nodesOf(p);
  const parents = new Set(nodes.map((n) => n.parent_id));
  return nodes.filter(
    (n) => n.kind === "item" && !parents.has(n.id) && n.e !== null,
  );
}

/** Объёмы: листья с типом, единиц — сумма ×N; узлы-группы не считаются. */
export function volumes(p: DemoProject, typeName: (id: string) => string) {
  const byType = new Map<string, number>();
  for (const n of leaves(p)) {
    if (!n.type_id) continue;
    byType.set(n.type_id, (byType.get(n.type_id) ?? 0) + n.multiplier);
  }
  return [...byType.entries()].map(([type_id, count]) => ({
    type_id,
    name: typeName(type_id),
    count,
  }));
}

/** Кандидаты: топ-10 по E и топ-10 по σ/E (порог сравнивает клиент). */
export function candidates(p: DemoProject) {
  const ls = leaves(p);
  const large = [...ls]
    .sort((a, b) => Number(b.e) - Number(a.e))
    .slice(0, 10)
    .map((n) => ({
      node_id: n.id,
      e_unit: hours(new Decimal(n.e ?? "0").div(n.multiplier).toFixed(2)),
      e: n.e ?? "0",
      repeating: n.multiplier > 1,
    }));
  const wide_fork = ls
    .filter((n) => n.sigma !== null && !new Decimal(n.e ?? "0").isZero())
    .map((n) => ({
      node_id: n.id,
      ratio_pct: new Decimal(n.sigma ?? "0")
        .div(n.e ?? "1")
        .times(100)
        .toFixed(1),
    }))
    .sort((a, b) => Number(b.ratio_pct) - Number(a.ratio_pct))
    .slice(0, 10);
  return { large, wide_fork };
}

function pathOf(p: DemoProject, nodeId: string): string[] {
  const byId = new Map(nodesOf(p).map((n) => [n.id, n]));
  const out: string[] = [];
  for (
    let n = byId.get(nodeId);
    n;
    n = n.parent_id ? byId.get(n.parent_id) : undefined
  )
    out.unshift(n.title);
  return out;
}

const TAGS: ["assumption" | "constraint" | "risk" | "tech", string, string][] =
  [
    [
      "assumption",
      "n-1c",
      "Обмен через REST, формат согласуем с заказчиком; спецификации пока нет",
    ],
    [
      "constraint",
      "n-ph-dev-d-frontend",
      "Поддерживаются браузеры Chrome и Edge последних версий",
    ],
    ["risk", "n-1c", "Спецификация 1С появится не раньше декабря"],
    [
      "risk",
      "n-auth",
      "Keycloak заказчика может не поддерживать нужные scopes",
    ],
    [
      "risk",
      "n-1c-tests",
      "Тестовая база 1С недоступна до подписания договора",
    ],
    [
      "tech",
      "n-auth",
      "OAuth2 через корпоративный Keycloak заказчика · Python 3.12, FastAPI · React",
    ],
  ];

/** Списки меток: только для «Портала дилеров» — строки макета. */
export function tagLists(p: DemoProject) {
  if (p.key !== "portal") return [];
  const order = ["assumption", "constraint", "risk", "tech"] as const;
  return order.map((category) => ({
    category,
    items: TAGS.filter(([c]) => c === category).map(([, node, text], i) => {
      const id = uuidFrom("node", p.key, node);
      return {
        node_id: id,
        tag_id: uuidFrom("tag", category, String(i)),
        text,
        path: pathOf(p, id),
      };
    }),
  }));
}
