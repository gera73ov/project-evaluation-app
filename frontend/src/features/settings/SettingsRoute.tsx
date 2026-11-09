/** FE-012 · маршрут `/projects/:id/settings`. */
import { ProjectSettingsPage } from './ProjectSettingsPage';

export function SettingsRoute({ id }: { id: string }) {
  return <ProjectSettingsPage key={id} projectId={id} />;
}
