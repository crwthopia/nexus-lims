"""
Barcodes for labels, as inline SVG data URIs.

Two decisions here are about what goes *in* the barcode, and they matter
more than the rendering:

**It encodes the sample code, not a URL and not the database id.** A URL
bakes a hostname into a physical object that will outlive the deployment --
a bottle in a retention fridge can be scanned in three years, by which time
the console may live somewhere else entirely. The database id is worse: it
is meaningless to a person, so when the scan fails there is nothing to type.
The sample code is the laboratory's own identity for the item (ISO/IEC
17025:2017 7.4.2), it is printed in plain text beside the bars, and it
scans straight into the field an analyst would otherwise fill by hand.

**Code 128, not QR.** A linear barcode is what bench and handheld scanners
in a laboratory read without being aimed, and it scans from the angle a
bottle happens to be lying at. QR earns its place on the job-order sheet,
where there is room and the target is a URL somebody is deliberately
pointing a phone at.

Rendered as vector SVG rather than a PNG: WeasyPrint draws SVG into the PDF
as path operations, so the bars stay crisp at whatever DPI the label printer
runs at. A rasterised barcode resampled by a 300dpi printer driver is how
edges blur and a scan starts failing intermittently -- the worst failure
mode this feature has, because it looks like a hardware problem.
"""

import base64
import io
import re

from barcode import Code128
from barcode.writer import SVGWriter

# X-dimension: the width of the narrowest bar, and the number every
# scannability spec is written in terms of. 0.25mm is the GS1 general
# distribution minimum for Code 128; below it, print gain on a thermal
# printer starts closing the narrow spaces.
DEFAULT_MODULE_WIDTH_MM = 0.25

# The floor auto-fit is allowed to shrink to. 0.19mm is readable by a
# close-range scanner on a good printer and is where GS1 stops; anything
# narrower is a barcode that works on the bench where it was tested and
# fails in the fridge aisle.
MIN_MODULE_WIDTH_MM = 0.19

# Blank margin each side. Code 128 needs 10 x-dimensions of quiet zone;
# 2mm is comfortably above that at any width used here, and a scanner that
# cannot find the quiet zone reports nothing at all rather than a bad read.
QUIET_ZONE_MM = 2.0

DEFAULT_HEIGHT_MM = 8.0

_SIZE_RE = re.compile(r'width="([\d.]+)mm"\s+height="([\d.]+)mm"')


class BarcodeTooWide(Exception):
    """The code will not fit the label at a scannable bar width."""


def _render_svg(value, *, module_width, height_mm):
    buffer = io.BytesIO()
    Code128(value, writer=SVGWriter()).write(
        buffer,
        options={
            # The human-readable text is laid out by the label template, in
            # the template's own font and at a size chosen for a bench, not
            # by the barcode library underneath the bars.
            "write_text": False,
            "module_width": module_width,
            "module_height": height_mm,
            "quiet_zone": QUIET_ZONE_MM,
        },
    )
    svg = buffer.getvalue()
    match = _SIZE_RE.search(svg.decode())
    width_mm = float(match.group(1)) if match else None
    height_mm = float(match.group(2)) if match else None
    return svg, width_mm, height_mm


def code128_data_uri(value, *, max_width_mm=None, height_mm=DEFAULT_HEIGHT_MM):
    """
    A Code 128 barcode for `value` as an `data:image/svg+xml` URI, plus the
    exact size it must be drawn at: `(uri, width_mm, height_mm)`.

    **Both dimensions are returned because the caller has to pin both.**
    Everything this module guarantees about scannability is a statement
    about the bar width in millimetres, and CSS that sets only one axis
    lets the renderer scale the other -- silently multiplying that bar
    width by whatever the ratio happens to be. Setting `height: 8mm` on a
    10mm-tall barcode is a 20% reduction, which takes a 0.25mm bar to
    0.20mm: still visible, still obviously a barcode, and no longer
    readable by a 300dpi scanner. Draw it at the size returned here and
    nothing scales.

    Shrinks the bar width to fit `max_width_mm` where one is given, because
    a code's width depends on its length and label stock does not. Refuses
    rather than overflowing once the floor is reached: a barcode running off
    the edge of a label is not a slightly worse barcode, it is one that can
    scan as a *different, shorter code* -- and a container carrying somebody
    else's identity is the exact failure ISO/IEC 17025:2017 7.4.2 is written
    to prevent. "Use wider label stock" is a fixable answer; a truncated
    barcode is a silent one.
    """
    if not value:
        raise ValueError("Cannot encode an empty sample code.")

    svg, width_mm, svg_height_mm = _render_svg(
        value, module_width=DEFAULT_MODULE_WIDTH_MM, height_mm=height_mm,
    )

    if max_width_mm is not None and width_mm is not None and width_mm > max_width_mm:
        # Only the bars scale with bar width; the quiet zone is a fixed
        # 2mm each side and has to come off both numbers first. Scaling on
        # the *total* width instead -- the obvious version -- overshoots by
        # the quiet zone every time, which on a 50mm label is the
        # difference between fitting and running off the edge.
        bars_mm = width_mm - 2 * QUIET_ZONE_MM
        available_bars_mm = max_width_mm - 2 * QUIET_ZONE_MM
        narrowest_fit = 2 * QUIET_ZONE_MM + bars_mm * MIN_MODULE_WIDTH_MM / DEFAULT_MODULE_WIDTH_MM

        if available_bars_mm <= 0 or narrowest_fit > max_width_mm:
            raise BarcodeTooWide(
                f"'{value}' needs {width_mm:.1f}mm at a {DEFAULT_MODULE_WIDTH_MM}mm bar width, and "
                f"still {narrowest_fit:.1f}mm at the {MIN_MODULE_WIDTH_MM}mm scannable minimum, but "
                f"the label allows {max_width_mm:.1f}mm. Print this one on wider stock."
            )

        scaled = DEFAULT_MODULE_WIDTH_MM * (available_bars_mm / bars_mm)
        svg, width_mm, svg_height_mm = _render_svg(value, module_width=scaled, height_mm=height_mm)

    uri = "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")
    return uri, width_mm, svg_height_mm


def qr_data_uri(value, *, scale=4):
    """
    A QR code as a `data:image/svg+xml` URI.

    Used on the job-order sheet, where it carries a deep link into the Staff
    Console: there is room for it, and somebody holding a printed sheet is
    deliberately pointing a phone at it. Not used on container labels -- see
    the module docstring.
    """
    import segno

    buffer = io.BytesIO()
    segno.make(value, error="m").save(buffer, kind="svg", scale=scale, border=2)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
