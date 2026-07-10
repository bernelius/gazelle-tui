"""Tests for launch-time and manual WiFi scanning behavior."""

import asyncio
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BASELINE = [
    {"ssid": "Home", "signal": 80, "security": "WPA2", "connected": False},
]

DIFFERENT = [
    {"ssid": "Home", "signal": 85, "security": "WPA2", "connected": False},
    {"ssid": "Guest", "signal": 60, "security": "WPA2", "connected": False},
]


@pytest.fixture(autouse=True)
def fast_scan_interval(monkeypatch):
    """Speed up scan tests by shrinking the polling delay."""
    monkeypatch.setattr("app.SCAN_POLL_INTERVAL", 0.01)


def _make_app(monkeypatch, tmp_path, initial_networks, has_wwan=False):
    """Build a Gazelle app with network/table helpers mocked for scan tests."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Avoid shelling out to mmcli/nmcli during app construction.
    monkeypatch.setattr("app.has_wwan_capabilities", lambda: has_wwan, raising=False)
    from app import Gazelle

    config_dir = tmp_path / ".config" / "gazelle"
    monkeypatch.setattr(Gazelle, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(Gazelle, "CONFIG_FILE", config_dir / "config.json")

    app = Gazelle()
    app.run_worker = MagicMock()
    app.refresh_all = MagicMock()
    app.notify = MagicMock()
    app._request_rescan = MagicMock()

    tables = {tid: MagicMock() for tid in ("#dev", "#sta", "#known", "#new")}

    def query_one(selector, *args, **kwargs):
        return tables.get(selector, MagicMock())

    app.query_one = query_one

    # Avoid shelling out to nmcli during unit tests.
    monkeypatch.setattr("app.get_wifi_list", MagicMock(return_value=initial_networks))
    monkeypatch.setattr("app.get_wifi_interface", MagicMock(return_value="wlan0"))
    return app, tables


def _async_sequence(values):
    """Return an async function that yields values from ``values`` in order."""
    gen = iter(values)

    async def _fn():
        return next(gen)

    return _fn


def test_on_mount_refreshes_immediately_with_cached_networks(monkeypatch, tmp_path):
    app, tables = _make_app(monkeypatch, tmp_path, BASELINE)
    app.on_mount()
    app.refresh_all.assert_called_once_with(networks=BASELINE)
    tables["#new"].add_row.assert_not_called()


def test_on_mount_shows_placeholder_when_cached_list_empty(monkeypatch, tmp_path):
    app, tables = _make_app(monkeypatch, tmp_path, [])
    app.on_mount()
    app.refresh_all.assert_not_called()
    tables["#new"].add_row.assert_called_once_with("Scanning for networks...", "", "")


def test_on_mount_launches_polling_scan_with_baseline(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    app.on_mount()
    app.run_worker.assert_called_once()
    args, kwargs = app.run_worker.call_args
    assert isinstance(args[0], partial)
    assert args[0].func.__func__ is app.scan_networks_async.__func__
    assert args[0].args == (BASELINE,)
    assert kwargs.get("exclusive") is True


async def _fake_list_returning(networks):
    return networks


def test_scan_networks_async_refreshes_when_first_poll_differs(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    app._list_wifi_async = MagicMock(side_effect=_async_sequence([DIFFERENT, DIFFERENT]))
    asyncio.run(app.scan_networks_async(BASELINE))
    app.refresh_all.assert_called_once_with(networks=DIFFERENT)


def test_scan_networks_async_refreshes_on_each_change(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    poll1 = list(BASELINE)
    poll2 = DIFFERENT
    poll3 = [{"ssid": "Other", "signal": 50, "security": "WPA2", "connected": False}]
    app._list_wifi_async = MagicMock(side_effect=_async_sequence([poll1, poll2, poll3, poll3]))
    asyncio.run(app.scan_networks_async(BASELINE))
    assert app.refresh_all.call_count == 2
    app.refresh_all.assert_any_call(networks=poll2)
    app.refresh_all.assert_called_with(networks=poll3)


def test_scan_networks_async_refreshes_first_poll_when_baseline_empty(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, [])
    app._list_wifi_async = MagicMock(side_effect=_async_sequence([BASELINE, BASELINE]))
    asyncio.run(app.scan_networks_async([]))
    app.refresh_all.assert_called_once_with(networks=BASELINE)


def test_scan_networks_async_skips_first_refresh_when_baseline_unchanged(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    app._list_wifi_async = MagicMock(side_effect=_async_sequence([BASELINE, BASELINE]))
    asyncio.run(app.scan_networks_async(BASELINE))
    app.refresh_all.assert_not_called()


def test_scan_networks_async_stops_when_stable_after_min_polls(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    from app import SCAN_MIN_POLLS, SCAN_REPEATS

    # Change on the second poll, then stable; should stop once SCAN_MIN_POLLS
    # has passed and SCAN_REPEATS consecutive unchanged polls are seen.
    expected_calls = max(SCAN_MIN_POLLS, SCAN_REPEATS + 1) + 1
    polls = [BASELINE, DIFFERENT] + [DIFFERENT] * SCAN_REPEATS
    app._list_wifi_async = MagicMock(side_effect=_async_sequence(polls))
    asyncio.run(app.scan_networks_async(BASELINE))
    assert app.refresh_all.call_count == 1
    app.refresh_all.assert_called_once_with(networks=DIFFERENT)
    assert app._list_wifi_async.call_count == expected_calls


def test_scan_networks_async_respects_max_polls(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    # First poll matches the baseline (no refresh), then every poll is different.
    values = [list(BASELINE)] + [
        [{"ssid": f"Net{i}", "signal": i, "security": "WPA2", "connected": False}]
        for i in range(1, 20)
    ]
    app._list_wifi_async = MagicMock(side_effect=_async_sequence(values))
    asyncio.run(app.scan_networks_async(BASELINE))
    from app import SCAN_MAX_POLLS

    assert app._list_wifi_async.call_count == SCAN_MAX_POLLS
    # Baseline matched first poll; every remaining poll differs from previous.
    assert app.refresh_all.call_count == SCAN_MAX_POLLS - 1


def test_scan_networks_async_manual_scan_refreshes_on_first_poll(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, [])
    app._list_wifi_async = MagicMock(side_effect=_async_sequence([BASELINE, BASELINE]))
    asyncio.run(app.scan_networks_async())
    app.refresh_all.assert_called_once_with(networks=BASELINE)


def test_scan_networks_async_notifies_on_list_failure(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)

    async def failing_list():
        raise RuntimeError("list failed")

    app._list_wifi_async = failing_list
    asyncio.run(app.scan_networks_async(BASELINE))
    app.refresh_all.assert_not_called()
    app.notify.assert_called_once_with("Scan failed: list failed")


def test_scan_wifi_async_kills_subprocess_on_cancellation(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    proc = MagicMock()
    proc.returncode = None
    proc.kill = MagicMock()

    async def communicate():
        raise asyncio.CancelledError()

    proc.communicate = communicate

    async def fake_create_subprocess_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr("app.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app._list_wifi_async())

    proc.kill.assert_called_once()
    assert app._scan_process is None


def test_scan_wifi_async_returns_parsed_networks(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    raw_stdout = "Home:80:WPA2:\nGuest:60:WPA2:\n"
    proc = MagicMock()
    proc.returncode = 0
    proc.kill = MagicMock()

    async def communicate():
        return raw_stdout.encode(), b""

    proc.communicate = communicate

    async def fake_create_subprocess_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr("app.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = asyncio.run(app._list_wifi_async())

    assert result == [
        {"ssid": "Home", "signal": 80, "security": "WPA2", "connected": False},
        {"ssid": "Guest", "signal": 60, "security": "WPA2", "connected": False},
    ]


def test_on_unmount_kills_running_scan(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    app.workers.cancel_all = MagicMock()
    app._scan_process = MagicMock()
    app._scan_process.returncode = None
    app._scan_process.kill = MagicMock()

    app.on_unmount()

    app.workers.cancel_all.assert_called_once()
    app._scan_process.kill.assert_called_once()


def test_on_unmount_safe_when_mount_never_ran(monkeypatch, tmp_path):
    """Regression: _scan_process must exist even if on_mount() failed or never ran."""
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    app.workers.cancel_all = MagicMock()
    # Do not run on_mount(); __init__ alone should leave _scan_process initialized.
    assert app._scan_process is None

    app.on_unmount()

    app.workers.cancel_all.assert_called_once()
    # No AttributeError raised.


def test_check_action_hides_wwan_bindings_without_capability(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE, has_wwan=False)
    assert app.check_action("wwan_screen", ()) is False
    assert app.check_action("toggle_wwan_radio", ()) is False


def test_check_action_shows_wwan_bindings_with_capability(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE, has_wwan=True)
    assert app.check_action("wwan_screen", ()) is True
    assert app.check_action("toggle_wwan_radio", ()) is True


def test_check_action_leaves_other_actions_unaffected(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE, has_wwan=False)
    assert app.check_action("quit", ()) is True
    assert app.check_action("vpn_screen", ()) is True
    assert app.check_action("scan", ()) is True


def test_action_toggle_wifi_on_triggers_manual_scan(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    monkeypatch.setattr("app.toggle_wifi", lambda: True)
    app.action_scan = MagicMock()
    app.set_timer = MagicMock()

    app.action_toggle_wifi()

    app.notify.assert_called_once_with("WiFi ON")
    app.action_scan.assert_called_once()
    app.set_timer.assert_not_called()


def test_action_toggle_wifi_off_refreshes_after_delay(monkeypatch, tmp_path):
    app, _ = _make_app(monkeypatch, tmp_path, BASELINE)
    monkeypatch.setattr("app.toggle_wifi", lambda: False)
    app.action_scan = MagicMock()
    app.set_timer = MagicMock()

    app.action_toggle_wifi()

    app.notify.assert_called_once_with("WiFi OFF")
    app.action_scan.assert_not_called()
    app.set_timer.assert_called_once_with(1, app.refresh_all)
