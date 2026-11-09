/**
 * DESIGN.md 16.3 · ключи иконок типов узлов (FR-TREE-03, GAP-07). Пока в проекте нет набора Tabler,
 * в строке дерева рисуется символ из SPEC 5.2; неизвестный ключ — «•».
 */
const SYMBOLS = new Map<string, string>([
  ['module', '▣'],
  ['function', 'ƒ'],
  ['screen', '▭'],
  ['integration', '⇄'],
  ['report', '▤'],
  ['entity', '◇'],
  ['service', '⚙'],
  ['test_suite', '✓'],
  ['document', '✎'],
  ['work', '•'],
]);

export function nodeTypeSymbol(icon: string | null | undefined): string {
  return (icon ? SYMBOLS.get(icon) : undefined) ?? '•';
}
