/** FE-022 · маршрут `/projects/:id`: при смене проекта экран создаётся заново со своим хранилищем. */
import { WorkPage } from './WorkPage';

export function WorkRoute({ id }: { id: string }) {
  return <WorkPage key={id} projectId={id} />;
}
