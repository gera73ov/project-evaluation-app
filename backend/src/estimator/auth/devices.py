"""AUTH-009 · вход с нового устройства (SEC-AUTH-06, FR-NOTIF-02, Q-12, 14.2 ``known_devices``).

Устройство — семейство браузера и подсеть (/24 для IPv4, /64 для IPv6). Устройство новое, если
с него не было входа последние :data:`FRESH_DAYS` дней (или не было никогда). Каждый успешный вход
обновляет ``known_devices.last_seen_at``. О новом устройстве уходит служебное письмо
``new_device_login`` (не отключается) — только тем, кто видит деньги: суперадминистраторам,
администраторам, руководителям пресейла, модераторам и пресейлу (по системной роли или по роли
хотя бы в одном проекте). Экспертам письмо не отправляется.

Письмо ставится после commit и только при настроенном SMTP. В письме — браузер, подсеть, время
входа в часовом поясе пользователя и ссылка на профиль (там список сеансов).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import re
from collections.abc import Collection
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.config import get_settings
from estimator.db.enums import ProjectRole, SystemRole
from estimator.db.models.projects import ProjectMember
from estimator.db.models.users import KnownDevice, User
from estimator.db.session import after_commit
from estimator.logging import get_logger
from estimator.notifications.mail.recipients import Recipient

log = get_logger(__name__)

KIND = "new_device_login"
FRESH_DAYS = 90
#: Системные роли, которые видят деньги (Q-12).
MONEY_ROLES = frozenset({SystemRole.SUPERADMIN, SystemRole.ADMIN, SystemRole.PRESALE_HEAD,
                         SystemRole.MODERATOR, SystemRole.PRESALE})  # fmt: skip
#: Роли в проекте, которые видят деньги.
MONEY_PROJECT_ROLES = (ProjectRole.MODERATOR, ProjectRole.PRESALE)

#: Порядок важен: Edge, Opera и Яндекс.Браузер тоже пишут «Chrome», Chrome пишет «Safari».
_FAMILIES = (
    ("Edge", re.compile(r"\bEdg(e|A|iOS)?/")),
    ("Яндекс.Браузер", re.compile(r"\bYaBrowser/")),
    ("Opera", re.compile(r"\b(OPR|Opera)/")),
    ("Firefox", re.compile(r"\b(Firefox|FxiOS)/")),
    ("Chrome", re.compile(r"\b(Chrome|CriOS|Chromium)/")),
    ("Safari", re.compile(r"\bSafari/")),
)
OTHER = "Другой"


def browser_family(user_agent: str | None) -> str:
    """Семейство браузера по User-Agent (без версии и ОС)."""
    for name, pattern in _FAMILIES:
        if user_agent and pattern.search(user_agent):
            return name
    return OTHER


def subnet_of(ip: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Подсеть адреса: /24 для IPv4 (в том числе IPv4-mapped IPv6), /64 для IPv6."""
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    prefix = 24 if address.version == 4 else 64
    return ipaddress.ip_network(f"{address}/{prefix}", strict=False)


async def sees_money(db: AsyncSession, user_id: object, roles: Collection[SystemRole]) -> bool:
    """Видит ли пользователь деньги: по системной роли или по роли хотя бы в одном проекте."""
    if MONEY_ROLES.intersection(roles):
        return True
    in_project = exists().where(
        ProjectMember.user_id == user_id, ProjectMember.role.in_(MONEY_PROJECT_ROLES)
    )
    return bool(await db.scalar(select(in_project)))


async def remember(
    db: AsyncSession, user_id: object, *, ip: str, user_agent: str | None, now: dt.datetime
) -> tuple[str, str, bool]:
    """Отметить вход с устройства; вернуть (браузер, подсеть, новое ли устройство)."""
    family = browser_family(user_agent)
    net = subnet_of(ip)
    last = await db.scalar(
        select(KnownDevice.last_seen_at).where(
            KnownDevice.user_id == user_id, KnownDevice.ua_family == family,
            KnownDevice.subnet == net,
        )
    )  # fmt: skip
    is_new = last is None or last < now - dt.timedelta(days=FRESH_DAYS)
    stmt = insert(KnownDevice).values(user_id=user_id, ua_family=family, subnet=net,
                                      last_seen_at=now)  # fmt: skip
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["user_id", "ua_family", "subnet"], set_={"last_seen_at": now},
    ))  # fmt: skip
    return family, str(net), is_new


def _local_time(moment: dt.datetime, timezone: str | None) -> str:
    try:
        zone = ZoneInfo(timezone or get_settings().app_timezone)
    except (KeyError, ValueError):
        zone = ZoneInfo(get_settings().app_timezone)
    return moment.astimezone(zone).strftime("%d.%m.%Y %H:%M")


async def on_login(
    db: AsyncSession, user: User, roles: Collection[SystemRole], *, ip: str,
    user_agent: str | None, now: dt.datetime | None = None,
) -> bool:  # fmt: skip
    """Учесть успешный вход; вернуть, было ли устройство новым (для ``details.new_device``)."""
    now = now or dt.datetime.now(dt.UTC)
    try:
        family, net, is_new = await remember(db, user.id, ip=ip, user_agent=user_agent, now=now)
    except ValueError:  # адрес не разобрать — устройство не учитываем
        return False
    if not is_new or not user.email or not await sees_money(db, user.id, roles):
        return is_new
    from estimator.auth.passwords import base_url, smtp_configured

    if not await smtp_configured(db):
        log.info("new_device_mail_skipped", reason="smtp_not_configured")
        return is_new
    fields = {"browser": family, "subnet": net, "time": _local_time(now, user.timezone),
              "link": f"{await base_url(db)}/profile"}  # fmt: skip
    recipient = Recipient(user.email, str(user.status.value))

    async def send() -> None:
        from estimator.notifications.tasks import enqueue_email

        try:
            enqueue_email(KIND, [recipient], fields)
        except Exception as exc:  # noqa: BLE001 — сбой очереди не мешает входу
            log.warning("new_device_mail_enqueue_failed", error=type(exc).__name__)

    after_commit(db, send)
    return is_new
