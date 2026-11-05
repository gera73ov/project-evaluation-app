/**
 * FE-003 · тема Mantine поверх токенов `app.css` (DESIGN.md 2–4). Цвета берутся из CSS-переменных,
 * чтобы единственным источником оставался `app.css`; палитра `accent` нужна Mantine для состояний.
 */
import { createTheme, type MantineColorsTuple } from '@mantine/core';

const accent: MantineColorsTuple = [
  '#e3f0f5',
  '#c9e2ec',
  '#9fcadb',
  '#72b0c8',
  '#4c97b4',
  '#2f82a0',
  '#1f6f8b',
  '#195e76',
  '#165468',
  '#0f3c4b',
];

export const theme = createTheme({
  primaryColor: 'accent',
  primaryShade: 6,
  colors: { accent },
  fontFamily: 'var(--f)',
  fontFamilyMonospace: 'var(--m)',
  fontSizes: { xs: '11.5px', sm: '13px', md: '13px', lg: '14px', xl: '18px' },
  radius: { xs: '4px', sm: '6px', md: '8px', lg: '10px', xl: '12px' },
  defaultRadius: 'sm',
  headings: { fontFamily: 'var(--f)', fontWeight: '700' },
});

/**
 * Nonce для `<style>`, которые вставляет Mantine (SEC-WEB-03: style-src без 'unsafe-inline').
 * Nginx подставляет его в `<meta name="csp-nonce">` (SEC-007); без meta — undefined (dev, тесты).
 */
export function cspNonce(doc: Document = document): string | undefined {
  const meta = doc.querySelector<HTMLMetaElement>('meta[name="csp-nonce"]');
  return meta?.content || undefined;
}
