"""Tests for Gazelle theme loading and resolution."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import (
    load_omarchy_colors,
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
        theme, save = resolve_theme("textual-dark", False, False, self._exists({"textual-dark"}))
        assert theme == "textual-dark"
        assert save is False

    def test_user_theme_wins_on_first_run(self):
        theme, save = resolve_theme(None, True, True, self._exists({"user-theme", "omarchy-auto"}))
        assert theme == "user-theme"
        assert save is True

    def test_omarchy_used_when_no_user_theme(self):
        theme, save = resolve_theme(None, False, True, self._exists({"omarchy-auto"}))
        assert theme == "omarchy-auto"
        assert save is True

    def test_textual_dark_is_default(self):
        theme, save = resolve_theme(None, False, False, self._exists({"textual-dark"}))
        assert theme == "textual-dark"
        assert save is True

    def test_recovers_when_saved_theme_is_invalid(self):
        theme, save = resolve_theme("user-theme", False, False, self._exists({"textual-dark"}))
        assert theme == "textual-dark"
        assert save is True

    def test_ansi_saved_theme_is_valid(self):
        theme, save = resolve_theme("ansi", False, False, self._exists({"ansi", "textual-dark"}))
        assert theme == "ansi"
        assert save is False

    def test_user_theme_wins_even_when_omarchy_present(self):
        theme, save = resolve_theme(None, True, True, self._exists({"user-theme", "omarchy-auto"}))
        assert theme == "user-theme"
        assert save is True

    def test_saved_theme_checked_against_available_themes(self):
        theme, save = resolve_theme(
            "monokai", False, False, self._exists({"monokai", "textual-dark"})
        )
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

    def test_returns_fallback_colors_for_empty_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        # First call creates the template
        assert load_user_colors(config_dir) is None

        # Second call should parse the empty template and return fallbacks
        result = load_user_colors(config_dir)

        assert result is not None
        assert result["primary"] == "#BF616A"
        assert result["accent"] == "#EBCB8B"
        assert result["foreground"] == "#D8DEE9"
        assert result["background"] == "#2E3440"

    def test_returns_custom_colors_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        theme_file.write_text(
            """
[colors.primary]
foreground = "#FFFFFF"
background = "#000000"

[colors.normal]
yellow = "#FFFF00"
red = "#FF0000"
"""
        )

        result = load_user_colors(config_dir)

        assert result is not None
        assert result["foreground"] == "#FFFFFF"
        assert result["background"] == "#000000"
        assert result["accent"] == "#FFFF00"
        assert result["primary"] == "#FF0000"


class TestLoadOmarchyColors:
    """Tests for loading colors from Omarchy's active theme."""

    def test_returns_none_when_no_omarchy(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_omarchy_colors() is None

    def test_loads_colors_from_alacritty_toml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        theme_dir = tmp_path / ".config" / "omarchy" / "current" / "theme"
        theme_dir.mkdir(parents=True)
        theme_file = theme_dir / "alacritty.toml"
        theme_file.write_text(
            """
[colors.primary]
foreground = "#D8DEE9"
background = "#2E3440"

[colors.normal]
yellow = "#EBCB8B"
red = "#BF616A"

[colors.bright]
yellow = "#EBCB8B"
red = "#BF616A"
"""
        )

        result = load_omarchy_colors()

        assert result is not None
        assert result["foreground"] == "#D8DEE9"
        assert result["background"] == "#2E3440"
        assert result["accent"] == "#EBCB8B"
        assert result["primary"] == "#BF616A"


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
        config_file = config_dir / "config.json"
        monkeypatch.setattr(Gazelle, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(Gazelle, "CONFIG_FILE", config_file)

        app = Gazelle()
        app.query_one = MagicMock(return_value=MagicMock())
        app.run_worker = MagicMock()
        return app

    def test_first_run_saves_textual_dark(self, gazelle_app):
        gazelle_app.on_mount()

        assert gazelle_app.theme == "textual-dark"
        assert gazelle_app.get_theme("ansi") is not None
        assert gazelle_app.CONFIG_FILE.exists()
        assert json.loads(gazelle_app.CONFIG_FILE.read_text()) == {"theme": "textual-dark"}

    def test_ansi_theme_can_be_selected_manually(self, gazelle_app):
        gazelle_app.CONFIG_DIR.mkdir(parents=True)
        gazelle_app.CONFIG_FILE.write_text(json.dumps({"theme": "ansi"}))

        gazelle_app.on_mount()

        assert gazelle_app.theme == "ansi"

    def test_existing_config_theme_is_source_of_truth(self, gazelle_app):
        gazelle_app.CONFIG_DIR.mkdir(parents=True)
        gazelle_app.CONFIG_FILE.write_text(json.dumps({"theme": "nord"}))

        gazelle_app.on_mount()

        assert gazelle_app.theme == "nord"

    def test_invalid_saved_theme_falls_back_and_saves(self, gazelle_app):
        gazelle_app.CONFIG_DIR.mkdir(parents=True)
        gazelle_app.CONFIG_FILE.write_text(json.dumps({"theme": "user-theme"}))

        gazelle_app.on_mount()

        assert gazelle_app.theme == "textual-dark"
        assert json.loads(gazelle_app.CONFIG_FILE.read_text()) == {"theme": "textual-dark"}

    def test_user_theme_detected_and_saved(self, tmp_path, monkeypatch, gazelle_app):
        # Create a user theme file in the patched home directory
        theme_dir = tmp_path / ".config" / "gazelle"
        theme_dir.mkdir(parents=True)
        (theme_dir / "theme.toml").write_text(
            """
[colors.primary]
foreground = "#FFFFFF"
background = "#000000"

[colors.normal]
yellow = "#FFFF00"
red = "#FF0000"
"""
        )

        gazelle_app.on_mount()

        assert gazelle_app.theme == "user-theme"
        assert json.loads(gazelle_app.CONFIG_FILE.read_text()) == {"theme": "user-theme"}

    def test_omarchy_theme_detected_and_saved(self, tmp_path, monkeypatch, gazelle_app):
        # Create an Omarchy theme file in the patched home directory
        omarchy_dir = tmp_path / ".config" / "omarchy" / "current" / "theme"
        omarchy_dir.mkdir(parents=True)
        (omarchy_dir / "alacritty.toml").write_text(
            """
[colors.primary]
foreground = "#D8DEE9"
background = "#2E3440"

[colors.normal]
yellow = "#EBCB8B"
red = "#BF616A"
"""
        )

        gazelle_app.on_mount()

        assert gazelle_app.theme == "omarchy-auto"
        assert json.loads(gazelle_app.CONFIG_FILE.read_text()) == {"theme": "omarchy-auto"}
