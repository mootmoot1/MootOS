"""CB-029B — trusted excerpt extraction and secret exclusion."""

from pathlib import Path

import pytest

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    ContextEngineError,
    classify_secret_path,
    extract_excerpt,
)


BASE = "b" * 64


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_extract_line_region_binds_digests(tmp_path):
    root = tmp_path / "repo"
    body = "one\ntwo\nthree\nfour\n"
    _write(root / "mod.py", body)
    ex = extract_excerpt(
        root, base_sha=BASE, path="mod.py", region=(2, 3), budget_bytes=1024
    )
    assert ex.available is True
    assert ex.text == "two\nthree\n"
    assert ex.start_line == 2 and ex.end_line == 3
    assert ex.path == "mod.py"
    assert ex.base_sha == BASE
    assert ex.truncated is False
    assert len(ex.file_sha256) == 64
    assert len(ex.excerpt_sha256) == 64
    for name in AUTHORITY_FLAGS:
        assert getattr(ex, name) is False


def test_truncation_flag_under_budget(tmp_path):
    root = tmp_path / "repo"
    lines = [f"line-{i}-{'x' * 40}\n" for i in range(50)]
    _write(root / "big.py", "".join(lines))
    ex = extract_excerpt(
        root, base_sha=BASE, path="big.py", budget_bytes=256
    )
    assert ex.available is True
    assert ex.truncated is True
    assert len(ex.text.encode("utf-8")) <= 256


def test_binary_unavailable(tmp_path):
    root = tmp_path / "repo"
    path = root / "blob.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x01\x02\xff" * 20)
    ex = extract_excerpt(root, base_sha=BASE, path="blob.bin")
    assert ex.available is False
    assert ex.text == ""
    assert ex.restriction == "non_text"


def test_symlink_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "real.py"
    target.write_text("print(1)\n", encoding="utf-8")
    link = root / "link.py"
    link.symlink_to(target)
    ex = extract_excerpt(root, base_sha=BASE, path="link.py")
    assert ex.available is False
    assert ex.restriction == "symlink_rejected"
    assert "print" not in ex.text


def test_traversal_and_absolute_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    # Fail-closed: unavailable structured restriction, never raises secret bytes.
    esc = extract_excerpt(root, base_sha=BASE, path="../escape.py")
    assert esc.available is False
    assert esc.text == ""
    assert esc.restriction in ("malformed_path", "path_rejected", "path_unavailable")
    abs_ex = extract_excerpt(root, base_sha=BASE, path="/etc/passwd")
    assert abs_ex.available is False
    assert abs_ex.text == ""


def test_git_and_db_rejected(tmp_path):
    root = tmp_path / "repo"
    _write(root / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(root / "data" / "mootos.db-wal", "wal")
    git_ex = extract_excerpt(root, base_sha=BASE, path=".git/HEAD")
    assert git_ex.available is False
    assert git_ex.restriction in ("git_path_rejected", "secret_path_segment") or (
        git_ex.restriction == "git_path_rejected"
    )
    assert git_ex.text == ""
    db_ex = extract_excerpt(root, base_sha=BASE, path="data/mootos.db-wal")
    assert db_ex.available is False
    assert db_ex.text == ""


def test_env_secret_never_leaks_bytes(tmp_path):
    root = tmp_path / "repo"
    secret = "SUPER_SECRET_VALUE_DO_NOT_LEAK=1\n"
    _write(root / ".env", secret)
    _write(root / ".env.local", secret)
    _write(root / "config" / "credentials.json", '{"key":"leak"}\n')
    _write(root / ".ssh" / "id_rsa", "-----BEGIN " + "RSA PRIVATE KEY-----\nAA\n")
    for rel in (".env", ".env.local", "config/credentials.json", ".ssh/id_rsa"):
        ex = extract_excerpt(root, base_sha=BASE, path=rel)
        assert ex.available is False
        assert ex.text == ""
        assert "SUPER_SECRET" not in ex.text
        assert "leak" not in ex.text
        assert "BEGIN RSA" not in ex.text
        assert ex.restriction is not None
        # Restriction codes must not embed secret bytes.
        assert "SUPER_SECRET" not in ex.restriction
        assert "AA" not in (ex.restriction or "")


def test_secret_content_markers_fail_closed(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "notes.py",
        "# helper\nAuthorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\n",
    )
    ex = extract_excerpt(root, base_sha=BASE, path="notes.py")
    assert ex.available is False
    assert ex.restriction == "secret_content"
    assert "eyJ" not in ex.text
    assert "Bearer" not in ex.text


def test_env_example_allowed(tmp_path):
    root = tmp_path / "repo"
    _write(root / ".env.example", "API_KEY=\n")
    assert classify_secret_path(".env.example") is None
    ex = extract_excerpt(root, base_sha=BASE, path=".env.example")
    assert ex.available is True
    assert "API_KEY=" in ex.text


def test_classify_secret_path_table():
    assert classify_secret_path(".env") == "secret_filename"
    assert classify_secret_path("keys/server.pem") == "secret_key_material"
    assert classify_secret_path("backend/ok.py") is None
    assert classify_secret_path("foo/api_key.txt") == "secret_api_key_file"
