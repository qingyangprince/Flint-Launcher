"""离线 UUID、账户持久化与微软认证链路。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from flint.core.account import (
    MC_LOGIN_URL,
    MC_PROFILE_URL,
    MS_DEVICE_CODE_URL,
    MS_TOKEN_URL,
    XBL_AUTH_URL,
    XSTS_AUTH_URL,
    Account,
    AccountExists,
    AccountManager,
    AccountNotFound,
    AccountType,
    DeviceCode,
    MicrosoftAuth,
    MicrosoftAuthError,
    offline_uuid,
)


def test_offline_uuid_matches_java() -> None:
    assert offline_uuid("Notch") == "b50ad385-829d-3141-a216-7e7d7539ba7f"
    assert offline_uuid("Notch") == offline_uuid("Notch")


def test_add_offline_and_select(tmp_path: Path, event_bus) -> None:
    actions: list[str] = []
    event_bus.subscribe("account_changed", lambda payload: actions.append(payload.action))
    manager = AccountManager(tmp_path / "accounts.json")

    account = manager.add_offline("Steve")
    assert account.type is AccountType.OFFLINE
    assert account.uuid == offline_uuid("Steve")
    assert manager.active == account
    assert actions == ["selected"]

    with pytest.raises(AccountExists):
        manager.add_offline("steve")


def test_remove_and_set_active(tmp_path: Path) -> None:
    manager = AccountManager(tmp_path / "accounts.json")
    first = manager.add_offline("Alex")
    second = manager.add_offline("Steve", make_active=True)

    assert manager.active == second
    manager.remove(second.id)
    assert manager.active == first
    manager.set_active(None)
    assert manager.active is None
    with pytest.raises(AccountNotFound):
        manager.get("missing")


def test_accounts_are_persisted_and_tokens_are_not_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    account = Account(
        name="Alex",
        type=AccountType.MICROSOFT,
        uuid="069a79f4-44e9-4726-a5be-fca90e38aaf5",
        access_token="secret-access-token",
        refresh_token="secret-refresh-token",
        expires_at=9999999999.0,
    )
    manager.add_microsoft(account)

    raw = path.read_text(encoding="utf-8")
    assert "secret-access-token" not in raw
    assert "secret-refresh-token" not in raw

    reloaded = AccountManager(path)
    loaded = reloaded.load()
    assert len(loaded) == 1
    assert loaded[0].access_token == "secret-access-token"
    assert loaded[0].refresh_token == "secret-refresh-token"
    assert reloaded.active is not None
    assert reloaded.active.id == account.id


def test_add_microsoft_replaces_existing_record(tmp_path: Path) -> None:
    manager = AccountManager(tmp_path / "accounts.json")
    account = Account(name="Alex", type=AccountType.MICROSOFT, uuid="uuid-1")
    manager.add_microsoft(account)
    updated = Account(
        name="Alex", type=AccountType.MICROSOFT, uuid="uuid-1", access_token="new-token"
    )
    manager.add_microsoft(updated)

    assert len(manager.accounts) == 1
    assert manager.get("uuid-1").access_token == "new-token"


@pytest.mark.asyncio
async def test_device_code_poll_then_success(tmp_path: Path, http_client) -> None:
    pending = httpx.Response(400, json={"error": "authorization_pending"})
    success = httpx.Response(
        200,
        json={"access_token": "ms-token", "refresh_token": "r", "expires_in": 3600},
    )
    with respx.mock:
        route = respx.post(MS_TOKEN_URL).mock(side_effect=[pending, success])
        auth = MicrosoftAuth(client=http_client)
        code = DeviceCode(
            user_code="ABCD", device_code="dev", verification_uri="https://example.com",
            expires_in=60, interval=0,
        )

        async def no_sleep(_seconds: float) -> None:
            return None

        tokens = await auth.poll_for_token(code, sleep=no_sleep)

    assert route.call_count == 2
    assert tokens["access_token"] == "ms-token"


@pytest.mark.asyncio
async def test_refresh_goes_through_xbox_chain(tmp_path: Path, http_client) -> None:
    with respx.mock:
        respx.post(MS_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "ms-token", "refresh_token": "refresh-2", "expires_in": 3600},
            )
        )
        respx.post(XBL_AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"Token": "xbl-token", "DisplayClaims": {"xui": [{"uhs": "user-hash"}]}},
            )
        )
        respx.post(XSTS_AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"Token": "xsts-token", "DisplayClaims": {"xui": [{"uhs": "user-hash"}]}},
            )
        )
        respx.post(MC_LOGIN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "mc-token", "expires_in": 86400})
        )
        respx.get(MC_PROFILE_URL).mock(
            return_value=httpx.Response(
                200, json={"id": "069a79f4-44e9-4726-a5be-fca90e38aaf5", "name": "Alex"}
            )
        )

        auth = MicrosoftAuth(client=http_client)
        original = Account(
            name="Alex",
            type=AccountType.MICROSOFT,
            uuid="069a79f4-44e9-4726-a5be-fca90e38aaf5",
            refresh_token="refresh-1",
        )
        refreshed = await auth.refresh(original)

    assert refreshed.access_token == "mc-token"
    assert refreshed.refresh_token == "refresh-2"
    assert refreshed.name == "Alex"
    assert not refreshed.expired


@pytest.mark.asyncio
async def test_device_code_login_requires_game_ownership(http_client) -> None:
    with respx.mock:
        respx.post(MS_DEVICE_CODE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "user_code": "ABCD",
                    "device_code": "dev",
                    "verification_uri": "https://microsoft.com/link",
                    "expires_in": 900,
                    "interval": 0,
                },
            )
        )
        respx.post(MS_TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "ms-token", "refresh_token": "r", "expires_in": 3600}
            )
        )
        respx.post(XBL_AUTH_URL).mock(
            return_value=httpx.Response(
                200, json={"Token": "xbl", "DisplayClaims": {"xui": [{"uhs": "hash"}]}}
            )
        )
        respx.post(XSTS_AUTH_URL).mock(
            return_value=httpx.Response(
                200, json={"Token": "xsts", "DisplayClaims": {"xui": [{"uhs": "hash"}]}}
            )
        )
        respx.post(MC_LOGIN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "mc", "expires_in": 3600})
        )
        respx.get(MC_PROFILE_URL).mock(return_value=httpx.Response(404))

        auth = MicrosoftAuth(client=http_client)
        with pytest.raises(MicrosoftAuthError) as excinfo:
            await auth.login()

    assert "Minecraft" in str(excinfo.value)


def test_store_file_is_json(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    manager.add_offline("Steve")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["accounts"][0]["name"] == "Steve"
    assert data["accounts"][0]["type"] == "offline"
