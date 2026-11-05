/** FE-003 · пустое состояние списка или ветки (FR-UI-05): что здесь будет и что сделать. */
import type { ReactNode } from 'react';

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty" role="status">
      <b>{title}</b>
      {hint ? <span>{hint}</span> : null}
      {action ? <div>{action}</div> : null}
    </div>
  );
}
