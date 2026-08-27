"""The weather, drawn.

Every mark and every chart on the weather panel is drawn here, in Cairo, from
the same Material 3 role table the rest of the screen is coloured from. None
of it is an icon requested from a theme, for the reason `glyphs.py` gives:
an icon name is a request, and the answer depends on what happens to be
installed.

The charts are the part worth defending. A weather panel that lists twelve
temperatures as twelve numbers has made the reader do the work of noticing
that it gets warmer until four and then falls off a cliff. A line does that
for them in one look. Likewise a column of highs and lows tells you Thursday
is 28 and Friday is 28, and a row of bars on one shared scale tells you
Friday is the warmer day because its night does not get cold, which is the
thing somebody deciding what to wear actually wanted.

Text is set through Pango rather than Cairo's toy font interface, so the
labels inside a chart are the same typeface at the same scale as the labels
beside it, including for somebody who asked for two hundred percent text.

Nothing here holds state and nothing here touches a widget: each function
takes a context, a size and some data. That is what lets the whole set be
rendered to a file and looked at, which is how the marks below were checked.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

from . import weather as W  # noqa: E402

#: Sky marks are drawn in a 24 by 24 space, the same as `glyphs.py`, so a
#: condition mark and a battery sitting in the same row agree about weight.
DESIGN = 24.0


def rgb(value: str) -> tuple[float, float, float]:
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _set(cr, colours: dict, role: str, alpha: float = 1.0) -> None:
    red, green, blue = rgb(colours[role])
    if alpha >= 1.0:
        cr.set_source_rgb(red, green, blue)
    else:
        cr.set_source_rgba(red, green, blue, alpha)


def _mix(colours: dict, cool: str, warm: str, amount: float
         ) -> tuple[float, float, float]:
    """A colour partway between two roles."""
    amount = max(0.0, min(1.0, amount))
    one, two = rgb(colours[cool]), rgb(colours[warm])
    return tuple(one[i] + (two[i] - one[i]) * amount for i in range(3))


def light_scheme(colours: dict) -> bool:
    """Whether this role table paints dark ink on a light ground."""
    red, green, blue = rgb(colours["surface"])
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) > 0.5


#: The temperature ramp, taken from the brand's tone palettes rather than from
#: the role table, for two reasons.
#:
#: The roles differ between the schemes, so a bar drawn from them is a clear
#: blue at night and a dark teal by day, and a week is not a different colour
#: depending on the time. And a two stop ramp from teal to amber passes
#: through olive at its midpoint, which is where most of a mild week sits, so
#: the middle of the week came out the muddiest part of the chart. A warm stop
#: in the middle is what every weather scale has always had.
RAMP = ((0.00, "#519ab7"), (0.55, "#fabc52"), (1.00, "#ed655b"))


def heat(amount: float) -> tuple[float, float, float]:
    """Cold to hot, as a colour."""
    amount = max(0.0, min(1.0, amount))
    for index in range(len(RAMP) - 1):
        low, cool = RAMP[index]
        high, warm = RAMP[index + 1]
        if amount <= high or index == len(RAMP) - 2:
            span = high - low
            step = 0.0 if span <= 0 else (amount - low) / span
            step = max(0.0, min(1.0, step))
            one, two = rgb(cool), rgb(warm)
            return tuple(one[i] + (two[i] - one[i]) * step for i in range(3))
    return rgb(RAMP[-1][1])


# -- text -------------------------------------------------------------------


def text(cr, font: Pango.FontDescription, words: str, x: float, y: float,
         *, align: str = "left", weight: int = 0, scale: float = 1.0
         ) -> tuple[float, float]:
    """One run of text, positioned by its box rather than by a baseline.

    `x` means what `align` says it means and `y` is always the top, because a
    chart positions labels against bands and a baseline is the one measurement
    a band does not have.
    """
    layout = PangoCairo.create_layout(cr)
    description = font.copy()
    if weight:
        description.set_weight(Pango.Weight(weight))
    if scale != 1.0:
        size = description.get_size() or (11 * Pango.SCALE)
        description.set_size(int(size * scale))
    layout.set_font_description(description)
    layout.set_text(words, -1)
    width, height = layout.get_pixel_size()
    if align == "center":
        x -= width / 2.0
    elif align == "right":
        x -= width
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)
    return width, height


def measure(cr, font: Pango.FontDescription, words: str, scale: float = 1.0
            ) -> tuple[float, float]:
    layout = PangoCairo.create_layout(cr)
    description = font.copy()
    if scale != 1.0:
        size = description.get_size() or (11 * Pango.SCALE)
        description.set_size(int(size * scale))
    layout.set_font_description(description)
    layout.set_text(words, -1)
    return layout.get_pixel_size()


# -- the sky ----------------------------------------------------------------


def cloud(cr, x: float, y: float, size: float) -> None:
    """A cloud silhouette as a closed path, ready to fill or stroke.

    Three lobes over a flat base, which is the shape everybody draws, because
    a cloud drawn from observation reads as a smudge at eighteen pixels.
    """
    unit = size / 24.0

    def at(px: float, py: float) -> tuple[float, float]:
        return x + px * unit, y + py * unit

    left_x, left_y = at(7.2, 13.4)
    top_x, top_y = at(11.6, 11.0)
    right_x, right_y = at(17.0, 13.2)
    cr.new_sub_path()
    cr.arc(left_x, left_y, 3.6 * unit, math.radians(90), math.radians(268))
    cr.arc(top_x, top_y, 4.7 * unit, math.radians(198), math.radians(346))
    cr.arc(right_x, right_y, 3.8 * unit, math.radians(268), math.radians(90))
    cr.close_path()


def sun(cr, x: float, y: float, radius: float, rays: bool = True) -> None:
    if rays:
        cr.save()
        cr.set_line_width(radius * 0.30)
        cr.set_line_cap(1)  # round
        for index in range(8):
            angle = math.radians(index * 45.0)
            inner = radius * 1.52
            outer = radius * 2.06
            cr.move_to(x + math.cos(angle) * inner, y + math.sin(angle) * inner)
            cr.line_to(x + math.cos(angle) * outer, y + math.sin(angle) * outer)
        cr.stroke()
        cr.restore()
    cr.new_sub_path()
    cr.arc(x, y, radius, 0, math.tau)
    cr.fill()


def crescent(cr, x: float, y: float, radius: float) -> None:
    """The moon as a disc with a bite taken out, cut rather than overdrawn.

    Overdrawing the bite in the background colour only works when the mark
    sits on that colour, and this one sits on a photograph.
    """
    import cairo  # noqa: PLC0415

    cr.save()
    cr.push_group()
    cr.new_sub_path()
    cr.arc(x, y, radius, 0, math.tau)
    cr.fill()
    cr.set_operator(cairo.OPERATOR_CLEAR)
    cr.new_sub_path()
    cr.arc(x + radius * 0.62, y - radius * 0.40, radius * 0.92, 0, math.tau)
    cr.fill()
    cr.pop_group_to_source()
    cr.paint()
    cr.restore()


def _drops(cr, count: int, y: float, length: float, lean: float = 2.0) -> None:
    span = 13.0
    step = span / max(1, count - 1) if count > 1 else 0.0
    start = 12.0 - span / 2.0
    for index in range(count):
        x = start + step * index
        cr.move_to(x + lean, y)
        cr.line_to(x, y + length)
    cr.stroke()


def _flakes(cr, count: int, y: float, radius: float,
            span: float = 13.0) -> None:
    """Six pointed stars, spaced so they stay separate marks.

    Three flakes at the size a status pill wants them is already close to the
    point where the arms of one touch the arms of the next and the whole
    thing reads as a blue smear, so the spacing is set from the radius rather
    than chosen.
    """
    step = span / max(1, count - 1) if count > 1 else 0.0
    start = 12.0 - (span if count > 1 else 0.0) / 2.0
    for index in range(count):
        x = start + step * index
        for arm in range(3):
            angle = math.radians(arm * 60.0)
            cr.move_to(x - math.cos(angle) * radius, y - math.sin(angle) * radius)
            cr.line_to(x + math.cos(angle) * radius, y + math.sin(angle) * radius)
    cr.stroke()


def sky(cr, condition: str, daylight: bool, colours: dict,
        lit: str = "", dim: str = "") -> None:
    """One condition, drawn in the 24 by 24 space.

    The sun and the moon are the accent, everything made of water is the
    tertiary blue, and cloud is the neutral, so a glance across a row of ten
    days reads wet or dry before it reads anything else.

    Cloud is the neutral for the scheme in use rather than a fixed role.
    `on_surface` is near white against a dark panel, which is exactly what a
    cloud should be, and near black against a light one, which is not: a black
    cloud reads as a hole. Against a light ground the outline grey is the
    cloud, which is what it looks like out of a window.
    """
    import cairo  # noqa: PLC0415

    pale = light_scheme(colours)
    lit = lit or ("outline" if pale else "on_surface")
    dim = dim or ("outline_variant" if pale else "on_surface_variant")

    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    warm = "warning" if daylight else "secondary"
    wet = "tertiary"

    def orb(x: float, y: float, radius: float, rays: bool = True) -> None:
        _set(cr, colours, warm)
        if daylight:
            sun(cr, x, y, radius, rays)
        else:
            crescent(cr, x, y, radius)

    def body(x: float = 0.0, y: float = 0.0, size: float = 24.0,
             role: str = "") -> None:
        _set(cr, colours, role or lit)
        cloud(cr, x, y, size)
        cr.fill()

    if condition == W.CLEAR:
        orb(12.0, 12.0, 4.6)
        return

    if condition == W.MOSTLY_CLEAR:
        orb(9.4, 9.0, 3.9)
        body(3.0, 4.6, 21.0, dim)
        return

    if condition == W.PARTLY:
        orb(8.6, 8.4, 3.6)
        body(2.0, 3.4, 22.0, lit)
        return

    if condition == W.CLOUDY:
        _set(cr, colours, dim)
        cloud(cr, 0.5, 0.0, 20.0)
        cr.fill()
        body(4.0, 3.6, 20.0, lit)
        return

    if condition == W.OVERCAST:
        body(0.0, 1.6, 24.0, lit)
        return

    if condition == W.HAZE:
        orb(12.0, 9.6, 4.0, rays=False)
        _set(cr, colours, dim)
        cr.set_line_width(1.7)
        for offset, half in ((15.4, 8.0), (19.0, 6.4)):
            cr.move_to(12.0 - half, offset)
            cr.line_to(12.0 + half, offset)
        cr.stroke()
        return

    if condition == W.WIND:
        _set(cr, colours, lit)
        cr.set_line_width(1.9)
        for y, length, radius in ((7.5, 9.0, 2.4), (12.0, 12.5, 2.9),
                                  (16.5, 7.5, 2.2)):
            cr.move_to(3.0, y)
            cr.line_to(3.0 + length, y)
            cr.stroke()
            cr.new_sub_path()
            cr.arc(3.0 + length, y - radius, radius,
                   math.radians(90), math.radians(340))
            cr.stroke()
        return

    if condition == W.FOG:
        body(1.0, -1.0, 22.0, lit)
        _set(cr, colours, dim)
        cr.set_line_width(1.8)
        for offset, half in ((17.4, 8.4), (21.0, 6.6)):
            cr.move_to(12.0 - half, offset)
            cr.line_to(12.0 + half, offset)
        cr.stroke()
        return

    # Everything below falls out of a cloud, so the cloud is drawn once and
    # what falls out of it is the only difference.
    body(1.0, -1.5, 22.0, lit)
    _set(cr, colours, wet)
    cr.set_line_width(1.9)

    if condition == W.DRIZZLE:
        _drops(cr, 2, 16.6, 3.0, 1.1)
    elif condition == W.RAIN:
        _drops(cr, 3, 16.2, 4.4, 1.7)
    elif condition == W.HEAVY_RAIN:
        cr.set_line_width(2.1)
        _drops(cr, 4, 15.4, 6.0, 2.2)
    elif condition == W.SNOW:
        cr.set_line_width(1.5)
        _flakes(cr, 3, 18.2, 1.9, 13.4)
    elif condition == W.HEAVY_SNOW:
        cr.set_line_width(1.5)
        _flakes(cr, 2, 16.4, 1.9, 9.0)
        _flakes(cr, 3, 21.0, 1.9, 14.0)
    elif condition == W.SLEET:
        _drops(cr, 2, 16.2, 4.0, 1.6)
        _flakes(cr, 1, 19.4, 2.0)
    elif condition == W.FREEZING:
        _drops(cr, 3, 15.8, 3.4, 1.4)
        _set(cr, colours, dim)
        cr.set_line_width(1.9)
        cr.move_to(6.0, 21.4)
        cr.line_to(18.0, 21.4)
        cr.stroke()
    elif condition == W.HAIL:
        _set(cr, colours, wet)
        for x, y in ((8.4, 17.6), (12.0, 20.6), (15.6, 17.6)):
            cr.new_sub_path()
            cr.arc(x, y, 1.5, 0, math.tau)
        cr.fill()
    elif condition == W.THUNDER:
        _set(cr, colours, "warning")
        cr.move_to(13.6, 14.2)
        cr.line_to(9.0, 20.2)
        cr.line_to(11.9, 20.2)
        cr.line_to(10.9, 24.0)
        cr.line_to(15.6, 18.0)
        cr.line_to(12.6, 18.0)
        cr.close_path()
        cr.fill()
    else:
        _drops(cr, 3, 16.2, 4.4, 1.7)


# -- the hourly band --------------------------------------------------------

#: Enough hours to see the shape of an afternoon without needing to scroll.
HOURS = 12


def hours_chart(cr, width: float, height: float, hours: list,
                units: str, colours: dict, font: Pango.FontDescription,
                zone=None) -> None:
    """Twelve hours as a line, with the sky above it and the rain below.

    The line is the point. Twelve numbers in a row is a table; a line is a
    shape, and a shape is what tells somebody at a login screen at eight in
    the morning that today has a spike in it at four.
    """
    import cairo  # noqa: PLC0415

    shown = [h for h in hours[:HOURS] if h.temperature is not None]
    if len(shown) < 2:
        return
    columns = len(shown)
    gutter = 14.0
    span = max(1.0, width - gutter * 2.0)
    step = span / (columns - 1)

    label_top = 0.0
    label_height = measure(cr, font, "12 AM", 0.86)[1]
    glyph_top = label_height + 6.0
    glyph_size = 20.0
    rain_top = glyph_top + glyph_size + 4.0
    rain_height = measure(cr, font, "100%", 0.80)[1]
    curve_top = rain_top + rain_height + 10.0
    value_height = measure(cr, font, "-88\N{DEGREE SIGN}", 0.92)[1]
    # Rain sits in a strip of its own along the bottom, on its own baseline.
    # Behind the temperature line it was a grey hill the line ran through,
    # and two quantities sharing one vertical axis that means different
    # things for each is a chart that lies about both.
    water_height = 22.0 if any((h.precipitation or 0) >= 5 for h in shown) else 0.0
    curve_bottom = height - water_height - (6.0 if water_height else 2.0)
    curve_span = max(18.0, curve_bottom - curve_top - value_height - 4.0)

    warmest = max(h.temperature for h in shown)
    coldest = min(h.temperature for h in shown)
    reach = max(2.0, warmest - coldest)

    def place(index: int, value: float) -> tuple[float, float]:
        x = gutter + step * index
        y = curve_top + value_height + 4.0 + (warmest - value) / reach * curve_span
        return x, y

    points = [place(i, h.temperature) for i, h in enumerate(shown)]

    if water_height:
        # A band rather than bars: rain is continuous, and bars imply it
        # stops between the hours somebody happened to sample it at.
        floor = height - 1.0
        wet = [(gutter + step * index,
                floor - (hour.precipitation or 0) / 100.0 * (water_height - 3.0))
               for index, hour in enumerate(shown)]
        cr.save()
        cr.new_path()
        cr.move_to(wet[0][0], floor)
        _curve(cr, wet)
        cr.line_to(wet[-1][0], floor)
        cr.close_path()
        _set(cr, colours, "tertiary", 0.30)
        cr.fill()
        cr.set_line_width(1.0)
        cr.move_to(gutter - 6.0, floor)
        cr.line_to(width - gutter + 6.0, floor)
        _set(cr, colours, "outline_variant", 0.7)
        cr.stroke()
        cr.restore()

    # The temperature line, through the points rather than between them.
    cr.save()
    cr.set_line_width(2.2)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    _curve(cr, points)
    _set(cr, colours, "primary")
    cr.stroke()
    cr.restore()

    # Twelve hours of data, but not twelve hours of text. A label under every
    # point at this width runs "Now1 PM2 PM3 PM" into one word, so the samples
    # stay at twelve and the writing thins out to every other column, which is
    # what a chart axis has always done. The warmest and coldest hours keep
    # their temperatures whichever column they land in, because those two are
    # the numbers somebody is actually looking for.
    peak = max(range(columns), key=lambda i: shown[i].temperature)
    trough = min(range(columns), key=lambda i: shown[i].temperature)
    widest = max(measure(cr, font, "12 AM", 0.86)[0],
                 measure(cr, font, "-88\N{DEGREE SIGN}", 0.92)[0])
    every = 1 if step >= widest + 6.0 else 2

    for index, hour in enumerate(shown):
        x = gutter + step * index
        point_x, point_y = points[index]
        spoken = index % every == 0

        if spoken:
            moment = hour.at
            if moment is not None and zone is not None:
                moment = moment.astimezone(zone)
            when = "Now" if index == 0 else (
                moment.strftime("%-I %p") if moment else "")
            _set(cr, colours,
                 "on_surface" if index == 0 else "on_surface_variant")
            text(cr, font, when, x, label_top, align="center", scale=0.86,
                 weight=600 if index == 0 else 0)

        cr.save()
        cr.translate(x - glyph_size / 2.0, glyph_top)
        cr.scale(glyph_size / DESIGN, glyph_size / DESIGN)
        sky(cr, hour.condition, hour.daylight, colours)
        cr.restore()

        chance = hour.precipitation or 0
        if chance >= 20 and spoken:
            _set(cr, colours, "tertiary")
            text(cr, font, f"{chance}%", x, rain_top, align="center", scale=0.80)

        cr.save()
        _set(cr, colours, "primary")
        cr.new_sub_path()
        cr.arc(point_x, point_y, 3.0, 0, math.tau)
        cr.fill()
        cr.restore()

        if spoken or index in (peak, trough):
            _set(cr, colours, "on_surface")
            text(cr, font, W.temperature(hour.temperature, units),
                 point_x, point_y - value_height - 6.0, align="center",
                 scale=0.92, weight=600)


def _curve(cr, points: list) -> None:
    """A Catmull-Rom spline as Cairo beziers.

    Straight segments between hourly samples make a temperature curve look
    like a stock chart, which is a graph of something that jumps. Air does
    not jump, and the smoothing says so without inventing any values: every
    sample is still on the line.
    """
    if len(points) < 2:
        return
    cr.move_to(*points[0])
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[min(len(points) - 1, index + 2)]
        cr.curve_to(
            p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0,
            p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0,
            p2[0], p2[1])


# -- the daily band ---------------------------------------------------------


def days_chart(cr, width: float, height: float, days: list, units: str,
               colours: dict, font: Pango.FontDescription,
               current: float | None = None, names: list | None = None) -> None:
    """Each day as a bar on one shared scale, which is the whole idea.

    A column of highs and a column of lows makes the reader hold ten pairs of
    numbers in their head to find the mild day. Bars on a common axis put the
    mild day where the eye already is, and today's bar carries a mark at the
    temperature right now, so the day in progress is placed inside its own
    forecast rather than sitting above it as an unrelated number.
    """
    shown = [d for d in days if d.high is not None and d.low is not None]
    if not shown:
        return
    rows = len(shown)
    row_height = height / rows
    glyph_size = min(21.0, row_height - 4.0)

    name_width = max(measure(cr, font, n or "Today", 0.94)[0]
                     for n in (names or [d.name or "Today" for d in shown]))
    # Measured from the names in hand rather than capped at a number that was
    # right for the week somebody happened to test on. "Wednesday" is wider
    # than "Friday" and a cap set for one runs the other into the sky mark.
    name_width = max(48.0, min(112.0, name_width + 6.0))
    number_width = measure(cr, font, "-88\N{DEGREE SIGN}", 0.94)[0] + 4.0
    rain_width = measure(cr, font, "100%", 0.80)[0] + 6.0

    bar_left = name_width + glyph_size + rain_width + number_width + 22.0
    bar_right = width - number_width - 8.0
    bar_span = max(24.0, bar_right - bar_left)

    warmest = max(d.high for d in shown)
    coldest = min(d.low for d in shown)
    reach = max(2.0, warmest - coldest)

    for index, day in enumerate(shown):
        top = index * row_height
        middle = top + row_height / 2.0
        first = index == 0

        name = (names[index] if names and index < len(names) else day.name) or ""
        _set(cr, colours, "on_surface" if first else "on_surface_variant")
        _, name_height = measure(cr, font, name or "Today", 0.94)
        text(cr, font, name, 0.0, middle - name_height / 2.0, scale=0.94,
             weight=600 if first else 0)

        cr.save()
        cr.translate(name_width + 4.0, middle - glyph_size / 2.0)
        cr.scale(glyph_size / DESIGN, glyph_size / DESIGN)
        sky(cr, day.condition, True, colours)
        cr.restore()

        chance = day.precipitation or 0
        if chance >= 20:
            _set(cr, colours, "tertiary")
            _, chance_height = measure(cr, font, f"{chance}%", 0.80)
            text(cr, font, f"{chance}%",
                 name_width + glyph_size + rain_width + 2.0,
                 middle - chance_height / 2.0, align="right", scale=0.80)

        _, number_height = measure(cr, font, "88\N{DEGREE SIGN}", 0.94)
        _set(cr, colours, "on_surface_variant")
        text(cr, font, W.temperature(day.low, units),
             bar_left - 10.0, middle - number_height / 2.0,
             align="right", scale=0.94)
        _set(cr, colours, "on_surface")
        text(cr, font, W.temperature(day.high, units),
             bar_right + 10.0, middle - number_height / 2.0,
             scale=0.94, weight=600 if first else 0)

        # The track, then this day's stretch of it.
        track_height = max(4.0, min(7.0, row_height * 0.30))
        _set(cr, colours, "on_surface", 0.10)
        _capsule(cr, bar_left, middle - track_height / 2.0, bar_span,
                 track_height)
        cr.fill()

        start = bar_left + (day.low - coldest) / reach * bar_span
        finish = bar_left + (day.high - coldest) / reach * bar_span
        _gradient_capsule(cr, start, middle - track_height / 2.0,
                          max(track_height, finish - start), track_height,
                          colours, (day.low - coldest) / reach,
                          (day.high - coldest) / reach)

        if first and current is not None and coldest <= current <= warmest:
            spot = bar_left + (current - coldest) / reach * bar_span
            _set(cr, colours, "surface")
            cr.new_sub_path()
            cr.arc(spot, middle, track_height * 0.62, 0, math.tau)
            cr.fill()
            _set(cr, colours, "on_surface")
            cr.new_sub_path()
            cr.arc(spot, middle, track_height * 0.38, 0, math.tau)
            cr.fill()


def _capsule(cr, x: float, y: float, width: float, height: float) -> None:
    radius = height / 2.0
    width = max(width, height)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius,
           math.radians(-90), math.radians(90))
    cr.arc(x + radius, y + radius, radius,
           math.radians(90), math.radians(270))
    cr.close_path()


def _gradient_capsule(cr, x: float, y: float, width: float, height: float,
                      colours: dict, cool: float, warm: float) -> None:
    """A day's range, coloured by where in the week's spread it sits."""
    import cairo  # noqa: PLC0415

    gradient = cairo.LinearGradient(x, 0, x + width, 0)
    gradient.add_color_stop_rgb(0.0, *heat(cool))
    gradient.add_color_stop_rgb(1.0, *heat(warm))
    cr.save()
    _capsule(cr, x, y, width, height)
    cr.set_source(gradient)
    cr.fill()
    cr.restore()


# -- the sun's day ----------------------------------------------------------


def sun_arc(cr, width: float, height: float, fraction: float | None,
            colours: dict, font: Pango.FontDescription,
            rise: str = "", set_: str = "", altitude: float | None = None
            ) -> None:
    """Where the sun is in its own day, which is a shape, not two times.

    Sunrise and sunset as a pair of clock readings make somebody subtract. An
    arc with the sun on it says how much daylight is left without anybody
    doing arithmetic, and it is drawn from a calculation this machine does
    itself, so it is still right when the network is not there.
    """
    import cairo  # noqa: PLC0415

    label_height = measure(cr, font, "12:00", 0.82)[1]
    horizon = height - label_height - 8.0
    left = 26.0
    right = width - 26.0
    if right <= left:
        return
    lift = max(16.0, horizon - 10.0)

    def curve_at(t: float) -> tuple[float, float]:
        x = left + (right - left) * t
        y = horizon - math.sin(math.pi * max(0.0, min(1.0, t))) * lift
        return x, y

    steps = 48
    path = [curve_at(index / steps) for index in range(steps + 1)]

    # Under the arc, a wash that stops at the horizon, so the shape reads as
    # a day and not as a hill.
    cr.save()
    cr.move_to(*path[0])
    for point in path[1:]:
        cr.line_to(*point)
    cr.line_to(right, horizon)
    cr.line_to(left, horizon)
    cr.close_path()
    gradient = cairo.LinearGradient(0, horizon - lift, 0, horizon)
    red, green, blue = rgb(colours["warning"])
    gradient.add_color_stop_rgba(0.0, red, green, blue, 0.22)
    gradient.add_color_stop_rgba(1.0, red, green, blue, 0.02)
    cr.set_source(gradient)
    cr.fill()
    cr.restore()

    cr.save()
    cr.set_line_width(1.8)
    cr.move_to(*path[0])
    for point in path[1:]:
        cr.line_to(*point)
    _set(cr, colours, "warning", 0.75)
    cr.stroke()
    cr.restore()

    cr.save()
    cr.set_line_width(1.0)
    cr.set_dash([2.0, 3.0])
    cr.move_to(6.0, horizon)
    cr.line_to(width - 6.0, horizon)
    _set(cr, colours, "outline_variant")
    cr.stroke()
    cr.restore()

    if fraction is not None:
        spot_x, spot_y = curve_at(fraction)
        up = altitude is None or altitude > -0.833
        _set(cr, colours, "warning" if up else "secondary", 0.28)
        cr.new_sub_path()
        cr.arc(spot_x, spot_y, 9.0, 0, math.tau)
        cr.fill()
        _set(cr, colours, "warning" if up else "secondary")
        cr.new_sub_path()
        cr.arc(spot_x, spot_y, 4.6, 0, math.tau)
        cr.fill()

    _set(cr, colours, "on_surface_variant")
    if rise:
        text(cr, font, rise, left, horizon + 5.0, align="center", scale=0.82)
    if set_:
        text(cr, font, set_, right, horizon + 5.0, align="center", scale=0.82)


# -- the small readouts -----------------------------------------------------


def compass(cr, size: float, bearing: int | None, colours: dict,
            font: Pango.FontDescription) -> None:
    """Which way the wind is going, and how hard.

    The arrow points the way the air is travelling, which is the opposite of
    the direction a forecast names it by. Both are on the dial: the arrow for
    anybody reading the picture, the letters for anybody reading the words.
    """
    import cairo  # noqa: PLC0415

    centre = size / 2.0
    radius = centre - 2.0
    cr.save()
    cr.set_line_width(1.4)
    _set(cr, colours, "on_surface", 0.14)
    cr.new_sub_path()
    cr.arc(centre, centre, radius, 0, math.tau)
    cr.stroke()

    _set(cr, colours, "on_surface_variant", 0.55)
    cr.set_line_width(1.2)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for index in range(8):
        angle = math.radians(index * 45.0 - 90.0)
        inner = radius - (5.0 if index % 2 == 0 else 3.0)
        cr.move_to(centre + math.cos(angle) * inner,
                   centre + math.sin(angle) * inner)
        cr.line_to(centre + math.cos(angle) * (radius - 1.0),
                   centre + math.sin(angle) * (radius - 1.0))
    cr.stroke()

    if bearing is not None:
        # Meteorological bearing is where the wind comes from, so the arrow
        # is drawn a half turn round from it.
        angle = math.radians((bearing + 180) % 360 - 90)
        tip = radius - 5.0
        tail = radius - 17.0
        head_x = centre + math.cos(angle) * tip
        head_y = centre + math.sin(angle) * tip
        cr.set_line_width(2.0)
        _set(cr, colours, "primary")
        cr.move_to(centre - math.cos(angle) * tail,
                   centre - math.sin(angle) * tail)
        cr.line_to(head_x, head_y)
        cr.stroke()
        for side in (140.0, -140.0):
            wing = angle + math.radians(side)
            cr.move_to(head_x, head_y)
            cr.line_to(head_x + math.cos(wing) * 5.6,
                       head_y + math.sin(wing) * 5.6)
        cr.stroke()

    # North stated rather than implied. A dial with an arrow on it and no
    # letters asks somebody to assume up is north, and half of them will.
    letter_height = measure(cr, font, "N", 0.66)[1]
    for letters, angle in (("N", -90.0), ("E", 0.0), ("S", 90.0), ("W", 180.0)):
        radians = math.radians(angle)
        at = radius - 9.0
        _set(cr, colours, "on_surface_variant", 0.9 if letters == "N" else 0.55)
        text(cr, font, letters,
             centre + math.cos(radians) * at,
             centre + math.sin(radians) * at - letter_height / 2.0,
             align="center", scale=0.66, weight=700 if letters == "N" else 0)
    cr.restore()


#: The ultraviolet scale runs to eleven and then says "and above", so the bar
#: does too rather than pretending the top is twelve.
UV_TOP = 11.0


def uv_bar(cr, width: float, height: float, index: float | None,
           colours: dict) -> None:
    import cairo  # noqa: PLC0415

    track = min(6.0, height)
    top = (height - track) / 2.0
    # The same ramp the week's bars use, so a hot day and a high ultraviolet
    # index are the same red rather than two reds that nearly match.
    gradient = cairo.LinearGradient(0, 0, width, 0)
    for stop in (0.0, 0.25, 0.5, 0.75, 1.0):
        gradient.add_color_stop_rgb(stop, *heat(stop))
    cr.save()
    _capsule(cr, 0.0, top, width, track)
    cr.set_source(gradient)
    cr.fill()
    cr.restore()

    if index is None:
        return
    spot = max(0.0, min(1.0, index / UV_TOP)) * width
    spot = max(track / 2.0 + 1.0, min(width - track / 2.0 - 1.0, spot))
    _set(cr, colours, "surface")
    cr.new_sub_path()
    cr.arc(spot, height / 2.0, track * 0.86, 0, math.tau)
    cr.fill()
    _set(cr, colours, "on_surface")
    cr.new_sub_path()
    cr.arc(spot, height / 2.0, track * 0.52, 0, math.tau)
    cr.fill()


def level_bar(cr, width: float, height: float, value: float | None,
              low: float, high: float, colours: dict,
              role: str = "primary") -> None:
    """A reading placed inside the range it can take, for humidity and pressure.

    Ninety four percent means nothing until you know it runs to a hundred,
    and a thousand and eighteen millibars means nothing at all until you can
    see it sitting just above the middle.
    """
    track = min(6.0, height)
    top = (height - track) / 2.0
    _set(cr, colours, "on_surface", 0.12)
    _capsule(cr, 0.0, top, width, track)
    cr.fill()
    if value is None or high <= low:
        return
    amount = max(0.0, min(1.0, (value - low) / (high - low)))
    _set(cr, colours, role)
    _capsule(cr, 0.0, top, max(track, width * amount), track)
    cr.fill()


def moon_disc(cr, size: float, lit: float, waxing: bool, colours: dict) -> None:
    """The moon at tonight's phase, as one closed path.

    The lit part of a moon is a half disc on one side and a half ellipse on
    the other, and the ellipse is what makes a gibbous moon look like a moon
    rather than like a badly cropped circle. Drawing it as a path rather than
    as a hole punched out of a disc matters here: this mark sits over a
    photograph, and a hole shows the photograph through it.
    """
    centre = size / 2.0
    radius = centre - 1.0
    lit = max(0.0, min(1.0, lit))

    _set(cr, colours, "on_surface", 0.14)
    cr.new_sub_path()
    cr.arc(centre, centre, radius, 0, math.tau)
    cr.fill()

    if lit <= 0.02:
        return

    # How far the terminator bulges, and which way. At full it lies on the
    # far rim, at new it lies on the near one, and at half it is straight.
    reach = (2.0 * lit - 1.0) * radius * (-1.0 if waxing else 1.0)
    kappa = 0.5523          # a quarter ellipse, as four control points

    cr.save()
    cr.translate(centre, centre)
    cr.new_path()
    cr.move_to(0.0, -radius)
    if waxing:
        cr.arc(0.0, 0.0, radius, math.radians(-90), math.radians(90))
    else:
        cr.arc_negative(0.0, 0.0, radius, math.radians(-90), math.radians(-270))
    cr.curve_to(reach * kappa, radius, reach, radius * kappa, reach, 0.0)
    cr.curve_to(reach, -radius * kappa, reach * kappa, -radius, 0.0, -radius)
    cr.close_path()
    _set(cr, colours, "secondary")
    cr.fill()
    cr.restore()
