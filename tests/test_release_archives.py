import stat
import struct
import warnings
import zipfile
from pathlib import Path

import pytest


ROOT_PREFIX = "example-v1"


def write_zip(path, entries, compression=zipfile.ZIP_DEFLATED):
    """Write small ZIP fixtures, including duplicate and special-mode entries."""
    with zipfile.ZipFile(path, "w") as archive:
        for entry in entries:
            name, contents = entry[:2]
            mode = entry[2] if len(entry) > 2 else None
            if isinstance(contents, str):
                contents = contents.encode("utf-8")

            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            if mode is not None:
                info.create_system = 3
                info.external_attr = (mode & 0xFFFF) << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(info, contents)
    return path


def patch_flag_bits(path, flag):
    contents = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while True:
            offset = contents.find(signature, start)
            if offset < 0:
                break
            current = struct.unpack_from("<H", contents, offset + flag_offset)[0]
            struct.pack_into(
                "<H", contents, offset + flag_offset, current | flag
            )
            start = offset + len(signature)
    path.write_bytes(contents)


def patch_filename(path, original, replacement):
    original = original.encode("utf-8")
    replacement = replacement.encode("utf-8")
    assert len(original) == len(replacement)
    contents = path.read_bytes()
    assert contents.count(original) >= 2
    path.write_bytes(contents.replace(original, replacement))


def corrupt_first_stored_payload(path):
    contents = bytearray(path.read_bytes())
    local_header = contents.find(b"PK\x03\x04")
    assert local_header >= 0
    name_length = struct.unpack_from("<H", contents, local_header + 26)[0]
    extra_length = struct.unpack_from("<H", contents, local_header + 28)[0]
    payload_offset = local_header + 30 + name_length + extra_length
    contents[payload_offset] ^= 0x01
    path.write_bytes(contents)


def patch_local_filename(path, original, replacement):
    """Create a local/central filename mismatch without changing ZIP lengths."""
    original = original.encode("utf-8")
    replacement = replacement.encode("utf-8")
    assert len(original) == len(replacement)
    contents = bytearray(path.read_bytes())
    local_header = contents.find(b"PK\x03\x04")
    assert local_header >= 0
    name_length = struct.unpack_from("<H", contents, local_header + 26)[0]
    name_offset = local_header + 30
    assert bytes(contents[name_offset : name_offset + name_length]) == original
    contents[name_offset : name_offset + name_length] = replacement
    path.write_bytes(contents)


def corrupt_unique_payload(path, payload):
    contents = bytearray(path.read_bytes())
    assert contents.count(payload) == 1
    contents[contents.index(payload)] ^= 0x01
    path.write_bytes(contents)


def make_extractor(plugin_core_module, **limits):
    archive_limits = plugin_core_module.ReleaseArchiveLimits(**limits)
    return plugin_core_module.SafeZipExtractor(archive_limits)


def assert_archive_rejected(
    plugin_core_module,
    archive_path,
    tmp_path,
    *,
    expected_root_prefix=ROOT_PREFIX,
    limits=None,
):
    destination = tmp_path / "extracted"
    extractor = make_extractor(plugin_core_module, **(limits or {}))

    with pytest.raises(ValueError):
        extractor.extract(
            str(archive_path),
            str(destination),
            expected_root_prefix=expected_root_prefix,
        )

    assert not destination.exists()


def test_safe_zip_extractor_accepts_a_valid_single_root_archive(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "valid.zip",
        [
            (ROOT_PREFIX + "/", b"", stat.S_IFDIR | 0o755),
            (
                ROOT_PREFIX + "/plugin.py",
                "print('valid')\n",
                stat.S_IFREG | 0o644,
            ),
            (ROOT_PREFIX + "/README.md", "Valid plugin\n"),
            (ROOT_PREFIX + "/config/", b"", stat.S_IFDIR | 0o755),
            (ROOT_PREFIX + "/config/default.json", "{}\n"),
        ],
    )
    destination = tmp_path / "extracted"
    extractor = make_extractor(plugin_core_module)

    result = extractor.extract(
        str(archive_path),
        str(destination),
        expected_root_prefix=ROOT_PREFIX,
    )

    assert result.root_prefix == ROOT_PREFIX
    assert Path(result.root_path) == destination / ROOT_PREFIX
    assert result.file_count == 3
    assert result.expanded_size == sum(
        len(contents.encode("utf-8"))
        for contents in ("print('valid')\n", "Valid plugin\n", "{}\n")
    )
    assert (destination / ROOT_PREFIX / "plugin.py").read_text(
        encoding="utf-8"
    ) == "print('valid')\n"
    assert (destination / ROOT_PREFIX / "config" / "default.json").is_file()


def test_release_archive_limits_match_reviewed_defaults(plugin_core_module):
    limits = plugin_core_module.ReleaseArchiveLimits()

    assert limits.max_archive_size == 50 * 1024 * 1024
    assert limits.max_expanded_size == 250 * 1024 * 1024
    assert limits.max_entries == 5000
    assert limits.max_file_size == 50 * 1024 * 1024
    assert limits.max_compression_ratio == 100.0


@pytest.mark.parametrize(
    "member_name",
    [
        ROOT_PREFIX + "/../escape.py",
        ROOT_PREFIX + "/nested/../../escape.py",
        "../" + ROOT_PREFIX + "/plugin.py",
    ],
)
def test_safe_zip_extractor_rejects_parent_traversal(
    plugin_core_module, tmp_path, member_name
):
    archive_path = write_zip(
        tmp_path / "traversal.zip", [(member_name, "unsafe")]
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "member_name",
    [
        "/absolute/plugin.py",
        "//server/share/plugin.py",
        "\\\\server\\share\\plugin.py",
        "C:/Windows/plugin.py",
        "C:\\Windows\\plugin.py",
        "C:relative-drive.py",
    ],
)
def test_safe_zip_extractor_rejects_absolute_unc_and_drive_paths(
    plugin_core_module, tmp_path, member_name
):
    archive_path = write_zip(
        tmp_path / "absolute.zip", [(member_name, "unsafe")]
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "member_name",
    [
        ROOT_PREFIX + "\\nested\\plugin.py",
        ROOT_PREFIX + "\\..\\escape.py",
        ROOT_PREFIX + "/nested\\..\\escape.py",
    ],
)
def test_safe_zip_extractor_rejects_backslash_paths(
    plugin_core_module, tmp_path, member_name
):
    archive_path = write_zip(
        tmp_path / "backslash.zip", [(member_name, "unsafe")]
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "special_mode",
    [
        stat.S_IFLNK | 0o777,
        stat.S_IFCHR | 0o600,
        stat.S_IFBLK | 0o600,
        stat.S_IFIFO | 0o600,
        stat.S_IFSOCK | 0o600,
    ],
    ids=("symlink", "character-device", "block-device", "fifo", "socket"),
)
def test_safe_zip_extractor_rejects_links_devices_and_fifos(
    plugin_core_module, tmp_path, special_mode
):
    archive_path = write_zip(
        tmp_path / "special.zip",
        [(ROOT_PREFIX + "/special", "target", special_mode)],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "member_name",
    [
        ROOT_PREFIX + "/control\x01.py",
        ROOT_PREFIX + "/tab\x09.py",
        ROOT_PREFIX + "/newline\x0a.py",
        ROOT_PREFIX + "/carriage-return\x0d.py",
        ROOT_PREFIX + "/delete\x7f.py",
    ],
)
def test_safe_zip_extractor_rejects_control_bytes_in_names(
    plugin_core_module, tmp_path, member_name
):
    archive_path = write_zip(
        tmp_path / "control.zip", [(member_name, "unsafe")]
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_rejects_nul_in_original_member_name(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "nul.zip",
        [(ROOT_PREFIX + "/nulXname.py", "unsafe")],
    )
    patch_filename(
        archive_path,
        ROOT_PREFIX + "/nulXname.py",
        ROOT_PREFIX + "/nul\x00name.py",
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "flag_bits",
    [
        pytest.param(0x1, id="traditional-encryption"),
        pytest.param(0x41, id="strong-encryption"),
    ],
)
def test_safe_zip_extractor_rejects_encrypted_members(
    plugin_core_module, tmp_path, flag_bits
):
    archive_path = write_zip(
        tmp_path / "encrypted.zip",
        [(ROOT_PREFIX + "/plugin.py", "encrypted")],
    )
    patch_flag_bits(archive_path, flag_bits)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_rejects_duplicate_member_names(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "duplicate.zip",
        [
            (ROOT_PREFIX + "/plugin.py", "first"),
            (ROOT_PREFIX + "/plugin.py", "second"),
        ],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "first_name,second_name",
    [
        ("Plugin.py", "plugin.py"),
        ("Straße.py", "STRASSE.py"),
        ("café.py", "cafe\u0301.py"),
    ],
    ids=("ascii-case", "unicode-casefold", "unicode-nfc"),
)
def test_safe_zip_extractor_rejects_casefold_and_unicode_collisions(
    plugin_core_module, tmp_path, first_name, second_name
):
    archive_path = write_zip(
        tmp_path / "collision.zip",
        [
            (ROOT_PREFIX + "/" + first_name, "first"),
            (ROOT_PREFIX + "/" + second_name, "second"),
        ],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "first_directory,second_directory",
    [
        pytest.param("Config", "config", id="casefold-components"),
        pytest.param("café", "cafe\u0301", id="nfc-components"),
    ],
)
def test_safe_zip_extractor_rejects_colliding_directory_components(
    plugin_core_module, tmp_path, first_directory, second_directory
):
    archive_path = write_zip(
        tmp_path / "directory-component-collision.zip",
        [
            (ROOT_PREFIX + "/" + first_directory + "/one.json", "1"),
            (ROOT_PREFIX + "/" + second_directory + "/two.json", "2"),
        ],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_rejects_a_single_non_nfc_member_name(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "non-nfc.zip",
        [(ROOT_PREFIX + "/cafe\u0301.json", "nonportable")],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "member_name",
    [
        "CON.txt",
        "aux",
        "PRN.json",
        "NUL.py",
        "COM1.log",
        "com9",
        "LPT1.txt",
        "lpt9",
        "CON/settings.json",
        "nested/AUX/data.json",
        "COM1/plugin.py",
    ],
)
def test_safe_zip_extractor_rejects_windows_reserved_names(
    plugin_core_module, tmp_path, member_name
):
    archive_path = write_zip(
        tmp_path / "reserved-name.zip",
        [(ROOT_PREFIX + "/" + member_name, "unsafe")],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "member_name",
    [
        ROOT_PREFIX + "/trailing-dot.",
        ROOT_PREFIX + "/trailing-space ",
        ROOT_PREFIX + "/folder./plugin.py",
        ROOT_PREFIX + "/folder /plugin.py",
    ],
)
def test_safe_zip_extractor_rejects_trailing_dots_and_spaces(
    plugin_core_module, tmp_path, member_name
):
    archive_path = write_zip(
        tmp_path / "trailing.zip", [(member_name, "unsafe")]
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "entries",
    [
        [
            (ROOT_PREFIX + "/data", "file"),
            (ROOT_PREFIX + "/data/settings.json", "{}"),
        ],
        [
            (ROOT_PREFIX + "/data/settings.json", "{}"),
            (ROOT_PREFIX + "/data", "file"),
        ],
        [
            (ROOT_PREFIX + "/Data", "file"),
            (ROOT_PREFIX + "/data/settings.json", "{}"),
        ],
        [
            (ROOT_PREFIX + "/data/", b"", stat.S_IFDIR | 0o755),
            (ROOT_PREFIX + "/data", "file"),
        ],
    ],
    ids=("file-first", "child-first", "casefold-prefix", "directory-file"),
)
def test_safe_zip_extractor_rejects_directory_file_prefix_collisions(
    plugin_core_module, tmp_path, entries
):
    archive_path = write_zip(tmp_path / "prefix.zip", entries)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "entries",
    [
        [
            (ROOT_PREFIX + "/plugin.py", "valid"),
            ("second-root/README.md", "ambiguous"),
        ],
        [(ROOT_PREFIX + "/plugin.py", "valid"), ("root-file.txt", "extra")],
        [],
    ],
    ids=("two-wrappers", "wrapper-and-root-file", "empty"),
)
def test_safe_zip_extractor_rejects_ambiguous_or_missing_roots(
    plugin_core_module, tmp_path, entries
):
    archive_path = write_zip(tmp_path / "roots.zip", entries)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_requires_the_indexed_root_prefix(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "wrong-root.zip", [("different-root/plugin.py", "valid")]
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize("archive_root", ["Example-v1", "example-V1"])
def test_safe_zip_extractor_matches_the_indexed_root_prefix_exactly(
    plugin_core_module, tmp_path, archive_root
):
    archive_path = write_zip(
        tmp_path / "root-case.zip",
        [(archive_root + "/plugin.py", "valid")],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_rejects_expected_root_that_is_a_file(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "root-file.zip", [(ROOT_PREFIX, "not a wrapper")]
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


@pytest.mark.parametrize(
    "member_name",
    [
        ".pypluginstore.json",
        ".PyPluginStore.JSON",
        ".pypluginstore/channels.json",
        ".PyPluginStore/transactions/pending.json",
        ".git/config",
        ".hg/store/requires",
        ".svn/wc.db",
        ".bzr/branch/last-revision",
    ],
)
def test_safe_zip_extractor_rejects_manager_and_vcs_metadata(
    plugin_core_module, tmp_path, member_name
):
    archive_path = write_zip(
        tmp_path / "manager-metadata.zip",
        [(ROOT_PREFIX + "/" + member_name, "unsafe")],
    )

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_enforces_compressed_archive_limit(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "archive-size.zip",
        [(ROOT_PREFIX + "/plugin.py", "small")],
        compression=zipfile.ZIP_STORED,
    )

    assert archive_path.stat().st_size > 64
    assert_archive_rejected(
        plugin_core_module,
        archive_path,
        tmp_path,
        limits={"max_archive_size": 64},
    )


def test_safe_zip_extractor_enforces_per_file_limit(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "file-size.zip", [(ROOT_PREFIX + "/large.bin", b"12345")]
    )

    assert_archive_rejected(
        plugin_core_module,
        archive_path,
        tmp_path,
        limits={"max_file_size": 4},
    )


def test_safe_zip_extractor_enforces_member_count_limit(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "count.zip",
        [
            (ROOT_PREFIX + "/one", "1"),
            (ROOT_PREFIX + "/two", "2"),
            (ROOT_PREFIX + "/three", "3"),
        ],
    )

    assert_archive_rejected(
        plugin_core_module,
        archive_path,
        tmp_path,
        limits={"max_entries": 2},
    )


def test_safe_zip_extractor_counts_explicit_directory_members(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "directory-count.zip",
        [
            (ROOT_PREFIX + "/", b"", stat.S_IFDIR | 0o755),
            (ROOT_PREFIX + "/config/", b"", stat.S_IFDIR | 0o755),
            (ROOT_PREFIX + "/config/value.json", "{}"),
        ],
    )

    assert_archive_rejected(
        plugin_core_module,
        archive_path,
        tmp_path,
        limits={"max_entries": 2},
    )


def test_safe_zip_extractor_enforces_total_expansion_limit(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "expanded.zip",
        [
            (ROOT_PREFIX + "/one", b"1234"),
            (ROOT_PREFIX + "/two", b"5678"),
        ],
    )

    assert_archive_rejected(
        plugin_core_module,
        archive_path,
        tmp_path,
        limits={"max_expanded_size": 7},
    )


def test_safe_zip_extractor_rejects_suspicious_compression_ratio(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "ratio.zip",
        [(ROOT_PREFIX + "/zeros.bin", b"\x00" * 1024)],
    )

    assert_archive_rejected(
        plugin_core_module,
        archive_path,
        tmp_path,
        limits={"max_compression_ratio": 2.0},
    )


def test_safe_zip_extractor_enforces_ratio_for_each_member(
    plugin_core_module, tmp_path
):
    archive_path = tmp_path / "per-member-ratio.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            ROOT_PREFIX + "/bomb.bin",
            b"\x00" * 4096,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            ROOT_PREFIX + "/stored.bin",
            bytes(range(256)) * 32,
            compress_type=zipfile.ZIP_STORED,
        )

    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        assert members[0].file_size / members[0].compress_size > 10.0
        assert sum(member.file_size for member in members) / sum(
            member.compress_size for member in members
        ) < 10.0

    assert_archive_rejected(
        plugin_core_module,
        archive_path,
        tmp_path,
        limits={"max_compression_ratio": 10.0},
    )


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("max_archive_size", True, id="archive-boolean"),
        pytest.param("max_expanded_size", 0, id="expanded-zero"),
        pytest.param("max_entries", -1, id="entries-negative"),
        pytest.param("max_file_size", 1.5, id="file-fractional"),
        pytest.param("max_compression_ratio", 0, id="ratio-zero"),
        pytest.param(
            "max_compression_ratio", float("inf"), id="ratio-infinite"
        ),
        pytest.param(
            "max_compression_ratio", float("nan"), id="ratio-not-a-number"
        ),
    ],
)
def test_release_archive_limits_reject_unbounded_or_ambiguous_values(
    plugin_core_module, field, value
):
    with pytest.raises(ValueError):
        plugin_core_module.ReleaseArchiveLimits(**{field: value})


@pytest.mark.parametrize("contents", [b"not a zip", b"PK\x03\x04truncated"])
def test_safe_zip_extractor_rejects_malformed_zip_bytes(
    plugin_core_module, tmp_path, contents
):
    archive_path = tmp_path / "malformed.zip"
    archive_path.write_bytes(contents)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_rejects_truncated_valid_zip(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "truncated.zip", [(ROOT_PREFIX + "/plugin.py", "valid")]
    )
    archive_path.write_bytes(archive_path.read_bytes()[:-12])

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_rejects_symlink_archive_path(
    plugin_core_module, tmp_path
):
    target = write_zip(
        tmp_path / "target.zip",
        [(ROOT_PREFIX + "/plugin.py", "valid")],
    )
    archive_path = tmp_path / "release.zip"
    try:
        archive_path.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("Symbolic links are unavailable on this test host.")

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_rejects_archive_replaced_while_opening(
    plugin_core_module, tmp_path, monkeypatch
):
    archive_path = write_zip(
        tmp_path / "release.zip",
        [(ROOT_PREFIX + "/plugin.py", "original")],
    )
    replacement = write_zip(
        tmp_path / "replacement.zip",
        [(ROOT_PREFIX + "/plugin.py", "replacement")],
    )
    real_open = plugin_core_module.os.open
    replaced = []

    def replace_then_open(path, flags, *args):
        if path == str(archive_path) and not replaced:
            replacement.replace(archive_path)
            replaced.append(True)
        return real_open(path, flags, *args)

    monkeypatch.setattr(plugin_core_module.os, "open", replace_then_open)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)
    assert replaced == [True]


def test_safe_zip_extractor_rejects_local_central_filename_mismatch(
    plugin_core_module, tmp_path
):
    central_name = ROOT_PREFIX + "/xx/evil.py"
    local_name = ROOT_PREFIX + "/../evil.py"
    archive_path = write_zip(
        tmp_path / "mismatched-name.zip", [(central_name, "unsafe")]
    )
    patch_local_filename(archive_path, central_name, local_name)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_validates_member_crc_before_writing(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "bad-crc.zip",
        [(ROOT_PREFIX + "/plugin.py", b"valid")],
        compression=zipfile.ZIP_STORED,
    )
    corrupt_first_stored_payload(archive_path)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_late_crc_failure_removes_every_partially_extracted_member(
    plugin_core_module, tmp_path
):
    late_payload = b"unique late crc payload"
    archive_path = write_zip(
        tmp_path / "late-bad-crc.zip",
        [
            (ROOT_PREFIX + "/first.py", b"first is valid"),
            (ROOT_PREFIX + "/second.py", late_payload),
        ],
        compression=zipfile.ZIP_STORED,
    )
    corrupt_unique_payload(archive_path, late_payload)

    assert_archive_rejected(plugin_core_module, archive_path, tmp_path)


def test_safe_zip_extractor_requires_a_new_destination(
    plugin_core_module, tmp_path
):
    archive_path = write_zip(
        tmp_path / "valid.zip", [(ROOT_PREFIX + "/plugin.py", "valid")]
    )
    destination = tmp_path / "extracted"
    destination.mkdir()
    extractor = make_extractor(plugin_core_module)

    with pytest.raises(ValueError):
        extractor.extract(
            str(archive_path),
            str(destination),
            expected_root_prefix=ROOT_PREFIX,
        )

    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("destination_kind", ["file", "nonempty-directory"])
def test_safe_zip_extractor_never_reuses_an_existing_destination(
    plugin_core_module, tmp_path, destination_kind
):
    archive_path = write_zip(
        tmp_path / "valid-existing-target.zip",
        [(ROOT_PREFIX + "/plugin.py", "valid")],
    )
    destination = tmp_path / "extracted"
    marker = b"existing data must survive"
    if destination_kind == "file":
        destination.write_bytes(marker)
    else:
        destination.mkdir()
        (destination / "marker").write_bytes(marker)
    extractor = make_extractor(plugin_core_module)

    with pytest.raises(ValueError):
        extractor.extract(
            str(archive_path),
            str(destination),
            expected_root_prefix=ROOT_PREFIX,
        )

    if destination_kind == "file":
        assert destination.read_bytes() == marker
    else:
        assert (destination / "marker").read_bytes() == marker
