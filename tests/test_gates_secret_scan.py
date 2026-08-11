"""Tests for the V0.3D secret-scan gate (scripts/gates/secret_scan.py).

Uses `evaluate_files` (a pure function over (relative_path, content_bytes)
pairs) for nearly everything -- fast, and tests the actual detection logic
directly without touching a real filesystem. A small number of tests
exercise `evaluate_paths` against a real temp directory to prove the
filesystem-reading layer works.
"""

from scripts.gates.secret_scan import evaluate_files, evaluate_paths


def _b(text: str) -> bytes:
    return text.encode("utf-8")


# --- 4. Secret-like tracked files fail ---------------------------------------


def test_dotenv_file_is_denied_by_filename_alone():
    result = evaluate_files([(".env", _b("SOME_KEY=whatever\n"))])
    assert result.passed is False
    assert any(".env" in v and "must never be a tracked file" in v for v in result.violations)


def test_pem_private_key_file_is_denied_by_extension():
    result = evaluate_files([("secrets/server.pem", _b("anything"))])
    assert result.passed is False


def test_ssh_private_key_prefix_is_denied():
    result = evaluate_files([("id_rsa", _b("anything"))])
    assert result.passed is False
    assert any("private-key prefix" in v for v in result.violations)


def test_aws_style_access_key_in_content_is_flagged():
    result = evaluate_files([("backend/config.py", _b('KEY = "AKIAABCDEFGHIJKLMNOP"\n'))])
    assert result.passed is False
    assert any("AWS-style access key ID" in v for v in result.violations)


def test_openai_style_secret_key_in_content_is_flagged():
    result = evaluate_files(
        [("backend/config.py", _b('OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwx"\n'))]
    )
    assert result.passed is False
    assert any("OpenAI-style secret key" in v for v in result.violations)


def test_pem_private_key_header_in_content_is_flagged():
    result = evaluate_files(
        [("backend/oops.py", _b("KEY = '''-----BEGIN RSA PRIVATE KEY-----\\nMII...\\n'''\n"))]
    )
    assert result.passed is False
    assert any("PEM private key header" in v for v in result.violations)


def test_obviously_named_secret_variable_with_long_literal_is_flagged():
    result = evaluate_files(
        [("backend/settings.py", _b('SESSION_SECRET = "correct-horse-battery-staple-long"\n'))]
    )
    assert result.passed is False
    assert any("obviously-named secret variable" in v for v in result.violations)


def test_violation_reports_path_and_line_number():
    result = evaluate_files(
        [("backend/config.py", _b('x = 1\ny = 2\nAPI_KEY = "abcdefghijklmnopqrstuvwx"\n'))]
    )
    assert any(v.startswith("backend/config.py:3:") for v in result.violations)


# --- 5. Harmless .env.example remains allowed --------------------------------


def test_env_example_is_allowed_by_filename():
    result = evaluate_files([(".env.example", _b("API_KEY=your-key-here\n"))])
    assert result.passed is True


def test_env_sample_and_env_template_are_also_allowed():
    result = evaluate_files(
        [
            (".env.sample", _b("SECRET_KEY=changeme\n")),
            (".env.template", _b("PASSWORD=changeme\n")),
        ]
    )
    assert result.passed is True


def test_env_example_with_a_realistic_placeholder_still_passes_content_scan():
    """The filename allow-list short-circuits the filename check, but the
    content-pattern check still runs on it -- so a genuinely long literal
    secret pasted into .env.example (not just a short placeholder) would
    still legitimately be caught. This test uses a clearly non-matching
    placeholder to confirm the ordinary/expected case stays clean."""
    result = evaluate_files([(".env.example", _b("API_KEY=CHANGE_ME\n"))])
    assert result.passed is True


# --- 6. Database files fail ---------------------------------------------------


def test_sqlite_db_file_is_denied():
    result = evaluate_files([("data/mootos.db", _b("SQLite format 3"))])
    assert result.passed is False
    assert any("denied suffix (.db)" in v for v in result.violations)


def test_sqlite3_extension_is_denied():
    result = evaluate_files([("backup/dump.sqlite3", _b("binary junk"))])
    assert result.passed is False


def test_sqlite_extension_is_denied():
    result = evaluate_files([("backup/dump.sqlite", _b("binary junk"))])
    assert result.passed is False


# --- Ordinary files pass ------------------------------------------------------


def test_ordinary_source_file_with_no_secrets_passes():
    result = evaluate_files(
        [("backend/tools_reference.py", _b("def build_tools():\n    return []\n"))]
    )
    assert result.passed is True
    assert "PASS" in result.summary()


def test_ordinary_markdown_docs_pass():
    result = evaluate_files([("docs/TOOL_SYSTEM.md", _b("# Tool System\n\nSome docs.\n"))])
    assert result.passed is True


def test_short_assigned_literal_below_length_threshold_is_not_flagged():
    """A 5-character placeholder assigned to an obviously-named variable
    does not meet the 16+ char threshold meant to distinguish a real
    secret from a short, harmless-looking test/default value."""
    result = evaluate_files([("backend/settings.py", _b('API_KEY = "short"\n'))])
    assert result.passed is True


# --- Adversarial: attempts to evade the secret-scan gate ---------------------


def test_key_split_across_string_concatenation_is_not_caught_by_design():
    """Documents a known, accepted limitation rather than pretending to
    catch it: splitting a key across concatenated string literals defeats
    the single-line regex scan. This is exactly the 'not proof of
    absence' limitation stated in the gate's module docstring."""
    result = evaluate_files(
        [("backend/sneaky.py", _b('KEY = "AKIAABCDE" + "FGHIJKLMNOP"\n'))]
    )
    assert result.passed is True  # known limitation, asserted explicitly


def test_binary_content_is_skipped_by_content_scan_but_filename_check_still_applies():
    binary_content = bytes([0xFF, 0xFE, 0x00, 0x01, 0x02]) * 10
    result = evaluate_files([("backend/blob.bin", binary_content)])
    assert result.passed is True  # not a denied filename, and content scan skips binary


def test_binary_looking_db_file_is_still_caught_by_filename_even_though_content_is_skipped():
    binary_content = bytes([0xFF, 0xFE, 0x00, 0x01, 0x02]) * 10
    result = evaluate_files([("data/app.db", binary_content)])
    assert result.passed is False


def test_oversized_file_skips_content_scan_but_not_filename_check():
    huge_but_harmless = _b("x = 1\n" * 100_000)  # well over MAX_SCANNED_FILE_BYTES
    result = evaluate_files([("backend/generated.py", huge_but_harmless)])
    assert result.passed is True  # too large to scan, and filename is fine


def test_renaming_env_to_avoid_the_exact_filename_match_produces_a_differently_named_file_not_a_bypass():
    """`.env.local` or `.env.production` are not literally `.env` and are
    not in ALLOWED_FILENAMES either -- they simply fall through both
    checks today. This test documents current behavior (neither denied
    nor explicitly allowed) rather than asserting a stronger guarantee
    the implementation doesn't make."""
    result = evaluate_files([(".env.local", _b("SECRET=whatever\n"))])
    assert result.passed is True  # documents current scope, not a claimed guarantee


def test_multiple_findings_in_one_file_are_all_reported():
    content = _b('AWS = "AKIAABCDEFGHIJKLMNOP"\nOPENAI = "sk-abcdefghijklmnopqrstuvwx"\n')
    result = evaluate_files([("backend/config.py", content)])
    assert len(result.violations) == 2


def test_denied_filename_short_circuits_content_scan_for_that_file():
    """A denied filename is already fatal on its own; the implementation
    does not also run (and duplicate-report from) the content scan on it."""
    content = _b('AKIAABCDEFGHIJKLMNOP\n')
    result = evaluate_files([(".env", content)])
    assert len(result.violations) == 1


# --- filesystem-backed integration -------------------------------------------


def test_evaluate_paths_reads_real_files_from_a_temp_directory(tmp_path):
    (tmp_path / "backend").mkdir()
    clean_file = tmp_path / "backend" / "clean.py"
    clean_file.write_text("def f():\n    return 1\n", encoding="utf-8")
    secret_file = tmp_path / ".env"
    secret_file.write_text("KEY=whatever\n", encoding="utf-8")

    result = evaluate_paths(["backend/clean.py", ".env"], tmp_path)
    assert result.passed is False
    assert any(".env" in v for v in result.violations)


def test_evaluate_paths_skips_a_path_that_no_longer_exists(tmp_path):
    """A deleted file has nothing to scan -- must not raise."""
    result = evaluate_paths(["backend/deleted_file.py"], tmp_path)
    assert result.passed is True


def test_evaluate_paths_against_the_real_repository_env_example_passes():
    from pathlib import Path

    repository_root = Path(__file__).resolve().parent.parent
    result = evaluate_paths([".env.example"], repository_root)
    assert result.passed is True, result.summary()
