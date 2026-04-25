"""Tests for devflow.integrations.detect — stack detection."""

from pathlib import Path

from devflow.integrations.detect import detect_stack


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


class TestFrontendDetection:
    """A typescript project with a frontend framework should resolve to 'frontend'."""

    def _ts_project(self, tmp_path: Path) -> None:
        (tmp_path / "index.ts").touch()
        (tmp_path / "app.tsx").touch()

    def test_react_project_detected_as_frontend(self, tmp_path: Path) -> None:
        import json
        self._ts_project(tmp_path)
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
        }))
        assert detect_stack(tmp_path) == "frontend"

    def test_next_project_detected_as_frontend(self, tmp_path: Path) -> None:
        import json
        self._ts_project(tmp_path)
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"next": "^14.0.0"},
        }))
        assert detect_stack(tmp_path) == "frontend"

    def test_devdependencies_count(self, tmp_path: Path) -> None:
        import json
        self._ts_project(tmp_path)
        (tmp_path / "package.json").write_text(json.dumps({
            "devDependencies": {"vue": "^3.0.0"},
        }))
        assert detect_stack(tmp_path) == "frontend"

    def test_typescript_without_framework_stays_typescript(self, tmp_path: Path) -> None:
        import json
        self._ts_project(tmp_path)
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"express": "^4.0.0"},
        }))
        assert detect_stack(tmp_path) == "typescript"

    def test_no_package_json_stays_typescript(self, tmp_path: Path) -> None:
        self._ts_project(tmp_path)
        assert detect_stack(tmp_path) == "typescript"

    def test_malformed_package_json_stays_typescript(self, tmp_path: Path) -> None:
        self._ts_project(tmp_path)
        (tmp_path / "package.json").write_text("{not valid json")
        assert detect_stack(tmp_path) == "typescript"

    def test_python_project_with_react_package_stays_python(self, tmp_path: Path) -> None:
        """Frontend promotion only applies when the primary language is JS/TS."""
        import json
        (tmp_path / "main.py").touch()
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18.0.0"},
        }))
        assert detect_stack(tmp_path) == "python"


class TestResolveStack:
    """Tests for resolve_stack — saved state takes precedence over detection."""

    def test_uses_saved_config_when_present(self, tmp_path: Path) -> None:
        from devflow.core.config import DevflowConfig, save_config
        from devflow.integrations.detect import resolve_stack

        # Saved stack is "typescript" — but no .ts files exist on disk.
        save_config(DevflowConfig(stack="typescript"), tmp_path)

        assert resolve_stack(tmp_path) == "typescript"

    def test_falls_back_to_detection_when_no_saved_stack(self, tmp_path: Path) -> None:
        from devflow.integrations.detect import resolve_stack

        (tmp_path / "main.py").touch()
        (tmp_path / "lib.py").touch()

        assert resolve_stack(tmp_path) == "python"

    def test_returns_none_when_nothing_to_detect(self, tmp_path: Path) -> None:
        from devflow.integrations.detect import resolve_stack

        assert resolve_stack(tmp_path) is None
