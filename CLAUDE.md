# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gazelle is a minimal, keyboard-driven NetworkManager TUI for Linux with complete 802.1X enterprise WiFi support. Built with Python's Textual framework, it wraps `nmcli`/`mmcli`/DBus to manage WiFi, VPN, and WWAN/cellular connections.

## Development Setup & Running

```bash
pip install -r requirements.txt
chmod +x gazelle
./gazelle
```

With Nix: `nix develop` then `python3 gazelle`.

CI runs via GitHub Actions on push/PR to `main`: ruff check, ruff format check, and pytest. All three must pass.

## Linting & Testing

```bash
uv sync                       # install deps including dev
uv run ruff check .           # lint
uv run ruff format --check .  # check formatting
uv run ruff format .          # auto-format
uv run pytest -v              # run tests
```

## Architecture

The application is three files plus tests:

- **`gazelle`** - Entry point script (8 lines). Imports and runs the `Gazelle` App class.
- **`app.py`** - Main TUI application (~817 lines). Contains all UI: the `Gazelle(App)` main class plus modal screens (`PasswordScreen`, `VPNScreen`, `WWANScreen`, `HiddenNetworkScreen`). Uses Textual's reactive widget system with inline CSS for styling.
- **`network.py`** - Network abstraction layer (~414 lines). Purely functional (no classes). Every function wraps `subprocess.run` calls to `nmcli`/`mmcli` or DBus operations. Returns parsed data as lists/dicts.

### Key Patterns

- **Functional network layer**: `network.py` has zero classes. Each function runs a subprocess command, parses output, and returns data. All error handling is try/except around subprocess calls.
- **DBus-with-fallback**: Toggle operations (WiFi/WWAN radio) attempt DBus first for speed, then fall back to `nmcli` if DBus is unavailable.
- **Async scanning**: Network scans use `asyncio.to_thread()` to avoid blocking the TUI event loop.
- **Modal screen pattern**: Dialogs (VPN, WWAN, hidden network, password) are Textual `ModalScreen` subclasses that return results via `dismiss()`.
- **4-section layout**: Device info, Station info, Known Networks (saved, in range), New Networks (unsaved). Tab switches between the two network sections.

### Theme System

`config.json["theme"]` is the source of truth once set. On first run, the app auto-detects a default in this order:
1. **User custom theme** - `~/.config/gazelle/theme.toml` (only if all four base `[colors]` keys are defined)
2. **Omarchy auto-detection** - reads `~/.config/omarchy/current/theme/alacritty.toml`
3. **Built-in Textual themes** - `textual-dark` is the default

The user `theme.toml` uses semantic color names under `[colors]`:

```toml
[colors]
secondary  = "#EBCB8B"
primary    = "#BF616A"
foreground = "#D8DEE9"
background = "#2E3440"
success    = "#A3BE8C"
warning    = "#EBCB8B"
error      = "#BF616A"
```

The four base colors (`secondary`, `primary`, `foreground`, `background`) must all be defined for the custom theme to activate. `success`, `warning`, and `error` are optional and default to the values shown above.

An empty or fully commented `[colors]` section means the custom theme does not activate, so Omarchy or the built-in default is used.

Textual's built-in themes are available and can be selected manually via the command palette (`Ctrl+P`) or by setting `"theme"` in `config.json`. Gazelle's own UI only uses the four base colors (`$primary`, `$secondary`, `$foreground`, and `$background`), so every built-in theme is flattened on startup: `$surface`, `$panel`, and `$boost` are collapsed to `$background` and `$accent` is forced to equal `$secondary`. Status colors (`$success`, `$warning`, `$error`) are preserved from the built-in theme or the user config for Textual widgets such as buttons and notifications.

Theme choice persists in `~/.config/gazelle/config.json`. Helper functions `resolve_theme()`, `load_omarchy_colors()`, `load_user_colors()`, `load_user_styles()`, and `normalize_color_format()` handle theme resolution, color/style loading, and format conversion (0xRRGGBB to #RRGGBB).

### Configuration

- Config dir: `~/.config/gazelle/` (uses `platformdirs` constant `CONFIG_DIR`)
- Config file: `config.json` (currently only stores theme preference)
- Theme file: `theme.toml` (user custom colors, auto-generated template on first run; `[styles]` section is optional)

## Packaging

- **AUR**: `PKGBUILD` at repo root
- **Nix**: `flake.nix` with Home Manager module in `home-manager/gazelle.nix`
- **Gentoo**: packaged in GURU overlay (externally maintained, not in this repo)

## Dependencies

Runtime: Python 3.8+, `textual>=0.47.0`, `rich`, `platformdirs`, `dbus-python`. Optional: `ModemManager` (WWAN), `networkmanager-openvpn`, `wireguard-tools`.
