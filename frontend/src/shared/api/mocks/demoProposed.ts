/**
 * FE-072 · предложенные типы (SPEC 7.5, FR-TREE-03): локальные типы проектов ждут решения
 * администратора — «Добавить» в словарь, «Объединить с …» существующим типом или «Отклонить».
 */
import { PEOPLE, PROJECTS, userRef } from "./data";
import { minutesAgo, uuidFrom } from "./ids";
import { PERSONAS } from "./personas";

type Proposed = {
  id: string;
  name: string;
  icon: string;
  project_id: string;
  project_name: string;
  author: ReturnType<typeof userRef>;
  created_at: string;
  nodes_count: number;
};

const SEED: Proposed[] = [
  {
    id: uuidFrom("type", "local:Шлюз оплаты"),
    name: "Шлюз оплаты",
    icon: "credit_card",
    project_id: PROJECTS.portal.id,
    project_name: PROJECTS.portal.name,
    author: userRef(PERSONAS.expert),
    created_at: minutesAgo(60 * 26),
    nodes_count: 2,
  },
  {
    id: uuidFrom("type", "local:Регламентный отчёт"),
    name: "Регламентный отчёт",
    icon: "file_spreadsheet",
    project_id: PROJECTS.fns.id,
    project_name: PROJECTS.fns.name,
    author: userRef(PEOPLE.petrov),
    created_at: minutesAgo(60 * 3),
    nodes_count: 5,
  },
];

let items: Proposed[] = [];

export function resetDemoProposed() {
  items = SEED.map((p) => ({ ...p }));
}
resetDemoProposed();

export const list = () => items;

export function take(id: string): Proposed | null {
  const found = items.find((p) => p.id === id) ?? null;
  if (found) items = items.filter((p) => p !== found);
  return found;
}
