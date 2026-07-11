"""Tests for Gazelle theme loading and resolution."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import (
    load_user_colors,
    resolve_theme,
    try_create_user_theme_template,
)


class TestResolveTheme:
    """Unit tests for the theme resolution function."""

    @staticmethod
    def _exists(available):
        return available.__contains__

    def test_uses_saved_valid_theme(self):
        theme, save = resolve_theme("textual-dark", False, self._exists({"textual-dark"}))
        assert theme == "textual-dark"
        assert save is False

    def test_user_theme_wins_on_first_run(self):
        theme, save = resolve_theme(None, True, self._exists({"user-theme", "textual-dark"}))
        assert theme == "user-theme"
        assert save is True

    def test_textual_dark_is_default(self):
        theme, save = resolve_theme(None, False, self._exists({"textual-dark"}))
        assert theme == "textual-dark"
        assert save is True

    def test_recovers_when_saved_theme_is_invalid(self):
        theme, save = resolve_theme("user-theme", False, self._exists({"textual-dark"}))
        assert theme == "textual-dark"
        assert save is True

    def test_saved_theme_checked_against_available_themes(self):
        theme, save = resolve_theme("monokai", False, self._exists({"monokai", "textual-dark"}))
        assert theme == "monokai"
        assert save is False


class TestLoadUserColors:
    """Tests for loading custom colors from theme.toml."""

    def test_creates_template_and_returns_none_on_first_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"

        result = load_user_colors(config_dir)

        assert result is None
        assert (config_dir / "theme.toml").exists()

    def test_returns_none_for_empty_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        # First call creates the template
        assert load_user_colors(config_dir) is None

        # An empty/commented template does not activate the custom theme
        result = load_user_colors(config_dir)

        assert result is None

    def test_returns_custom_colors_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        theme_file.write_text(
            """
[colors]
secondary = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
background = "#000000"
"""
        )

        result = load_user_colors(config_dir)

        assert result is not None
        assert result["secondary"] == "#FFFF00"
        assert result["primary"] == "#FF0000"
        assert result["foreground"] == "#FFFFFF"
        assert result["background"] == "#000000"
        assert result["success"] == "#A3BE8C"
        assert result["warning"] == "#EBCB8B"
        assert result["error"] == "#BF616A"

    def test_returns_custom_status_colors_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        theme_file.write_text(
            """
[colors]
secondary = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
background = "#000000"
success = "#00FF00"
warning = "#FFAA00"
error = "#FF00FF"
"""
        )

        result = load_user_colors(config_dir)

        assert result is not None
        assert result["success"] == "#00FF00"
        assert result["warning"] == "#FFAA00"
        assert result["error"] == "#FF00FF"

    def test_returns_none_when_color_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        theme_file.write_text(
            """
[colors]
secondary = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
"""
        )

        assert load_user_colors(config_dir) is None


class TestTryCreateUserThemeTemplate:
    """Tests for the template creation helper."""

    def test_creates_file_and_returns_true(self, tmp_path):
        config_dir = tmp_path / ".config" / "gazelle"
        assert try_create_user_theme_template(config_dir) is True
        assert (config_dir / "theme.toml").exists()

    def test_returns_false_when_file_exists(self, tmp_path):
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        (config_dir / "theme.toml").write_text("# existing")
        assert try_create_user_theme_template(config_dir) is False


class TestOnMountThemeSelection:
    """Integration tests for Gazelle.on_mount theme behavior."""

    @pytest.fixture
    def gazelle_app(self, tmp_path, monkeypatch):
        """Provide a Gazelle app with config and home redirected to tmp_path."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from app import Gazelle

        config_dir = tmp_path / ".config" / "gazelle"
        config_file = config_dir / "config.toml"
        monkeypatch.setattr(Gazelle, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(Gazelle, "CONFIG_FILE", config_file)

        app = Gazelle()
        app.query_one = MagicMock(return_value=MagicMock())
        app.run_worker = MagicMock()
        return app

    def test_first_run_saves_textual_dark(self, gazelle_app):
        gazelle_app.on_mount()

        assert gazelle_app.theme == "textual-dark"
        assert gazelle_app.CONFIG_FILE.exists()

        assert gazelle_app.CONFIG_FILE.read_text() == 'theme = "textual-dark"\n'

    def test_existing_config_theme_is_source_of_truth(self, gazelle_app):
        gazelle_app.CONFIG_DIR.mkdir(parents=True)
        gazelle_app.CONFIG_FILE.write_text('theme = "nord"\n')

        gazelle_app.on_mount()

        assert gazelle_app.theme == "nord"

    def test_invalid_saved_theme_falls_back_and_saves(self, gazelle_app):
        gazelle_app.CONFIG_DIR.mkdir(parents=True)
        gazelle_app.CONFIG_FILE.write_text('theme = "user-theme"\n')

        gazelle_app.on_mount()

        assert gazelle_app.theme == "textual-dark"
        assert gazelle_app.CONFIG_FILE.read_text() == 'theme = "textual-dark"\n'

    def test_user_theme_detected_and_saved(self, tmp_path, monkeypatch, gazelle_app):
        # Create a user theme file in the patched home directory
        theme_dir = tmp_path / ".config" / "gazelle"
        theme_dir.mkdir(parents=True)
        (theme_dir / "theme.toml").write_text(
            """
[colors]
secondary = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
background = "#000000"
"""
        )

        gazelle_app.on_mount()

        assert gazelle_app.theme == "user-theme"
        assert gazelle_app.CONFIG_FILE.read_text() == 'theme = "user-theme"\n'

    def test_builtin_themes_are_flattened(self, gazelle_app):
        gazelle_app.on_mount()

        flattened = gazelle_app.get_theme("nord")
        assert flattened is not None
        # accent is forced to equal secondary so no extra highlight color leaks in.
        assert flattened.accent == flattened.secondary
        # surface/panel collapsed to background.
        assert flattened.surface == flattened.background
        assert flattened.panel == flattened.background
        # boost made transparent so there are no hover/focus tints.
        assert flattened.boost == "transparent"
        # status colors preserved from the original builtin theme.
        assert flattened.success == "#A3BE8C"
        assert flattened.warning == "#EBCB8B"
        assert flattened.error == "#BF616A"
