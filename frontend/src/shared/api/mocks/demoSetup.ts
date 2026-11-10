/**
 * FE-064 · мастер первичной настройки в демо (SPEC 7.1, FR-SA-02): пять шагов, у каждого —
 * свои ключи settings.schema.json. Шаг сохраняется с `complete: true` только по порядку;
 * в режиме AD шаг 3 требует обеих проверок (FR-AUTH-AD-03), шаг 5 — заведённого администратора.
 * По умолчанию демо-мастер уже пройден; `?demo=setup` в адресе (или `restartDemoSetup()` в тестах)
 * начинает его заново, как после `estimator create-superadmin`.
 */
import {
  admins,
  firstInstall,
  saveSettings,
  settingValues,
} from "./demoSystem";
import { afterSave, checksMissing } from "./demoAuth";

export const SETUP_STEPS = [
  "app",
  "smtp",
  "auth",
  "security",
  "first_admin",
] as const;
type Step = (typeof SETUP_STEPS)[number];

const KEYS = new Map<Step, readonly string[]>([
  ["app", ["app.base_url", "app.timezone"]],
  ["smtp", ["smtp.server", "smtp.password"]],
  [
    "auth",
    [
      "auth.mode",
      "auth.ad.connection",
      "auth.ad.bind_password",
      "auth.ad.access_groups",
      "auth.ad.role_mapping",
      "security.password_policy",
    ],
  ],
  [
    "security",
    [
      "security.session",
      "security.lockout",
      "security.mfa_policy",
      "security.admin_networks",
      "security.alert_email",
    ],
  ],
  ["first_admin", []],
]);

const done = new Set<Step>(SETUP_STEPS);

export function resetDemoSetup() {
  for (const s of SETUP_STEPS) done.add(s);
}

export function restartDemoSetup() {
  done.clear();
  firstInstall();
}

export const setupCompleted = () => done.size === SETUP_STEPS.length;

const stepOf = (name: string): Step | null =>
  SETUP_STEPS.find((s) => s === name) ?? null;

export function getStep(name: string) {
  const step = stepOf(name);
  if (!step) return null;
  return {
    step,
    done: done.has(step),
    values: settingValues(KEYS.get(step) ?? []),
  };
}

export type SetupError =
  | "SETUP_ALREADY_COMPLETED"
  | "AD_CHECKS_REQUIRED"
  | "VALIDATION_FAILED";

export function postStep(
  name: string,
  body: unknown,
):
  | { error: SetupError; missing?: string[] }
  | ReturnType<typeof getStep>
  | null {
  const step = stepOf(name);
  if (!step) return null;
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const raw = b.get("values");
  const values = new Map(
    Object.entries(raw && typeof raw === "object" ? raw : {}),
  );
  const complete = b.get("complete") === true;
  if (!complete && values.size === 0) return getStep(step);
  if (setupCompleted()) return { error: "SETUP_ALREADY_COMPLETED" };
  const index = SETUP_STEPS.indexOf(step);
  if (complete && SETUP_STEPS.slice(0, index).some((s) => !done.has(s)))
    return { error: "VALIDATION_FAILED" };
  if (step === "auth" && complete && values.get("auth.mode") === "ad") {
    const missing = checksMissing();
    if (missing.length) return { error: "AD_CHECKS_REQUIRED", missing };
  }
  if (
    step === "first_admin" &&
    complete &&
    !admins().some((a) => a.roles.includes("admin") && a.status !== "blocked")
  )
    return { error: "VALIDATION_FAILED" };
  const allowed = new Set(KEYS.get(step) ?? []);
  const bySection = new Map<string, Record<string, unknown>>();
  for (const [key, value] of values) {
    if (!allowed.has(key)) continue;
    const section = key.split(".")[0] ?? "";
    bySection.set(section, { ...bySection.get(section), [key]: value });
  }
  for (const [section, part] of bySection) saveSettings(section, part);
  if (step === "auth" && values.get("auth.mode") === "ad") afterSave();
  if (complete) done.add(step);
  return getStep(step);
}
