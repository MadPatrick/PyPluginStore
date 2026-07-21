#!/usr/bin/env python3
"""Deterministically migrate public package data to explicit v2 records.

The command performs no network access. Domoticz runtime identities must come
from a reviewed certification document that binds the legacy package ID,
repository identity, branch, and exact ``plugin.py`` SHA-256.
"""

import argparse
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
for import_path in (REPO_ROOT, SCRIPT_DIR):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from package_registry import PackageRecord, PackageRegistry  # noqa: E402
from registry_records import validate_explicit_delivery  # noqa: E402


CERTIFICATION_SCHEMA_VERSION = 1
MIGRATION_REPORT_SCHEMA_VERSION = 1
LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
CERTIFICATION_FIELDS = {
    "legacy_package_id",
    "repository_identity",
    "branch",
    "domoticz_key",
    "plugin_py_sha256",
}
CERTIFICATION_FAILURE_FIELDS = {"legacy_package_id", "reason"}


@dataclass(frozen=True)
class PublicDataMigration:
    ready: bool
    registry_bytes: object
    update_times_bytes: object
    platform_metadata_bytes: object
    report_bytes: bytes


def _strict_json_object(contents, label):
    if not isinstance(contents, (bytes, bytearray)):
        raise ValueError(label + " must be bytes.")

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(label + " contains duplicate JSON key " + key + ".")
            result[key] = value
        return result

    try:
        document = json.loads(
            bytes(contents).decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(label + " is not valid UTF-8 JSON.") from error
    if not isinstance(document, dict):
        raise ValueError(label + " must contain a JSON object.")
    return document


def _canonical_bytes(document):
    return (
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _require_exact_fields(document, label, allowed, required=None):
    if not isinstance(document, dict):
        raise ValueError(label + " must be an object.")
    required = set(allowed if required is None else required)
    missing = sorted(required - set(document))
    unknown = sorted(set(document) - set(allowed))
    if missing:
        raise ValueError(label + " is missing " + missing[0] + ".")
    if unknown:
        raise ValueError(label + " contains unknown field " + unknown[0] + ".")
    return document


def _require_string(value, label):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(label + " must be a canonical non-empty string.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(label + " contains a control character.")
    return value


def _load_certifications(contents):
    document = _strict_json_object(contents, "identity certifications")
    _require_exact_fields(
        document,
        "identity certifications",
        {"schema_version", "certifications", "failures"},
        {"schema_version", "certifications"},
    )
    if document["schema_version"] != CERTIFICATION_SCHEMA_VERSION:
        raise ValueError("Identity certification schema is unsupported.")
    records = document["certifications"]
    if not isinstance(records, list):
        raise ValueError("Identity certifications must be an array.")

    result = {}
    for record in records:
        _require_exact_fields(
            record,
            "identity certification",
            CERTIFICATION_FIELDS,
        )
        legacy_id = _require_string(
            record["legacy_package_id"], "legacy_package_id"
        )
        if legacy_id in result:
            raise ValueError("Identity certifications contain a duplicate package ID.")
        normalized = {
            field: _require_string(record[field], field)
            for field in CERTIFICATION_FIELDS
        }
        if not LOWER_SHA256.fullmatch(normalized["plugin_py_sha256"]):
            raise ValueError("plugin_py_sha256 must be a lowercase SHA-256 digest.")
        result[legacy_id] = normalized
    failures = document.get("failures", [])
    if not isinstance(failures, list):
        raise ValueError("Identity certification failures must be an array.")
    for failure in failures:
        _require_exact_fields(
            failure,
            "identity certification failure",
            CERTIFICATION_FAILURE_FIELDS,
        )
        legacy_id = _require_string(
            failure["legacy_package_id"], "legacy_package_id"
        )
        _require_string(failure["reason"], "failure reason")
        if legacy_id in result:
            raise ValueError(
                "Identity certification cannot both pass and fail for "
                + legacy_id
                + "."
            )
    return result


def _legacy_package_mapping(registry_document):
    registry = PackageRegistry.from_legacy_document(registry_document)
    by_repository = {
        package.repository_identity: package for package in registry.packages
    }
    mapping = {}
    for legacy_id, legacy_entry in registry_document.items():
        if legacy_id == "Idle":
            continue
        single = PackageRegistry.from_legacy_document(
            {legacy_id: copy.deepcopy(legacy_entry)}
        ).packages[0]
        mapping[legacy_id] = by_repository[single.repository_identity]
    return mapping


def _certify_packages(mapping, certifications):
    unknown = sorted(set(certifications) - set(mapping))
    if unknown:
        raise ValueError(
            "Identity certifications contain unknown package " + unknown[0] + "."
        )

    package_sort_key = lambda value: (value.casefold(), value)
    missing = sorted(set(mapping) - set(certifications), key=package_sort_key)
    packages = []
    report_mappings = []
    for legacy_id in sorted(mapping, key=package_sort_key):
        package = mapping[legacy_id]
        certification = certifications.get(legacy_id)
        report_entry = {
            "legacy_package_id": legacy_id,
            "package_id": package.package_id,
            "repository_identity": package.repository_identity,
        }
        if certification is not None:
            if certification["repository_identity"] != package.repository_identity:
                raise ValueError(
                    "Identity certification repository does not match "
                    + legacy_id
                    + "."
                )
            if certification["branch"] != package.branch:
                raise ValueError(
                    "Identity certification branch does not match "
                    + legacy_id
                    + "."
                )
            package_document = package.to_document()
            package_document["domoticz_key"] = certification["domoticz_key"]
            release = package_document["delivery"].get("release")
            if (
                package.repository_identity.startswith("codeberg.org/")
                and isinstance(release, dict)
                and release.get("provider") == "forgejo"
            ):
                release["provider"] = "codeberg"
            package = PackageRecord.from_document(package_document)
            validate_explicit_delivery(package)
            report_entry.update(
                domoticz_key=certification["domoticz_key"],
                plugin_py_sha256=certification["plugin_py_sha256"],
            )
            packages.append(package)
        report_mappings.append(report_entry)
    return packages, missing, report_mappings


def _normalize_timestamp(value):
    value = _require_string(value, "updated_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("updated_at is not an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError("updated_at must include a timezone.")
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _convert_update_times(document, mapping):
    if not isinstance(document, dict) or "schema_version" in document:
        raise ValueError("Legacy update_times.json must be a package-keyed object.")
    stale = sorted(set(document) - set(mapping))
    if stale:
        raise ValueError("update_times.json contains unknown package " + stale[0] + ".")
    updates = [
        {
            "package_id": mapping[legacy_id].package_id,
            "updated_at": _normalize_timestamp(value),
        }
        for legacy_id, value in document.items()
    ]
    updates.sort(key=lambda item: item["package_id"])
    return {"schema_version": 2, "updates": updates}


def _convert_platform_metadata(document, mapping):
    _require_exact_fields(document, "platform metadata", {"version", "entries"})
    if document["version"] != 1 or not isinstance(document["entries"], dict):
        raise ValueError("Legacy platform metadata schema is unsupported.")
    stale = sorted(set(document["entries"]) - set(mapping))
    if stale:
        raise ValueError(
            "Platform metadata contains unknown package " + stale[0] + "."
        )

    detections = []
    for legacy_id, legacy_record in document["entries"].items():
        if not isinstance(legacy_record, dict):
            raise ValueError("Platform metadata entries must be objects.")
        if "package_id" in legacy_record:
            raise ValueError("Legacy platform metadata already contains package_id.")
        record = {"package_id": mapping[legacy_id].package_id}
        record.update(copy.deepcopy(legacy_record))
        detections.append(record)
    detections.sort(key=lambda item: item["package_id"])
    return {"schema_version": 2, "detections": detections}


def migrate_public_data(
    registry_contents,
    update_times_contents,
    platform_metadata_contents,
    certification_contents,
):
    legacy_registry = _strict_json_object(registry_contents, "legacy registry")
    mapping = _legacy_package_mapping(legacy_registry)
    certifications = _load_certifications(certification_contents)
    packages, missing, package_mappings = _certify_packages(
        mapping, certifications
    )
    renamed = [
        {
            "legacy_package_id": entry["legacy_package_id"],
            "package_id": entry["package_id"],
        }
        for entry in package_mappings
        if entry["legacy_package_id"] != entry["package_id"]
    ]
    report = {
        "schema_version": MIGRATION_REPORT_SCHEMA_VERSION,
        "status": "blocked" if missing else "ready",
        "package_count": len(mapping),
        "package_mappings": package_mappings,
        "renamed_packages": renamed,
        "missing_certifications": missing,
    }
    report_bytes = _canonical_bytes(report)
    if missing:
        return PublicDataMigration(False, None, None, None, report_bytes)

    registry = PackageRegistry(packages)
    registry_bytes = registry.to_bytes()
    # Reparse the exact output before converting dependent files.
    PackageRegistry.from_bytes(registry_bytes)
    update_times = _convert_update_times(
        _strict_json_object(update_times_contents, "legacy update_times"),
        mapping,
    )
    platform_metadata = _convert_platform_metadata(
        _strict_json_object(
            platform_metadata_contents, "legacy platform metadata"
        ),
        mapping,
    )
    return PublicDataMigration(
        True,
        registry_bytes,
        _canonical_bytes(update_times),
        _canonical_bytes(platform_metadata),
        report_bytes,
    )


def _atomic_write(path, contents):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix="." + target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, target)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _parser():
    parser = argparse.ArgumentParser(
        description="Migrate public PyPluginStore data to registry schema v2."
    )
    parser.add_argument("--registry", default="registry.json")
    parser.add_argument("--update-times", default="update_times.json")
    parser.add_argument(
        "--platform-metadata", default=".github/platform_detection.json"
    )
    parser.add_argument("--certifications", required=True)
    parser.add_argument(
        "--report", default=".github/package_identity_migration.json"
    )
    parser.add_argument("--write", action="store_true")
    return parser


def main(argv=None):
    arguments = _parser().parse_args(argv)
    try:
        result = migrate_public_data(
            Path(arguments.registry).read_bytes(),
            Path(arguments.update_times).read_bytes(),
            Path(arguments.platform_metadata).read_bytes(),
            Path(arguments.certifications).read_bytes(),
        )
        if arguments.write:
            _atomic_write(arguments.report, result.report_bytes)
            if result.ready:
                _atomic_write(arguments.registry, result.registry_bytes)
                _atomic_write(arguments.update_times, result.update_times_bytes)
                _atomic_write(
                    arguments.platform_metadata,
                    result.platform_metadata_bytes,
                )
        else:
            sys.stdout.buffer.write(result.report_bytes)
        return 0 if result.ready else 2
    except (OSError, ValueError) as error:
        print("Registry v2 migration failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
