/**
 * INF-003 · ESLint (SEC-SDLC-01, SEC-WEB-02).
 * Плоский конфиг ESLint 9 (`eslint.config.js` вместо `.eslintrc.*` из PLAN.md: старый формат
 * в ESLint 9 устарел). eslint-plugin-react пока не поддерживает ESLint 10, поэтому ESLint 9.
 */
import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import security from 'eslint-plugin-security';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const DANGER = 'SEC-WEB-02: dangerouslySetInnerHTML запрещён, текст выводится как текст';

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules', 'src/shared/api/generated', 'mock-public'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  security.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { globals: globals.browser },
    settings: { react: { version: '18.3' } },
    plugins: { react, 'react-hooks': reactHooks },
    rules: {
      ...react.configs.recommended.rules,
      ...react.configs['jsx-runtime'].rules,
      ...reactHooks.configs.recommended.rules,
      // SEC-WEB-02: и в JSX, и через объект пропсов (createElement, spread)
      'react/no-danger': 'error',
      'react/no-danger-with-children': 'error',
      'no-restricted-syntax': [
        'error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: DANGER },
        { selector: "Property[key.name='dangerouslySetInnerHTML']", message: DANGER },
        { selector: "MemberExpression[property.name='innerHTML']", message: DANGER },
        { selector: "MemberExpression[property.name='outerHTML']", message: DANGER },
        { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: DANGER },
      ],
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'react/jsx-no-script-url': 'error',
      'react/jsx-no-target-blank': 'error',
    },
  },
  {
    files: ['*.{js,mjs}', 'scripts/**/*.mjs', 'vite.config.ts'],
    languageOptions: { globals: globals.node },
  },
  {
    // Скрипты сборки читают только собственный dist/ и разбирают свой же HTML; в бандл и на
    // сервер не попадают. Для продуктового кода src/ правила остаются включены.
    files: ['scripts/**/*.mjs'],
    rules: {
      'security/detect-non-literal-fs-filename': 'off',
      'security/detect-unsafe-regex': 'off',
    },
  },
  {
    // FE-001: моки API работают только в `npm run dev:mock` и в тестах, в сборку не попадают.
    // Ключи объектов и шаблоны pattern приходят из контрактов репозитория (contracts/*),
    // а не от пользователя. Остальные правила безопасности для моков действуют.
    files: ['src/shared/api/mocks/**/*.{ts,tsx}'],
    rules: {
      'security/detect-object-injection': 'off',
      'security/detect-non-literal-regexp': 'off',
    },
  },
);
