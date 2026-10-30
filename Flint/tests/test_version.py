"""版本相关测试：manifest 解析、继承链合并与 rules 过滤。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from flint.core import version as version_module
from flint.core.version import (
    VersionError,
    VersionManifest,
    VersionNotFound,
    VersionResolver,
    build_resolved,
    filter_libraries,
    merge_version_json,
    resolve_json,
    rule_matches,
    rules_allow,
)
from flint.infra.cache import HttpCache
from flint.infra.http import HttpClient

MANIFEST_URL = "https://example.invalid/version_manifest_v2.json"


def manifest_payload() -> dict:
    return {
        "latest": {"release": "1.20.1", "snapshot": "23w31a"},
        "versions": [
            {
                "id": "1.20.1",
                "type": "release",
                "url": "https://example.invalid/v/1.20.1.json",
                "time": "2023-06-12T12:00:00+00:00",
                "releaseTime": "2023-06-12T12:00:00+00:00",
                "sha1": "a" * 40,
                "complianceLevel": 1,
            },
            {
                "id": "23w31a",
                "type": "snapshot",
                "url": "https://example.invalid/v/23w31a.json",
                "time": "2023-08-02T12:00:00+00:00",
                "releaseTime": "2023-08-02T12:00:00+00:00",
                "sha1": "b" * 40,
                "complianceLevel": 1,
            },
        ],
    }


def parent_version() -> dict:
    return {
        "id": "1.20.1",
        "type": "release",
        "mainClass": "net.minecraft.client.main.Main",
        "assets": "5",
        "assetIndex": {
            "id": "5",
            "url": "https://example.invalid/assets/5.json",
            "sha1": "c" * 40,
            "size": 123,
        },
        "downloads": {
            "client": {"url": "https://example.invalid/client.jar", "sha1": "d" * 40, "size": 456}
        },
        "libraries": [
            {"name": "com.example:shared:1.0"},
            {
                "name": "com.example:native:1.0",
                "rules": [{"action": "allow", "os": {"name": "windows"}}],
            },
            {
                "name": "com.example:unix:1.0",
                "rules": [
                    {"action": "allow", "os": {"name": "linux"}},
                    {"action": "allow", "os": {"name": "osx"}},
                ],
            },
        ],
        "arguments": {"jvm": ["-Xmx2G"], "game": ["--parent"]},
        "javaVersion": {"component": "java-runtime-gamma", "majorVersion": 17},
    }


def loader_version() -> dict:
    return {
        "id": "1.20.1-loader",
        "inheritsFrom": "1.20.1",
        "mainClass": "example.loader.Main",
        "libraries": [
            {"name": "com.example:shared:2.0"},
            {"name": "example:loader:1.0"},
        ],
        "arguments": {"jvm": ["-Dloader=1"], "game": ["--child"]},
    }


def test_manifest_parsing():
    manifest = VersionManifest.from_json(manifest_payload())
    assert len(manifest) == 2
    assert manifest.latest_release == "1.20.1"
    assert manifest.latest_snapshot == "23w31a"
    found = manifest.find("23w31a")
    assert found is not None and found.type == "snapshot"
    assert manifest.find("does-not-exist") is None
    assert manifest.latest_of("release").id == "1.20.1" # type: ignore
    assert [item.id for item in manifest.filter("snapshot")] == ["23w31a"]


def test_manifest_rejects_malformed_payloads():
    with pytest.raises(VersionError):
        VersionManifest.from_json([])
    with pytest.raises(VersionError):
        VersionManifest.from_json({"versions": "not-a-list"})
    with pytest.raises(VersionError):
        VersionManifest.from_json({"versions": [{"id": "x"}]})
    with pytest.raises(VersionError):
        VersionManifest.from_json({})


def test_merge_inheritance_merges_libraries_and_arguments():
    merged = merge_version_json(loader_version(), parent_version())

    assert merged["id"] == "1.20.1-loader"
    assert merged["mainClass"] == "example.loader.Main"
    assert merged["assets"] == "5"
    assert merged["inheritsFrom"] == "1.20.1"

    names = [library["name"] for library in merged["libraries"]]
    assert names == [
        "com.example:shared:2.0",
        "com.example:native:1.0",
        "com.example:unix:1.0",
        "example:loader:1.0",
    ]
    assert merged["arguments"]["jvm"] == ["-Xmx2G", "-Dloader=1"]
    assert merged["arguments"]["game"] == ["--parent", "--child"]


def test_resolve_json_walks_inheritance_and_filters_rules():
    library = {"1.20.1": parent_version(), "1.20.1-loader": loader_version()}

    resolved = resolve_json(
        loader_version(), lambda version_id: library[version_id], os_name="windows", arch="x86_64"
    )

    assert isinstance(resolved.id, str)
    assert resolved.id == "1.20.1-loader"
    assert resolved.inherited_from == ("1.20.1",)
    assert resolved.main_class == "example.loader.Main"
    assert resolved.recommended_java_major == 17
    assert resolved.asset_index == parent_version()["assetIndex"]
    assert resolved.client_download["size"] == 456 # type: ignore
    assert [lib["name"] for lib in resolved.libraries] == [
        "com.example:shared:2.0",
        "com.example:native:1.0",
        "example:loader:1.0",
    ]

    linux = resolve_json(
        loader_version(), lambda version_id: library[version_id], os_name="linux", arch="x86_64"
    )
    assert [lib["name"] for lib in linux.libraries] == [
        "com.example:shared:2.0",
        "com.example:unix:1.0",
        "example:loader:1.0",
    ]


def test_resolve_json_missing_parent():
    def loader(version_id: str) -> dict:
        raise VersionNotFound(version_id)

    with pytest.raises(VersionNotFound):
        resolve_json(loader_version(), loader)


def test_resolve_json_detects_cycles():
    cyclic = {
        "a": {"id": "a", "mainClass": "A", "inheritsFrom": "b"},
        "b": {"id": "b", "mainClass": "B", "inheritsFrom": "a"},
    }

    with pytest.raises(VersionError, match="cyclic"):
        resolve_json(cyclic["a"], lambda version_id: cyclic[version_id])


def test_build_resolved_requires_main_class():
    with pytest.raises(VersionError):
        build_resolved({"id": "broken"})


def test_rules_allow_and_features():
    assert rules_allow(None) is True
    assert rules_allow([]) is True

    windows_only = [{"action": "allow", "os": {"name": "windows"}}]
    assert rules_allow(windows_only, os_name="windows", arch="x86_64") is True
    assert rules_allow(windows_only, os_name="linux", arch="x86_64") is False

    disallow_windows = [
        {"action": "allow"},
        {"action": "disallow", "os": {"name": "windows"}},
    ]
    assert rules_allow(disallow_windows, os_name="windows", arch="x86_64") is False
    assert rules_allow(disallow_windows, os_name="linux", arch="x86_64") is True

    feature_rule = {"action": "allow", "features": {"has_custom_resolution": True}}
    assert rules_allow([feature_rule], os_name="windows", arch="x86_64", features={}) is False
    assert (
        rules_allow(
            [feature_rule],
            os_name="windows",
            arch="x86_64",
            features={"has_custom_resolution": True},
        )
        is True
    )
    assert (
        rule_matches({"os": {"arch": "x86"}}, os_name="windows", arch="x86_64", features={})
        is False
    )


def test_filter_libraries_returns_deep_copies():
    libraries = [{"name": "a:b:1", "natives": {"windows": "natives-windows"}}]
    filtered = filter_libraries(libraries, os_name="windows", arch="x86_64")
    filtered[0]["name"] = "mutated"
    assert libraries[0]["name"] == "a:b:1"


def test_local_resolution_and_corrupt_json(tmp_path: Path):
    versions = tmp_path / "versions"
    (versions / "1.20.1").mkdir(parents=True)
    (versions / "1.20.1" / "1.20.1.json").write_text(json.dumps(parent_version()), encoding="utf-8")
    (versions / "1.20.1-loader").mkdir(parents=True)
    (versions / "1.20.1-loader" / "1.20.1-loader.json").write_text(
        json.dumps(loader_version()), encoding="utf-8"
    )

    resolver = VersionResolver(cache=HttpCache(tmp_path / "cache"), version_dir=versions)
    resolved = resolver.resolve_local("1.20.1-loader")
    assert resolved.inherited_from == ("1.20.1",)
    assert resolved.main_class == "example.loader.Main"

    (versions / "broken").mkdir()
    (versions / "broken" / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(VersionError, match="corrupt"):
        resolver.resolve_local("broken")


async def test_resolver_fetches_inheritance_over_http(tmp_path: Path):
    versions_dir = tmp_path / "versions"
    client = HttpClient(retries=0, backoff=0.0)
    resolver = VersionResolver(
        client=client,
        cache=HttpCache(tmp_path / "cache"),
        version_dir=versions_dir,
        manifest_url=MANIFEST_URL,
        os_name="windows",
        arch="x86_64",
    )

    try:
        with respx.mock() as mock:
            mock.get(MANIFEST_URL).mock(return_value=httpx.Response(200, json=manifest_payload()))
            mock.get("https://example.invalid/v/loader.json").mock(
                return_value=httpx.Response(200, json=loader_version())
            )
            mock.get("https://example.invalid/v/1.20.1.json").mock(
                return_value=httpx.Response(200, json=parent_version())
            )

            resolved = await resolver.resolve(
                "1.20.1-loader", url="https://example.invalid/v/loader.json"
            )
    finally:
        await client.aclose()

    assert resolved.id == "1.20.1-loader"
    assert resolved.inherited_from == ("1.20.1",)
    assert resolved.libraries[0]["name"] == "com.example:shared:2.0"


async def test_resolver_uses_etag_cache(tmp_path: Path):
    url = "https://example.invalid/v/cached.json"
    client = HttpClient(retries=0, backoff=0.0)
    resolver = VersionResolver(
        client=client, cache=HttpCache(tmp_path / "cache"), version_dir=tmp_path / "versions"
    )

    try:
        with respx.mock() as mock:
            route = mock.get(url).mock(
                side_effect=[
                    httpx.Response(200, json=parent_version(), headers={"etag": '"v1"'}),
                    httpx.Response(304, headers={"etag": '"v1"'}),
                ]
            )
            first = await resolver.fetch_version_json(url)
            second = await resolver.fetch_version_json(url)
    finally:
        await client.aclose()

    assert first == second
    assert route.call_count == 2
    assert route.calls[1].request.headers["if-none-match"] == '"v1"'


async def test_resolver_reports_unknown_version(tmp_path: Path):
    client = HttpClient(retries=0, backoff=0.0)
    resolver = VersionResolver(
        client=client,
        cache=HttpCache(tmp_path / "cache"),
        version_dir=tmp_path / "versions",
        manifest_url=MANIFEST_URL,
    )

    try:
        with respx.mock() as mock:
            mock.get(MANIFEST_URL).mock(return_value=httpx.Response(200, json=manifest_payload()))
            with pytest.raises(VersionNotFound):
                await resolver.resolve("nope")
    finally:
        await client.aclose()


def test_manifest_url_per_mirror():
    official = VersionResolver(cache=HttpCache(Path("unused")), version_dir=Path("unused"))
    mirrored = VersionResolver(
        cache=HttpCache(Path("unused")),
        version_dir=Path("unused"),
        mirror="bmclapi",
    )
    assert official.manifest_url == version_module.OFFICIAL_MANIFEST_URL
    assert mirrored.manifest_url == version_module.BMCLAPI_MANIFEST_URL
