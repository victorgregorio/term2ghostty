# term2ghostty

Convert macOS `.terminal` profile files to [Ghostty](https://ghostty.org/) config format.

macOS Terminal.app stores its themes as `.terminal` files — XML property lists with fonts
and colors encoded as binary NSKeyedArchiver objects. This tool decodes them and produces
a plain-text Ghostty config you can drop straight into your setup.

## Requirements

- Python 3.9+
- macOS (`.terminal` files are macOS-specific)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Export your profile

1. Open **Terminal → Settings** (or Preferences on older macOS)
2. Select the **Profiles** tab
3. Choose the profile you want to convert
4. Click the **⚙ (gear)** menu at the bottom of the profile list and choose **Export...**
5. Save the resulting `.terminal` file somewhere convenient

## Usage

```bash
# Output filename is derived automatically:
# "Pro.terminal" → "pro.ghostty" in the same directory
python term2ghostty.py "Pro.terminal"

# Specify an output file explicitly
python term2ghostty.py "Pro.terminal" my-theme.ghostty
```

## What gets converted

| Terminal.app setting     | Ghostty key              |
|--------------------------|--------------------------|
| Text color               | `foreground`             |
| Background color         | `background`             |
| Cursor color             | `cursor-color`           |
| Selection color          | `selection-background`   |
| ANSI colors (up to 16)   | `palette = N=#RRGGBB`    |
| Font family              | `font-family`            |
| Font size                | `font-size`              |
| Window columns           | `window-width`           |
| Window rows              | `window-height`          |
| Blink cursor             | `cursor-style-blink`     |

Settings not present in the source `.terminal` file are omitted from the output.

## Notes

- Colors are decoded from the sRGB `NSComponents` representation, which matches what
  macOS displays in the Terminal color picker.
- Grayscale colors (`NSColorSpace` 3/4) are expanded to `#RRGGBB` with R=G=B.
- Font PostScript style suffixes (e.g. `-Regular`, `-Bold`) are stripped to produce
  a clean `font-family` value (e.g. `Menlo-Regular` → `Menlo`).
- If an output file already exists it is overwritten.
- Conversion warnings (unknown color spaces, malformed data, etc.) are printed to
  stderr and also included as `# WARNING:` comments at the bottom of the output file.

## Using the output

Copy or symlink the generated `.ghostty` file, or paste its contents into your Ghostty
config at `~/.config/ghostty/config`.
