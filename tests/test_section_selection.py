"""Tests for section selection, focus, and visual highlighting."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from textual.app import App


@pytest.fixture
def gazelle_app(tmp_path, monkeypatch):
    """Provide a Gazelle app with config/home redirected to tmp_path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from app import Gazelle

    config_dir = tmp_path / ".config" / "gazelle"
    monkeypatch.setattr(Gazelle, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(Gazelle, "CONFIG_FILE", config_dir / "config.json")

    app = Gazelle()
    app.query_one = MagicMock(return_value=MagicMock())
    app.run_worker = MagicMock()
    return app


def test_tab_binding_is_priority():
    from app import Gazelle

    tab_binding = next(b for b in Gazelle.BINDINGS if b.key == "tab")
    assert tab_binding.priority is True


def test_info_tables_are_not_focusable_after_mount(gazelle_app):
    dev = MagicMock()
    sta = MagicMock()
    known = MagicMock()
    new = MagicMock()

    def query_one(selector, *args, **kwargs):
        return {
            "#dev": dev,
            "#sta": sta,
            "#known": known,
            "#new": new,
        }.get(selector, MagicMock())

    gazelle_app.query_one = query_one
    gazelle_app.on_mount()

    assert dev.can_focus is False
    assert sta.can_focus is False


def test_active_section_defaults_to_new_after_mount(gazelle_app):
    gazelle_app.on_mount()
    assert gazelle_app.active_section == "new"


def _build_section_app(gazelle_app, known_focused):
    """Wire up mocked section containers and tables, return them."""
    known_container = MagicMock()
    known_container.classes = set()

    def known_add(c):
        known_container.classes.add(c)

    def known_remove(c):
        known_container.classes.discard(c)

    known_container.add_class = known_add
    known_container.remove_class = known_remove

    new_container = MagicMock()
    new_container.classes = set()

    def new_add(c):
        new_container.classes.add(c)

    def new_remove(c):
        new_container.classes.discard(c)

    new_container.add_class = new_add
    new_container.remove_class = new_remove

    known_table = MagicMock()
    known_table.has_focus = known_focused
    known_table.id = "known"
    known_table.focus = MagicMock()

    new_table = MagicMock()
    new_table.has_focus = not known_focused
    new_table.id = "new"
    new_table.focus = MagicMock()

    def query_one(selector, *args, **kwargs):
        return {
            "#known-section": known_container,
            "#new-section": new_container,
            "#known": known_table,
            "#new": new_table,
        }.get(selector, MagicMock())

    gazelle_app.query_one = query_one
    return known_container, new_container, known_table, new_table


def test_switch_section_toggles_to_new(gazelle_app):
    gazelle_app.on_mount()
    known_c, new_c, known_t, new_t = _build_section_app(gazelle_app, known_focused=True)
    # Pre-seed state so the switch is a real change and the watcher fires.
    gazelle_app.active_section = "known"

    gazelle_app.action_switch_section()

    assert gazelle_app.active_section == "new"
    new_t.focus.assert_called_once()
    assert "active-section" in new_c.classes
    assert "active-section" not in known_c.classes


def test_switch_section_toggles_back_to_known(gazelle_app):
    gazelle_app.on_mount()
    known_c, new_c, known_t, new_t = _build_section_app(gazelle_app, known_focused=False)

    gazelle_app.action_switch_section()

    assert gazelle_app.active_section == "known"
    known_t.focus.assert_called_once()
    assert "active-section" in known_c.classes
    assert "active-section" not in new_c.classes


def test_switch_section_delegates_when_not_network_table(gazelle_app):
    gazelle_app.on_mount()
    known = MagicMock()
    known.has_focus = False
    new = MagicMock()
    new.has_focus = False

    def query_one(selector, *args, **kwargs):
        if selector == "#known":
            return known
        if selector == "#new":
            return new
        return MagicMock()

    gazelle_app.query_one = query_one

    with patch.object(App, "action_focus_next") as super_focus_next:
        gazelle_app.action_switch_section()
        super_focus_next.assert_called_once()


def test_on_focus_updates_active_section(gazelle_app):
    gazelle_app.on_mount()
    known_c, new_c, known_t, new_t = _build_section_app(gazelle_app, known_focused=False)

    focus_event = MagicMock()
    focus_event.control = known_t
    gazelle_app.on_focus(focus_event)

    assert gazelle_app.active_section == "known"
    assert "active-section" in known_c.classes
    assert "active-section" not in new_c.classes
