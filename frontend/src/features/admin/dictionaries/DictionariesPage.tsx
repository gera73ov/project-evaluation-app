/**
 * FE-071 · «Справочники» админки администратора (SPEC 7.5): вкладки справочников над шаблоном
 * «список + форма справа»; «Пороги и проценты» — одна форма без списка.
 */
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import { AdminLayout } from '../layout/AdminLayout';
import { DICTS, dictPath, type DictKey } from './dictionaries';
import {
  CurrenciesDict,
  DisciplinesDict,
  NodeTypesDict,
  PhasesDict,
  ProfilesDict,
  RatiosDict,
  ReasonsDict,
  TagsDict,
  VatDict,
} from './kinds';
import { MethodForm } from './MethodForm';

function screen(kind: DictKey) {
  switch (kind) {
    case 'phases':
      return <PhasesDict />;
    case 'disciplines':
      return <DisciplinesDict />;
    case 'node-types':
      return <NodeTypesDict />;
    case 'profiles':
      return <ProfilesDict />;
    case 'method':
      return <MethodForm />;
    case 'ratios':
      return <RatiosDict />;
    case 'tags':
      return <TagsDict />;
    case 'currencies':
      return <CurrenciesDict />;
    case 'vat-rates':
      return <VatDict />;
    case 'loss-reasons':
      return <ReasonsDict />;
  }
}

export function DictionariesPage({ kind }: { kind: DictKey }) {
  const { t } = useTranslation();
  return (
    <AdminLayout active="dictionaries" title={t('admin.menu.dictionaries')} subtitle={t(`admin.dict.sub.${kind}`)}>
      <nav className="adm-tabs" aria-label={t('admin.dict.tabs')}>
        {DICTS.map((k) => (
          <Link
            key={k}
            to={dictPath(k)}
            className={k === kind ? 'on' : undefined}
            {...(k === kind ? { 'aria-current': 'page' as const } : {})}
          >
            {t(`admin.dict.tab.${k}`)}
          </Link>
        ))}
      </nav>
      <div key={kind}>{screen(kind)}</div>
    </AdminLayout>
  );
}
