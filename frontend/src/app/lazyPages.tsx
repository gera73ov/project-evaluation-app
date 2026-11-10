/**
 * FE-081 · экраны вне рабочего экрана загружаются отдельными частями сборки по первому переходу
 * (NFR-PERF-02): админки, система, аудит, статистика, сравнение, портфель, мастер настройки,
 * документы, итоги и корзина. Вход, «Мои оценки», профиль, создание проекта, рабочий экран и
 * настройки проекта остаются в основной части. Пока часть грузится, `AppRoutes` показывает загрузку.
 */
import { lazy } from 'react';

export const DocumentsPage = lazy(() =>
  import('../features/documents/DocumentsPage').then((m) => ({ default: m.DocumentsPage })),
);
export const ReadinessPage = lazy(() =>
  import('../features/stats/grid/ReadinessPage').then((m) => ({ default: m.ReadinessPage })),
);
export const CandidatesPage = lazy(() =>
  import('../features/stats/details/DetailsPages').then((m) => ({ default: m.CandidatesPage })),
);
export const SharesPage = lazy(() =>
  import('../features/stats/details/DetailsPages').then((m) => ({ default: m.SharesPage })),
);
export const TagsPage = lazy(() =>
  import('../features/stats/details/DetailsPages').then((m) => ({ default: m.TagsPage })),
);
export const VolumesPage = lazy(() =>
  import('../features/stats/details/DetailsPages').then((m) => ({ default: m.VolumesPage })),
);
export const SnapshotsPage = lazy(() =>
  import('../features/stats/details/SnapshotsPage').then((m) => ({ default: m.SnapshotsPage })),
);
export const ComparePage = lazy(() =>
  import('../features/compare/ComparePage').then((m) => ({ default: m.ComparePage })),
);
export const DiscussionsPage = lazy(() =>
  import('../features/stats/questions/DiscussionsPage').then((m) => ({ default: m.DiscussionsPage })),
);
export const QuestionsPage = lazy(() =>
  import('../features/stats/questions/QuestionsPage').then((m) => ({ default: m.QuestionsPage })),
);
export const TotalsPage = lazy(() =>
  import('../features/stats/totals/TotalsPage').then((m) => ({ default: m.TotalsPage })),
);
export const PortfolioRoute = lazy(() =>
  import('../features/portfolio/PortfolioRoute').then((m) => ({ default: m.PortfolioRoute })),
);
export const AuditPage = lazy(() => import('../features/audit/AuditPage').then((m) => ({ default: m.AuditPage })));
export const CalendarPage = lazy(() =>
  import('../features/admin/calendar/CalendarPage').then((m) => ({ default: m.CalendarPage })),
);
export const DictionariesPage = lazy(() =>
  import('../features/admin/dictionaries/DictionariesPage').then((m) => ({ default: m.DictionariesPage })),
);
export const ProposedTypesPage = lazy(() =>
  import('../features/admin/proposed-types/ProposedTypesPage').then((m) => ({ default: m.ProposedTypesPage })),
);
export const AdminRegistryPage = lazy(() =>
  import('../features/admin/registry/RegistryPage').then((m) => ({ default: m.RegistryPage })),
);
export const UsersPage = lazy(() =>
  import('../features/admin/users/UsersPage').then((m) => ({ default: m.UsersPage })),
);
export const AccountsPage = lazy(() =>
  import('../features/system/admins/AccountsPage').then((m) => ({ default: m.AccountsPage })),
);
export const AnonymizePage = lazy(() =>
  import('../features/system/admins/AnonymizeRegistryPages').then((m) => ({ default: m.AnonymizePage })),
);
export const RegistryPage = lazy(() =>
  import('../features/system/admins/AnonymizeRegistryPages').then((m) => ({ default: m.RegistryPage })),
);
export const AuthPage = lazy(() => import('../features/system/auth/AuthPage').then((m) => ({ default: m.AuthPage })));
export const HealthPage = lazy(() =>
  import('../features/system/health/HealthPage').then((m) => ({ default: m.HealthPage })),
);
export const RetentionPage = lazy(() =>
  import('../features/system/settings/MailRetentionPages').then((m) => ({ default: m.RetentionPage })),
);
export const SmtpPage = lazy(() =>
  import('../features/system/settings/MailRetentionPages').then((m) => ({ default: m.SmtpPage })),
);
export const SecurityPage = lazy(() =>
  import('../features/system/settings/SecurityPage').then((m) => ({ default: m.SecurityPage })),
);
export const SystemRoute = lazy(() =>
  import('../features/system/SystemRoute').then((m) => ({ default: m.SystemRoute })),
);
export const SetupWizardPage = lazy(() =>
  import('../features/setup-wizard/SetupWizardPage').then((m) => ({ default: m.SetupWizardPage })),
);
export const OutcomePage = lazy(() =>
  import('../features/settings/outcome/OutcomePage').then((m) => ({ default: m.OutcomePage })),
);
export const TrashPage = lazy(() => import('../features/trash/TrashPage').then((m) => ({ default: m.TrashPage })));
