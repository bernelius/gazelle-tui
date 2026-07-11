"""Gazelle - Minimal NetworkManager TUI"""

from textual.app import App, ComposeResult
from textual.theme import Theme
from textual.widgets import Footer, Static, Input, Button, DataTable, Select
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.reactive import reactive
from network import *
from network import _parse_wifi_list
import subprocess
import asyncio
import json
from pathlib import Path
from functools import partial

# Launch scan tuning: request a rescan, then poll the plain list every
# SCAN_POLL_INTERVAL seconds. Stop early once the list is stable, but only
# after SCAN_MIN_POLLS polls so we don't trust the stale pre-scan cache.
SCAN_POLL_INTERVAL = 0.5
SCAN_MIN_POLLS = 5
SCAN_MAX_POLLS = 20
SCAN_REPEATS = 4

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # Fallback for older Python  #pyright: ignore[reportMissingImports]

    except ImportError:
        tomllib = None  # Will use fallback colors


def normalize_color_format(color):
    """Convert 0xRRGGBB to #RRGGBB for CSS/Textual compatibility.

    Args:
        color: Color string in any format

    Returns:
        Color string in CSS format (#RRGGBB)
    """
    if isinstance(color, str) and color.startswith("0x"):
        return "#" + color[2:]
    return color


class HiddenNetworkScreen(ModalScreen):
    """Modal for connecting to hidden SSID"""

    BINDINGS = [
        ("enter", "submit", "Submit"),
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Connect to Hidden Network", id="title"),
            Static("SSID:"),
            Input(placeholder="Network name", id="ssid"),
            Static("Security:"),
            Select(
                [
                    ("Open", "open"),
                    ("WPA2/WPA3", "psk"),
                    ("802.1X Enterprise", "8021x"),
                ],
                value="psk",
                id="sec",
            ),
            Horizontal(
                Button("Next", variant="primary", id="next"),
                Button("Cancel", id="cancel"),
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
        elif event.button.id == "next":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in Input field"""
        self._submit()

    def _submit(self) -> None:
        """Submit the form"""
        ssid = self.query_one("#ssid", Input).value
        sec = self.query_one("#sec", Select).value
        if ssid:
            self.dismiss((ssid, sec))

    def action_cancel(self) -> None:
        """Handle Esc key"""
        self.app.pop_screen()


class VPNScreen(ModalScreen):
    """Screen for VPN connection management"""

    BINDINGS = [
        ("escape", "cancel", "Back"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("space", "toggle_vpn", "Connect/Disconnect"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "cancel", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("VPN Connections", classes="section-title"),
            DataTable(id="vpn-table", cursor_type="row"),
            classes="section",
        )

    def on_mount(self) -> None:
        """Initialize VPN table"""
        table = self.query_one("#vpn-table", DataTable)
        table.add_columns("Status", "Name")
        self.refresh_vpn_list()
        table.focus()

    def refresh_vpn_list(self) -> None:
        """Refresh VPN connection list"""
        table = self.query_one("#vpn-table", DataTable)
        table.clear()
        for vpn in get_vpn_list():
            status = "🟢" if vpn["active"] else "⚪"
            table.add_row(status, vpn["name"])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter key)"""
        self.action_toggle_vpn()

    def action_toggle_vpn(self) -> None:
        """Toggle VPN connection on Space/Enter key"""
        table = self.query_one("#vpn-table", DataTable)
        if table.cursor_row >= 0 and table.cursor_row < table.row_count:
            row = table.get_row_at(table.cursor_row)
            status, name = str(row[0]), str(row[1])

            if status == "🟢":
                # Disconnect
                self.notify("Disconnecting...")
                success = disconnect_vpn(name)
                self.notify("✓ Disconnected" if success else "✗ Failed")
            else:
                # Connect
                self.notify("Connecting...")
                success, msg = connect_vpn(name)
                self.notify("✓ Connected" if success else "✗ Failed")

            self.refresh_vpn_list()

    def action_cursor_down(self) -> None:
        """Move cursor down"""
        table = self.query_one("#vpn-table", DataTable)
        if table.row_count > 0:
            table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up"""
        table = self.query_one("#vpn-table", DataTable)
        if table.row_count > 0:
            table.action_cursor_up()

    def action_refresh(self) -> None:
        """Refresh VPN list"""
        self.refresh_vpn_list()
        self.notify("Refreshed")

    def action_cancel(self) -> None:
        """Return to main screen on Escape"""
        self.app.pop_screen()


class WWANScreen(ModalScreen):
    """Screen for WWAN (cellular) connection management"""

    BINDINGS = [
        ("escape", "cancel", "Back"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("space", "toggle_wwan", "Connect/Disconnect"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "cancel", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("WWAN Connections", classes="section-title"),
            DataTable(id="wwan-table", cursor_type="row"),
            classes="section",
        )

    def on_mount(self) -> None:
        """Initialize WWAN table"""
        table = self.query_one("#wwan-table", DataTable)
        table.add_columns("Status", "Name", "Signal", "Operator", "Tech")
        self.refresh_wwan_list()
        table.focus()

    def refresh_wwan_list(self) -> None:
        """Refresh WWAN connection list"""
        table = self.query_one("#wwan-table", DataTable)
        table.clear()
        wwans = get_wwan_list()

        if not wwans:
            table.add_row("⚪", "No WWAN connections found", "-", "-", "-")
        else:
            for wwan in wwans:
                status = "🟢" if wwan["active"] else "⚪"
                table.add_row(
                    status,
                    wwan["name"],
                    wwan.get("signal", "-"),
                    wwan.get("operator", "-"),
                    wwan.get("tech", "-"),
                )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter key)"""
        self.action_toggle_wwan()

    def action_toggle_wwan(self) -> None:
        """Toggle WWAN connection on Space/Enter key"""
        table = self.query_one("#wwan-table", DataTable)
        if table.cursor_row >= 0 and table.cursor_row < table.row_count:
            row = table.get_row_at(table.cursor_row)
            status, name = str(row[0]), str(row[1])

            # Don't try to connect if no connections found
            if name == "No WWAN connections found":
                return

            if status == "🟢":
                # Disconnect
                self.notify("Disconnecting...")
                success = disconnect_wwan(name)
                self.notify("✓ Disconnected" if success else "✗ Failed")
            else:
                # Connect
                self.notify("Connecting...")
                success, msg = connect_wwan(name)
                self.notify("✓ Connected" if success else "✗ Failed")

            self.refresh_wwan_list()

    def action_cursor_down(self) -> None:
        """Move cursor down"""
        table = self.query_one("#wwan-table", DataTable)
        if table.row_count > 0:
            table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up"""
        table = self.query_one("#wwan-table", DataTable)
        if table.row_count > 0:
            table.action_cursor_up()

    def action_refresh(self) -> None:
        """Refresh WWAN list"""
        self.refresh_wwan_list()
        self.notify("Refreshed")

    def action_cancel(self) -> None:
        """Return to main screen on Escape"""
        self.app.pop_screen()


class Wired8021xScreen(ModalScreen):
    """Modal for connecting to wired 802.1X network"""

    BINDINGS = [
        ("enter", "submit", "Submit"),
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Wired 802.1X Connection", id="title"),
            Static("Connection Name:"),
            Input(placeholder="e.g. office-wired", id="con_name"),
            Static("EAP Method:"),
            Select(
                [("PEAP", "peap"), ("TTLS", "ttls"), ("TLS", "tls")],
                value="peap",
                id="eap",
            ),
            Static("Phase 2 Auth:"),
            Select(
                [
                    ("MSCHAPv2", "mschapv2"),
                    ("MSCHAP", "mschap"),
                    ("PAP", "pap"),
                    ("CHAP", "chap"),
                    ("GTC", "gtc"),
                    ("MD5", "md5"),
                ],
                value="mschapv2",
                id="phase2",
            ),
            Static("Username:"),
            Input(placeholder="user@domain.com", id="user"),
            Static("Password:"),
            Input(placeholder="Password", password=True, id="pwd"),
            Horizontal(Button("Connect", variant="primary", id="ok"), Button("Cancel", id="no")),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "no":
            self.app.pop_screen()
        elif event.button.id == "ok":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in Input fields"""
        self._submit()

    def _submit(self) -> None:
        """Submit the form"""
        con_name = self.query_one("#con_name", Input).value
        user = self.query_one("#user", Input).value
        pwd = self.query_one("#pwd", Input).value
        eap = self.query_one("#eap", Select).value
        phase2 = self.query_one("#phase2", Select).value
        if con_name and user and pwd:
            self.dismiss((con_name, user, pwd, eap, phase2))

    def action_cancel(self) -> None:
        """Handle Esc key"""
        self.app.pop_screen()

    def action_submit(self) -> None:
        """Handle Enter key binding"""
        self._submit()


class PasswordScreen(ModalScreen):
    BINDINGS = [
        ("enter", "submit", "Submit"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, ssid, is_enterprise=False, is_hidden=False):
        super().__init__()
        self.ssid, self.is_enterprise, self.is_hidden = ssid, is_enterprise, is_hidden

    def compose(self) -> ComposeResult:
        if self.is_enterprise:
            yield Container(
                Static(f"Connect: {self.ssid}", id="title"),
                Static("EAP Method:"),
                Select(
                    [("PEAP", "peap"), ("TTLS", "ttls"), ("TLS", "tls")],
                    value="peap",
                    id="eap",
                ),
                Static("Phase 2 Auth:"),
                Select(
                    [
                        ("MSCHAPv2", "mschapv2"),
                        ("MSCHAP", "mschap"),
                        ("PAP", "pap"),
                        ("CHAP", "chap"),
                        ("GTC", "gtc"),
                        ("MD5", "md5"),
                    ],
                    value="mschapv2",
                    id="phase2",
                ),
                Static("Username:"),
                Input(placeholder="user@domain.com", id="user"),
                Static("Password:"),
                Input(placeholder="Password", password=True, id="pwd"),
                Horizontal(
                    Button("Connect", variant="primary", id="ok"),
                    Button("Cancel", id="no"),
                ),
                id="dialog",
            )
        else:
            yield Container(
                Static(f"Connect: {self.ssid}", id="title"),
                Static("Password:"),
                Input(placeholder="Password", password=True, id="pwd"),
                Horizontal(
                    Button("Connect", variant="primary", id="ok"),
                    Button("Cancel", id="no"),
                ),
                id="dialog",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "no":
            self.app.pop_screen()
        elif event.button.id == "ok":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in Input fields"""
        self._submit()

    def _submit(self) -> None:
        """Submit the form"""
        if self.is_enterprise:
            u = self.query_one("#user", Input).value
            p = self.query_one("#pwd", Input).value
            eap = self.query_one("#eap", Select).value
            phase2 = self.query_one("#phase2", Select).value
            if u and p:
                self.dismiss((self.ssid, p, u, True, eap, phase2, self.is_hidden))
        else:
            p = self.query_one("#pwd", Input).value
            if p:
                self.dismiss((self.ssid, p, None, False, None, None, self.is_hidden))

    def action_cancel(self) -> None:
        """Handle Esc key"""
        self.app.pop_screen()


# Base semantic colors required for a custom theme to activate.
_DEFAULT_THEME_COLORS = {
    "secondary": "#EBCB8B",
    "primary": "#BF616A",
    "foreground": "#D8DEE9",
    "background": "#2E3440",
}

# Optional status colors default to base colors when not specified.
_DEFAULT_STATUS_COLORS = {
    "success": "#A3BE8C",
    "warning": "#EBCB8B",
    "error": "#BF616A",
}

_SEMANTIC_COLOR_KEYS = set(_DEFAULT_THEME_COLORS) | set(_DEFAULT_STATUS_COLORS)


def load_user_colors(config_dir: Path):
    """
    Load colors from user defined theme file.
    Returns dict with RGB color values, or None if not found/invalid.
    Create file if it doesnt exist, dont load after creation.
    """
    if tomllib is None or try_create_user_theme_template(config_dir):
        return None
    theme_file = config_dir / "theme.toml"

    if not theme_file.exists():
        return None

    try:
        with open(theme_file, "rb") as f:
            data = tomllib.load(f)

        colors = data.get("colors", {})

        secondary = colors.get("secondary")
        primary = colors.get("primary")
        foreground = colors.get("foreground")
        background = colors.get("background")

        # All four base semantic colors must be defined for a custom theme to activate.
        if not all((secondary, primary, foreground, background)):
            return None

        result = {
            "secondary": normalize_color_format(secondary),
            "primary": normalize_color_format(primary),
            "foreground": normalize_color_format(foreground),
            "background": normalize_color_format(background),
        }
        for key in _DEFAULT_STATUS_COLORS:
            value = colors.get(key)
            result[key] = normalize_color_format(value) if value else _DEFAULT_STATUS_COLORS[key]

        return result
    except Exception:
        # If parsing fails, return None to use fallback
        return None


def resolve_theme(saved_theme, has_user_theme, theme_exists):
    """Determine the effective theme and whether it should be persisted.

    config.toml is the source of truth: if it names a valid theme, that theme
    is used unchanged. Otherwise the app auto-detects a default and the result
    is written back to config.toml.

    Args:
        saved_theme: Theme name from config.toml, or None.
        has_user_theme: True if a user theme.toml was loaded successfully.
        theme_exists: Callable that returns True for available theme names.

    Returns:
        Tuple of (effective_theme_name, should_save_to_config).
    """
    if saved_theme and theme_exists(saved_theme):
        return saved_theme, False

    if has_user_theme:
        return "user-theme", True
    return "textual-dark", True


def _flatten_builtin_themes(app: App) -> None:
    """Override every builtin Textual theme with a 4-color flattened version.

    Gazelle only uses $primary and $secondary, so $accent is forced to equal
    $secondary. $surface, $panel and $background are collapsed to the same
    color and $boost is made transparent so there are no hover/focus tints.
    """
    from textual.design import DEFAULT_DARK_BACKGROUND, DEFAULT_LIGHT_BACKGROUND

    custom_names = {"user-theme"}
    for name in list(app.available_themes):
        if name in custom_names:
            continue
        original = app.get_theme(name)
        if original is None:
            continue

        background = original.background or (
            DEFAULT_DARK_BACKGROUND if original.dark else DEFAULT_LIGHT_BACKGROUND
        )
        secondary = original.secondary or original.accent or original.primary

        app.register_theme(
            Theme(
                name=name,
                primary=original.primary,
                secondary=secondary,
                accent=secondary,
                foreground=original.foreground,
                background=background,
                surface=background,
                panel=background,
                boost="transparent",
                success=original.success,
                warning=original.warning,
                error=original.error,
                dark=original.dark,
                variables=original.variables,
            )
        )


def try_create_user_theme_template(config_dir: Path):
    """If file doesn't exist, create a template theme.toml file with commented color examples"""
    theme_file = config_dir / "theme.toml"
    theme_dir = theme_file.parent

    # Create directory if it doesn't exist
    theme_dir.mkdir(parents=True, exist_ok=True)

    if not theme_file.exists():
        template_content = """# Gazelle Theme Configuration
# Uncomment and modify these values to customize your theme
# Colors should be in hex format (#RRGGBB) or 0xRRGGBB
[colors]
#secondary  = "#EBCB8B"
#primary    = "#BF616A"
#foreground = "#D8DEE9"
#background = "#2E3440"
#success    = "#A3BE8C"
#warning    = "#EBCB8B"
#error      = "#BF616A"
"""
        with open(theme_file, "w") as f:
            f.write(template_content)
        return True
    return False


class Gazelle(App):
    TITLE = "Gazelle"
    CONFIG_DIR = Path.home() / ".config" / "gazelle"
    CONFIG_FILE = CONFIG_DIR / "config.toml"

    CSS = """
    PasswordScreen, HiddenNetworkScreen, Wired8021xScreen { align: center middle; }
    #dialog { width: 60; height: auto; border: solid $secondary; background: $background; padding: 1 2; }
    #title { text-style: bold; color: $secondary; margin-bottom: 1; }
    .section { border: heavy $foreground; border-title-style: bold; margin: 1 1; padding: 0 1; height: 1fr; layout: vertical; }
    .section.active-section { border: heavy $primary; }
    .section-title { text-style: bold; color: $secondary; background: $background; padding: 0 1; height: auto; }
    .section DataTable { height: 1fr; }
    #device-section, #station-section { height: 4; }
    Static { height: auto; }
    Input { height: 3; margin-bottom: 1; }
    Select { height: 3; margin-bottom: 1; }
    Horizontal { height: auto; margin-top: 1; }
    Button { min-width: 12; }

    /* Flat DataTable: one background color everywhere except the cursor. */
    DataTable {
        background: $background;
    }

    DataTable > .datatable--cursor {
        background: $foreground 30%;
        color: $foreground;
    }

    DataTable > .datatable--header {
        background: $background;
        color: $foreground;
    }

    DataTable:focus {
        background-tint: transparent;
    }

    DataTable:focus > .datatable--header {
        background: $background;
        background-tint: transparent;
        color: $secondary;
    }

    DataTable > .datatable--header-hover {
        background: $background;
        color: $secondary;
    }

    DataTable > .datatable--row-hover {
        background: $background;
        color: $foreground;
    }

    DataTable > .datatable--even-row, DataTable > .datatable--odd-row {
        background: $background;
    }
    """

    # Currently selected network section ("known" or "new") for visual highlighting.
    active_section = reactive(None)

    # Hide the Device/Station info sections when the terminal is too short.
    MIN_HEIGHT_FOR_INFO_SECTIONS = 22

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("tab", "switch_section", "Switch", priority=True),
        Binding("space", "select", "Connect"),
        Binding("s", "scan", "Scan"),
        Binding("d", "disconnect", "Disconnect"),
        Binding("f", "forget", "Forget"),
        Binding("h", "hidden", "Hidden"),
        Binding("v", "vpn_screen", "VPN"),
        Binding("m", "wwan_screen", "WWAN"),
        Binding("ctrl+m", "toggle_wwan_radio", "Toggle WWAN"),
        Binding("ctrl+w", "toggle_wifi", "Toggle WiFi"),
        Binding("e", "wired_8021x", "802.1X Wired"),
    ]

    def __init__(self, *args, **kwargs):
        # Detect WWAN support once at startup so the footer and key handling
        # can hide WWAN-specific bindings on systems without cellular hardware.
        self._has_wwan = has_wwan_capabilities()
        super().__init__(*args, **kwargs)
        # Track any running async scan subprocess so we can kill it on quit.
        # Initialized here (rather than in on_mount) so on_unmount can safely
        # inspect it even if the app shuts down before/during mount.
        self._scan_process = None

    def compose(self) -> ComposeResult:
        device_container = Container(DataTable(id="dev"), classes="section", id="device-section")
        device_container.border_title = "Device"
        station_container = Container(
            DataTable(id="sta"),
            classes="section",
            id="station-section",
        )
        known_container = Container(
            DataTable(id="known", cursor_type="row"),
            classes="section",
            id="known-section",
        )
        known_container.border_title = "Known Networks"
        new_container = Container(
            DataTable(id="new", cursor_type="row"),
            classes="section",
            id="new-section",
        )
        new_container.border_title = "New Networks"
        station_container.border_title = "Station"
        yield ScrollableContainer(
            device_container,
            station_container,
            known_container,
            new_container,
        )
        yield Footer()

    def on_mount(self) -> None:
        # Load color sources
        user_colors = load_user_colors(self.CONFIG_DIR)

        # Register custom themes when their source colors are available
        if user_colors:
            self.register_theme(
                Theme(
                    name="user-theme",
                    primary=user_colors["primary"],
                    secondary=user_colors["secondary"],
                    accent=user_colors["secondary"],
                    foreground=user_colors["foreground"],
                    background=user_colors["background"],
                    surface=user_colors["background"],
                    panel=user_colors["background"],
                    boost="transparent",
                    success=user_colors["success"],
                    warning=user_colors["warning"],
                    error=user_colors["error"],
                    dark=True,
                )
            )

        # Flatten all builtin themes so they only use the four Gazelle colors.
        _flatten_builtin_themes(self)

        # config.toml is the source of truth for the active theme
        config = self.load_config()
        saved_theme = config.get("theme")

        effective_theme, should_save = resolve_theme(
            saved_theme,
            user_colors is not None,
            lambda name: self.get_theme(name) is not None,
        )

        if should_save:
            config["theme"] = effective_theme
            self.save_config(config)

        try:
            self.theme = effective_theme
        except Exception:
            self.theme = "textual-dark"

        self.query_one("#dev", DataTable).add_columns("Name", "Mode", "Powered", "MAC Address")
        self.query_one("#dev", DataTable).cursor_type = "none"
        self.query_one("#dev", DataTable).can_focus = False
        self.query_one("#sta", DataTable).add_columns(
            "State", "Frequency", "Security", "IPv4 Address"
        )
        self.query_one("#sta", DataTable).cursor_type = "none"
        self.query_one("#sta", DataTable).can_focus = False
        self.query_one("#known", DataTable).add_columns("Name", "Security", "Signal")
        self.query_one("#new", DataTable).add_columns("Name", "Security", "Signal")

        # Show cached network list immediately
        initial_networks = get_wifi_list(force_rescan=False)
        if initial_networks:
            self.refresh_all(networks=initial_networks)
        else:
            # Show placeholder while background rescan runs
            new_table = self.query_one("#new", DataTable)
            new_table.add_row("Scanning for networks...", "", "")

        # Trigger async rescan in background; refresh on every changed poll.
        self.run_worker(partial(self.scan_networks_async, initial_networks), exclusive=True)

        self.query_one("#new").focus()
        self.active_section = "new"
        self.query_one("#known", DataTable).cursor_type = "none"
        self.query_one("#new", DataTable).cursor_type = "row"
        self.update_info_sections_visibility()

    def on_unmount(self) -> None:
        """Kill any in-flight scan subprocess on quit."""
        self.workers.cancel_all()
        if self._scan_process is not None and self._scan_process.returncode is None:
            self._scan_process.kill()

    def update_info_sections_visibility(self) -> None:
        """Hide Device/Station sections when the viewport is too short."""
        tall_enough = self.size.height >= self.MIN_HEIGHT_FOR_INFO_SECTIONS
        self.query_one("#device-section").display = tall_enough
        self.query_one("#station-section").display = tall_enough

    def on_resize(self) -> None:
        """Re-evaluate section visibility when the terminal is resized."""
        self.update_info_sections_visibility()

    def load_config(self) -> dict:
        """Load configuration from ~/.config/gazelle/config.toml

        Returns:
            dict: Configuration dictionary, or empty dict if file doesn't exist
        """
        try:
            if self.CONFIG_FILE.exists() and tomllib is not None:
                with open(self.CONFIG_FILE, "rb") as f:
                    return tomllib.load(f)
        except Exception as e:
            # If config is corrupted, log error and return empty dict
            self.log.error(f"Failed to load config: {e}")
        return {}

    def save_config(self, data: dict) -> None:
        """Save configuration to ~/.config/gazelle/config.toml

        Args:
            data: Dictionary to save as TOML
        """
        try:
            # Create config directory if it doesn't exist
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

            # Write minimal TOML manually; only theme is supported
            lines = []
            if "theme" in data:
                lines.append(f"theme = {json.dumps(data['theme'])}")
            self.CONFIG_FILE.write_text("\n".join(lines) + "\n")
        except OSError as e:
            self.log.error(f"Failed to save config: {e}")

    def watch_theme(self, new_theme: str) -> None:
        """Automatically called by Textual when self.theme changes.

        Saves the new theme to config.toml for persistence.

        Args:
            new_theme: The new theme name that was just set
        """
        # Load existing config, update theme, save back
        config = self.load_config()
        config["theme"] = new_theme
        self.save_config(config)
        self.log.info(f"Theme changed to: {new_theme}")

    def _request_rescan(self) -> None:
        """Ask NetworkManager to scan. Ignore errors (e.g. scan already in progress)."""
        try:
            subprocess.run(
                ["nmcli", "device", "wifi", "rescan"],
                capture_output=True,
            )
        except Exception:
            pass

    async def _list_wifi_async(self) -> list:
        """Run a cancellable plain ``nmcli device wifi list``.

        Returns:
            Parsed list of network dicts.
        """
        proc = await asyncio.create_subprocess_exec(
            "nmcli",
            "-t",
            "--colors",
            "no",
            "-f",
            "SSID,SIGNAL,SECURITY,IN-USE",
            "device",
            "wifi",
            "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._scan_process = proc
        try:
            stdout, _ = await proc.communicate()
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
            raise
        finally:
            self._scan_process = None

        if proc.returncode != 0:
            return []

        return _parse_wifi_list(stdout.decode())

    async def scan_networks_async(self, baseline_networks=None) -> None:
        """Async WiFi network scanning in background.

        Fires ``nmcli device wifi rescan`` once, then polls the plain list and
        refreshes the UI whenever it changes. Stops early when the list has
        been stable for two consecutive polls, but only after SCAN_MIN_POLLS
        so we don't trust the stale pre-scan cache.
        """
        try:
            self._request_rescan()

            previous = None
            unchanged = 0
            for i in range(SCAN_MAX_POLLS):
                await asyncio.sleep(SCAN_POLL_INTERVAL)
                networks = await self._list_wifi_async()

                if previous is None:
                    # First poll: refresh if the baseline was empty or if the
                    # list already changed. This also removes the placeholder.
                    if not baseline_networks or networks != baseline_networks:
                        self.refresh_all(networks=networks)
                    unchanged = 0
                elif networks != previous:
                    self.refresh_all(networks=networks)
                    unchanged = 0
                else:
                    unchanged += 1
                    if i >= SCAN_MIN_POLLS and unchanged >= SCAN_REPEATS:
                        break

                previous = networks

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.notify(f"Scan failed: {str(e)}")

    def refresh_all(self, networks=None, force_rescan=False) -> None:
        # Fetch network list once if not provided
        if networks is None:
            networks = get_wifi_list(force_rescan=force_rescan)
        avail = {n["ssid"]: n for n in networks}

        iface = get_wifi_interface()

        # Device
        device_table = self.query_one("#dev", DataTable)
        device_table.clear()
        try:
            mac = subprocess.run(
                ["cat", f"/sys/class/net/{iface}/address"],
                capture_output=True,
                text=True,
            ).stdout.strip()
        except:
            mac = "-"
        device_table.add_row(iface, "station", "On" if wifi_enabled() else "Off", mac)

        # Add WWAN status if the system has WWAN capability
        if has_wwan_capabilities():
            device_table.add_row("wwan", "wwan", "On" if wwan_enabled() else "Off", "-")

        # Station
        station_table = self.query_one("#sta", DataTable)
        station_table.clear()
        info = get_station_info()
        ipv4 = get_device_ipv4(iface) if info["state"] == "connected" else "-"
        station_table.add_row(info["state"], info["frequency"], info["security"], ipv4)

        # Known (only show networks that are in range)
        known_table = self.query_one("#known", DataTable)
        known_table.clear()
        known_ssids = set()
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.strip().split("\n"):
                if ":802-11-wireless" in line or ":wifi" in line:
                    name = line.split(":")[0]
                    known_ssids.add(name)
                    # Only show if network is in range
                    if name in avail:
                        security = avail[name]["security"]
                        if is_enterprise(security):
                            sec = "802.1x"
                        elif is_owe(security):
                            sec = "owe"
                        elif security:
                            sec = "psk"
                        else:
                            sec = "-"
                        sig = f"{avail[name]['signal']}%"
                        known_table.add_row(name, sec, sig)
        except:
            pass

        # New (exclude networks that are already known)
        new_table = self.query_one("#new", DataTable)
        new_table.clear()
        for n in networks:
            if n["ssid"] not in known_ssids:
                if is_enterprise(n["security"]):
                    sec = "802.1x"
                elif is_owe(n["security"]):
                    sec = "owe"
                elif n["security"]:
                    sec = "psk"
                else:
                    sec = "-"
                new_table.add_row(n["ssid"], sec, f"{n['signal']}%")

    def _get_focused_table(self) -> DataTable:
        """Get the currently focused table"""
        known = self.query_one("#known", DataTable)
        new = self.query_one("#new", DataTable)
        if known.has_focus:
            return known
        else:
            return new

    def action_cursor_down(self) -> None:
        t = self._get_focused_table()
        if t.row_count > 0:
            t.action_cursor_down()

    def action_cursor_up(self) -> None:
        t = self._get_focused_table()
        if t.row_count > 0:
            t.action_cursor_up()

    def watch_active_section(self, old_section: str | None, new_section: str | None) -> None:
        """Update the visual highlight when the active network section changes."""
        if new_section is None:
            return
        known_section = self.query_one("#known-section")
        new_container = self.query_one("#new-section")
        if new_section == "known":
            known_section.add_class("active-section")
            new_container.remove_class("active-section")
        else:
            new_container.add_class("active-section")
            known_section.remove_class("active-section")

    def on_focus(self, event) -> None:
        """Keep active_section in sync with keyboard or mouse focus changes."""
        if event.control.id in ("known", "new"):
            self.active_section = event.control.id
            known = self.query_one("#known", DataTable)
            new = self.query_one("#new", DataTable)
            if event.control.id == "known":
                known.cursor_type = "row"
                new.cursor_type = "none"
            else:
                new.cursor_type = "row"
                known.cursor_type = "none"

    def action_switch_section(self) -> None:
        """Toggle focus between Known and New network sections.

        Falls back to the default focus traversal when a modal/dialog is open.
        """
        known = self.query_one("#known", DataTable)
        new = self.query_one("#new", DataTable)
        if not (known.has_focus or new.has_focus):
            super().action_focus_next()
            return
        if known.has_focus:
            known.cursor_type = "none"
            new.focus()
            new.cursor_type = "row"
            self.active_section = "new"
        else:
            new.cursor_type = "none"
            known.focus()
            known.cursor_type = "row"
            self.active_section = "known"

    def action_scan(self) -> None:
        self.notify("Scanning...")
        self.run_worker(self.scan_networks_async, exclusive=True)

    def action_select(self) -> None:
        t = self._get_focused_table()
        is_known = self.query_one("#known").has_focus

        if t.cursor_row >= 0 and t.cursor_row < t.row_count:
            row = t.get_row_at(t.cursor_row)
            ssid, sec = str(row[0]), str(row[1])

            if is_known:
                self.notify("Connecting...")
                r = subprocess.run(
                    ["nmcli", "connection", "up", ssid], capture_output=True, text=True
                )
                self.notify("✓ Connected" if r.returncode == 0 else "✗ Failed")
                self.refresh_all()
            else:
                if sec == "802.1x":
                    self.push_screen(PasswordScreen(ssid, is_enterprise=True), self.handle_connect)
                elif sec == "psk":
                    self.push_screen(PasswordScreen(ssid, is_enterprise=False), self.handle_connect)
                else:  # Open or OWE - NetworkManager handles OWE automatically
                    ok, msg = connect_wifi(ssid, "", hidden=False)
                    self.notify("✓ Connected" if ok else f"✗ {msg}")
                    self.refresh_all()

    def handle_connect(self, result) -> None:
        if not result:
            return
        ssid, pwd, user, is_ent, eap, phase2, is_hidden = result
        self.notify("Connecting...")
        if is_ent:
            ok, msg = connect_802_1x(
                ssid, user, pwd, eap or "peap", phase2 or "mschapv2", is_hidden
            )
        else:
            ok, msg = connect_wifi(ssid, pwd, is_hidden)
        self.notify("✓ Connected" if ok else f"✗ {msg}")
        self.refresh_all()

    def action_hidden(self) -> None:
        """Connect to hidden network (h key)"""

        def handle_hidden(result):
            if not result:
                return
            ssid, sec = result
            if sec == "open":
                self.notify("Connecting...")
                ok, msg = connect_wifi(ssid, "", hidden=True)
                self.notify("✓ Connected" if ok else f"✗ {msg}")
                self.refresh_all()
            elif sec == "psk":
                self.push_screen(
                    PasswordScreen(ssid, is_enterprise=False, is_hidden=True),
                    self.handle_connect,
                )
            else:  # 8021x
                self.push_screen(
                    PasswordScreen(ssid, is_enterprise=True, is_hidden=True),
                    self.handle_connect,
                )

        self.push_screen(HiddenNetworkScreen(), handle_hidden)

    def action_disconnect(self) -> None:
        self.notify("Disconnected" if disconnect() else "Not connected")
        self.refresh_all()

    def action_forget(self) -> None:
        """Remove selected known network"""
        known = self.query_one("#known", DataTable)
        if not known.has_focus or known.row_count == 0:
            return
        if known.cursor_row < 0 or known.cursor_row >= known.row_count:
            return
        row = known.get_row_at(known.cursor_row)
        ssid = str(row[0]).strip()
        if not ssid:
            return
        success = forget_network(ssid)
        self.notify("✓ Network forgotten" if success else "✗ Failed")
        self.refresh_all()

    def action_toggle_wifi(self) -> None:
        enabled = toggle_wifi()
        self.notify(f"WiFi {'ON' if enabled else 'OFF'}")
        if enabled:
            self.action_scan()
        else:
            self.set_timer(1, self.refresh_all)

    def action_toggle_wwan_radio(self) -> None:
        try:
            result = toggle_wwan()
            msg = "ON" if result else "OFF"

            with open("/tmp/gazelle_debug.log", "a") as f:
                f.write(f"Toggle Result: {result} -> {msg}\n")

            self.notify(f"WWAN {msg}")
            self.set_timer(1, self.refresh_all)
        except Exception as e:
            with open("/tmp/gazelle_debug.log", "a") as f:
                f.write(f"Action Error: {e}\n")

    def action_vpn_screen(self) -> None:
        """Open VPN management screen"""
        if not get_vpn_list():
            self.notify(
                "No VPNs found. VPN connections must be configured in Network Manager before they are available in Gazelle."
            )
            return
        self.push_screen(VPNScreen())

    def action_wwan_screen(self) -> None:
        """Open WWAN management screen"""
        self.push_screen(WWANScreen())

    def action_wired_8021x(self) -> None:
        """Open wired 802.1X connection dialog"""
        iface = get_ethernet_interface()
        if not iface:
            self.notify("No Ethernet interface found")
            return
        self.push_screen(Wired8021xScreen(), self.handle_wired_8021x)

    def handle_wired_8021x(self, result) -> None:
        """Handle wired 802.1X connection result"""
        if not result:
            return
        con_name, user, pwd, eap, phase2 = result
        self.notify("Connecting...")
        ok, msg = connect_802_1x_wired(con_name, user, pwd, eap or "peap", phase2 or "mschapv2")
        self.notify("✓ Connected" if ok else f"✗ {msg}")
        self.refresh_all()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Hide WWAN bindings when no WWAN capability is available."""
        if action in ("wwan_screen", "toggle_wwan_radio") and not self._has_wwan:
            return False
        return True
