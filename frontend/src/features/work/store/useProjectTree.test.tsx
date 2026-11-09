/** FE-021 · дерево в React: подписка после загрузки с `since`, события WS, ответ сервера на правку. */
import { QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { createQueryClient } from '../../../app/App';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { WsProvider } from '../../../shared/ws/WsProvider';
import { FakeSocket } from '../../../test/fakeSocket';
import { persona } from '../../../test/setup';
import { useProjectTree, useTree } from './useProjectTree';

type Project = components['schemas']['Project'];

function Probe({ project }: { project: Project }) {
  const tree = useProjectTree(project);
  const total = useTree(tree.store, (s) => s.result?.total.e.toString() ?? '—');
  const version = useTree(tree.store, (s) => s.version);
  const count = useTree(tree.store, (s) => s.nodes.size);
  return (
    <output>
      {tree.loaded ? 'loaded' : 'loading'} v{version} n{count} e{total}
    </output>
  );
}

describe('useProjectTree', () => {
  it('подписывается с версией загруженного дерева и применяет node.deleted', async () => {
    persona.current = PERSONAS.moderator;
    FakeSocket.all = [];
    const project = (await call(() =>
      api.GET('/projects/{id}', { params: { path: { id: PROJECTS.portal.id } } }),
    )) as Project;
    render(
      <QueryClientProvider client={createQueryClient()}>
        <WsProvider enabled onSessionEnded={() => {}} options={{ createSocket: FakeSocket.factory, backoff: () => 10 }}>
          <Probe project={project} />
        </WsProvider>
      </QueryClientProvider>,
    );
    await screen.findByText(/^loaded/);
    const before = screen.getByRole('status').textContent ?? '';
    const version = Number(/v(\d+)/.exec(before)?.[1]);
    const count = Number(/n(\d+)/.exec(before)?.[1]);

    await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0));
    act(() => FakeSocket.last().open());
    await waitFor(() =>
      expect(FakeSocket.last().sent.find((c) => c.op === 'subscribe')).toMatchObject({
        project_id: project.id,
        since: version,
      }),
    );
    FakeSocket.last().ack('subscribe', { project_version: version, channels: [], resync: false });

    const leaf = PROJECTS.portal.nodes.find(
      (n) =>
        (n as { kind: string }).kind === 'item' &&
        !PROJECTS.portal.nodes.some((c) => (c as { parent_id: string }).parent_id === (n as { id: string }).id),
    ) as { id: string };
    act(() =>
      FakeSocket.last().push({
        type: 'event',
        event: 'node.deleted',
        channel: `project:${project.id}`,
        ts: '2026-11-09T10:00:00Z',
        project_version: version + 1,
        data: { node_ids: [leaf.id], batch_id: 'b', author: { id: 'u', full_name: 'X', initials: 'X' } },
      }),
    );
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain(`v${version + 1} n${count - 1}`));
  });
});
