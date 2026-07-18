"""Provider-neutral contracts and selection helpers for release discovery."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata
import urllib.parse


GIT_OBJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
ARTIFACT_KINDS = {"asset_zip", "generic_zip", "source_zip"}
ARTIFACT_PROVENANCE = {
    "attached_asset",
    "forge_release_asset",
    "forge_source_archive",
    "generic_manifest",
    "release_asset",
}
WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *("com" + str(number) for number in range(1, 10)),
    *("lpt" + str(number) for number in range(1, 10)),
}


def _require_string(value, label, allow_empty=False):
    """Return one canonical string without coercing untrusted values."""
    if not isinstance(value, str):
        raise ValueError(label + " must be a string.")
    if value != value.strip() or CONTROL_CHARACTER_PATTERN.search(value):
        raise ValueError(label + " must be a canonical string.")
    if not value and not allow_empty:
        raise ValueError(label + " must not be empty.")
    return value


def _require_repository_identity(value):
    """Validate a lowercase host/path identity without assuming one forge."""
    value = _require_string(value, "repository_identity")
    if (
        value != value.lower()
        or unicodedata.normalize("NFC", value) != value
        or any(character.isspace() for character in value)
        or "://" in value
        or "\\" in value
        or value.endswith("/")
    ):
        raise ValueError("repository_identity must be canonical.")

    try:
        parsed = urllib.parse.urlsplit("//" + value)
        parsed.port
    except ValueError as error:
        raise ValueError("repository_identity has an invalid host.") from error
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname in (".", "..")
        or parsed.hostname.startswith(".")
        or parsed.hostname.endswith(".")
    ):
        raise ValueError("repository_identity is unsafe.")

    parts = parsed.path.lstrip("/").split("/")
    if (
        not parts
        or any(not part or part in (".", "..") for part in parts)
        or any("%" in part for part in parts)
        or parts[-1].endswith(".git")
    ):
        raise ValueError("repository_identity has an unsafe path.")
    canonical = parsed.netloc.lower() + "/" + "/".join(parts)
    if canonical != value:
        raise ValueError("repository_identity must be normalized.")
    return value


def _parse_utc_timestamp(value, label="released_at"):
    """Parse the canonical second-precision UTC timestamp used by the index."""
    value = _require_string(value, label)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(label + " must be an ISO 8601 UTC timestamp.") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(label + " must be a canonical UTC timestamp.")
    return parsed.replace(tzinfo=timezone.utc)


def _require_git_object_id(value, allow_empty=False):
    """Validate a full lowercase SHA-1 or SHA-256 Git object ID."""
    value = _require_string(value, "commit", allow_empty=allow_empty)
    if value or not allow_empty:
        if not GIT_OBJECT_ID_PATTERN.fullmatch(value):
            raise ValueError("commit must be a full lowercase Git object ID.")
    return value


def _require_sha256(value, allow_empty=False):
    """Validate a lowercase SHA-256 digest, optionally before download."""
    value = _require_string(
        value, "provider_sha256", allow_empty=allow_empty
    )
    if value or not allow_empty:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError(
                "provider_sha256 must be a lowercase SHA-256 digest."
            )
    return value


def _require_https_url(value):
    """Validate one credential-free HTTPS artifact URL."""
    value = _require_string(value, "artifact_url")
    try:
        parsed = urllib.parse.urlsplit(value)
        parsed.port
    except ValueError as error:
        raise ValueError("artifact_url is not a valid URL.") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path
    ):
        raise ValueError(
            "artifact_url must be a credential-free HTTPS URL."
        )
    return value


def _require_source_path(value):
    """Validate a normalized cross-platform relative source path."""
    value = _require_string(value, "source_path")
    if value == ".":
        return value
    if (
        unicodedata.normalize("NFC", value) != value
        or value.startswith(("/", "\\"))
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ValueError("source_path must be a canonical relative POSIX path.")

    parts = value.split("/")
    if any(not part or part in (".", "..") for part in parts):
        raise ValueError("source_path must be a normalized relative path.")
    for part in parts:
        if part.endswith((".", " ")) or ":" in part:
            raise ValueError("source_path is not portable.")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            raise ValueError("source_path contains a reserved path name.")
    return value


@dataclass(frozen=True)
class ReleaseCandidate:
    """One validated provider-neutral release discovery result."""

    provider: str
    repository_identity: str
    release_id: str
    version: str
    tag: str
    released_at: str
    source_revision: str
    commit: str
    artifact_kind: str
    artifact_provenance: str
    artifact_url: str
    artifact_size: object
    provider_sha256: str
    source_path: str
    migration_eligible: bool

    def __post_init__(self):
        provider = _require_string(self.provider, "provider")
        if not PROVIDER_PATTERN.fullmatch(provider):
            raise ValueError("provider must be a canonical provider identifier.")
        _require_repository_identity(self.repository_identity)
        _require_string(self.release_id, "release_id")
        _require_string(self.version, "version")
        tag = _require_string(self.tag, "tag", allow_empty=True)
        if provider != "generic" and not tag:
            raise ValueError("Forge candidates require a release tag.")
        _parse_utc_timestamp(self.released_at)
        source_revision = _require_string(
            self.source_revision, "source_revision"
        )
        commit = _require_git_object_id(self.commit, allow_empty=True)
        if commit and source_revision != commit:
            raise ValueError("A Git source revision must equal its commit ID.")

        if self.artifact_kind not in ARTIFACT_KINDS:
            raise ValueError("artifact_kind is unsupported.")
        if self.artifact_provenance not in ARTIFACT_PROVENANCE:
            raise ValueError("artifact_provenance is unsupported.")
        _require_https_url(self.artifact_url)
        if self.artifact_size is not None and (
            type(self.artifact_size) is not int or self.artifact_size <= 0
        ):
            raise ValueError("artifact_size must be a positive integer or null.")
        _require_sha256(self.provider_sha256, allow_empty=True)
        _require_source_path(self.source_path)
        if type(self.migration_eligible) is not bool:
            raise ValueError("migration_eligible must be a boolean.")
        if self.migration_eligible and not commit:
            raise ValueError(
                "Migration eligibility requires a full Git commit ID."
            )


class ReleaseProviderAdapter(ABC):
    """Common resolve contract implemented independently by each provider."""

    @abstractmethod
    def resolve(self, repository, policy, transport, *, now=None):
        """Return one validated ReleaseCandidate for repository and policy."""
        raise NotImplementedError


def tag_matches_pattern(tag, tag_pattern):
    """Return whether a tag fully matches the reviewed stable-tag policy."""
    tag = _require_string(tag, "tag")
    tag_pattern = _require_string(tag_pattern, "tag_pattern")
    try:
        pattern = re.compile(tag_pattern)
    except re.error as error:
        raise ValueError("tag_pattern is not a valid regular expression.") from error
    return pattern.fullmatch(tag) is not None


def select_latest_stable_release(
    releases,
    tag_pattern,
    *,
    released_at_key="published_at",
    excluded=None,
    now=None,
):
    """Select the newest eligible full-match tag by parsed release time."""
    if not isinstance(releases, (list, tuple)):
        raise ValueError("Provider releases must be a list.")
    if excluded is not None and not callable(excluded):
        raise ValueError("excluded must be callable.")
    if now is not None:
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("now must be a timezone-aware datetime.")
        now = now.astimezone(timezone.utc)

    candidates = []
    for position, release in enumerate(releases):
        if not isinstance(release, dict):
            raise ValueError("Each provider release must be an object.")
        skip = False
        for flag in ("draft", "prerelease", "upcoming_release"):
            if flag in release:
                if type(release[flag]) is not bool:
                    raise ValueError(flag + " must be a boolean.")
                skip = skip or release[flag]
        if skip or (excluded is not None and excluded(release)):
            continue

        tag = release.get("tag_name")
        if not isinstance(tag, str) or not tag_matches_pattern(tag, tag_pattern):
            continue
        released_at = _parse_utc_timestamp(
            release.get(released_at_key), released_at_key
        )
        if now is not None and released_at > now:
            continue
        candidates.append((released_at, -position, release))

    if not candidates:
        raise ValueError("No stable release matches the reviewed tag policy.")
    return max(candidates, key=lambda candidate: candidate[:2])[2]


def select_asset(
    assets, *, asset_name="", asset_pattern="", name_key="name"
):
    """Select exactly one reviewed asset name or full-match pattern."""
    if not isinstance(assets, (list, tuple)):
        raise ValueError("Release assets must be a list.")
    asset_name = _require_string(asset_name, "asset_name", allow_empty=True)
    asset_pattern = _require_string(
        asset_pattern, "asset_pattern", allow_empty=True
    )
    if bool(asset_name) == bool(asset_pattern):
        raise ValueError("Configure exactly one asset selector.")
    pattern = None
    if asset_pattern:
        try:
            pattern = re.compile(asset_pattern)
        except re.error as error:
            raise ValueError("asset_pattern is not a valid expression.") from error
    name_key = _require_string(name_key, "name_key")

    matches = []
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("Each release asset must be an object.")
        name = asset.get(name_key)
        if not isinstance(name, str):
            raise ValueError("Each release asset must have a string name.")
        if name == asset_name or (
            pattern is not None and pattern.fullmatch(name) is not None
        ):
            matches.append(asset)
    if not matches:
        raise ValueError("Configured release asset was not published.")
    if len(matches) != 1:
        raise ValueError("Configured release asset name is ambiguous.")
    return matches[0]


def select_exact_asset(assets, asset_name, *, name_key="name"):
    """Select exactly one case-sensitive asset name without fuzzy fallback."""
    return select_asset(
        assets,
        asset_name=asset_name,
        name_key=name_key,
    )
