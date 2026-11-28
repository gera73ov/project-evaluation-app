import { useLayoutEffect, type RefObject } from 'react';

/** Наибольшая высота поля ввода в строках; дальше поле не растёт, появляется прокрутка. */
export const AUTO_GROW_MAX_ROWS = 10;

const px = (value: string) => parseFloat(value) || 0;

/**
 * Высота `<textarea>` по тексту: поле растёт по мере набора, чтобы был виден весь текст,
 * и сжимается обратно после отправки. Выше `maxRows` строк — прокрутка внутри поля.
 */
export function useAutoGrow(ref: RefObject<HTMLTextAreaElement | null>, value: string, maxRows = AUTO_GROW_MAX_ROWS) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const style = window.getComputedStyle(el);
    // box-sizing: border-box — к scrollHeight (текст + отступы) добавляем рамку
    const border = px(style.borderTopWidth) + px(style.borderBottomWidth);
    const max = (px(style.lineHeight) || 18) * maxRows + px(style.paddingTop) + px(style.paddingBottom) + border;
    el.style.height = 'auto';
    const needed = el.scrollHeight + border;
    el.style.height = `${Math.min(needed, max)}px`;
    el.style.overflowY = needed > max ? 'auto' : 'hidden';
  }, [ref, value, maxRows]);
}
