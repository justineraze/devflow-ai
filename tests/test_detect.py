"""Tests for devflow.detect — stack detection."""

from pathlib import Path

from devflow.detect import detect_stack


class TestDetectStack:
    def test_python_project(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").touch()
        (tmp_path / "utils.py").touch()
        assert detect_stack(tmp_path) == "python"

    def test_typescript_project(self, tmp_path: Path) -> None:
        (tmp_path / "index.ts").touch()
        (tmp_path / "app.tsx").touch()
        assert detect_stack(tmp_path) == "typescript"

    def test_php_project(self, tmp_path: Path) -> None:
        (tmp_path / "index.php").touch()
        (tmp_path / "routes.php").touch()
        assert detect_stack(tmp_path) == "php"

    def test_mixed_project_returns_majority(self, tmp_path: Path) -> None:
        # 3 Python files vs 1 TypeScript file.
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.py").touch()
        (tmp_path / "d.ts").touch()
        assert detect_stack(tmp_path) == "python"

    def test_empty_project(self, tmp_path: Path) -> None:
        assert detect_stack(tmp_path) is None

    def test_no_recognized_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.md").touch()
        (tmp_path / "data.csv").touch()
        assert detect_stack(tmp_path) is None

    def test_ignores_git_directory(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)
        (git_dir / "pre-commit.py").touch()
        # Only the .git python file — should be ignored.
        assert detect_stack(tmp_path) is None

    def test_ignores_node_modules(self, tmp_path: Path) -> None:
        nm = tmp_path / "node_modules" / "lodash"
        nm.mkdir(parents=True)
        (nm / "index.js").touch()
        (nm / "utils.js").touch()
        # Real source file.
        (tmp_path / "app.py").touch()
        assert detect_stack(tmp_path) == "python"

    def test_ignores_venv(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "site.py").touch()
        assert detect_stack(tmp_path) is None

    def test_js_jsx_count_as_typescript(self, tmp_path: Path) -> None:
        (tmp_path / "app.js").touch()
        (tmp_path / "widget.jsx").touch()
        assert detect_stack(tmp_path) == "typescript"

    def test_nested_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "devflow"
        src.mkdir(parents=True)
        (src / "cli.py").touch()
        (src / "models.py").touch()
        assert detect_stack(tmp_path) == "python"
