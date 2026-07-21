#!/usr/bin/env python3
"""Fetch and certify exact Domoticz identities for a legacy registry cutover."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
for import_path in (REPO_ROOT, SCRIPT_DIR):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from cleanup_registry import headers_for_url  # noqa: E402
from package_identity import certify_plugin_py  # noqa: E402
from package_registry import PackageRegistry  # noqa: E402
from registry_records import RegistryRecord  # noqa: E402


CERTIFICATION_SCHEMA_VERSION = 1
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024


def _json_bytes(document):
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


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
        temporary_path = ""
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _load_legacy_registry(contents):
    if not isinstance(contents, (bytes, bytearray)):
        raise ValueError("registry contents must be bytes.")

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(
                    "Legacy registry contains duplicate JSON key " + key + "."
                )
            result[key] = value
        return result

    try:
        document = json.loads(
            bytes(contents).decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Legacy registry is not valid JSON.") from error
    if not isinstance(document, dict) or "schema_version" in document:
        raise ValueError("Identity discovery requires a legacy registry object.")
    registry = PackageRegistry.from_legacy_document(document)
    packages = {item.repository_identity: item for item in registry.packages}
    records = []
    for legacy_id, value in document.items():
        if legacy_id == "Idle":
            continue
        legacy_record = RegistryRecord.from_entry(legacy_id, value)
        normalized = PackageRegistry.from_legacy_document(
            {legacy_id: value}
        ).packages[0]
        package = packages[normalized.repository_identity]
        records.append((legacy_id, legacy_record, package))
    return sorted(records, key=lambda item: (item[0].casefold(), item[0]))


def _download(url, opener):
    request = urllib.request.Request(url, headers=headers_for_url(url))
    with opener(request, timeout=20) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise ValueError("plugin.py request returned HTTP " + str(status) + ".")
        contents = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(contents) > MAX_DOWNLOAD_BYTES:
        raise ValueError("plugin.py exceeds the download limit.")
    return contents


def _certify_record(record, opener):
    legacy_id, legacy_record, package = record
    identity = certify_plugin_py(_download(legacy_record.raw_plugin_url, opener))
    return {
        "legacy_package_id": legacy_id,
        "repository_identity": package.repository_identity,
        "branch": package.branch,
        "domoticz_key": identity.domoticz_key,
        "plugin_py_sha256": identity.plugin_py_sha256,
    }


def discover_identities(registry_contents, *, opener=None, workers=8):
    if type(workers) is not int or workers <= 0 or workers > 32:
        raise ValueError("workers must be between 1 and 32.")
    opener = opener or urllib.request.urlopen
    records = _load_legacy_registry(registry_contents)
    certifications = []
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {
            executor.submit(_certify_record, record, opener): record[0]
            for record in records
        }
        for future in as_completed(pending):
            legacy_id = pending[future]
            try:
                certifications.append(future.result())
            except Exception as error:
                failures.append(
                    {"legacy_package_id": legacy_id, "reason": str(error)}
                )
    certifications.sort(
        key=lambda item: (
            item["legacy_package_id"].casefold(),
            item["legacy_package_id"],
        )
    )
    failures.sort(
        key=lambda item: (
            item["legacy_package_id"].casefold(),
            item["legacy_package_id"],
        )
    )
    return {
        "schema_version": CERTIFICATION_SCHEMA_VERSION,
        "certifications": certifications,
        "failures": failures,
    }


def _parser():
    parser = argparse.ArgumentParser(
        description="Certify Domoticz plugin identities for registry v2."
    )
    parser.add_argument("--registry", default="registry.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8)
    return parser


def main(argv=None):
    arguments = _parser().parse_args(argv)
    try:
        document = discover_identities(
            Path(arguments.registry).read_bytes(),
            workers=arguments.workers,
        )
        _atomic_write(arguments.output, _json_bytes(document))
    except (OSError, ValueError) as error:
        print("Identity certification failed: " + str(error), file=sys.stderr)
        return 2
    if document["failures"]:
        print(
            "Identity certification incomplete: "
            + str(len(document["failures"]))
            + " package(s) failed.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
