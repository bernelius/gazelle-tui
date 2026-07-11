"""Regression tests for the theme-fixes branch.

These tests exercise the behavior changes that theme-fixes introduces over
main. They should fail when run on main and pass when run on theme-fixes.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock


class TestDefaultFallback:
    """Default theme selection when no user or Omarchy theme exists."""

    def test_default_fallback_is_textual_dark_not_auto(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from app import Gazelle

        config_dir = tmp_path / ".config" / "gazelle"
        monkeypatch.setattr(Gazelle, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(Gazelle, "CONFIG_FILE", config_dir / "config.toml")

        app = Gazelle()
        app.query_one = MagicMock(return_value=MagicMock())
        app.run_worker = MagicMock()
        app.on_mount()

        assert app.theme == "textual-dark"
        assert app.get_theme("textual-dark") is not None
        assert app.get_theme("auto") is None


class TestGlobalColorSystem:
    """Global color-system handling."""

    def test_no_global_rich_color_system_override(self, tmp_path):
        env = os.environ.copy()
        env.pop("RICH_COLOR_SYSTEM", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; import app; print(os.environ.get('RICH_COLOR_SYSTEM', '__NONE__'))",
            ],
            cwd=str(Path(__file__).parent.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        value = result.stdout.strip()
        assert value != "standard", f"RICH_COLOR_SYSTEM was forced to {value!r}"


class TestAnsiColorMode:
    """ANSI color mode must not be forced at the App class level."""

    def test_app_does_not_force_ansi_color_mode(self):
        from app import Gazelle

        assert getattr(Gazelle, "ansi_color", None) is not True


class TestLegacyAutoThemeMigration:
    """Users upgrading from main with theme='auto' should migrate to textual-dark."""

    def test_legacy_auto_theme_migrates_to_textual_dark(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from app import Gazelle

        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('theme = "auto"\n')

        monkeypatch.setattr(Gazelle, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(Gazelle, "CONFIG_FILE", config_file)

        app = Gazelle()
        app.query_one = MagicMock(return_value=MagicMock())
        app.run_worker = MagicMock()
        app.on_mount()

        assert app.theme == "textual-dark"
        assert config_file.read_text() == 'theme = "textual-dark"\n'


class TestUserThemeFallbackRemoval:
    """The redundant user-theme fallback registration must be gone."""

    def test_user_theme_fallback_registration_removed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from app import Gazelle

        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('theme = "user-theme"\n')
        # Intentionally no theme.toml

        monkeypatch.setattr(Gazelle, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(Gazelle, "CONFIG_FILE", config_file)

        app = Gazelle()
        app.query_one = MagicMock(return_value=MagicMock())
        app.run_worker = MagicMock()
        app.on_mount()

        assert app.theme == "textual-dark"
        assert app.get_theme("user-theme") is None


class TestResolveTheme:
    """The centralized resolve_theme() logic that eliminates redundant checks."""

    def test_resolve_theme_short_circuits_on_user_theme(self):
        from app import resolve_theme

        def exists(available):
            return lambda name: name in available

        theme, save = resolve_theme(
            None,
            True,
            True,
            exists({"user-theme", "omarchy-auto", "textual-dark"}),
        )
        assert theme == "user-theme"
        assert save is True

    def test_resolve_theme_keeps_valid_saved_theme(self):
        from app import resolve_theme

        theme, save = resolve_theme(
            "textual-dark",
            False,
            False,
            lambda name: name == "textual-dark",
        )
        assert theme == "textual-dark"
        assert save is False
