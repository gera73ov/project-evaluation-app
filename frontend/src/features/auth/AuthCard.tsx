/** FE-005 · шаблон «Карточка по центру» (DESIGN.md 5.3): логотип, заголовок, подзаголовок. */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export function AuthCard({
  title,
  subtitle,
  wide = false,
  children,
}: {
  title: string;
  subtitle?: string | undefined;
  wide?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="page-center">
      <section className={wide ? 'card-center wide' : 'card-center'} aria-labelledby="auth-title">
        <div className="logo">
          <i aria-hidden="true" />
          {t('app.name')}
        </div>
        <h1 id="auth-title">{title}</h1>
        {subtitle ? <p className="sub">{subtitle}</p> : null}
        {children}
      </section>
    </div>
  );
}
