"""CB-029D — static AST interface enrichment."""

from pathlib import Path

from backend.continuous_builder.context_engine import (
    AUTHORITY_FLAGS,
    enrich_interface_summary,
)


BASE = "d" * 64


def test_extracts_class_fn_constants_imports(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "mod.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "MAX_X = 3\n"
        "class Foo(object):\n"
        "    def bar(self, a, b=1):\n"
        "        return a\n"
        "def helper(x, *args, y=2, **kw):\n"
        "    return x\n",
        encoding="utf-8",
    )
    summary = enrich_interface_summary(root, base_sha=BASE, path="mod.py")
    assert summary.available is True
    assert any(c["name"] == "Foo" for c in summary.classes)
    foo = next(c for c in summary.classes if c["name"] == "Foo")
    assert any(m.startswith("bar(") for m in foo["methods"])
    # Defaults must not be evaluated/rendered as executed values.
    assert "b=1" not in foo["methods"][0]
    assert any(f.startswith("helper(") for f in summary.functions)
    assert "MAX_X" in summary.constants
    assert "json" in summary.imports
    assert any(i.startswith("pathlib:") for i in summary.imports)
    for name in AUTHORITY_FLAGS:
        assert getattr(summary, name) is False


def test_parse_failure_uncertainty(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "bad.py").write_text("def (\n", encoding="utf-8")
    summary = enrich_interface_summary(root, base_sha=BASE, path="bad.py")
    assert summary.available is False
    assert summary.restriction == "parse_failure"
    assert summary.classes == ()
    assert summary.functions == ()


def test_secret_path_not_parsed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    summary = enrich_interface_summary(root, base_sha=BASE, path=".env")
    assert summary.available is False
    assert summary.restriction is not None
    assert "SECRET" not in str(summary.to_dict())
