#!/usr/bin/env python3
"""
compose_figure.py — Compose multi-panel publication figures from a simple text config.

Usage:
    python3 compose_figure.py layout.txt

Config syntax (see example_layout.txt for a full example):

    # Leaf panel: name = filepath, [label=TEXT], [label_pos=top-left],
    #                              [font_size=48], [scale=1.0], [width=PX], [height=PX]
    img1 = panel_a.png, label=A

    # PDF panels are automatically converted to PNG via pdftoppm / pymupdf.
    img2 = panel_b.pdf, label=B

    # Side-by-side. weights=1:1.5 controls relative widths after height-matching.
    # align = top | center | bottom (vertical alignment if heights differ)
    row1 = hstack(img1, img2, weights=1:1.5, gap=20, align=center)

    # Stacked. weights controls relative heights. align = left | center | right
    col1 = vstack(img1, img2, gap=20, align=center)

    # Paste one composition/image on top of another, sized relative to the base.
    # scale = fraction of base WIDTH the inset should occupy (aspect ratio preserved)
    # pos   = top-left | top-right | bottom-left | bottom-right | center | "x,y" (pixels)
    final = overlay(img3, row1, scale=0.35, pos=top-left, margin=30)

    # Settings (reserved names, no function call)
    canvas     = final          # which node to render
    dpi        = 300
    output     = figure_final.png
    background = white
"""

import sys
import re
import shutil
import argparse
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RESERVED = {"canvas", "dpi", "output", "background"}

DEFAULT_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def find_default_font():
    for f in DEFAULT_FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


COMMENT_RE = re.compile(r"(?:^|\s)#.*$")


def strip_comment(line):
    """Strip a trailing comment, but only when '#' is at line-start or
    preceded by whitespace, so a literal '#' inside a file path is left alone."""
    m = COMMENT_RE.search(line)
    return line[: m.start()] if m else line


DESCRIBE_TEXT = """
compose_figure.py — Layout DSL Reference
=========================================

OVERVIEW
--------
This script composes multi-panel publication figures from a plain-text
config file. Each line either defines a named panel (an image loaded from
disk) or a named composition (built by combining previously-defined names).
Because everything refers to earlier names, layouts of arbitrary depth and
complexity can be built by chaining simple steps.

COMMENTS
--------
A '#' starts a comment when it appears at the start of a line or is preceded
by whitespace. It is ignored if directly attached to other text, so file
paths containing '#' are safe, e.g.:
    img1 = scans/sample#2.png      # this trailing bit is a real comment
Blank lines are ignored.

PANEL DEFINITIONS
-----------------
    name = filepath [, key=value ...]

  Recognized keys:
    label          Text to draw on the panel, e.g. label=A
    label_pos      top-left | top-right | bottom-left | bottom-right
                   (default: top-left)
    font_size      Integer point size (default: ~image_width/25)
    font_path      Path to a .ttf/.otf font file (default: DejaVu Sans Bold,
                   falls back to Liberation Sans Bold, then PIL's basic font)
    label_color    Any PIL color name or hex code (default: black)
    label_bg       Optional background color drawn behind the label text
    label_margin   Pixel margin from the chosen corner (default: 16)
    scale          Resize multiplier applied to the loaded image
    width, height  Explicit pixel dimensions (overrides scale; if only one
                   of width/height is given, aspect ratio is preserved)
    fit            stretch | contain (default: stretch). Only relevant when
                   BOTH width and height are given. 'stretch' resizes the
                   image to exactly width x height, distorting its aspect
                   ratio if needed (previous/default behavior). 'contain'
                   scales the image to fit inside width x height while
                   preserving its aspect ratio, then pads the leftover
                   space with pad_color and centers the image in the box.
    pad_color      Fill color for the letterbox/pillarbox padding created
                   by fit=contain (default: the top-level 'background'
                   setting, or white if that isn't set)
    trim_top       Pixels to trim from the top edge (default: 0)
    trim_bottom    Pixels to trim from the bottom edge (default: 0)
    trim_left      Pixels to trim from the left edge (default: 0)
    trim_right     Pixels to trim from the right edge (default: 0)

  PDF support: .pdf files are rasterized at 300 dpi. Converters are tried
  in order: pdftoppm (poppler-utils) → pymupdf (fitz) → ImageMagick convert.
  Install the recommended one with:  sudo apt install poppler-utils

  Example:
    img1 = panel_a.png, label=A, font_size=48, label_bg=white
    img2 = figure.pdf,  label=B, scale=0.5
    img3 = panel_c.png, width=800, height=600, fit=contain, pad_color=white

COMPOSITION FUNCTIONS
----------------------
  hstack(a, b, ..., weights=W1:W2:..., gap=PX, align=top|center|bottom,
         fit=stretch|contain, pad_color=COLOR)
    Places panels side by side. All inputs are first resized to a common
    height (the tallest input, or an explicit height=PX). 'weights' then
    determines each panel's allotted width (its "slot") relative to the
    others — weights=1:1.5 gives the second panel 1.5x the width of the
    first. By default (fit=stretch) the panel image is stretched to
    exactly fill its slot, which distorts its aspect ratio whenever the
    weight isn't 1. With fit=contain, the panel image instead keeps its
    own aspect ratio, is scaled down to fit inside its slot, and is
    centered there (both horizontally and vertically) — the leftover
    space in the slot is padded with 'pad_color' (default: the top-level
    'background' setting, or white). 'gap' is the pixel spacing between
    panels.

  vstack(a, b, ..., weights=W1:W2:..., gap=PX, align=left|center|right,
         fit=stretch|contain, pad_color=COLOR)
    The vertical mirror of hstack: panels are stacked top to bottom, first
    matched to a common width, then each given a height "slot" scaled by
    'weights'. fit=contain preserves each panel's own aspect ratio inside
    its slot instead of stretching it, centering it (both directions) and
    padding the leftover space with 'pad_color'.

  overlay(base, inset, scale=FRACTION, pos=POSITION, margin=PX)
    Pastes 'inset' on top of 'base'. 'scale' sets the inset's width as a
    fraction of the base's width (aspect ratio preserved). 'pos' is one of
    top-left | top-right | bottom-left | bottom-right | center, or an
    explicit pixel coordinate written as "x,y". 'margin' is the pixel
    offset from the chosen edge(s); ignored for explicit coordinates and
    'center'.

  Composition functions also accept label= / label_pos= / etc., applied to
  the resulting combined image (useful for labeling a whole row or the
  final figure).

  Results can be chained: define row1 = hstack(...), then
  final = vstack(row1, img3) to keep building up a layout.

SETTINGS (reserved names)
--------------------------
    canvas      Name of the node to render as the final image (required)
    dpi         Output resolution metadata, e.g. dpi = 300 (default: 300)
    output      Output filename, relative to the config file's directory
                (default: figure_output.png)
    background  Fill color behind any transparent regions (default: white)

PATH RESOLUTION
----------------
Relative file paths (panels and 'output') are resolved relative to the
directory containing the config file, not the current working directory.

FULL EXAMPLE
------------
    img1 = panel_a.png, label=A
    img2 = panel_b.png, label=B
    img3 = panel_c.png, label=C, label_pos=top-right

    row1  = hstack(img1, img2, weights=1:1.5, gap=20, align=center)
    final = overlay(img3, row1, scale=0.35, pos=top-left, margin=30)

    canvas     = final
    dpi        = 300
    output     = figure_final.png
    background = white

USAGE
-----
    python3 compose_figure.py layout.txt
    python3 compose_figure.py --describe
"""


def split_args(s):
    """Split a comma-separated arg string into (positional_list, kwargs_dict).
    No nested function calls are supported (none needed: everything composes
    via named references), so a plain comma split is sufficient."""
    positional, kwargs = [], {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            kwargs[k.strip()] = v.strip()
        else:
            positional.append(part)
    return positional, kwargs


def parse_config(path):
    nodes = {}       # name -> ("panel", path, kwargs) or (funcname, [refs], kwargs)
    settings = {}     # canvas / dpi / output / background
    order = []

    func_re = re.compile(r"^(\w+)\((.*)\)$")

    with open(path, "r") as f:
        for lineno, raw in enumerate(f, 1):
            line = strip_comment(raw).strip()
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"Line {lineno}: expected 'name = ...': {raw!r}")
            name, rhs = line.split("=", 1)
            name = name.strip()
            rhs = rhs.strip()

            if name in RESERVED:
                settings[name] = rhs.strip()
                continue

            m = func_re.match(rhs)
            if m:
                funcname, inner = m.group(1), m.group(2)
                positional, kwargs = split_args(inner)
                nodes[name] = (funcname, positional, kwargs)
            else:
                positional, kwargs = split_args(rhs)
                if not positional:
                    raise ValueError(f"Line {lineno}: missing file path for '{name}'")
                nodes[name] = ("panel", positional[0], kwargs)

            order.append(name)

    return nodes, settings, order


def load_font(size, font_path=None):
    fp = font_path or find_default_font()
    if fp:
        return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def apply_label(img, kwargs):
    label = kwargs.get("label")
    if not label:
        return img
    img = img.copy()
    draw = ImageDraw.Draw(img)
    font_size = int(kwargs.get("font_size", max(24, img.width // 25)))
    font = load_font(font_size, kwargs.get("font_path"))
    color = kwargs.get("label_color", "black")
    margin = int(kwargs.get("label_margin", 16))

    pos = kwargs.get("label_pos", "top-left")
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    positions = {
        "top-left": (margin, margin),
        "top-right": (img.width - tw - margin, margin),
        "bottom-left": (margin, img.height - th - margin),
        "bottom-right": (img.width - tw - margin, img.height - th - margin),
    }
    xy = positions.get(pos, (margin, margin))

    bg = kwargs.get("label_bg")
    if bg:
        pad = 6
        draw.rectangle(
            [xy[0] - pad, xy[1] - pad, xy[0] + tw + pad, xy[1] + th + pad],
            fill=bg,
        )
    draw.text(xy, label, fill=color, font=font)
    return img


def _pdf_to_png(pdf_path, dpi=300):
    """Convert the first page of a PDF to a PIL Image.

    Tries converters in order:
      1. pdftoppm  (poppler-utils) — not affected by ImageMagick security policy
      2. pymupdf   (fitz)          — pure Python, no external binary needed
      3. ImageMagick convert       — last resort; blocked by default on Ubuntu/Debian

    Install the recommended converter:  sudo apt install poppler-utils
    """
    # 1. pdftoppm (poppler-utils) --------------------------------------------
    if shutil.which("pdftoppm"):
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "page"
            subprocess.run(
                ["pdftoppm", "-r", str(dpi), "-f", "1", "-l", "1",
                 "-png", str(pdf_path), str(prefix)],
                check=True, capture_output=True,
            )
            candidates = sorted(Path(td).glob("page*.png"))
            if not candidates:
                raise RuntimeError(f"pdftoppm produced no output for {pdf_path}")
            return Image.open(candidates[0]).copy()  # .copy() outlives the tempdir

    # 2. pymupdf (fitz) -------------------------------------------------------
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        page = doc[0]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    except ImportError:
        pass

    # 3. ImageMagick convert (may be blocked by /etc/ImageMagick-6/policy.xml) -
    if shutil.which("convert"):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["convert", "-density", str(dpi), str(pdf_path) + "[0]", tmp_path],
                check=True, capture_output=True,
            )
            return Image.open(tmp_path).copy()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    raise RuntimeError(
        f"Cannot convert PDF '{pdf_path}': no suitable converter found.\n"
        "Install poppler-utils (recommended):  sudo apt install poppler-utils\n"
        "  or pymupdf:                          pip install pymupdf"
    )


def fit_and_pad(img, target_w, target_h, pad_color):
    """Scale img to fit inside target_w x target_h preserving aspect ratio,
    then center it on a target_w x target_h canvas filled with pad_color."""
    scale = min(target_w / img.width, target_h / img.height)
    new_w = max(1, round(img.width * scale))
    new_h = max(1, round(img.height * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (target_w, target_h), pad_color)
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


def load_panel(path, kwargs, base_dir, default_pad_color="white"):
    p = Path(path)
    if not p.is_absolute():
        p = base_dir / p
    if p.suffix.lower() == ".pdf":
        img = _pdf_to_png(p).convert("RGBA")
    else:
        img = Image.open(p).convert("RGBA")

    # Trim pixels from edges
    left = int(kwargs.get("trim_left", 0))
    top = int(kwargs.get("trim_top", 0))
    right = int(kwargs.get("trim_right", 0))
    bottom = int(kwargs.get("trim_bottom", 0))
    if left or top or right or bottom:
        w, h = img.size
        img = img.crop((left, top, w - right, h - bottom))

    if "scale" in kwargs:
        s = float(kwargs["scale"])
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    if "width" in kwargs and "height" in kwargs:
        target_w, target_h = int(kwargs["width"]), int(kwargs["height"])
        if kwargs.get("fit", "stretch") == "contain":
            pad_color = kwargs.get("pad_color", default_pad_color)
            img = fit_and_pad(img, target_w, target_h, pad_color)
        else:
            img = img.resize((target_w, target_h), Image.LANCZOS)
    elif "width" in kwargs:
        w = int(kwargs["width"])
        h = int(img.height * w / img.width)
        img = img.resize((w, h), Image.LANCZOS)
    elif "height" in kwargs:
        h = int(kwargs["height"])
        w = int(img.width * h / img.height)
        img = img.resize((w, h), Image.LANCZOS)

    return img


def parse_weights(s, n):
    if not s:
        return [1.0] * n
    parts = [float(x) for x in s.split(":")]
    if len(parts) != n:
        raise ValueError(f"weights '{s}' must have {n} values, separated by ':'")
    return parts


def do_hstack(pairs, kwargs, default_pad_color="white"):
    """pairs is a list of (image, per_panel_kwargs) tuples."""
    imgs = [p[0] for p in pairs]
    per_kw = [p[1] for p in pairs]
    n = len(imgs)
    gap = int(kwargs.get("gap", 0))
    align = kwargs.get("align", "center")
    weights = parse_weights(kwargs.get("weights"), n)
    fit = kwargs.get("fit", "stretch")
    pad_color = kwargs.get("pad_color", default_pad_color)

    target_h = int(kwargs["height"]) if "height" in kwargs else max(im.height for im in imgs)

    resized = []
    for im, w, pkw in zip(imgs, weights, per_kw):
        scale = target_h / im.height
        slot_w = max(1, round(im.width * scale * w))
        if fit == "contain":
            im = fit_and_pad(im, slot_w, target_h, pad_color)
        else:
            im = im.resize((slot_w, target_h), Image.LANCZOS)
        resized.append(apply_label(im, pkw))

    total_w = sum(im.width for im in resized) + gap * (n - 1)
    canvas = Image.new("RGBA", (total_w, target_h), (0, 0, 0, 0))

    x = 0
    for im in resized:
        y = {"top": 0, "center": (target_h - im.height) // 2, "bottom": target_h - im.height}.get(align, 0)
        canvas.paste(im, (x, y), im)
        x += im.width + gap
    return canvas


def do_vstack(pairs, kwargs, default_pad_color="white"):
    """pairs is a list of (image, per_panel_kwargs) tuples."""
    imgs = [p[0] for p in pairs]
    per_kw = [p[1] for p in pairs]
    n = len(imgs)
    gap = int(kwargs.get("gap", 0))
    align = kwargs.get("align", "center")
    weights = parse_weights(kwargs.get("weights"), n)
    fit = kwargs.get("fit", "stretch")
    pad_color = kwargs.get("pad_color", default_pad_color)

    target_w = int(kwargs["width"]) if "width" in kwargs else max(im.width for im in imgs)

    resized = []
    for im, w, pkw in zip(imgs, weights, per_kw):
        scale = target_w / im.width
        slot_h = max(1, round(im.height * scale * w))
        if fit == "contain":
            im = fit_and_pad(im, target_w, slot_h, pad_color)
        else:
            im = im.resize((target_w, slot_h), Image.LANCZOS)
        resized.append(apply_label(im, pkw))

    total_h = sum(im.height for im in resized) + gap * (n - 1)
    canvas = Image.new("RGBA", (target_w, total_h), (0, 0, 0, 0))

    y = 0
    for im in resized:
        x = {"left": 0, "center": (target_w - im.width) // 2, "right": target_w - im.width}.get(align, 0)
        canvas.paste(im, (x, y), im)
        y += im.height + gap
    return canvas


def do_overlay(base, inset, kwargs):
    base = base.copy()
    scale = float(kwargs.get("scale", 0.3))
    new_w = max(1, int(base.width * scale))
    new_h = max(1, int(inset.height * new_w / inset.width))
    inset = inset.resize((new_w, new_h), Image.LANCZOS)

    margin = int(kwargs.get("margin", 20))
    pos = kwargs.get("pos", "top-left")

    if "," in pos:
        x, y = (int(v) for v in pos.split(","))
    else:
        positions = {
            "top-left": (margin, margin),
            "top-right": (base.width - inset.width - margin, margin),
            "bottom-left": (margin, base.height - inset.height - margin),
            "bottom-right": (base.width - inset.width - margin, base.height - inset.height - margin),
            "center": ((base.width - inset.width) // 2, (base.height - inset.height) // 2),
        }
        x, y = positions.get(pos, (margin, margin))

    base.paste(inset, (x, y), inset)
    return apply_label(base, kwargs)


def build(nodes, order, base_dir, default_pad_color="white"):
    # resolved maps name -> (img, kwargs) so labels can be applied after resizing
    resolved = {}
    for name in order:
        kind, a, kwargs = nodes[name]
        if kind == "panel":
            img = load_panel(a, kwargs, base_dir, default_pad_color)
            resolved[name] = (img, kwargs)
        elif kind == "hstack":
            pairs = [resolved[r] for r in a]
            img = apply_label(do_hstack(pairs, kwargs, default_pad_color), kwargs)
            resolved[name] = (img, {})
        elif kind == "vstack":
            pairs = [resolved[r] for r in a]
            img = apply_label(do_vstack(pairs, kwargs, default_pad_color), kwargs)
            resolved[name] = (img, {})
        elif kind == "overlay":
            base_img = resolved[a[0]][0]
            inset_img = resolved[a[1]][0]
            resolved[name] = (do_overlay(base_img, inset_img, kwargs), {})
        else:
            raise ValueError(f"Unknown layout function: {kind}")
    return resolved


def main():
    parser = argparse.ArgumentParser(
        description="Compose multi-panel publication figures from a text layout config.",
        add_help=True,
    )
    parser.add_argument("config", nargs="?", help="Path to the layout config file")
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print a full reference of the layout DSL syntax and exit",
    )
    args = parser.parse_args()

    if args.describe:
        print(DESCRIBE_TEXT)
        sys.exit(0)

    if not args.config:
        parser.error("a config file is required unless --describe is given")

    config_path = Path(args.config)
    base_dir = config_path.parent

    nodes, settings, order = parse_config(config_path)
    background = settings.get("background", "white")
    resolved = build(nodes, order, base_dir, default_pad_color=background)

    canvas_name = settings.get("canvas")
    if not canvas_name or canvas_name not in resolved:
        raise ValueError("Config must set 'canvas = <node_name>' pointing to a defined node")

    final = resolved[canvas_name][0]
    flat = Image.new("RGB", final.size, background)
    flat.paste(final, (0, 0), final)

    dpi = int(settings.get("dpi", 300))
    output = settings.get("output", "figure_output.png")
    out_path = base_dir / output

    flat.save(out_path, dpi=(dpi, dpi))
    print(f"Saved {out_path} ({flat.width}x{flat.height}px @ {dpi} dpi)")


if __name__ == "__main__":
    main()
