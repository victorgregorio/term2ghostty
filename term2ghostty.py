#!/usr/bin/env python3
"""term2ghostty: Convert macOS .terminal profiles to Ghostty config format."""

import plistlib
import re
import sys
from pathlib import Path

import click


# Regex to strip PostScript font style suffixes from font family names
_FONT_STYLE_RE = re.compile(
    r'-(Regular|Bold|Italic|BoldItalic|Light|Medium|Semibold|SemiBold|Heavy|'
    r'ExtraLight|ExtraBold|UltraLight|UltraBold|Thin|Black|Condensed|Expanded|'
    r'Retina|Book|Oblique|BoldOblique|LightItalic|MediumItalic)$',
    re.IGNORECASE,
)

# Named colors: .terminal key -> Ghostty key (order determines output order)
_COLOR_MAP = [
    ('TextColor',       'foreground'),
    ('BackgroundColor', 'background'),
    ('CursorColor',     'cursor-color'),
    ('SelectionColor',  'selection-background'),
]

# ANSI palette: .terminal key -> palette index
_ANSI_MAP = [
    ('ANSIBlackColor',         0),
    ('ANSIRedColor',           1),
    ('ANSIGreenColor',         2),
    ('ANSIYellowColor',        3),
    ('ANSIBlueColor',          4),
    ('ANSIMagentaColor',       5),
    ('ANSICyanColor',          6),
    ('ANSIWhiteColor',         7),
    ('ANSIBrightBlackColor',   8),
    ('ANSIBrightRedColor',     9),
    ('ANSIBrightGreenColor',   10),
    ('ANSIBrightYellowColor',  11),
    ('ANSIBrightBlueColor',    12),
    ('ANSIBrightMagentaColor', 13),
    ('ANSIBrightCyanColor',    14),
    ('ANSIBrightWhiteColor',   15),
]


def _decode_bytes_field(raw) -> str:
    """Decode a bytes color component field, stripping null terminators."""
    if isinstance(raw, bytes):
        return raw.rstrip(b'\x00').decode('utf-8').strip()
    return str(raw).strip()


def parse_nscolor(data: bytes) -> str:
    """
    Decode a binary plist containing an NSKeyedArchiver-encoded NSColor.

    Returns a hex color string like '#RRGGBB'.
    Raises ValueError if the color cannot be decoded.
    """
    try:
        inner = plistlib.loads(data)
    except Exception as exc:
        raise ValueError(f'Failed to parse color binary plist: {exc}') from exc

    objects = inner.get('$objects', [])

    for obj in objects:
        if not isinstance(obj, dict):
            continue

        color_space = obj.get('NSColorSpace')

        if 'NSComponents' in obj:
            s = _decode_bytes_field(obj['NSComponents'])
            parts = s.split()
            if len(parts) < 3:
                raise ValueError(f'NSComponents has fewer than 3 parts: {s!r}')

            if color_space == 5:
                # CMYK: C M Y K as floats 0-1
                c, m, y, k = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                r = round(255 * (1 - c) * (1 - k))
                g = round(255 * (1 - m) * (1 - k))
                b = round(255 * (1 - y) * (1 - k))
            else:
                # RGB (sRGB, linear, or other): R G B [A]
                r = round(float(parts[0]) * 255)
                g = round(float(parts[1]) * 255)
                b = round(float(parts[2]) * 255)

            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            return f'#{r:02X}{g:02X}{b:02X}'

        elif 'NSWhite' in obj:
            # Grayscale (NSColorSpace 3 or 4)
            s = _decode_bytes_field(obj['NSWhite'])
            v = max(0, min(255, round(float(s) * 255)))
            return f'#{v:02X}{v:02X}{v:02X}'

    raise ValueError('No recognizable color representation found in $objects')


def parse_nsfont(data: bytes) -> tuple:
    """
    Decode a binary plist containing an NSKeyedArchiver-encoded NSFont.

    Returns (family_name, size) where family_name has PostScript style
    suffixes stripped (e.g. 'Menlo-Regular' -> 'Menlo').
    Raises ValueError if the font cannot be decoded.
    """
    try:
        inner = plistlib.loads(data)
    except Exception as exc:
        raise ValueError(f'Failed to parse font binary plist: {exc}') from exc

    objects = inner.get('$objects', [])

    for obj in objects:
        if not isinstance(obj, dict) or 'NSName' not in obj:
            continue

        name_ref = obj['NSName']
        postscript_name = objects[int(name_ref)]
        size = float(obj['NSSize'])
        family = _FONT_STYLE_RE.sub('', postscript_name)
        return family, size

    raise ValueError('No NSFont object found in $objects')


def parse_terminal_file(path: Path) -> dict:
    """
    Read a .terminal plist file and extract all convertible settings.

    Returns a dict with keys:
      source_name, colors, palette, font_family, font_size,
      window_width, window_height, cursor_blink, warnings
    """
    try:
        plist = plistlib.loads(path.read_bytes())
    except Exception as exc:
        raise click.ClickException(f'Cannot parse {path.name}: {exc}')

    warnings = []
    result = {
        'source_name': plist.get('name', path.stem),
        'colors': {},
        'palette': {},
        'font_family': None,
        'font_size': None,
        'window_width': None,
        'window_height': None,
        'cursor_style': None,
        'cursor_blink': None,
        'warnings': warnings,
    }

    for plist_key, ghostty_key in _COLOR_MAP:
        val = plist.get(plist_key)
        if val is None:
            continue
        if not isinstance(val, bytes):
            warnings.append(f'Skipping {plist_key}: expected binary data, got {type(val).__name__}')
            continue
        try:
            result['colors'][ghostty_key] = parse_nscolor(val)
        except ValueError as exc:
            warnings.append(f'Could not decode {plist_key}: {exc}')

    for plist_key, index in _ANSI_MAP:
        val = plist.get(plist_key)
        if val is None:
            continue
        if not isinstance(val, bytes):
            warnings.append(f'Skipping {plist_key}: expected binary data, got {type(val).__name__}')
            continue
        try:
            result['palette'][index] = parse_nscolor(val)
        except ValueError as exc:
            warnings.append(f'Could not decode {plist_key}: {exc}')

    font_val = plist.get('Font')
    if isinstance(font_val, bytes):
        try:
            result['font_family'], result['font_size'] = parse_nsfont(font_val)
        except ValueError as exc:
            warnings.append(f'Could not decode Font: {exc}')

    if 'columnCount' in plist:
        result['window_width'] = int(plist['columnCount'])
    if 'rowCount' in plist:
        result['window_height'] = int(plist['rowCount'])
    cursor_type = plist.get('CursorType', 0)
    _CURSOR_STYLE_MAP = {0: 'block', 1: 'underline', 2: 'bar'}
    result['cursor_style'] = _CURSOR_STYLE_MAP.get(int(cursor_type), 'block')
    if 'BlinkText' in plist:
        result['cursor_blink'] = bool(plist['BlinkText'])

    return result


def generate_ghostty_config(settings: dict) -> str:
    """Produce Ghostty config file text from a settings dict."""
    lines = []

    lines.append('# Generated by term2ghostty')
    lines.append(f'# Source: {settings.get("source_name", "unknown")}')
    lines.append('')

    if settings['colors']:
        lines.append('# Colors')
        for ghostty_key, hex_color in settings['colors'].items():
            lines.append(f'{ghostty_key} = {hex_color}')
        lines.append('')

    if settings['palette']:
        lines.append('# ANSI palette')
        for index in sorted(settings['palette']):
            lines.append(f'palette = {index}={settings["palette"][index]}')
        lines.append('')

    font_lines = []
    if settings['font_family'] is not None:
        font_lines.append(f'font-family = {settings["font_family"]}')
    if settings['font_size'] is not None:
        size = settings['font_size']
        size_str = str(int(size)) if size == int(size) else str(size)
        font_lines.append(f'font-size = {size_str}')
    if font_lines:
        lines.append('# Font')
        lines.extend(font_lines)
        lines.append('')

    dim_lines = []
    if settings['window_width'] is not None:
        dim_lines.append(f'window-width = {settings["window_width"]}')
    if settings['window_height'] is not None:
        dim_lines.append(f'window-height = {settings["window_height"]}')
    if dim_lines:
        lines.append('# Window')
        lines.extend(dim_lines)
        lines.append('')

    cursor_lines = []
    if settings['cursor_style'] is not None:
        cursor_lines.append(f'cursor-style = {settings["cursor_style"]}')
    if settings['cursor_blink'] is not None:
        cursor_lines.append(f'cursor-style-blink = {str(settings["cursor_blink"]).lower()}')
    if cursor_lines:
        lines.append('# Cursor')
        lines.extend(cursor_lines)
        lines.append('')

    for warning in settings.get('warnings', []):
        lines.append(f'# WARNING: {warning}')

    return '\n'.join(lines).rstrip('\n') + '\n'


def _derive_output_path(input_path: Path) -> Path:
    """Derive a .ghostty output path from a .terminal input path."""
    slug = re.sub(r'[^a-z0-9]+', '-', input_path.stem.lower()).strip('-')
    return input_path.parent / (slug + '.ghostty')


@click.command()
@click.argument('input_file', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output_file', type=click.Path(dir_okay=False, path_type=Path), required=False)
@click.version_option('1.0.0')
def main(input_file: Path, output_file) -> None:
    """Convert a macOS .terminal profile to Ghostty config format.

    \b
    INPUT_FILE   path to the .terminal file to convert
    OUTPUT_FILE  optional output path (default: input name as lowercase-hyphenated .ghostty
                 in the same directory)
    """
    if output_file is None:
        output_file = _derive_output_path(input_file)

    settings = parse_terminal_file(input_file)

    for warning in settings['warnings']:
        click.echo(f'Warning: {warning}', err=True)

    config_text = generate_ghostty_config(settings)
    output_file.write_text(config_text, encoding='utf-8')

    click.echo(f'Wrote {output_file}')


if __name__ == '__main__':
    main()
