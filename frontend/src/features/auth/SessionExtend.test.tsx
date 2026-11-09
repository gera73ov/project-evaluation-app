/** FE-007 · «Продлить сессию?» (FR-SESS-02): за 2 минуты до истечения; «Продлить» — запрос пользователя. */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { BACKGROUND_HEADER, api } from '../../shared/api/client';
import { lastActivityAt, markActivity } from '../../shared/api/activity';
import { renderUi } from '../../test/render';
import { SessionExtend, formatLeft, idleWarning } from './SessionExtend';

const HOUR = 3600;
const FAR = '2099-01-01T00:00:00Z';

describe('idleWarning', () => {
  const now = Date.parse('2026-11-09T12:00:00Z');
  it('за 2 минуты и меньше — сколько осталось; раньше — null', () => {
    expect(idleWarning(now, now - (HOUR * 1000 - 120_000), HOUR, FAR)).toBe(120_000);
    expect(idleWarning(now, now - (HOUR * 1000 - 121_000), HOUR, FAR)).toBeNull();
    expect(idleWarning(now, now - HOUR * 1000, HOUR, FAR)).toBeNull(); // уже истекла
  });
  it('абсолютный срок раньше бездействия — продлевать нечего', () => {
    const soon = new Date(now + 30_000).toISOString();
    expect(idleWarning(now, now - (HOUR * 1000 - 60_000), HOUR, soon)).toBeNull();
  });
  it('формат м:сс', () => {
    expect(formatLeft(120_000)).toBe('2:00');
    expect(formatLeft(61_200)).toBe('1:02');
  });
});

describe('SessionExtend', () => {
  it('диалог за 2 минуты; «Продлить» делает пользовательский запрос и закрывает диалог', async () => {
    markActivity(Date.now() - (15 * 60_000 - 90_000)); // 15 минут администратора, осталось 1:30
    renderUi(<SessionExtend idleTimeoutSeconds={15 * 60} sessionExpiresAt={FAR} onLogout={() => {}} />);
    expect(await screen.findByText('Продлить сессию?')).toBeTruthy();
    expect(screen.getByText(/завершится через 1:(29|30)/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Продлить' }));
    await waitFor(() => expect(screen.queryByText('Продлить сессию?')).toBeNull());
    expect(Date.now() - lastActivityAt()).toBeLessThan(5000);
  });

  it('«Выйти» передаётся наверх; фоновые запросы активность не продлевают', async () => {
    const onLogout = vi.fn();
    const before = Date.now() - (HOUR * 1000 - 60_000);
    markActivity(before);
    renderUi(<SessionExtend idleTimeoutSeconds={HOUR} sessionExpiresAt={FAR} onLogout={onLogout} />);
    await screen.findByText('Продлить сессию?');
    await api.GET('/me', { headers: { [BACKGROUND_HEADER]: '1' } });
    expect(lastActivityAt()).toBe(before);
    fireEvent.click(screen.getByRole('button', { name: 'Выйти' }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });
});
