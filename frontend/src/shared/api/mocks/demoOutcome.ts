/**
 * FE-016 · «Результат пресейла» в демо (BR-PRJ-05): справочник причин проигрыша и результат
 * каждого проекта. По умолчанию «не известен»; изменения живут до перезагрузки страницы.
 */
import type { DemoProject } from "./data";
import { find } from "./demoDictionaries";
import { uuidFrom } from "./ids";

export type DemoOutcome = {
  outcome: "unknown" | "won" | "lost" | "cancelled";
  loss_reason_id: string | null;
  loss_reason_text: string | null;
  contract_amount: string | null;
};

export const LOSS_REASONS = [
  { key: "price", name: "Цена", is_other: false, is_active: true },
  { key: "terms", name: "Сроки", is_other: false, is_active: true },
  { key: "rival", name: "Выбран конкурент", is_other: false, is_active: true },
  {
    key: "refusal",
    name: "Отказ от проекта",
    is_other: false,
    is_active: true,
  },
  { key: "budget", name: "Нет бюджета", is_other: false, is_active: false },
  { key: "other", name: "Другое", is_other: true, is_active: true },
].map(({ key, ...rest }) => ({ id: uuidFrom("loss-reason", key), ...rest }));

const EMPTY: DemoOutcome = {
  outcome: "unknown",
  loss_reason_id: null,
  loss_reason_text: null,
  contract_amount: null,
};

const outcomes = new Map<string, DemoOutcome>();

export function resetDemoOutcome(): void {
  outcomes.clear();
}

/** Ответ GET: деньги — отдельным блоком (его снимает stripMoney без права на деньги). */
export function outcomeOf(project: DemoProject) {
  const o = outcomes.get(project.id) ?? EMPTY;
  return {
    outcome: o.outcome,
    loss_reason_id: o.loss_reason_id,
    loss_reason_text: o.loss_reason_text,
    money: { contract_amount: o.contract_amount },
  };
}

type Put = {
  outcome?: string;
  loss_reason_id?: string | null;
  loss_reason_text?: string | null;
  contract_amount?: string | null;
};

/**
 * PUT: проверки сервера (CORE-029). Причина обязательна при «проигран», текст — при «Другое»;
 * сумма — только при «выигран» и только с `money.read` (CR-015). Возвращает код ошибки или результат.
 */
export function putOutcome(
  project: DemoProject,
  raw: unknown,
  moneyWrite: boolean,
):
  | { error: "VALIDATION_FAILED" | "FORBIDDEN"; field: string }
  | ReturnType<typeof outcomeOf> {
  // проверка моков по контракту шлёт пустое тело `{}` — отвечаем текущим результатом
  const body = (raw ?? {}) as Put;
  if (body.outcome === undefined) return outcomeOf(project);
  const outcome = body.outcome as DemoOutcome["outcome"];
  if (!["unknown", "won", "lost", "cancelled"].includes(outcome))
    return { error: "VALIDATION_FAILED", field: "outcome" };
  const prev = outcomes.get(project.id) ?? EMPTY;
  const hasAmount = body.contract_amount !== undefined;
  if (hasAmount && !moneyWrite)
    return { error: "FORBIDDEN", field: "contract_amount" };
  let reason: string | null = null;
  let text: string | null = null;
  if (outcome === "lost") {
    const found = find("loss_reasons", String(body.loss_reason_id));
    if (!found) return { error: "VALIDATION_FAILED", field: "loss_reason_id" };
    reason = String(found.id);
    if (found.is_other) {
      text = (body.loss_reason_text ?? "").trim();
      if (!text || text.length > 500)
        return { error: "VALIDATION_FAILED", field: "loss_reason_text" };
    }
  }
  const amount =
    outcome !== "won"
      ? null
      : hasAmount
        ? (body.contract_amount ?? null)
        : prev.contract_amount;
  if (amount !== null && !/^\d+$/.test(amount))
    return { error: "VALIDATION_FAILED", field: "contract_amount" };
  outcomes.set(project.id, {
    outcome,
    loss_reason_id: reason,
    loss_reason_text: text,
    contract_amount: amount,
  });
  return outcomeOf(project);
}
