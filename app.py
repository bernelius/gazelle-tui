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


def load_omarchy_colors():
    """
    Load colors from Omarchy's active theme.
    Returns dict with RGB color values, or None if not found.
    """
    if tomllib is None:
        return None

    theme_file = Path.home() / ".config/omarchy/current/theme/alacritty.toml"

    if not theme_file.exists():
        return None

    try:
        with open(theme_file, "rb") as f:
            data = tomllib.load(f)

        colors = data.get("colors", {})
        normal = colors.get("normal", {})
        bright = colors.get("bright", {})
        primary = colors.get("primary", {})

        return {
            "accent": normalize_color_format(
                normal.get("yellow") or bright.get("yellow") or "#EBCB8B"
            ),
            "primary": normalize_color_format(normal.get("red") or bright.get("red") or "#BF616A"),
            "foreground": normalize_color_format(primary.get("foreground") or "#D8DEE9"),
            "background": normalize_color_format(primary.get("background") or "#2E3440"),
        }
    except Exception:
        # If parsing fails, return None to use fallback
        return None


def load_omarchy_styles():
    """
    Detect border style preferences from Omarchy's Hyprland config.
    Checks all Hyprland config sources in cascade order (last value wins):
      1. ~/.local/share/omarchy/default/hypr/looknfeel.conf (system default)
      2. ~/.config/omarchy/current/theme/hyprland.conf (theme override)
      3. ~/.config/hypr/looknfeel.conf (user override)
    Returns dict with border style overrides, or None if not found.
    """
    # Check if this is an Omarchy system
    omarchy_indicator = Path.home() / ".config/omarchy/current/theme/alacritty.toml"
    if not omarchy_indicator.exists():
        return None

    # Hyprland sources in cascade order — last uncommented value wins
    config_files = [
        Path.home() / ".local/share/omarchy/default/hypr/looknfeel.conf",
        Path.home() / ".config/omarchy/current/theme/hyprland.conf",
        Path.home() / ".config/hypr/looknfeel.conf",
    ]

    rounding = 0  # Default: no rounding
    border_size = 2  # Omarchy default

    try:
        for config_file in config_files:
            if not config_file.exists():
                continue
            with open(config_file, "r") as f:
                for line in f:
                    stripped = line.strip()
                    # Skip comments
                    if stripped.startswith("#"):
                        continue
                    if "=" in stripped:
                        key, _, val = stripped.partition("=")
                        key_name = key.strip()
                        if key_name == "rounding":
                            rounding = int(val.strip())
                        elif key_name == "border_size":
                            border_size = int(val.strip())
    except Exception:
        return None

    # Rounding takes priority — use rounded borders
    if rounding > 0:
        return {
            "dialog_border": "round",
            "section_border": "round",
        }

    # Map Hyprland border_size to closest Textual border style
    if border_size == 0:
        border_style = "blank"
    elif border_size >= 3:
        border_style = "heavy"
    else:
        border_style = "solid"

    return {
        "dialog_border": border_style,
        "section_border": border_style,
    }


_DEFAULT_THEME_COLORS = {
    "accent": "#EBCB8B",
    "primary": "#BF616A",
    "foreground": "#D8DEE9",
    "background": "#2E3440",
}

_SEMANTIC_COLOR_KEYS = set(_DEFAULT_THEME_COLORS)


def _is_old_theme_format(data: dict) -> bool:
    """Return True if theme.toml uses the pre-semantic nested color format."""
    colors = data.get("colors")
    if not isinstance(colors, dict):
        return False

    # Already migrated if any new semantic key is present as a concrete value.
    if any(key in colors and not isinstance(colors[key], dict) for key in _SEMANTIC_COLOR_KEYS):
        return False

    # Old format used nested dicts under colors.
    return any(isinstance(colors.get(section), dict) for section in ("normal", "bright", "primary"))


def _write_theme_file(
    theme_file: Path, colors: dict, styles: dict, commented: bool = False
) -> None:
    """Write a theme.toml file from the semantic color and style dicts."""
    comment_prefix = "#" if commented else ""
    lines = [
        "# Gazelle Theme Configuration",
        "# Uncomment and modify these values to customize your theme",
        "# Colors should be in hex format (#RRGGBB) or 0xRRGGBB",
        "[colors]",
    ]
    for key in ("accent", "primary", "foreground", "background"):
        lines.append(f"{comment_prefix}{key} = {json.dumps(colors[key])}")

    if styles:
        lines.extend(
            [
                "",
                "# TUI Style Overrides",
                "# Uncomment and modify these values to customize borders, spacing, etc.",
                "# Border styles: ascii, blank, dashed, double, heavy, hidden, hkey, inner,",
                "#   none, outer, panel, round, solid, tall, thick, vkey, wide",
                '# Spacing values use Textual CSS units (e.g. "1 2" = 1 vertical, 2 horizontal)',
                "[styles]",
            ]
        )
        for key, value in styles.items():
            lines.append(f"{key} = {json.dumps(value)}")

    theme_file.write_text("\n".join(lines) + "\n")


def migrate_user_theme(config_dir: Path) -> bool:
    """
    One-time migration from the old nested color format to the semantic format.

    Backs up the original file to theme.toml.bak. Returns True if a migration
    was performed. An empty old template (no color values set) is rewritten to
    the new empty template so it remains inactive.
    """
    if tomllib is None:
        return False

    theme_file = config_dir / "theme.toml"
    if not theme_file.exists():
        return False

    try:
        with open(theme_file, "rb") as f:
            data = tomllib.load(f)

        if not _is_old_theme_format(data):
            return False

        colors = data.get("colors", {})
        normal = colors.get("normal", {})
        bright = colors.get("bright", {})
        primary = colors.get("primary", {})

        migrated = {
            "accent": normal.get("yellow") or bright.get("yellow"),
            "primary": normal.get("red") or bright.get("red"),
            "foreground": primary.get("foreground"),
            "background": primary.get("background"),
        }

        # If no old colors were actually set, rewrite to the new empty template
        # so an all-commented file still does not activate a custom theme.
        if not any(migrated.values()):
            _write_theme_file(theme_file, _DEFAULT_THEME_COLORS, {}, commented=True)
            return True

        # Fill any missing colors from defaults so the migrated theme is complete.
        for key, default in _DEFAULT_THEME_COLORS.items():
            if not migrated[key]:
                migrated[key] = default
            else:
                migrated[key] = normalize_color_format(migrated[key])

        styles = data.get("styles", {})
        if not isinstance(styles, dict):
            styles = {}

        backup_file = theme_file.with_name("theme.toml.bak")
        backup_file.write_text(theme_file.read_text())

        _write_theme_file(theme_file, migrated, styles)
        return True
    except Exception:
        # If migration fails, leave the file untouched and let loading fall back.
        return False


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

    # Migrate old-format theme files before loading.
    migrate_user_theme(config_dir)

    try:
        with open(theme_file, "rb") as f:
            data = tomllib.load(f)

        colors = data.get("colors", {})

        accent = colors.get("accent")
        primary = colors.get("primary")
        foreground = colors.get("foreground")
        background = colors.get("background")

        # All four semantic colors must be defined for a custom theme to activate.
        if not all((accent, primary, foreground, background)):
            return None

        return {
            "accent": normalize_color_format(accent),
            "primary": normalize_color_format(primary),
            "foreground": normalize_color_format(foreground),
            "background": normalize_color_format(background),
        }
    except Exception:
        # If parsing fails, return None to use fallback
        return None


# Default style values matching the original hardcoded CSS
DEFAULT_STYLES = {
    "dialog_border": "solid",
    "dialog_width": "60",
    "dialog_padding": "1 2",
    "section_border": "solid",
    "section_margin": "1 2",
    "section_padding": "0 1",
    "section_title_padding": "0 1",
    "input_height": "3",
    "button_min_width": "12",
    "cursor_opacity": "30%",
    "hover_opacity": "20%",
    "title_text_style": "bold",
    "section_title_text_style": "bold",
}

# Valid Textual border styles for validation
VALID_BORDER_STYLES = {
    "none",
    "ascii",
    "blank",
    "dashed",
    "double",
    "heavy",
    "hidden",
    "hkey",
    "inner",
    "outer",
    "panel",
    "round",
    "solid",
    "tall",
    "thick",
    "vkey",
    "wide",
}


def load_user_styles(config_dir: Path, omarchy_styles: dict | None = None):
    """
    Load TUI style overrides from user theme file.
    Returns dict with style values merged over defaults.
    Priority: defaults -> omarchy auto-detect -> user theme.toml
    """
    styles = dict(DEFAULT_STYLES)

    # Apply Omarchy auto-detected styles over defaults
    if omarchy_styles:
        for key, value in omarchy_styles.items():
            if key in DEFAULT_STYLES:
                styles[key] = value

    if tomllib is None:
        return styles

    theme_file = config_dir / "theme.toml"
    if not theme_file.exists():
        return styles

    try:
        with open(theme_file, "rb") as f:
            data = tomllib.load(f)

        user_styles = data.get("styles", {})
        for key, value in user_styles.items():
            # Normalize key: allow hyphens or underscores
            norm_key = key.replace("-", "_")
            if norm_key in DEFAULT_STYLES:
                str_val = str(value)
                # Validate border styles
                if norm_key in ("dialog_border", "section_border"):
                    if str_val.lower() not in VALID_BORDER_STYLES:
                        continue
                    str_val = str_val.lower()
                styles[norm_key] = str_val
    except Exception:
        pass

    return styles


def build_css(styles: dict) -> str:
    """Build Textual CSS string from style configuration."""
    return f"""
    PasswordScreen, HiddenNetworkScreen, Wired8021xScreen {{ align: center middle; }}
    #dialog {{ width: {styles["dialog_width"]}; height: auto; border: {styles["dialog_border"]} $accent; background: $background; padding: {styles["dialog_padding"]}; }}
    #title {{ text-style: {styles["title_text_style"]}; color: $accent; margin-bottom: 1; }}
    .section {{ border: {styles["section_border"]} $accent; margin: {styles["section_margin"]}; padding: {styles["section_padding"]}; height: 1fr; layout: vertical; }}
    .section.active-section {{ border: {styles["section_border"]} $primary; }}
    .section-title {{ text-style: {styles["section_title_text_style"]}; color: $accent; background: $background; padding: {styles["section_title_padding"]}; height: auto; }}
    .section DataTable {{ height: 1fr; }}
    #device-section, #station-section {{ height: 4; }}
    Static {{ height: auto; }}
    Input {{ height: {styles["input_height"]}; margin-bottom: 1; }}
    Select {{ height: {styles["input_height"]}; margin-bottom: 1; }}
    Horizontal {{ height: auto; margin-top: 1; }}
    Button {{ min-width: {styles["button_min_width"]}; }}

    /* DataTable selection/cursor colors */
    DataTable > .datatable--cursor {{
        background: $accent {styles["cursor_opacity"]};
        color: $foreground;
    }}

    /* Remove the default focus background tint from all DataTables so the
       container background doesn't change. */
    DataTable:focus {{
        background-tint: transparent;
    }}

    /* Keep header rows unchanged when DataTables are focused or hovered. */
    DataTable:focus > .datatable--header {{
        background-tint: transparent;
    }}

    DataTable > .datatable--header-hover {{
        background: transparent;
    }}
    """


def resolve_theme(saved_theme, has_user_theme, has_omarchy_theme, theme_exists):
    """Determine the effective theme and whether it should be persisted.

    config.json is the source of truth: if it names a valid theme, that theme
    is used unchanged. Otherwise the app auto-detects a default and the result
    is written back to config.json.

    Args:
        saved_theme: Theme name from config.json, or None.
        has_user_theme: True if a user theme.toml was loaded successfully.
        has_omarchy_theme: True if an Omarchy theme was detected.
        theme_exists: Callable that returns True for available theme names.

    Returns:
        Tuple of (effective_theme_name, should_save_to_config).
    """
    if saved_theme and theme_exists(saved_theme):
        return saved_theme, False

    if has_user_theme:
        return "user-theme", True
    if has_omarchy_theme:
        return "omarchy-auto", True
    return "textual-dark", True


def try_create_user_theme_template(config_dir: Path):
    """If file doesn't exist, create a template theme.toml file with commented examples"""
    theme_file = config_dir / "theme.toml"
    theme_dir = theme_file.parent

    # Create directory if it doesn't exist
    theme_dir.mkdir(parents=True, exist_ok=True)

    if not theme_file.exists():
        template_content = """# Gazelle Theme Configuration
# Uncomment and modify these values to customize your theme
# Colors should be in hex format (#RRGGBB) or 0xRRGGBB
[colors]
#accent     = "#EBCB8B"
#primary    = "#BF616A"
#foreground = "#D8DEE9"
#background = "#2E3440"

# TUI Style Overrides
# Uncomment and modify these values to customize borders, spacing, etc.
# Border styles: ascii, blank, dashed, double, heavy, hidden, hkey, inner,
#   none, outer, panel, round, solid, tall, thick, vkey, wide
# Spacing values use Textual CSS units (e.g. "1 2" = 1 vertical, 2 horizontal)
[styles]
#dialog_border = "solid"
#dialog_width = "60"
#dialog_padding = "1 2"
#section_border = "solid"
#section_margin = "1 2"
#section_padding = "0 1"
#section_title_padding = "0 1"
#input_height = "3"
#button_min_width = "12"
#cursor_opacity = "30%"
#hover_opacity = "20%"
#title_text_style = "bold"
#section_title_text_style = "bold"
"""
        with open(theme_file, "w") as f:
            f.write(template_content)
        return True
    return False


class Gazelle(App):
    TITLE = "Gazelle"
    CONFIG_DIR = Path.home() / ".config" / "gazelle"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    # Load styles: defaults -> omarchy auto-detect -> user overrides
    _omarchy_styles = load_omarchy_styles()
    _user_styles = load_user_styles(CONFIG_DIR, _omarchy_styles)
    CSS = build_css(_user_styles)

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
        Binding("r", "forget", "Forget"),
        Binding("h", "hidden", "Hidden"),
        Binding("v", "vpn_screen", "VPN"),
        Binding("w", "wwan_screen", "WWAN"),
        Binding("ctrl+r", "toggle_wifi", "WiFi"),
        Binding("ctrl+b", "toggle_wwan_radio", "WWAN Radio"),
        Binding("e", "wired_8021x", "802.1X Wired"),
        Binding("?", "help", "Help"),
    ]

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
        omarchy_colors = load_omarchy_colors()

        # Register custom themes when their source colors are available
        if user_colors:
            self.register_theme(
                Theme(
                    name="user-theme",
                    primary=user_colors["primary"],
                    secondary=user_colors["accent"],
                    accent=user_colors["accent"],
                    foreground=user_colors["foreground"],
                    background=user_colors["background"],
                    surface=user_colors["background"],
                    panel=user_colors["background"],
                    dark=True,
                )
            )

        if omarchy_colors:
            self.register_theme(
                Theme(
                    name="omarchy-auto",
                    primary=omarchy_colors["primary"],
                    secondary=omarchy_colors["accent"],
                    accent=omarchy_colors["accent"],
                    foreground=omarchy_colors["foreground"],
                    background=omarchy_colors["background"],
                    surface=omarchy_colors["background"],
                    panel=omarchy_colors["background"],
                    dark=True,
                )
            )

        # config.json is the source of truth for the active theme
        config = self.load_config()
        saved_theme = config.get("theme")

        effective_theme, should_save = resolve_theme(
            saved_theme,
            user_colors is not None,
            omarchy_colors is not None,
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

        # Track any running async scan subprocess so we can kill it on quit.
        self._scan_process = None

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
        """Load configuration from ~/.config/gazelle/config.json

        Returns:
            dict: Configuration dictionary, or empty dict if file doesn't exist
        """
        try:
            if self.CONFIG_FILE.exists():
                return json.loads(self.CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            # If config is corrupted, log error and return empty dict
            self.log.error(f"Failed to load config: {e}")
        return {}

    def save_config(self, data: dict) -> None:
        """Save configuration to ~/.config/gazelle/config.json

        Args:
            data: Dictionary to save as JSON
        """
        try:
            # Create config directory if it doesn't exist
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

            # Write config file with pretty formatting
            self.CONFIG_FILE.write_text(json.dumps(data, indent=2))
        except OSError as e:
            self.log.error(f"Failed to save config: {e}")

    def watch_theme(self, new_theme: str) -> None:
        """Automatically called by Textual when self.theme changes.

        Saves the new theme to config file for persistence.

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

        # Add WWAN status if wwan device exists
        try:
            # Use nmcli to detect if any gsm/wwan device exists
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE", "device"],
                capture_output=True,
                text=True,
            )
            wwan_iface = None
            for line in result.stdout.strip().split("\n"):
                if ":gsm" in line:
                    wwan_iface = line.split(":")[0]
                    break

            if wwan_iface:
                # Try to get MAC or IMEI? Just show iface for now
                device_table.add_row(wwan_iface, "wwan", "On" if wwan_enabled() else "Off", "-")
        except:
            pass

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
        known = self.query_one("#known")
        new = self.query_one("#new")
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
        self.notify(f"WiFi {'ON' if toggle_wifi() else 'OFF'}")
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

    def action_help(self) -> None:
        self.notify(
            "j/k:Move Tab:Switch Space:Connect s:Scan h:Hidden v:VPN e:802.1X Wired d:Disconnect r:Forget q:Quit",
            timeout=5,
        )
