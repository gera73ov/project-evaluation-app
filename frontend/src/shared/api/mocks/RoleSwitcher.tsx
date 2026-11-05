/** FE-001 · переключатель роли моков: фиксированная плашка в правом нижнем углу. */
import { MantineProvider, Paper, Select, Text } from '@mantine/core';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { useTranslation } from 'react-i18next';

import './mocks.css';

import { PERSONA_KEYS, PERSONAS, currentPersona, setPersona, type PersonaKey } from './personas';

export function RoleSwitcher({ onChange }: { onChange: (key: PersonaKey) => void }) {
  const { t } = useTranslation();
  const persona = currentPersona();
  return (
    <Paper shadow="md" p="xs" withBorder className="mock-role-switcher">
      <Text size="xs" c="dimmed">
        {t('mock.switcher.title')}
      </Text>
      <Select
        size="xs"
        aria-label={t('mock.switcher.label')}
        allowDeselect={false}
        value={persona.key}
        data={PERSONA_KEYS.map((key) => ({
          value: key,
          label: t('mock.persona.' + key, { name: PERSONAS[key].fullName }),
        }))}
        onChange={(value) => value && onChange(value as PersonaKey)}
      />
    </Paper>
  );
}

/** Смена роли перезагружает страницу: приложение заново читает /me и права. */
export function mountRoleSwitcher(): void {
  const host = document.createElement('div');
  host.id = 'mock-role-switcher';
  document.body.append(host);
  createRoot(host).render(
    <StrictMode>
      <MantineProvider>
        <RoleSwitcher
          onChange={(key) => {
            setPersona(key);
            window.location.reload();
          }}
        />
      </MantineProvider>
    </StrictMode>,
  );
}
