"""Tests for Gazelle theme loading and resolution."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import (
    load_omarchy_colors,
    load_user_colors,
    migrate_user_theme,
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
accent = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
background = "#000000"
"""
        )

        result = load_user_colors(config_dir)

        assert result is not None
        assert result["accent"] == "#FFFF00"
        assert result["primary"] == "#FF0000"
        assert result["foreground"] == "#FFFFFF"
        assert result["background"] == "#000000"

    def test_returns_none_when_color_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        theme_file.write_text(
            """
[colors]
accent = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
"""
        )

        assert load_user_colors(config_dir) is None


class TestMigrateUserTheme:
    """Tests for migrating old-format theme.toml files."""

    def test_migrates_old_full_format(self, tmp_path, monkeypatch):
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

[colors.bright]
yellow = "#EEEE00"
red = "#EE0000"
"""
        )

        assert migrate_user_theme(config_dir) is True

        # Normal colors take precedence over bright colors.
        result = load_user_colors(config_dir)
        assert result is not None
        assert result["accent"] == "#FFFF00"
        assert result["primary"] == "#FF0000"
        assert result["foreground"] == "#FFFFFF"
        assert result["background"] == "#000000"

        assert (config_dir / "theme.toml.bak").exists()
        assert "[colors.normal]" not in theme_file.read_text()

    def test_migrates_partial_old_format_with_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        theme_file.write_text(
            """
[colors.normal]
yellow = "#FFFF00"

[colors.primary]
foreground = "#FFFFFF"
"""
        )

        assert migrate_user_theme(config_dir) is True

        result = load_user_colors(config_dir)
        assert result is not None
        assert result["accent"] == "#FFFF00"
        assert result["primary"] == "#BF616A"
        assert result["foreground"] == "#FFFFFF"
        assert result["background"] == "#2E3440"

    def test_migration_preserves_styles(self, tmp_path, monkeypatch):
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

[styles]
dialog_border = "round"
section_border = "round"
"""
        )

        assert migrate_user_theme(config_dir) is True

        result = load_user_colors(config_dir)
        assert result is not None

        migrated_text = theme_file.read_text()
        assert 'dialog_border = "round"' in migrated_text
        assert 'section_border = "round"' in migrated_text

    def test_empty_old_template_rewritten_without_activating(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        theme_file.write_text(
            """
[colors.primary]
#foreground = "#D8DEE9"
#background = "#2E3440"

[colors.normal]
#yellow = "#EBCB8B"
#red = "#BF616A"
"""
        )

        assert migrate_user_theme(config_dir) is True
        assert load_user_colors(config_dir) is None

        migrated_text = theme_file.read_text()
        assert "[colors.normal]" not in migrated_text
        assert "#accent =" in migrated_text

    def test_new_format_not_migrated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        config_dir = tmp_path / ".config" / "gazelle"
        config_dir.mkdir(parents=True)
        theme_file = config_dir / "theme.toml"
        original_text = """
[colors]
accent = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
background = "#000000"
"""
        theme_file.write_text(original_text)

        assert migrate_user_theme(config_dir) is False
        assert theme_file.read_text() == original_text


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
        assert gazelle_app.CONFIG_FILE.exists()

        assert json.loads(gazelle_app.CONFIG_FILE.read_text()) == {"theme": "textual-dark"}

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
[colors]
accent = "#FFFF00"
primary = "#FF0000"
foreground = "#FFFFFF"
background = "#000000"
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
