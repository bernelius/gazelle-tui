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

  # Nix representation of theme.toml.
  themeType = types.submodule {
    options = {
      colors = mkOption {
        type = types.nullOr (
          types.submodule {
            options = {
              secondary = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Secondary color used for highlights, borders, and the cursor.";
              };
              success = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Success color used for positive status indicators.";
              };
              warning = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Warning color used for cautionary status indicators.";
              };
              error = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Error color used for negative status indicators.";
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
          Semantic color overrides. All four base colors must be set for
          Gazelle to register and use the custom <literal>user-theme</literal>.
          Optional status colors (<literal>success</literal>,
          <literal>warning</literal>, <literal>error</literal>) override the
          defaults used by Textual widgets such as buttons and notifications.
        '';
      };

    };
  };

  # Remove unset (null) options so theme.toml only contains explicitly set values.
  themeToToml =
    theme:
    let
      colors = if theme.colors == null then null else filterAttrs (n: v: v != null) theme.colors;
    in
    optionalAttrs (colors != null && colors != { }) { inherit colors; };

  hasFullColors =
    theme:
    theme.colors != null
    && all (k: theme.colors.${k} != null) [
      "secondary"
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
      description = "Gazelle settings (will be written to ~/.config/gazelle/config.toml)";
    };

    theme = mkOption {
      type = types.nullOr themeType;
      default = null;
      description = ''
        Gazelle theme configuration written to
        <literal>~/.config/gazelle/theme.toml</literal>.

        To use a complete custom color theme, set all four base
        <literal>colors</literal> and also set
        <literal>settings.theme = "user-theme"</literal>.
      '';
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.theme == null || cfg.theme.colors == null || hasFullColors cfg.theme;
        message = "programs.gazelle.theme.colors: if set, all four base colors (secondary, primary, foreground, background) must be specified";
      }
    ];

    home.file.".config/gazelle/config.toml".source = tomlFormat.generate "config.toml" cfg.settings;

    home.file.".config/gazelle/theme.toml" = mkIf (cfg.theme != null) {
      source = tomlFormat.generate "theme.toml" (themeToToml cfg.theme);
    };
  };
}
