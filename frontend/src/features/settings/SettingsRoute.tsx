/** FE-012, FE-015 · маршруты `/projects/:id/settings` и `/projects/:id/log`. */
import { JournalPage } from './journal/JournalPage';
import { ProjectSettingsPage } from './ProjectSettingsPage';

export function SettingsRoute({ id }: { id: string }) {
  return <ProjectSettingsPage key={id} projectId={id} />;
}

export function JournalRoute({ id }: { id: string }) {
  return <JournalPage key={id} projectId={id} />;
}
