# Gazelle Theme System Analysis

## Two separate subsystems

The theme system has **two completely independent layers** that are conflated because they both live in `theme.toml`.

### 1. Colors → Textual `Theme` object (registered)

Read from `theme.toml` `[colors.*]` sections by `load_user_colors()` at `app.py:457-487`.

The `[colors]` section uses an **Alacritty terminal emulator color scheme format** (copied from Omarchy), but only **4 of the 18 listed keys are actually used**:

| `theme.toml` key | Maps to Textual `Theme` prop | Referenced in CSS as |
|---|---|---|
| `colors.normal.yellow` (falls back to `bright.yellow`) | `accent` | `$accent` |
| `colors.normal.red` (falls back to `bright.red`) | `primary` | `$primary` |
| `colors.primary.foreground` | `foreground` | `$foreground` |
| `colors.primary.background` | `background` | `$background` |

**The other 14 keys** (`black`, `green`, `blue`, `magenta`, `cyan`, `white` in both `normal` and `bright`) are **dead code** — never read, never used. They're only in the template because it was lifted from an Omarchy/Alacritty config template verbatim.

### 2. Styles → Inline CSS string (injected at class level)

Read from `theme.toml` `[styles]` section by `load_user_styles()` at `app.py:510-550`.

These map to the `DEFAULT_STYLES` dict (`app.py:490-505`) and are interpolated into a CSS string via `build_css()` (`app.py:552-576`). **Unlike the colors, all `[styles]` keys are actually used.**

| `[styles]` key | CSS target |
|---|---|
| `dialog_border`, `dialog_width`, `dialog_padding` | `#dialog` (modal dialogs) |
| `section_border`, `section_margin`, `section_padding` | `.section` (the four main panels) |
| `section_title_padding`, `section_title_text_style` | `.section-title` |
| `title_text_style` | `#title` (dialog titles) |
| `info_section_height` | `#device-section`, `#station-section` |
| `input_height` | `Input`, `Select` |
| `button_min_width` | `Button` |
| `cursor_opacity` | `DataTable > .datatable--cursor` background |
| `hover_opacity` | `DataTable > .datatable--hover` background |

## CSS classes — what they map to

- **`.section`** — `Container` wrapping each of the 4 panels (Device, Station, Known, New) in `Gazelle.compose()`. Gets border, margin, padding from styles.
- **`.section-title`** — `Static` label at top of each section panel.
- **`.datatable--cursor`** / **`.datatable--hover`** — Textual's internal DataTable CSS classes for cursor row and hover row.
- **`#dialog`** — The `Container(id="dialog")` in every modal screen (PasswordScreen, HiddenNetworkScreen, Wired8021xScreen).
- **`#title`** — The title `Static` within each dialog.

## The naming confusion

The problem is that `theme.toml` `[colors]` uses **terminal color slot names** (`normal.yellow`, `normal.red`, `primary.foreground`) that are conceptually about ANSI palette positions, while the CSS uses **semantic names** (`$accent`, `$primary`, `$foreground`). The mapping is:

> `terminal color palette slot` → `load_user_colors()` → `Textual Theme(accent=..., primary=...)` → CSS `$accent`, `$primary`

If you want to change a CSS color, you'd need to know, for example, that to change the dialog border color (`$accent` in `build_css()`), you need to set `colors.normal.yellow` in `theme.toml`. That's completely non-obvious.

## Unused `theme.toml` keys

**All of these are unused:**
- `colors.normal.black`, `green`, `blue`, `magenta`, `cyan`, `white`
- `colors.bright.black`, `red`, `green`, `blue`, `yellow`, `magenta`, `cyan`, `white`
- `colors.primary` — only `foreground` and `background` are read; any `primary` key itself is never used

Only `normal.yellow`, `normal.red`, `primary.foreground`, `primary.background` (with fallbacks to `bright.*`) are actually consumed.
