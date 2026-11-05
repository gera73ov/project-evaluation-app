import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import '../shared/i18n';
import { App } from './App';

// jsdom не реализует matchMedia, а Mantine его вызывает
window.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList;

describe('App', () => {
  it('показывает заголовок из ресурсов i18n', () => {
    render(<App />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(
      'Приложение оценки проектов',
    );
  });
});
