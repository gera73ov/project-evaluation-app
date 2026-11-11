"""Провайдер ``ad``: вход через Active Directory по LDAP (AUTH-013; 7.2, FR-AUTH-AD-01, -02, -05,
-09, -12, -13, Q-19, R-04).

Подключение
    Контроллеры перебираются по порядку (первый ответивший). Только LDAPS (636) или StartTLS
    (389); сертификат контроллера проверяется всегда по CA компании из настроек (PEM) — отключить
    проверку нельзя. Таймаут — ``timeout_seconds`` (по умолчанию 5 с). Поиск идёт от сервисной
    учётной записи (``bind_dn`` и зашифрованный пароль).

Алгоритм входа (FR-AUTH-AD-13)
    1. пустые логин или пароль — отказ без обращения к AD (``providers.base.authenticate``);
    2. поиск сервисной учёткой по ``user_filter`` с экранированным логином
       (``escape_filter_chars``);
       найдено не ровно одна запись — отказ (``user_not_found`` / ``ad_ambiguous``);
    3. bind найденной записью и введённым паролем — ``wrong_password``; ответ AD «data 533»
       (пароль верный, учётка отключена) считается верным паролем, отказ даёт шаг 4;
    4. ``userAccountControl`` с ACCOUNTDISABLE — ``ad_account_disabled``;
    5. членство в группах доступа с учётом вложенности (``LDAP_MATCHING_RULE_IN_CHAIN``) —
       ``ad_not_in_group``;
    6. учётка в приложении по ``objectGUID`` (создаётся при первом входе, AUTH-014), роли по
       группам — если сопоставление включено.

    Любой отказ пользователю — один и тот же ответ (``LOGIN_FAILED``), причина — в аудите. Если
    запись не найдена, выполняется пустой bind с введённым паролем, чтобы время ответа было
    сопоставимо. Все контроллеры недоступны — ``ad_unavailable`` (вход отвечает 503
    «Сервис аутентификации временно недоступен»). Суперадминистраторы в AD не идут никогда
    (``provider_for_login``).

Каталог (:class:`Directory`) отделён от провайдера: настоящий — :class:`Ldap3Directory`, в тестах —
имитация AD (``set_directory_factory``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers.base import (
    AuthProvider,
    AuthResult,
    Credentials,
    Identity,
    register_provider,
)
from estimator.db.models.users import User
from estimator.logging import get_logger

log = get_logger(__name__)

AD = "ad"
CONNECTION = "auth.ad.connection"
BIND_PASSWORD = "auth.ad.bind_password"  # noqa: S105  # nosec B105 — ключ настройки
ACCESS_GROUPS = "auth.ad.access_groups"
ROLE_MAPPING = "auth.ad.role_mapping"
KEYS = (CONNECTION, BIND_PASSWORD, ACCESS_GROUPS, ROLE_MAPPING)
#: ``userAccountControl``: учётная запись отключена.
ACCOUNTDISABLE = 0x0002
#: Членство с учётом вложенных групп (LDAP_MATCHING_RULE_IN_CHAIN).
IN_CHAIN = "1.2.840.113556.1.4.1941"
#: DN для пустого bind, когда запись не найдена (выравнивание времени ответа).
NO_SUCH_DN = "CN=estimator-no-such-user"
DEFAULT_FILTER = "(&(objectClass=user)(sAMAccountName={login}))"


class AdUnavailableError(Exception):
    """Ни один контроллер AD не ответил (или не прошёл проверку TLS)."""


class AdConfigError(ValueError):
    """Параметры AD не заданы или неполны."""


@dataclass(frozen=True)
class Controller:
    host: str
    port: int


@dataclass(frozen=True)
class AdConfig:
    """Параметры AD из ``system_settings`` (пароль сервисной учётки — расшифрованный)."""

    controllers: tuple[Controller, ...]
    protocol: str
    ca_cert_pem: str | None
    base_dn: str
    user_filter: str
    login_attribute: str
    attr_full_name: str
    attr_email: str
    attr_department: str
    bind_dn: str
    bind_password: str = field(repr=False)
    timeout_seconds: int = 5
    access_groups: tuple[str, ...] = ()
    mapping_enabled: bool = False
    #: (DN группы, роль) — только moderator и presale.
    mappings: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_values(cls, values: Mapping[str, Any], bind_password: str | None) -> AdConfig:
        conn = values.get(CONNECTION) or {}
        if not conn.get("controllers") or not conn.get("base_dn") or not conn.get("bind_dn"):
            raise AdConfigError("не заданы контроллеры, Base DN или сервисная учётная запись")
        if not bind_password:
            raise AdConfigError("не задан пароль сервисной учётной записи")
        if conn.get("protocol") not in ("ldaps", "starttls"):
            raise AdConfigError("допустимы только LDAPS и StartTLS")
        mapping = values.get(ROLE_MAPPING) or {}
        return cls(
            controllers=tuple(Controller(str(c["host"]), int(c["port"]))
                              for c in conn["controllers"]),
            protocol=str(conn["protocol"]),
            ca_cert_pem=conn.get("ca_cert_pem") or None,
            base_dn=str(conn["base_dn"]),
            user_filter=str(conn.get("user_filter") or DEFAULT_FILTER),
            login_attribute=str(conn.get("login_attribute") or "sAMAccountName"),
            attr_full_name=str(conn.get("attr_full_name") or "displayName"),
            attr_email=str(conn.get("attr_email") or "mail"),
            attr_department=str(conn.get("attr_department") or "department"),
            bind_dn=str(conn["bind_dn"]),
            bind_password=bind_password,
            timeout_seconds=int(conn.get("timeout_seconds") or 5),
            access_groups=tuple(values.get(ACCESS_GROUPS) or ()),
            mapping_enabled=bool(mapping.get("enabled")),
            mappings=tuple((str(m["group_dn"]), str(m["role"]))
                           for m in mapping.get("mappings") or ()),
        )  # fmt: skip

    def groups_to_check(self) -> tuple[str, ...]:
        """Группы, членство в которых нужно знать: доступа и сопоставления."""
        seen = dict.fromkeys(self.access_groups)
        seen.update(dict.fromkeys(dn for dn, _ in self.mappings))
        return tuple(seen)


async def stored_values(db: AsyncSession) -> tuple[dict[str, Any], str | None]:
    """Сохранённые ключи AD и расшифрованный пароль сервисной учётки."""
    from estimator.admin.settings import schema
    from estimator.auth.policy import read_settings
    from estimator.security.crypto import get_cipher
    from estimator.security.crypto.aead import is_encrypted_setting

    raw = await read_settings(db, *KEYS)
    values = {key: raw.get(key, schema.default(key)) for key in KEYS if key != BIND_PASSWORD}
    secret = raw.get(BIND_PASSWORD)
    password = (get_cipher().decrypt_setting(BIND_PASSWORD, secret)
                if is_encrypted_setting(secret) else None)  # fmt: skip
    return values, password


async def load_config(db: AsyncSession) -> AdConfig:
    values, password = await stored_values(db)
    return AdConfig.from_values(values, password)


def fingerprint(values: Mapping[str, Any], password: str | None) -> str:
    """Отпечаток параметров подключения и групп доступа для ``auth.ad.verification``.

    Пароль сервисной учётки входит только как HMAC на ключе шифрования приложения: сам пароль
    и его простой хэш не хранятся, но после смены пароля проверки нужны заново.
    """
    import hmac

    from estimator.config import get_settings

    secret = get_settings().encryption_key
    key = (secret.get_secret_value() if secret else "").encode()
    mac = hmac.new(key, (password or "").encode(), hashlib.sha256).hexdigest()
    body = {"connection": values.get(CONNECTION), "access_groups": values.get(ACCESS_GROUPS),
            "password": mac}  # fmt: skip
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class Entry:
    """Запись пользователя AD."""

    dn: str
    object_guid: uuid.UUID
    login: str
    full_name: str
    email: str | None = None
    department: str | None = None
    disabled: bool = False


class Directory(Protocol):
    """Каталог AD. Все методы бросают :class:`AdUnavailableError`, если AD недоступен."""

    async def ping(self) -> None:
        """Bind сервисной учёткой и поиск в Base DN (проверка подключения)."""

    async def find_user(self, login: str) -> list[Entry]:
        """Записи по ``user_filter`` с экранированным логином."""

    async def check_password(self, dn: str, password: str) -> bool:
        """Bind записью ``dn`` с паролем; False — неверный пароль."""

    async def groups_of(self, dn: str, groups: Sequence[str]) -> set[str]:
        """Какие из ``groups`` содержат ``dn`` (с учётом вложенности)."""

    async def by_guid(self, guid: uuid.UUID) -> Entry | None:
        """Запись по ``objectGUID``; None — записи нет."""

    async def search(self, text: str, limit: int) -> list[Entry]:
        """Поиск людей по фрагменту ФИО, логина или email."""


DirectoryFactory = Callable[[AdConfig], Directory]


def _default_factory(config: AdConfig) -> Directory:
    return Ldap3Directory(config)


_factory: DirectoryFactory = _default_factory


def set_directory_factory(factory: DirectoryFactory | None) -> None:
    """Подменить каталог (имитация AD в тестах); None — вернуть настоящий."""
    global _factory
    _factory = factory or _default_factory


def directory(config: AdConfig) -> Directory:
    return _factory(config)


# --- настоящий каталог: ldap3 -------------------------------------------------------------------


class Ldap3Directory:
    """Каталог через ``ldap3``; синхронные вызовы — в пуле потоков."""

    def __init__(self, config: AdConfig) -> None:
        self.config = config

    # подключение

    def _tls(self) -> Any:
        from ldap3 import Tls

        return Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLS_CLIENT,
                   ca_certs_data=self.config.ca_cert_pem)  # fmt: skip

    def _connect(self, user: str | None, password: str | None) -> Any:
        """Открыть соединение с первым ответившим контроллером и выполнить bind.

        Возвращает соединение (``bound`` — успешен ли bind). Ни один контроллер не ответил —
        :class:`AdUnavailableError`.
        """
        from ldap3 import NONE, Connection, Server
        from ldap3.core.exceptions import LDAPException

        cfg = self.config
        for controller in cfg.controllers:
            server = Server(controller.host, port=controller.port,
                            use_ssl=cfg.protocol == "ldaps", tls=self._tls(), get_info=NONE,
                            connect_timeout=cfg.timeout_seconds)  # fmt: skip
            conn = Connection(server, user=user, password=password,
                              receive_timeout=cfg.timeout_seconds, raise_exceptions=False,
                              read_only=True)  # fmt: skip
            try:
                conn.open()
                if cfg.protocol == "starttls" and not conn.start_tls():
                    raise AdUnavailableError("StartTLS не выполнен")
                conn.bind()
            except (LDAPException, AdUnavailableError, OSError) as exc:
                log.warning("ad_controller_unavailable", host=controller.host,
                            error=type(exc).__name__)  # fmt: skip
                _close_quietly(conn)
                continue
            return conn
        raise AdUnavailableError("ни один контроллер AD не ответил")

    def _service(self) -> Any:
        conn = self._connect(self.config.bind_dn, self.config.bind_password)
        if not conn.bound:
            conn.unbind()
            raise AdUnavailableError("сервисная учётная запись не прошла bind")
        return conn

    def _attributes(self) -> list[str]:
        cfg = self.config
        return ["objectGUID", "userAccountControl", cfg.login_attribute, cfg.attr_full_name,
                cfg.attr_email, cfg.attr_department]  # fmt: skip

    def _entry(self, raw: Mapping[str, Any]) -> Entry | None:
        cfg = self.config
        attrs = raw.get("attributes") or {}
        raw_attrs = raw.get("raw_attributes") or {}
        guid_raw = (raw_attrs.get("objectGUID") or [None])[0]
        if not guid_raw:
            return None
        guid = (uuid.UUID(bytes_le=bytes(guid_raw)) if len(guid_raw) == 16
                else uuid.UUID(str(_first(guid_raw))))  # fmt: skip
        uac = _first(attrs.get("userAccountControl"))
        login = _first(attrs.get(cfg.login_attribute))
        if not login:
            return None
        return Entry(
            dn=str(raw.get("dn")), object_guid=guid, login=str(login),
            full_name=str(_first(attrs.get(cfg.attr_full_name)) or login),
            email=_text(attrs.get(cfg.attr_email)),
            department=_text(attrs.get(cfg.attr_department)),
            disabled=bool(int(uac or 0) & ACCOUNTDISABLE),
        )  # fmt: skip

    def _search(self, conn: Any, base: str, flt: str, *, scope: str = "SUBTREE",
                limit: int = 0) -> list[Entry]:  # fmt: skip
        conn.search(base, flt, search_scope=scope, attributes=self._attributes(),
                    size_limit=limit)  # fmt: skip
        out = [
            self._entry(item)
            for item in conn.response or []
            if item.get("type") == "searchResEntry"
        ]
        return [e for e in out if e is not None]

    # операции (синхронные)

    def _ping(self) -> None:
        conn = self._service()
        try:
            conn.search(self.config.base_dn, "(objectClass=*)", search_scope="BASE",
                        attributes=["objectClass"])  # fmt: skip
            if conn.result.get("result") not in (0, None):
                raise AdUnavailableError(f"поиск в Base DN: {conn.result.get('description')}")
        finally:
            conn.unbind()

    def _find_user(self, login: str) -> list[Entry]:
        from ldap3.utils.conv import escape_filter_chars

        flt = self.config.user_filter.replace("{login}", escape_filter_chars(login))
        conn = self._service()
        try:
            return self._search(conn, self.config.base_dn, flt, limit=2)
        finally:
            conn.unbind()

    def _check_password(self, dn: str, password: str) -> bool:
        conn = self._connect(dn, password)
        try:
            return bool(conn.bound) or password_ok_but_disabled(conn.result)
        finally:
            conn.unbind()

    def _groups_of(self, dn: str, groups: Sequence[str]) -> set[str]:
        from ldap3.utils.conv import escape_filter_chars

        found: set[str] = set()
        if not groups:
            return found
        conn = self._service()
        try:
            for group in groups:
                flt = f"(memberOf:{IN_CHAIN}:={escape_filter_chars(group)})"
                conn.search(dn, flt, search_scope="BASE", attributes=["objectClass"])
                if any(i.get("type") == "searchResEntry" for i in conn.response or []):
                    found.add(group)
        finally:
            conn.unbind()
        return found

    def _by_guid(self, guid: uuid.UUID) -> Entry | None:
        from ldap3.utils.conv import escape_bytes

        conn = self._service()
        try:
            flt = f"(objectGUID={escape_bytes(guid.bytes_le)})"
            found = self._search(conn, self.config.base_dn, flt, limit=1)
        finally:
            conn.unbind()
        return found[0] if found else None

    def _search_people(self, text: str, limit: int) -> list[Entry]:
        from ldap3.utils.conv import escape_filter_chars

        cfg = self.config
        part = escape_filter_chars(text)
        attrs = dict.fromkeys(["sAMAccountName", cfg.login_attribute, cfg.attr_full_name,
                               cfg.attr_email])  # fmt: skip
        any_of = "".join(f"({a}=*{part}*)" for a in attrs)
        flt = f"(&(objectCategory=person)(objectClass=user)(|{any_of}))"
        conn = self._service()
        try:
            return self._search(conn, cfg.base_dn, flt, limit=limit)
        finally:
            conn.unbind()

    # асинхронный интерфейс

    async def ping(self) -> None:
        await asyncio.to_thread(self._ping)

    async def find_user(self, login: str) -> list[Entry]:
        return await asyncio.to_thread(self._find_user, login)

    async def check_password(self, dn: str, password: str) -> bool:
        return await asyncio.to_thread(self._check_password, dn, password)

    async def groups_of(self, dn: str, groups: Sequence[str]) -> set[str]:
        return await asyncio.to_thread(self._groups_of, dn, groups)

    async def by_guid(self, guid: uuid.UUID) -> Entry | None:
        return await asyncio.to_thread(self._by_guid, guid)

    async def search(self, text: str, limit: int) -> list[Entry]:
        return await asyncio.to_thread(self._search_people, text, limit)


#: Подкод ответа AD на bind (49 invalidCredentials, «data 533»): пароль верный, но учётная запись
#: отключена. AD не пускает отключённую учётку даже с верным паролем, поэтому без этого признака
#: причина в аудите была бы ``wrong_password`` вместо ``ad_account_disabled`` (G-04; найдено на
#: Samba AD, QA-012). Другие подкоды (истёк пароль или срок учётки, блокировка) — отказ как есть.
DISABLED_SUBCODE = "data 533"


def password_ok_but_disabled(result: Mapping[str, Any] | None) -> bool:
    """Bind отклонён только потому, что учётка отключена (дальше её отклонит шаг 4 алгоритма)."""
    result = result or {}
    return result.get("result") == 49 and DISABLED_SUBCODE in str(result.get("message") or "")


def _close_quietly(conn: Any) -> None:
    """Закрыть соединение, которое не удалось открыть. После сбоя StartTLS (чужой сертификат)
    ldap3 уже закрыл сокет, и ``unbind`` падает с ``LDAPSocketSendError`` — вход отвечал 500
    вместо 503 (найдено на Samba AD, QA-012)."""
    from ldap3.core.exceptions import LDAPException

    try:
        conn.unbind()
    except (LDAPException, OSError):
        log.debug("ad_unbind_failed")


def _first(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return value[0] if value else None
    return value


def _text(value: Any) -> str | None:
    first = _first(value)
    return str(first).strip() or None if first not in (None, "") else None


# --- провайдер ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """Итог проверки записи AD (для входа и «Проверить вход»)."""

    entry: Entry | None
    reason: str | None
    groups: frozenset[str] = frozenset()

    @property
    def in_access_group(self) -> bool:
        return self.reason != "ad_not_in_group"


async def verify(directory_: Directory, config: AdConfig, login: str, password: str) -> Verdict:
    """Шаги 2–5 алгоритма FR-AUTH-AD-13; :class:`AdUnavailableError` пробрасывается."""
    entries = await directory_.find_user(login)
    if len(entries) != 1:
        await directory_.check_password(NO_SUCH_DN, password)  # сопоставимое время ответа
        return Verdict(None, "user_not_found" if not entries else "ad_ambiguous")
    entry = entries[0]
    if not await directory_.check_password(entry.dn, password):
        return Verdict(entry, "wrong_password")
    groups = frozenset(await directory_.groups_of(entry.dn, config.groups_to_check()))
    if entry.disabled:
        return Verdict(entry, "ad_account_disabled", groups)
    if not groups.intersection(config.access_groups):
        return Verdict(entry, "ad_not_in_group", groups)
    return Verdict(entry, None, groups)


class LdapProvider(AuthProvider):
    name: ClassVar[str] = AD

    async def authenticate(self, session: AsyncSession, credentials: Credentials) -> AuthResult:
        from estimator.auth import ad_provisioning

        try:
            config = await load_config(session)
        except AdConfigError as exc:
            log.warning("ad_not_configured", error=str(exc))
            return AuthResult.failure("ad_unavailable")
        try:
            verdict = await verify(directory(config), config, credentials.login.strip(),
                                   credentials.password)  # fmt: skip
        except AdUnavailableError:
            return AuthResult.failure("ad_unavailable")
        known = None
        if verdict.entry is not None:
            known = await session.scalar(
                select(User.id).where(User.ad_object_guid == verdict.entry.object_guid)
            )
        entry = verdict.entry
        if verdict.reason is not None or entry is None:
            return AuthResult.failure(verdict.reason or "user_not_found", known)
        user, reason = await ad_provisioning.on_login(session, config, entry, verdict.groups)
        if reason is not None or user is None:
            return AuthResult.failure(reason or "user_not_found", user.id if user else known)
        return AuthResult.success(Identity(
            provider=AD, external_id=str(entry.object_guid), login=user.login,
            attributes={"full_name": user.full_name, "email": user.email}, user_id=user.id,
        ))  # fmt: skip


register_provider(AD, LdapProvider)
