import { render } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it } from 'vitest';

import { useAutoGrow } from './useAutoGrow';

function Field({ value, scroll }: { value: string; scroll: number }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useAutoGrow(ref, value, 10);
  return (
    <textarea
      ref={(el) => {
        ref.current = el;
        if (el) Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => scroll });
      }}
      style={{ lineHeight: '18px', padding: '6px 10px', border: '1px solid #000' }}
      value={value}
      readOnly
    />
  );
}

describe('useAutoGrow', () => {
  it('растит поле по тексту и сжимает обратно', () => {
    const view = render(<Field value="строка" scroll={30} />);
    const el = view.container.querySelector('textarea')!;
    expect(el.style.height).toBe('32px');
    expect(el.style.overflowY).toBe('hidden');
    view.rerender(<Field value={'a\nb\nc'} scroll={66} />);
    expect(el.style.height).toBe('68px');
    view.rerender(<Field value="" scroll={30} />);
    expect(el.style.height).toBe('32px');
  });

  it('выше 10 строк — не растёт, включается прокрутка', () => {
    const view = render(<Field value={'x\n'.repeat(30)} scroll={600} />);
    const el = view.container.querySelector('textarea')!;
    expect(el.style.height).toBe(`${18 * 10 + 12 + 2}px`);
    expect(el.style.overflowY).toBe('auto');
  });
});
