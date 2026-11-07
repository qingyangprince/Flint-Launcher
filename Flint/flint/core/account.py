"""账户：微软 OAuth 设备码流程、离线账户与加密持久化。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from flint.core import events
from flint.infra import fs, http
from flint.platform import paths

logger = logging.getLogger(__name__)

MS_DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
MS_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

DEFAULT_CLIENT_ID = "00000000402b5328"
DEFAULT_SCOPE = "XboxLive.signin offline_access"

ACCOUNTS_FILE_NAME = "accounts.json"
ACCOUNT_KEY_FILE_NAME = "account.key"
STORE_SCHEMA_VERSION = 1


class AccountError(Exception):
    """账户操作失败时抛出。"""


class AccountNotFound(AccountError):
    """按 id 找不到账户。"""


class AccountExists(AccountError):
    """同名账户已存在。"""


class MicrosoftAuthError(AccountError):
    """微软/Xbox 认证链路失败。"""


class AccountType(StrEnum):
    MICROSOFT = "microsoft"
    OFFLINE = "offline"


def offline_uuid(username: str) -> str:
    """复刻 Java ``UUID.nameUUIDFromBytes("OfflinePlayer:<name>")``。"""
    if not isinstance(username, str) or not username:
        raise AccountError("offline account name must not be empty")
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode(), usedforsecurity=False).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def validate_username(username: str) -> str:
    if not isinstance(username, str):
        raise AccountError("account name must be a string")
    cleaned = username.strip()
    if not cleaned:
        raise AccountError("account name must not be empty")
    if len(cleaned) > 32:
        raise AccountError("account name must be at most 32 characters")
    if any(ch in '<>:"/\\|?*' for ch in cleaned):
        raise AccountError(f"account name contains invalid characters: {username!r}")
    return cleaned


@dataclass
class Account:
    """一个可启动游戏的账户。"""

    name: str
    type: AccountType = AccountType.OFFLINE
    uuid: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    added_at: str = ""
    skin_model: str = "classic"

    def __post_init__(self) -> None:
        self.name = validate_username(self.name)
        if isinstance(self.type, str):
            self.type = AccountType(self.type)
        if not self.uuid:
            self.uuid = offline_uuid(self.name) if self.type is AccountType.OFFLINE else ""
        if not self.added_at:
            self.added_at = _now_iso()

    @property
    def id(self) -> str:
        return self.uuid or self.name

    @property
    def is_microsoft(self) -> bool:
        return self.type is AccountType.MICROSOFT

    @property
    def expired(self) -> bool:
        return bool(self.expires_at) and self.expires_at <= time.time()

    @property
    def display_type(self) -> str:
        return "微软账户" if self.is_microsoft else "离线账户"

    def to_dict(self, cipher: TokenCipher) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "uuid": self.uuid,
            "access_token": cipher.encrypt(self.access_token),
            "refresh_token": cipher.encrypt(self.refresh_token),
            "expires_at": self.expires_at,
            "added_at": self.added_at,
            "skin_model": self.skin_model,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], cipher: TokenCipher) -> Account:
        name, account_type = data.get("name"), data.get("type", "offline")
        if not isinstance(name, str):
            raise AccountError("account record requires a 'name'")
        return cls(
            name=name,
            type=AccountType(str(account_type)),
            uuid=str(data.get("uuid", "")),
            access_token=cipher.decrypt(str(data.get("access_token", ""))),
            refresh_token=cipher.decrypt(str(data.get("refresh_token", ""))),
            expires_at=float(data.get("expires_at", 0.0) or 0.0),
            added_at=str(data.get("added_at", "")),
            skin_model=str(data.get("skin_model", "classic")),
        )


# --------------------------------------------------------------------------
# token 加密
# --------------------------------------------------------------------------
class TokenCipher(Protocol):
    def encrypt(self, value: str) -> str: ...

    def decrypt(self, value: str) -> str: ...


class _Base64Cipher:
    """无加密依赖时的退化实现：仅做编码，并在日志中明确警告。"""

    prefix = "b64:"
    _warned = False

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        if not _Base64Cipher._warned:
            logger.warning(
                "cryptography is not installed; account tokens are stored obfuscated only. "
                "Install flint[secure] to encrypt them."
            )
            _Base64Cipher._warned = True
        return self.prefix + base64.b64encode(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        if value.startswith(self.prefix):
            try:
                return base64.b64decode(value[len(self.prefix) :]).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                logger.warning("cannot decode stored account token")
                return ""
        return value


class _FernetCipher:
    """用 Fernet（AES-CBC + HMAC）加密 token，密钥文件权限 0600。"""

    prefix = "enc:"

    def __init__(self, key_path: Path) -> None:
        from cryptography.fernet import Fernet

        self._fernet = Fernet(self._load_key(key_path, Fernet))

    @staticmethod
    def _load_key(key_path: Path, fernet: Any) -> bytes:
        if key_path.is_file():
            return key_path.read_bytes().strip()
        key = fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key)
        _restrict_permissions(key_path)
        return key

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self.prefix + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        if not value.startswith(self.prefix):
            return value
        from cryptography.fernet import InvalidToken

        try:
            return self._fernet.decrypt(value[len(self.prefix) :].encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            logger.warning("cannot decrypt stored account token (key changed?)")
            return ""


def _restrict_permissions(path: Path) -> None:
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover - 某些文件系统不支持
            logger.debug("cannot restrict permissions of %s", path)


def default_cipher(key_path: Path | None = None) -> TokenCipher:
    """优先 Fernet；未安装 ``cryptography`` 时退化为编码存储。"""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return _Base64Cipher()
    try:
        return _FernetCipher(Path(key_path) if key_path else paths.data_dir() / ACCOUNT_KEY_FILE_NAME)
    except (OSError, ValueError) as exc:
        logger.warning("cannot initialise token encryption, falling back to obfuscation: %s", exc)
        return _Base64Cipher()


# --------------------------------------------------------------------------
# 微软认证
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DeviceCode:
    user_code: str
    device_code: str
    verification_uri: str
    expires_in: int
    interval: int = 5
    message: str = ""


class MicrosoftAuth:
    """设备码 OAuth → Xbox Live → XSTS → Minecraft Services。"""

    def __init__(
        self,
        client: http.HttpClient | None = None,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        scope: str = DEFAULT_SCOPE,
    ) -> None:
        self._client = client
        self.client_id = client_id
        self.scope = scope

    @property
    def client(self) -> http.HttpClient:
        if self._client is None:
            self._client = http.get_client()
        return self._client

    async def request_device_code(self) -> DeviceCode:
        data = await self._post_form(
            MS_DEVICE_CODE_URL, {"client_id": self.client_id, "scope": self.scope}
        )
        try:
            return DeviceCode(
                user_code=str(data["user_code"]),
                device_code=str(data["device_code"]),
                verification_uri=str(
                    data.get("verification_uri") or data.get("verification_url") or ""
                ),
                expires_in=int(data.get("expires_in", 900)),
                interval=max(int(data.get("interval", 5)), 0),
                message=str(data.get("message", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MicrosoftAuthError(f"malformed device code response: {exc}") from exc

    async def poll_for_token(
        self,
        device_code: DeviceCode,
        *,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> dict[str, Any]:
        """轮询 token 端点直到用户完成登录或设备码过期。"""
        waiter = sleep or asyncio.sleep
        deadline = time.monotonic() + max(device_code.expires_in, 1)
        interval = max(device_code.interval, 0)

        while time.monotonic() < deadline:
            try:
                return await self._post_form(
                    MS_TOKEN_URL,
                    {
                        "client_id": self.client_id,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": device_code.device_code,
                    },
                )
            except MicrosoftAuthError as exc:
                code = str(exc.args[0]) if exc.args else ""
                if code == "authorization_pending":
                    pass
                elif code == "slow_down":
                    interval += 5
                elif code == "expired_token":
                    raise MicrosoftAuthError("device code expired") from exc
                elif code == "authorization_declined":
                    raise MicrosoftAuthError("user declined the sign-in request") from exc
                else:
                    raise
            await waiter(interval)

        raise MicrosoftAuthError("device code expired before sign-in completed")

    async def refresh_tokens(self, refresh_token: str) -> dict[str, Any]:
        if not refresh_token:
            raise MicrosoftAuthError("account has no refresh token")
        return await self._post_form(
            MS_TOKEN_URL,
            {
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": self.scope,
            },
        )

    async def login(self, *, on_device_code: Callable[[DeviceCode], None] | None = None) -> Account:
        code = await self.request_device_code()
        if on_device_code is not None:
            on_device_code(code)
        tokens = await self.poll_for_token(code)
        return await self._account_from_tokens(tokens)

    async def refresh(self, account: Account) -> Account:
        tokens = await self.refresh_tokens(account.refresh_token)
        refreshed = await self._account_from_tokens(tokens, fallback=account)
        refreshed.name = account.name
        refreshed.added_at = account.added_at
        return refreshed

    async def _account_from_tokens(
        self, tokens: Mapping[str, Any], *, fallback: Account | None = None
    ) -> Account:
        microsoft_token = str(tokens.get("access_token", ""))
        if not microsoft_token:
            raise MicrosoftAuthError("token response has no access_token")
        refresh_token = str(tokens.get("refresh_token", "")) or (
            fallback.refresh_token if fallback else ""
        )

        xbl_token, user_hash = await self.authenticate_xbox(microsoft_token)
        xsts_token, user_hash = await self.authorize_xsts(xbl_token, user_hash)
        minecraft = await self.login_with_xbox(xsts_token, user_hash)
        minecraft_token = str(minecraft.get("access_token", ""))
        if not minecraft_token:
            raise MicrosoftAuthError("Minecraft services did not return an access token")
        expires_at = time.time() + float(minecraft.get("expires_in", 0) or 0)

        profile = await self.fetch_profile(minecraft_token)
        if profile is None:
            raise MicrosoftAuthError("该账户没有 Minecraft: Java Edition，无法用于启动游戏")

        return Account(
            name=str(profile.get("name") or (fallback.name if fallback else "")),
            type=AccountType.MICROSOFT,
            uuid=str(profile.get("id", "")),
            access_token=minecraft_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            added_at=fallback.added_at if fallback else "",
        )

    async def authenticate_xbox(self, microsoft_access_token: str) -> tuple[str, str]:
        try:
            data = await self._post_json(
                XBL_AUTH_URL,
                {
                    "Properties": {
                        "AuthMethod": "RPS",
                        "SiteName": "user.auth.xboxlive.com",
                        "RpsTicket": f"d={microsoft_access_token}",
                    },
                    "RelyingParty": "http://auth.xboxlive.com",
                    "TokenType": "JWT",
                },
            )
        except http.HttpError as exc:
            raise MicrosoftAuthError(f"Xbox Live 认证失败（HTTP {exc.status_code}）") from exc
        return _token_and_hash(data, "Xbox Live")

    async def authorize_xsts(
        self, xbl_token: str, user_hash: str | None = None
    ) -> tuple[str, str]:
        try:
            data = await self._post_json(
                XSTS_AUTH_URL,
                {
                    "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
                    "RelyingParty": "rp://api.minecraftservices.com/",
                    "TokenType": "JWT",
                },
            )
        except http.HttpError as exc:
            raise MicrosoftAuthError(_xsts_error_message(exc)) from exc
        token, resolved_hash = _token_and_hash(data, "XSTS")
        return token, user_hash or resolved_hash

    async def login_with_xbox(self, xsts_token: str, user_hash: str) -> dict[str, Any]:
        try:
            return await self._post_json(
                MC_LOGIN_URL, {"identityToken": f"XBL3.0 x={user_hash};{xsts_token}"}
            )
        except http.HttpError as exc:
            raise MicrosoftAuthError(
                f"Minecraft 服务登录失败（HTTP {exc.status_code}）"
            ) from exc

    async def fetch_profile(self, minecraft_access_token: str) -> dict[str, Any] | None:
        """获取 Minecraft 档案；没有游戏所有权时返回 ``None``。"""
        try:
            response = await self.client.request(
                "GET",
                MC_PROFILE_URL,
                headers={"Authorization": f"Bearer {minecraft_access_token}"},
            )
        except http.HttpError as exc:
            if exc.status_code == 404:
                return None
            raise MicrosoftAuthError(f"cannot read Minecraft profile: {exc}") from exc
        data = response.json()
        await response.aclose()
        return data if isinstance(data, dict) else None

    async def _post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        response = await self.client.request("POST", url, json=dict(payload), headers=request_headers)
        data = response.json()
        await response.aclose()
        if not isinstance(data, dict):
            raise MicrosoftAuthError(f"{url} did not return a JSON object")
        return data

    async def _post_form(self, url: str, form: Mapping[str, str]) -> dict[str, Any]:
        try:
            response = await self.client.request(
                "POST", url, data=dict(form), headers={"Accept": "application/json"}
            )
        except http.HttpError as exc:
            raise _oauth_error(exc) from exc
        data = response.json()
        await response.aclose()
        if not isinstance(data, dict):
            raise MicrosoftAuthError(f"{url} did not return a JSON object")
        return data


def _token_and_hash(data: Mapping[str, Any], label: str) -> tuple[str, str]:
    token = data.get("Token")
    claims = data.get("DisplayClaims")
    user_hash = ""
    if isinstance(claims, Mapping):
        xui = claims.get("xui")
        if isinstance(xui, list) and xui and isinstance(xui[0], Mapping):
            user_hash = str(xui[0].get("uhs", ""))
    if not isinstance(token, str) or not token:
        raise MicrosoftAuthError(f"{label} did not return a token")
    return token, user_hash


def _xsts_error_message(exc: http.HttpError) -> str:
    code = ""
    if exc.body:
        try:
            payload = json.loads(exc.body)
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            code = str(payload.get("XErr", ""))
    messages = {
        "2148916233": "该微软账户尚未创建 Xbox 档案，请先在 xbox.com 登录一次",
        "2148916238": "该账户属于未成年人，需要先在 Xbox 家庭中完成授权",
        "2148916227": "该微软账户已被封禁",
    }
    if code in messages:
        return messages[code]
    return f"Xbox 认证失败（HTTP {exc.status_code}{'，XErr ' + code if code else ''}）"


def _oauth_error(exc: http.HttpError) -> MicrosoftAuthError:
    code = f"HTTP {exc.status_code}"
    if exc.body:
        try:
            payload = json.loads(exc.body)
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            code = str(payload.get("error") or code)
            description = payload.get("error_description")
            if description and code != "authorization_pending":
                logger.info("Microsoft OAuth error %s: %s", code, description)
    return MicrosoftAuthError(code)


# --------------------------------------------------------------------------
# 账户管理
# --------------------------------------------------------------------------
class AccountManager:
    """账户集合、当前账户与持久化。"""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        bus: events.EventBus | None = None,
        cipher: TokenCipher | None = None,
        auth: MicrosoftAuth | None = None,
    ) -> None:
        self._path = Path(path) if path is not None else paths.data_dir() / ACCOUNTS_FILE_NAME
        self._bus = bus or events.bus
        self._cipher = cipher or default_cipher(self._path.parent / ACCOUNT_KEY_FILE_NAME)
        self._auth = auth
        self._lock = threading.RLock()
        self._accounts: list[Account] = []
        self._active_id = ""

    @property
    def path(self) -> Path:
        return self._path

    @property
    def auth(self) -> MicrosoftAuth:
        if self._auth is None:
            self._auth = MicrosoftAuth()
        return self._auth

    @property
    def accounts(self) -> list[Account]:
        with self._lock:
            return list(self._accounts)

    @property
    def active(self) -> Account | None:
        with self._lock:
            if not self._active_id:
                return None
            return next((a for a in self._accounts if a.id == self._active_id), None)

    def load(self) -> list[Account]:
        with self._lock:
            if not self._path.is_file():
                self._accounts, self._active_id = [], ""
                return []
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("cannot read account store %s: %s", self._path, exc)
                self._accounts, self._active_id = [], ""
                return []

            accounts: list[Account] = []
            if isinstance(data, dict):
                for record in data.get("accounts", []):
                    if not isinstance(record, Mapping):
                        continue
                    try:
                        accounts.append(Account.from_dict(record, self._cipher))
                    except (AccountError, ValueError) as exc:
                        logger.warning("skipping invalid account record: %s", exc)
                self._active_id = str(data.get("active", ""))
            self._accounts = accounts
            if self._active_id and not any(a.id == self._active_id for a in accounts):
                self._active_id = accounts[0].id if accounts else ""
            return list(accounts)

    def save(self) -> None:
        with self._lock:
            payload = {
                "schema": STORE_SCHEMA_VERSION,
                "active": self._active_id,
                "accounts": [account.to_dict(self._cipher) for account in self._accounts],
            }
            fs.write_atomic(self._path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            _restrict_permissions(self._path)

    def get(self, account_id: str) -> Account:
        with self._lock:
            for account in self._accounts:
                if account.id == account_id:
                    return account
        raise AccountNotFound(f"account not found: {account_id!r}")

    def add_offline(self, username: str, *, make_active: bool | None = None) -> Account:
        name = validate_username(username)
        with self._lock:
            if any(a.type is AccountType.OFFLINE and a.name.lower() == name.lower() for a in self._accounts):
                raise AccountExists(f"offline account already exists: {name}")
            account = Account(name=name, type=AccountType.OFFLINE)
            if any(a.id == account.id for a in self._accounts):
                raise AccountExists(f"account already exists: {name}")
            self._accounts.append(account)
            if make_active is None:
                make_active = not self._active_id
            if make_active:
                self._active_id = account.id
            self.save()
        self._emit("added" if not make_active else "selected", account)
        return account

    def add_microsoft(self, account: Account, *, make_active: bool = True) -> Account:
        if account.type is not AccountType.MICROSOFT:
            raise AccountError("add_microsoft requires a Microsoft account")
        with self._lock:
            existing = next((a for a in self._accounts if a.id == account.id), None)
            if existing is not None:
                index = self._accounts.index(existing)
                self._accounts[index] = account
            else:
                self._accounts.append(account)
            if make_active or not self._active_id:
                self._active_id = account.id
            self.save()
        self._emit("updated" if existing else "added", account)
        return account

    def remove(self, account_id: str) -> None:
        with self._lock:
            account = self.get(account_id)
            self._accounts.remove(account)
            if self._active_id == account.id:
                self._active_id = self._accounts[0].id if self._accounts else ""
            self.save()
        self._emit("removed", account)

    def set_active(self, account_id: str | None) -> Account | None:
        with self._lock:
            if account_id is None:
                self._active_id = ""
                self.save()
                self._emit("selected", None)
                return None
            account = self.get(account_id)
            self._active_id = account.id
            self.save()
        self._emit("selected", account)
        return account

    async def login_microsoft(
        self, *, on_device_code: Callable[[DeviceCode], None] | None = None
    ) -> Account:
        account = await self.auth.login(on_device_code=on_device_code)
        return self.add_microsoft(account)

    async def refresh(self, account_id: str) -> Account:
        account = self.get(account_id)
        if account.type is not AccountType.MICROSOFT:
            return account
        refreshed = await self.auth.refresh(account)
        with self._lock:
            index = self._accounts.index(account)
            self._accounts[index] = refreshed
            self.save()
        self._emit("updated", refreshed)
        return refreshed

    def _emit(self, action: str, account: Account | None) -> None:
        payload = events.AccountChangedEvent(
            action=action,
            account=account,
            account_id=account.id if account is not None else "",
        )
        self._bus.emit(events.EventType.ACCOUNT_CHANGED, payload)


_manager: AccountManager | None = None
_manager_lock = threading.RLock()


def get_account_manager() -> AccountManager:
    """返回进程级账户管理器单例。"""
    global _manager
    with _manager_lock:
        if _manager is None:
            manager = AccountManager()
            manager.load()
            _manager = manager
        return _manager


def set_account_manager(manager: AccountManager | None) -> None:
    global _manager
    with _manager_lock:
        _manager = manager
