/** i18n (FR-UI-01): все пользовательские тексты — в файлах ресурсов, язык MVP — русский. */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import ru from './ru.json';

void i18n.use(initReactI18next).init({
  lng: 'ru',
  fallbackLng: 'ru',
  resources: { ru: { translation: ru } },
  interpolation: { escapeValue: false }, // React экранирует сам (SEC-WEB-02)
  returnNull: false,
});

export default i18n;
