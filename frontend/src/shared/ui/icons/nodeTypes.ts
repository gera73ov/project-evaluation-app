/**
 * DESIGN.md 16.3 · ключи иконок типов узлов (FR-TREE-03, GAP-07): 10 типов SPEC 5.2 и 20 для
 * локальных типов. Пока в проекте нет набора Tabler, рисуется символ (у типов 5.2 — из SPEC);
 * неизвестный ключ — «•». Порядок набора — порядок сетки выбора иконки.
 */
import type { components } from "../../api/client";

export type NodeTypeIcon = components["schemas"]["NodeTypeIcon"];

const SYMBOLS = new Map<NodeTypeIcon, string>([
  ["module", "▣"],
  ["function", "ƒ"],
  ["screen", "▭"],
  ["integration", "⇄"],
  ["report", "▤"],
  ["entity", "◇"],
  ["service", "⚙"],
  ["test_suite", "✓"],
  ["document", "✎"],
  ["work", "•"],
  ["api", "⟨⟩"],
  ["cloud", "☁"],
  ["server", "▥"],
  ["lock", "⚿"],
  ["users", "⚇"],
  ["mail", "✉"],
  ["bell", "⍾"],
  ["chart_bar", "▊"],
  ["file_spreadsheet", "▦"],
  ["device_mobile", "▯"],
  ["world", "◍"],
  ["search", "⌕"],
  ["upload", "⇧"],
  ["download", "⇩"],
  ["calendar", "⊞"],
  ["credit_card", "▬"],
  ["shield_check", "⛉"],
  ["bug", "✲"],
  ["robot", "⌬"],
  ["map", "⌖"],
]);

/** Курируемый набор ключей (30), в порядке сетки. */
export const NODE_TYPE_ICON_KEYS: readonly NodeTypeIcon[] = [...SYMBOLS.keys()];

export function nodeTypeSymbol(icon: string | null | undefined): string {
  return (icon ? SYMBOLS.get(icon as NodeTypeIcon) : undefined) ?? "•";
}
