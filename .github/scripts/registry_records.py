#!/usr/bin/env python3
"""Lossless registry records and reviewed delivery-policy validation."""

import copy
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field


DEFAULT_GIT_HOST = "github.com"
SHORTHAND_GIT_HOSTS = {
    "github.com",
    "gitlab.com",
    "codeberg.org",
    "gitea.com",
}
SUPPORTED_PROVIDERS = {"github", "gitlab", "forgejo", "gitea", "generic"}
SUPPORTED_PREFERENCES = {"git", "release", "release_if_indexed"}
SUPPORTED_PLATFORMS = ("linux", "windows")
MAX_RELEASE_PAGE_SIZE = 100
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *("com" + str(number) for number in range(1, 10)),
    *("lpt" + str(number) for number in range(1, 10)),
}

OBJECT_FIELDS = {
    "owner",
    "repository",
    "description",
    "branch",
    "updated_at",
    "platforms",
    "delivery",
}
DELIVERY_FIELDS = {"schema_version", "preferred", "git_supported", "release"}
RELEASE_FIELDS = {
    "provider",
    "channel",
    "tag_pattern",
    "artifact",
    "source_path",
    "mutable_paths",
    "allowed_origins",
    "api_base",
    "web_base",
    "release_page_size",
    "manifest_url",
    "asset_name",
    "asset_pattern",
}
RESERVED_MUTABLE_ROOTS = {".git", ".pypluginstore"}
RESERVED_MUTABLE_PATHS = {".pypluginstore.json", "plugin.py"}


def _require_string(value, label, *, allow_empty=False, canonical=True):
    if not isinstance(value, str):
        raise ValueError(label + " must be a string.")
    if canonical and value != value.strip():
        raise ValueError(label + " must be canonical without outer whitespace.")
    value = value.strip()
    if not allow_empty and not value:
        raise ValueError(label + " must not be empty.")
    if CONTROL_CHARACTERS.search(value):
        raise ValueError(label + " contains a control character.")
    return value


def _require_exact_fields(document, label, allowed, required=()):
    if not isinstance(document, dict):
        raise ValueError(label + " must be an object.")
    missing = sorted(set(required) - set(document))
    unknown = sorted(set(document) - set(allowed))
    if missing:
        raise ValueError(label + " is missing " + ", ".join(missing) + ".")
    if unknown:
        raise ValueError(label + " contains unknown field " + unknown[0] + ".")
    return document


def _validate_path_segment(value, label):
    value = _require_string(value, label)
    if (
        value in {".", ".."}
        or value.startswith(".")
        or "/" in value
        or "\\" in value
        or value.endswith(".git")
        or urllib.parse.quote(value, safe="-._~") != value
    ):
        raise ValueError(label + " is not a safe repository path segment.")
    return value


def _validate_plugin_key(value):
    value = _require_string(value, "Plugin key")
    if value.startswith(".") or "/" in value or "\\" in value:
        raise ValueError("Plugin key is not a visible folder name.")
    return value


def _normalize_platforms(platforms, *, strict=False):
    if isinstance(platforms, str):
        platforms = [platforms]
    if platforms in (None, []):
        if strict and platforms == []:
            raise ValueError("Registry platforms must not be empty.")
        return []
    if not isinstance(platforms, list):
        raise ValueError("Registry platforms must be a list.")
    normalized = []
    for value in platforms:
        platform = _require_string(value, "Registry platform").lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Unsupported registry platform " + platform + ".")
        if platform not in normalized:
            normalized.append(platform)
    return [value for value in SUPPORTED_PLATFORMS if value in normalized]


@dataclass(frozen=True)
class RepositoryLocation:
    host: str
    owner_path: str
    web_base: str
    explicit_url: bool = False


def parse_registry_owner(owner):
    """Return a canonical host/base while preserving reviewed path case."""
    owner = _require_string(owner, "Registry owner").rstrip("/")
    parsed = urllib.parse.urlsplit(owner)
    if parsed.scheme or parsed.netloc:
        try:
            parsed.port
        except ValueError as error:
            raise ValueError("Registry owner is not a valid URL.") from error
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Custom registry owners require a credential-free HTTPS URL."
            )
        host = parsed.netloc.lower()
        owner_path = parsed.path.strip("/")
        web_base = "https://" + parsed.netloc
        explicit_url = True
    else:
        first, separator, remainder = owner.partition("/")
        if first.lower() in SHORTHAND_GIT_HOSTS and separator:
            host = first.lower()
            owner_path = remainder.strip("/")
            web_base = "https://" + host
        elif "." in first or ":" in first:
            raise ValueError(
                "Custom registry owners must use a full HTTPS URL."
            )
        else:
            host = DEFAULT_GIT_HOST
            owner_path = owner
            web_base = "https://" + host
        explicit_url = False

    parts = owner_path.split("/") if owner_path else []
    if not parts:
        raise ValueError("Registry owner must include an owner path.")
    for part in parts:
        _validate_path_segment(part, "Registry owner path")
    return RepositoryLocation(host, "/".join(parts), web_base, explicit_url)


def normalize_repository_identity(owner, repository):
    location = parse_registry_owner(owner)
    repository = _validate_path_segment(repository, "Repository")
    return (
        location.host
        + "/"
        + location.owner_path
        + "/"
        + repository
    ).lower()


def build_clone_url(owner, repository):
    location = parse_registry_owner(owner)
    repository = _validate_path_segment(repository, "Repository")
    return (
        location.web_base
        + "/"
        + location.owner_path
        + "/"
        + repository
        + ".git"
    )


def _validate_https_url(value, label, *, origin_only=False):
    value = _require_string(value, label)
    try:
        parsed = urllib.parse.urlsplit(value)
        parsed.port
    except ValueError as error:
        raise ValueError(label + " is not a valid URL.") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(label + " must be a credential-free HTTPS URL.")
    if origin_only:
        if parsed.path not in {"", "/"}:
            raise ValueError(label + " must contain only an origin.")
        hostname = parsed.hostname.lower()
        host = "[" + hostname + "]" if ":" in hostname else hostname
        if parsed.port not in (None, 443):
            host += ":" + str(parsed.port)
        return "https://" + host
    return value.rstrip("/")


def _normalize_relative_path(value, label, *, allow_root=True):
    value = _require_string(value, label)
    if value == "." and allow_root:
        return value
    if (
        value.startswith("/")
        or "\\" in value
        or WINDOWS_DRIVE.match(value)
        or CONTROL_CHARACTERS.search(value)
        or unicodedata.normalize("NFC", value) != value
    ):
        raise ValueError(label + " must be a relative POSIX path.")
    parts = value.split("/")
    if not parts or any(
        not part
        or part in {".", ".."}
        or ":" in part
        for part in parts
    ):
        raise ValueError(label + " must be a normalized relative path.")
    for part in parts:
        if part.endswith((".", " ")):
            raise ValueError(label + " must be portable across platforms.")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            raise ValueError(label + " contains a reserved path name.")
    return "/".join(parts)


@dataclass(frozen=True)
class ReleasePolicy:
    provider: str
    channel: str
    tag_pattern: str
    artifact: str
    source_path: str
    mutable_paths: list
    allowed_origins: list
    api_base: str = ""
    web_base: str = ""
    release_page_size: int = 0
    manifest_url: str = ""
    asset_name: str = ""
    asset_pattern: str = ""
    _document: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_document(cls, document, location):
        document = _require_exact_fields(
            document,
            "delivery.release",
            RELEASE_FIELDS,
            required=("provider",),
        )
        provider = _require_string(
            document["provider"], "delivery.release.provider"
        ).lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError("delivery.release.provider is not supported.")

        expected_provider = {
            "github.com": "github",
            "gitlab.com": "gitlab",
            "codeberg.org": "forgejo",
        }.get(location.host)
        if (
            expected_provider
            and provider not in {expected_provider, "generic"}
        ):
            raise ValueError("Release provider does not match registry host.")
        if (
            location.host not in {"github.com", "gitlab.com", "codeberg.org"}
            and provider in {"github", "gitlab"}
        ):
            raise ValueError(
                "Custom GitHub and GitLab release hosts are not supported."
            )

        channel = _require_string(
            document.get("channel", "stable"), "delivery.release.channel"
        ).lower()
        if channel != "stable":
            raise ValueError("Only the stable release channel is supported.")

        tag_pattern = document.get("tag_pattern", "")
        if tag_pattern:
            tag_pattern = _require_string(
                tag_pattern, "delivery.release.tag_pattern"
            )
            try:
                re.compile(tag_pattern)
            except re.error as error:
                raise ValueError("Release tag_pattern is invalid.") from error
        if provider in {"github", "gitlab", "forgejo", "gitea"} and not tag_pattern:
            raise ValueError(provider + " requires a reviewed tag_pattern.")
        if provider == "generic" and tag_pattern:
            raise ValueError("Generic manifests do not use tag_pattern.")

        artifact = _require_string(
            document.get("artifact", "source_zip"),
            "delivery.release.artifact",
        )
        if artifact not in {"source_zip", "asset_zip"}:
            raise ValueError("Unsupported release artifact selection.")
        source_path = _normalize_relative_path(
            document.get("source_path", "."),
            "delivery.release.source_path",
        )

        mutable_document = document.get("mutable_paths", [])
        if not isinstance(mutable_document, list):
            raise ValueError("delivery.release.mutable_paths must be a list.")
        mutable_paths = []
        mutable_keys = []
        for value in mutable_document:
            path = _normalize_relative_path(
                value,
                "delivery.release.mutable_paths entry",
                allow_root=False,
            )
            lowered = path.lower()
            if (
                lowered in RESERVED_MUTABLE_PATHS
                or lowered.split("/", 1)[0] in RESERVED_MUTABLE_ROOTS
            ):
                raise ValueError("Mutable path is manager-reserved.")
            collision_key = unicodedata.normalize("NFC", path).casefold()
            if any(
                collision_key == existing
                or collision_key.startswith(existing + "/")
                or existing.startswith(collision_key + "/")
                for existing in mutable_keys
            ):
                raise ValueError("Mutable paths must be unique and non-overlapping.")
            mutable_paths.append(path)
            mutable_keys.append(collision_key)

        allowed_document = document.get("allowed_origins", [])
        if not isinstance(allowed_document, list):
            raise ValueError("delivery.release.allowed_origins must be a list.")
        allowed_origins = []
        normalized_origins = set()
        for value in allowed_document:
            origin = _validate_https_url(
                value,
                "delivery.release.allowed_origins entry",
                origin_only=True,
            )
            normalized = origin.lower()
            if normalized in normalized_origins:
                raise ValueError("Allowed origins must be unique.")
            normalized_origins.add(normalized)
            allowed_origins.append(origin)

        asset_name = document.get("asset_name", "")
        if asset_name:
            asset_name = _require_string(asset_name, "delivery.release.asset_name")
        asset_pattern = document.get("asset_pattern", "")
        if asset_pattern:
            asset_pattern = _require_string(
                asset_pattern, "delivery.release.asset_pattern"
            )
            try:
                re.compile(asset_pattern)
            except re.error as error:
                raise ValueError("Release asset_pattern is invalid.") from error
        if asset_name and asset_pattern:
            raise ValueError("Choose asset_name or asset_pattern, not both.")
        if artifact == "source_zip" and (asset_name or asset_pattern):
            raise ValueError("Source ZIP policies cannot select an asset.")
        if (
            artifact == "asset_zip"
            and provider != "generic"
            and not (asset_name or asset_pattern)
        ):
            raise ValueError("Asset ZIP policies require an exact reviewed selector.")
        if provider == "generic" and artifact != "asset_zip":
            raise ValueError("Generic manifests require asset_zip delivery.")

        api_base = document.get("api_base", "")
        web_base = document.get("web_base", "")
        page_size = document.get("release_page_size", 0)
        manifest_url = document.get("manifest_url", "")

        if provider in {"forgejo", "gitea"}:
            codeberg_defaults = (
                provider == "forgejo" and location.host == "codeberg.org"
            )
            if codeberg_defaults:
                if "api_base" in document:
                    api_base = _validate_https_url(
                        api_base, "delivery.release.api_base"
                    )
                if "web_base" in document:
                    web_base = _validate_https_url(
                        web_base, "delivery.release.web_base"
                    )
                if "release_page_size" in document and (
                    type(page_size) is not int or not 1 <= page_size <= 100
                ):
                    raise ValueError(
                        "release_page_size must be between 1 and 100."
                    )
            else:
                if not api_base or not web_base or not page_size:
                    raise ValueError(
                        "Custom Forgejo and Gitea policies require api_base, "
                        "web_base, and release_page_size."
                    )
                api_base = _validate_https_url(api_base, "delivery.release.api_base")
                web_base = _validate_https_url(web_base, "delivery.release.web_base")
                if type(page_size) is not int or not 1 <= page_size <= 100:
                    raise ValueError("release_page_size must be between 1 and 100.")
            if web_base:
                web_host = urllib.parse.urlsplit(web_base).netloc.lower()
                if web_host != location.host:
                    raise ValueError(
                        "delivery.release.web_base does not match owner host."
                    )
        elif api_base or web_base or page_size:
            raise ValueError(
                "Host capability fields are only valid for Forgejo and Gitea."
            )

        if provider == "generic":
            if not manifest_url:
                raise ValueError("Generic release policy requires manifest_url.")
            manifest_url = _validate_https_url(
                manifest_url, "delivery.release.manifest_url"
            )
        elif manifest_url:
            raise ValueError("manifest_url is only valid for generic releases.")

        return cls(
            provider=provider,
            channel=channel,
            tag_pattern=tag_pattern,
            artifact=artifact,
            source_path=source_path,
            mutable_paths=mutable_paths,
            allowed_origins=allowed_origins,
            api_base=api_base,
            web_base=web_base,
            release_page_size=page_size,
            manifest_url=manifest_url,
            asset_name=asset_name,
            asset_pattern=asset_pattern,
            _document=copy.deepcopy(document),
        )

    def to_document(self):
        return copy.deepcopy(self._document)


@dataclass(frozen=True)
class DeliveryPolicy:
    schema_version: int
    preferred: str
    git_supported: bool
    release: object = None
    _document: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def implicit(cls):
        return cls(1, "release_if_indexed", True, None, {})

    @classmethod
    def from_document(cls, document, location):
        document = _require_exact_fields(
            document,
            "delivery",
            DELIVERY_FIELDS,
            required=("schema_version", "preferred", "git_supported"),
        )
        if (
            type(document["schema_version"]) is not int
            or document["schema_version"] != 1
        ):
            raise ValueError("delivery.schema_version is not supported.")
        preferred = _require_string(document["preferred"], "delivery.preferred")
        if preferred not in SUPPORTED_PREFERENCES:
            raise ValueError("delivery.preferred is not supported.")
        if type(document["git_supported"]) is not bool:
            raise ValueError("delivery.git_supported must be a boolean.")
        git_supported = document["git_supported"]
        release_document = document.get("release")
        release = (
            ReleasePolicy.from_document(release_document, location)
            if release_document is not None
            else None
        )
        if preferred == "release" and release is None:
            raise ValueError("Release delivery requires delivery.release.")
        if preferred == "git" and not git_supported:
            raise ValueError("Git delivery requires git_supported.")
        return cls(
            1,
            preferred,
            git_supported,
            release,
            copy.deepcopy(document),
        )

    def to_document(self):
        return copy.deepcopy(self._document)


@dataclass(frozen=True)
class RegistryRecord:
    key: str
    owner: str
    repository: str
    description: str
    branch: str
    updated_at: str
    platforms: list
    delivery: DeliveryPolicy
    is_legacy: bool
    extra_fields: dict
    _document: object = field(repr=False, compare=False)

    @classmethod
    def from_entry(cls, key, entry):
        key = _validate_plugin_key(key)
        original = copy.deepcopy(entry)
        if isinstance(entry, list):
            if len(entry) < 4:
                raise ValueError("Legacy registry entry must contain four fields.")
            owner = _require_string(entry[0], "Registry owner")
            repository = _validate_path_segment(entry[1], "Repository")
            description = _require_string(
                entry[2], "Description", canonical=False
            )
            branch = _require_string(entry[3], "Branch")
            updated_at = (
                _require_string(entry[4], "Updated at", allow_empty=True)
                if len(entry) > 4
                else ""
            )
            platforms = (
                _normalize_platforms(entry[5], strict=True)
                if len(entry) > 5
                else []
            )
            location = parse_registry_owner(owner)
            delivery = DeliveryPolicy.implicit()
            extra_fields = {}
            is_legacy = True
        elif isinstance(entry, dict):
            for required in ("owner", "repository", "description", "branch"):
                if required not in entry:
                    raise ValueError(
                        "Object registry entry is missing " + required + "."
                    )
            owner = _require_string(entry["owner"], "Registry owner")
            repository = _validate_path_segment(entry["repository"], "Repository")
            description = _require_string(
                entry["description"], "Description", canonical=False
            )
            branch = _require_string(entry["branch"], "Branch")
            updated_at = _require_string(
                entry.get("updated_at", ""), "Updated at", allow_empty=True
            )
            platforms = (
                _normalize_platforms(entry["platforms"], strict=True)
                if "platforms" in entry
                else []
            )
            location = parse_registry_owner(owner)
            delivery = (
                DeliveryPolicy.from_document(entry["delivery"], location)
                if "delivery" in entry
                else DeliveryPolicy.implicit()
            )
            extra_fields = {
                field_name: copy.deepcopy(value)
                for field_name, value in entry.items()
                if field_name not in OBJECT_FIELDS
            }
            is_legacy = False
        else:
            raise ValueError("Registry entry must be a legacy list or object.")

        # Parse after core validation so malformed custom owner URLs fail early.
        parse_registry_owner(owner)
        return cls(
            key=key,
            owner=owner,
            repository=repository,
            description=description,
            branch=branch,
            updated_at=updated_at,
            platforms=platforms,
            delivery=delivery,
            is_legacy=is_legacy,
            extra_fields=extra_fields,
            _document=original,
        )

    @property
    def repository_identity(self):
        return normalize_repository_identity(self.owner, self.repository)

    @property
    def clone_url(self):
        return build_clone_url(self.owner, self.repository)

    @property
    def raw_plugin_url(self):
        location = parse_registry_owner(self.owner)
        path = "/".join(
            urllib.parse.quote(part, safe="")
            for part in (location.owner_path + "/" + self.repository).split("/")
        )
        branch = urllib.parse.quote(self.branch, safe="")
        if location.host == "github.com":
            return (
                "https://raw.githubusercontent.com/"
                + path
                + "/"
                + branch
                + "/plugin.py"
            )
        if location.host == "gitlab.com":
            return location.web_base + "/" + path + "/-/raw/" + branch + "/plugin.py"
        return (
            location.web_base
            + "/"
            + path
            + "/raw/branch/"
            + branch
            + "/plugin.py"
        )

    def to_document(self):
        return copy.deepcopy(self._document)

    def with_description(self, description):
        description = _require_string(
            description, "Description", canonical=False
        )
        document = self.to_document()
        if self.is_legacy:
            document[2] = description
        else:
            document["description"] = description
        return type(self).from_entry(self.key, document)

    def with_platforms(self, platforms):
        platforms = _normalize_platforms(platforms)
        document = self.to_document()
        if self.is_legacy:
            while len(document) < 5:
                document.append("")
            if len(document) == 5:
                document.append(platforms)
            else:
                document[5] = platforms
        else:
            document["platforms"] = platforms
        return type(self).from_entry(self.key, document)
