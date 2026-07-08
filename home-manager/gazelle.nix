{
  config,
  lib,
  pkgs,
  ...
}:

with lib;

let
  cfg = config.programs.gazelle;

  tomlFormat = pkgs.formats.toml { };

  validBorderStyles = [
    "none"
    "ascii"
    "blank"
    "dashed"
    "double"
    "heavy"
    "hidden"
    "hkey"
    "inner"
    "outer"
    "panel"
    "round"
    "solid"
    "tall"
    "thick"
    "vkey"
    "wide"
  ];

  # Nix representation of theme.toml.
  themeType = types.submodule {
    options = {
      colors = mkOption {
        type = types.nullOr (
          types.submodule {
            options = {
              accent = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Accent color used for highlights, borders, and the cursor.";
              };
              primary = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Primary color used for active/selected elements.";
              };
              foreground = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Default text color.";
              };
              background = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Background color.";
              };
            };
          }
        );
        default = null;
        description = ''
          Semantic color overrides. All four colors must be set for Gazelle
          to register and use the custom <literal>user-theme</literal>.
        '';
      };

      styles = mkOption {
        type = types.nullOr (
          types.submodule {
            options = {
              dialog_border = mkOption {
                type = types.nullOr (types.enum validBorderStyles);
                default = null;
                description = "Border style of modal dialogs.";
              };
              dialog_width = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Width of modal dialogs (Textual CSS units).";
              };
              dialog_padding = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Padding inside modal dialogs (Textual CSS units).";
              };
              section_border = mkOption {
                type = types.nullOr (types.enum validBorderStyles);
                default = null;
                description = "Border style of main sections.";
              };
              section_margin = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Margin around main sections (Textual CSS units).";
              };
              section_padding = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Padding inside main sections (Textual CSS units).";
              };
              section_title_padding = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Padding around section titles (Textual CSS units).";
              };
              info_section_height = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Height of the device/station info sections.";
              };
              input_height = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Height of input fields and selects.";
              };
              button_min_width = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Minimum width of buttons.";
              };
              cursor_opacity = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Opacity of the DataTable cursor highlight.";
              };
              hover_opacity = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Opacity of the DataTable hover highlight.";
              };
              title_text_style = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Text style of dialog titles.";
              };
              section_title_text_style = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Text style of section titles.";
              };
            };
          }
        );
        default = null;
        description = "TUI style overrides for borders, spacing, and text styling.";
      };
    };
  };

  # Remove unset (null) options so theme.toml only contains explicitly set values.
  themeToToml =
    theme:
    let
      colors = if theme.colors == null then null else filterAttrs (n: v: v != null) theme.colors;
      styles = if theme.styles == null then null else filterAttrs (n: v: v != null) theme.styles;
    in
    optionalAttrs (colors != null && colors != { }) { inherit colors; }
    // optionalAttrs (styles != null && styles != { }) { inherit styles; };

  hasFullColors =
    theme:
    theme.colors != null
    && all (k: theme.colors.${k} != null) [
      "accent"
      "primary"
      "foreground"
      "background"
    ];

in
{
  options.programs.gazelle = {
    enable = mkOption {
      type = types.bool;
      default = false;
      description = "Enable gazelle configuration";
    };

    settings = mkOption {
      type = types.attrsOf types.str;
      default = {
        theme = "textual-dark";
      };
      description = "Gazelle settings (will be written to ~/.config/gazelle/config.json)";
    };

    theme = mkOption {
      type = types.nullOr themeType;
      default = null;
      description = ''
        Gazelle theme configuration written to
        <literal>~/.config/gazelle/theme.toml</literal>.

        To use a complete custom color theme, set all four
        <literal>colors</literal> and also set
        <literal>settings.theme = "user-theme"</literal>.
      '';
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.theme == null || cfg.theme.colors == null || hasFullColors cfg.theme;
        message = "programs.gazelle.theme.colors: if set, all four colors (accent, primary, foreground, background) must be specified";
      }
    ];

    home.file.".config/gazelle/config.json".text = builtins.toJSON cfg.settings;

    home.file.".config/gazelle/theme.toml" = mkIf (cfg.theme != null) {
      source = tomlFormat.generate "theme.toml" (themeToToml cfg.theme);
    };
  };
}
