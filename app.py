"""Streamlit UI that classifies uploaded camera trap images with a Darknet/YOLO model.

Start it with `streamlit run server.py`, which adds the route that receives the uploaded images.
"""

import colorsys
import functools
import hashlib
import io
import json
from collections.abc import Callable
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

import analysis
from analysis import ImageResult
from detector import Detection
from i18n import init_language, language_selector, number, t, time_locale, upload_texts
from shutdown import end_program
from upload_field import upload_field

GALLERY_STEP = 24
GALLERY_COLUMNS = 3
REFRESH_SECONDS = 2  # how often the results are updated during an upload
TIMELINE_STEP = 22  # height of a row of the timeline in pixels
TIMELINE_FONT_SIZE = 12  # of the class names in the timeline
TIMELINE_BOX_SPACE = 24  # pixels between the class names and the timeline, for the boxes
ALL_IMAGES_OPACITY = 0.25  # of one image in the row "all images" of the timeline
UNTICKED_OPACITY = 0.45  # of the name of a class that isn't ticked in the timeline
SCALE_WIDTH = 400  # of the confidence scale above the timeline, at most, in pixels
CONTROLS_WIDTH = 300  # room for the axis switch and the help right of the confidence scale, see PAGE_CSS
# internal columns, never shown
IMAGE_ID = "_image"  # to count images
CLASS_ID = "_class"  # a row of the timeline: the class name of the model, which doesn't change with the language
TICKED = "_ticked"  # whether a row of the timeline is ticked
CLICK = "_click"  # the number of the next click on a row of the timeline, see timeline_reported()
ALL_ROWS = ""  # CLASS_ID of the row "all images"
STEP = "_step"  # a threshold that the confidence scale above the timeline can be set to
SHADE = "_shade"  # position in the diverging colours, see shade()
SCALE_X = "_x"  # position on the confidence scale in pixels
# Bin edges of the confidence histogram. The confidence scale in the timeline sets the threshold in the same 5 % steps
# (rounded the same way), so a bin never holds detections from both sides of the threshold.
CONFIDENCE_STEP = 0.05
DEFAULT_THRESHOLD = 0.5
CONFIDENCE_EDGES = [round(analysis.MIN_CONFIDENCE + i * CONFIDENCE_STEP, 2)
                    for i in range(round((1 - analysis.MIN_CONFIDENCE) / CONFIDENCE_STEP) + 1)]


# The charts take their colours from the theme (see .streamlit/config.toml), so they change with it without a rerun:
# the default mark colour and the first two categorical colours stand for "detected" and "not detected", the
# diverging colours for confidence, see shade(). Text and annotations use this grey, readable on light and dark
# background.
MUTED_COLOR = "#898781"

# Layout that Streamlit has no options for. If an update changes the structure, the rules just have no effect.
PAGE_CSS = """<style>
/* less space above the title than Streamlit's 6rem */
[data-testid="stMainBlockContainer"] { padding-top: 2rem; }
/* The axis switch and the help lie over the top right of the timeline, next to its confidence scale, which leaves
   them room (CONTROLS_WIDTH). On top, so that they receive the clicks there, but the row as wide as the chart lets
   the clicks beside them through to the scale. */
.st-key-timeline_controls { position: relative; z-index: 1; margin-bottom: -3.5rem; pointer-events: none; }
.st-key-timeline_controls > * { pointer-events: auto; }
</style>"""
# Streamlit cuts axis labels at 100 px, which would cut long class names like "Krähen (verschiedene)"
CLASS_AXIS = alt.Axis(labelLimit=200)


def bin_start(field: str) -> str:
    """Start of a detection's bin in the confidence histogram, as Vega-Lite expression. Confidences have 4 decimals
    (see DarkHelpDetector), so the tiny addition only affects confidences exactly on an edge: they belong to the bin
    starting there, just like a detection counts from the threshold on. 100 % goes into the last bin."""
    return (f"min(floor((datum[{json.dumps(field)}] - {analysis.MIN_CONFIDENCE}) / {CONFIDENCE_STEP} + 1e-9), "
            f"{len(CONFIDENCE_EDGES) - 2}) * {CONFIDENCE_STEP} + {analysis.MIN_CONFIDENCE}")


def shade(field: str) -> str:
    """Colour of a confidence in the timeline, as Vega-Lite expression: its position in the ten diverging colours,
    the first five for confidences below the threshold (orange), the last five from it on (blue), both from low to
    high. Nothing lies between the fifth and sixth colour, so no confidence gets a mix of both."""
    return (f"(datum[{json.dumps(field)}] - {analysis.MIN_CONFIDENCE}) / {1 - analysis.MIN_CONFIDENCE} * 4 / 9 "
            f"+ (datum[{json.dumps(field)}] >= threshold.{STEP}[0] ? 5 / 9 : 0)")


def class_name(name: str) -> str:
    """Display name of a class in the current language, see analysis.get_display_names()."""
    return analysis.get_display_names().get(name, {}).get(st.session_state.language, name)


def class_color(class_id: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((class_id * 0.618034) % 1.0, 0.85, 0.95)
    return int(r * 255), int(g * 255), int(b * 255)


@functools.cache
def label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """DejaVu Sans (in the Docker image from fonts-dejavu-core), since Pillow's own font has no umlauts."""
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


@st.cache_data(max_entries=512, show_spinner=False)
def annotated_preview(path: str, detections: tuple[Detection, ...], labels: tuple[str, ...]) -> Image.Image:
    """The preview with boxes and labels, scaled to the image width so they stay readable in the gallery."""
    image = Image.open(path)
    draw = ImageDraw.Draw(image)
    font = label_font(max(12, image.width // 24))
    line = max(2, image.width // 200)
    # the most confident detection is drawn last, so its label stays on top
    for d, label in reversed(list(zip(detections, labels))):
        x0, y0, x1, y1 = d.to_pixels(image.width, image.height)
        color = class_color(d.class_id)
        draw.rectangle((x0, y0, x1, y1), outline=color, width=line)
        # label above the box, or inside it if there is no room at the top of the image
        anchor = "lb" if draw.textbbox((x0, y0), label, font=font, anchor="lb")[1] >= 0 else "lt"
        left, top, right, bottom = draw.textbbox((x0 + line, y0), label, font=font, anchor=anchor)
        draw.rectangle((left - line, top - line, right + line, bottom + line), fill=color)
        draw.text((x0 + line, y0), label, fill="black", font=font, anchor=anchor)
    return image


def excel_file(sheets: dict[str, pd.DataFrame], percent_columns: set[str]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
            for title, cells in zip(df.columns, writer.sheets[name].iter_cols()):
                width = max(len(str(cell.value)) for cell in cells if cell.value is not None)
                writer.sheets[name].column_dimensions[cells[0].column_letter].width = min(width + 2, 60)
                if title in percent_columns:
                    for cell in cells[1:]:
                        cell.number_format = "0.0%"
    return buffer.getvalue()


def bar_chart(df: pd.DataFrame) -> alt.LayerChart:
    """Horizontal bars of images per class, largest first, with the value at the tip."""
    images, klass = t("col_images"), t("col_class")
    base = alt.Chart(df).encode(
        y=alt.Y(field=klass, type="nominal", sort="-x", title=None, axis=CLASS_AXIS),
        x=alt.X(field=images, type="quantitative", title=images, axis=alt.Axis(tickMinStep=1)),
        tooltip=[alt.Tooltip(field=klass, type="nominal"), alt.Tooltip(field=images, type="quantitative"),
                 alt.Tooltip(field=t("col_detections"), type="quantitative")])
    bars = base.mark_bar(size=18, cornerRadiusEnd=4)
    labels = base.mark_text(align="left", dx=4, color=MUTED_COLOR).encode(
        text=alt.Text(field=images, type="quantitative"))
    return (bars + labels).properties(height=alt.Step(28))


def confidence_histogram(df: pd.DataFrame, threshold: float) -> alt.LayerChart:
    """Histogram of all detections in the bins of bin_start(): blue from the threshold on, orange below, and a rule
    at the threshold."""
    confidence, status, detections = t("col_confidence"), t("col_status"), t("col_detections")
    scale = alt.Scale(domain=[analysis.MIN_CONFIDENCE, 1])
    bars = alt.Chart(df).transform_calculate(bin_start=bin_start(confidence)).transform_calculate(
        bin_end=f"datum.bin_start + {CONFIDENCE_STEP}").mark_bar(
        cornerRadiusTopLeft=4, cornerRadiusTopRight=4, xOffset=1, x2Offset=-1,  # 2 px gap between the bars
    ).encode(
        x=alt.X(field="bin_start", type="quantitative", title=confidence, scale=scale,
                axis=alt.Axis(format=".0%", values=CONFIDENCE_EDGES)),
        x2=alt.X2(field="bin_end"),
        # A bin holds only one status, so nothing to stack. Stacked bars with rounded corners and x2 aren't drawn.
        y=alt.Y(aggregate="count", type="quantitative", stack=None, title=detections, axis=alt.Axis(tickMinStep=1)),
        color=alt.Color(field=status, type="nominal", title=None, legend=alt.Legend(orient="top"),
                        scale=alt.Scale(domain=[t("detected"), t("not_detected")], range="category")),
        tooltip=[alt.Tooltip(field="bin_start", type="quantitative", format=".0%", title=t("from")),
                 alt.Tooltip(field="bin_end", type="quantitative", format=".0%", title=t("to")),
                 alt.Tooltip(field=status, type="nominal"),
                 alt.Tooltip(aggregate="count", type="quantitative", title=detections)])
    # same scale as the bars, otherwise the layers' domains are merged and the axis starts at 0
    rule = alt.Chart(pd.DataFrame({"threshold": [threshold]})).encode(
        x=alt.X(field="threshold", type="quantitative", title=confidence, scale=scale))
    label = rule.mark_text(align="left", baseline="top", dx=4, color=MUTED_COLOR,
                           text=t("threshold_label", value=f"{threshold:.0%}")).encode(y=alt.value(0))
    return bars + rule.mark_rule(color=MUTED_COLOR, strokeWidth=2) + label


def hour_chart(df: pd.DataFrame) -> alt.LayerChart:
    """Images per hour of the day, all 24 hours on the axis. Images with detection are stacked at the bottom, images
    without on top.

    Vega-Lite has no gap between stacked segments, so the stack is computed explicitly: a segment on top of another
    one starts 2 px higher, and only the topmost segment gets rounded corners. Mark properties can't depend on the
    data, hence one layer per combination.
    """
    hour, detection, images = t("col_hour"), t("col_detection"), t("col_images")
    with_detection, without_detection = t("with_detection"), t("without_detection")
    base = alt.Chart(df).transform_calculate(
        order=f"datum[{json.dumps(detection)}] == {json.dumps(with_detection)} ? 0 : 1",
    ).transform_stack(
        stack=images, groupby=[hour], sort=[alt.SortField("order")], as_=["bottom", "top"],
    ).transform_joinaggregate(total="max(top)", groupby=[hour]).encode(
        x=alt.X(field=hour, type="ordinal", scale=alt.Scale(domain=list(range(24))), title=t("hour_axis"),
                axis=alt.Axis(labelAngle=0)),
        y=alt.Y(field="top", type="quantitative", title=images, axis=alt.Axis(tickMinStep=1)),
        y2=alt.Y2(field="bottom"),
        color=alt.Color(field=detection, type="nominal", title=None, legend=alt.Legend(orient="top"),
                        scale=alt.Scale(domain=[with_detection, without_detection], range="category")),
        tooltip=[alt.Tooltip(field=hour, type="ordinal"), alt.Tooltip(field=detection, type="nominal"),
                 alt.Tooltip(field=images, type="quantitative")])
    layers = [base.mark_bar(size=16, cornerRadiusTopLeft=radius, cornerRadiusTopRight=radius, y2Offset=offset)
              .transform_filter(f"(datum.top == datum.total) == {top} && (datum.bottom > 0) == {stacked}")
              for top, radius in (("true", 4), ("false", 0)) for stacked, offset in (("true", -2), ("false", 0))]
    return alt.layer(*layers)


def timeline_chart(df: pd.DataFrame, rows: pd.DataFrame, by_order: bool, zoom: list[float] | None,
                   threshold: float | None) -> alt.LayerChart:
    """The images on an axis of capture times or of their order: one row with all images, then one row per class,
    coloured by its confidence, see shade(). A click on the box or the name left of a row ticks it, see
    timeline_reported(). The confidence scale above sets the threshold by click or by dragging.

    Every image gets a line of fixed width, so images taken seconds apart stay visible when zoomed out. Where they
    overlap, the most confident one is drawn on top.

    The axis zooms with Ctrl + wheel or a pinch on the touchpad (the plain wheel keeps scrolling the page) and moves by
    dragging, starting at zoom. Streamlit reports the visible part, which filters the results. On the time axis,
    Vega-Lite would place a tick every 40 px, too close for the labels: it would hide every second one, over several
    days possibly all dates, leaving only "12:00". With a tick every 90 px, no label has to be hidden. The first label
    also shows the date, unless it is one already (midnight).

    The times are ISO strings without time zone, which the browser reads as local time, so they appear as the camera
    wrote them.
    """
    file, taken, position, klass, confidence = (t("col_file"), t("col_taken"), t("col_position"), t("col_class"),
                                                t("col_confidence"))
    day = t("axis_day")
    has_confidence = f"isValid(datum[{json.dumps(confidence)}])"
    # Events on the confidence scale, the only marks with the column STEP, neither move nor reset the visible part.
    on_scale = f"event.item && event.item.datum && isValid(event.item.datum.{STEP})"
    zoom_param = alt.selection_interval(
        bind="scales", encodings=["x"], zoom="wheel![event.ctrlKey]", name="zoom", clear=f"dblclick[!({on_scale})]",
        translate=f"[pointerdown[!({on_scale})], window:pointerup] > window:pointermove!",
        **({"value": {"x": zoom}} if zoom else {}))
    if by_order:
        # Vega-Lite would read the dot in "Bild Nr." as access to a nested field
        position_field = position.replace(".", "\\.")
        x = alt.X(field=position_field, type="quantitative", title=None, scale=alt.Scale(nice=False, padding=8),
                  axis=alt.Axis(format="d", tickMinStep=1))
        image_tooltip = [alt.Tooltip(field=file, type="nominal"),
                         alt.Tooltip(field=position_field, type="quantitative", title=position),
                         alt.Tooltip(field=taken, type="temporal", format=t("time_format"))]
    else:
        x = alt.X(field=taken, type="temporal", title=None, scale=alt.Scale(nice=False, padding=8),
                  axis=alt.Axis(format={"year": "%Y", "quarter": "%B", "month": "%B", "week": day, "date": day,
                                        "hours": "%H:%M", "minutes": "%H:%M", "seconds": "%H:%M:%S",
                                        "milliseconds": "%H:%M:%S.%L"},
                                tickCount=alt.ExprRef("ceil(width / 90)"),
                                labelExpr="datum.index == 0 && hours(datum.value) + minutes(datum.value) "
                                          "+ seconds(datum.value) > 0 ? [datum.label, timeFormat(datum.value, "
                                          f"{json.dumps(t('day_format'))})] : datum.label"))
        image_tooltip = [alt.Tooltip(field=file, type="nominal"),
                         alt.Tooltip(field=taken, type="temporal", format=t("time_format"))]
    # The class names are drawn by a layer below, so that they can be clicked. The axis labels just keep the room
    # free for them.
    y = alt.Y(field=klass, type="nominal", sort=list(rows[klass]), title=None,
              axis=alt.Axis(labelOpacity=0, labelFontSize=TIMELINE_FONT_SIZE, labelLimit=200,
                            labelPadding=TIMELINE_BOX_SPACE, ticks=False))
    base = alt.Chart(df).encode(x=x, y=y, tooltip=image_tooltip)
    # All images in the text colour of the page (black or white, following the theme) and translucent, so that images
    # close together add up to a stronger line than a single one
    images = base.transform_filter(f"!{has_confidence}").mark_tick(
        color="currentColor", opacity=ALL_IMAGES_OPACITY, thickness=2, size=TIMELINE_STEP - 6).add_params(zoom_param)
    # opaque, ticks are drawn with 70 % opacity by default
    shades = alt.Scale(domain=[0, 1], range="diverging")
    detections = base.transform_filter(has_confidence).transform_calculate(**{SHADE: shade(confidence)}).mark_tick(
        opacity=1, thickness=3, size=TIMELINE_STEP - 6).encode(
        color=alt.Color(field=SHADE, type="quantitative", scale=shades, legend=None),
        order=alt.Order(field=confidence, type="quantitative", sort="ascending"),
        tooltip=[*image_tooltip, alt.Tooltip(field=klass, type="nominal"),
                 alt.Tooltip(field=confidence, type="quantitative", format=".0%")])

    # A click selects its row, see timeline_reported(). The selection reacts to clicks on any mark of the chart, so
    # the filter keeps it to the boxes and names, the only marks with the column TICKED. Until the rerun after the
    # click draws the chart again, the clicked row shows the opposite of whether it's ticked.
    rows_param = alt.selection_point(fields=[CLASS_ID, CLICK], toggle=False, clear=False, name="rows",
                                     on=f"click[event.item && event.item.datum && isValid(event.item.datum.{TICKED})]")
    clicked = {"param": "rows", "empty": False}
    is_ticked = {"field": TICKED, "equal": True}
    shows_ticked = {"or": [{"and": [clicked, {"not": is_ticked}]}, {"and": [{"not": clicked}, is_ticked]}]}
    # outside the plot, where Vega-Lite would cut them off in a zoomable chart
    labels = alt.Chart(rows).encode(y=y, x=alt.value(0))
    boxes = labels.mark_point(shape="square", size=110, filled=True, fill="transparent", stroke=MUTED_COLOR,
                              strokeWidth=1.5, xOffset=-TIMELINE_BOX_SPACE / 2, clip=False, cursor="pointer",
                              ).add_params(rows_param)
    ticks = labels.transform_filter(shows_ticked).mark_text(
        text="✓", fontSize=TIMELINE_FONT_SIZE - 1, fontWeight="bold", color="currentColor",
        xOffset=-TIMELINE_BOX_SPACE / 2, clip=False)
    # Vega-Lite only lets marks with a selection or a tooltip receive clicks. The tooltip shows long names in full.
    names = labels.mark_text(align="right", dx=-TIMELINE_BOX_SPACE, fontSize=TIMELINE_FONT_SIZE, limit=200,
                             color="currentColor", clip=False, cursor="pointer").encode(
        text=alt.Text(field=klass, type="nominal"), tooltip=alt.Tooltip(field=klass, type="nominal"),
        opacity={"condition": {"test": shows_ticked, "value": 1}, "value": UNTICKED_OPACITY})
    chart = alt.layer(images, detections, boxes, ticks, names, *confidence_scale(threshold, on_scale, shades)
                      ).properties(height=alt.Step(TIMELINE_STEP))
    locale = time_locale()
    return chart.configure(locale={"time": locale}) if locale else chart


def confidence_scale(threshold: float | None, on_scale: str, shades: alt.Scale) -> list[alt.Chart]:
    """Layers of the timeline that draw the confidence scale above it, in the colours of the timeline. It works like
    a slider in the steps of the histogram: a click or dragging selects the step closest to the pointer.

    The scale lies outside the plot, as the plot's x axis shows times, so it is placed in pixels. The handle and the
    title follow the selection right away, the results after the rerun, see timeline_reported().
    """
    scale_width = f"clamp(width - {CONTROLS_WIDTH}, 100, {SCALE_WIDTH})"

    def x(field: str) -> str:
        return f"(datum.{field} - {analysis.MIN_CONFIDENCE}) / {1 - analysis.MIN_CONFIDENCE} * {scale_width}"

    pixels = alt.X(field=SCALE_X, type="quantitative", scale=None)
    # a rectangle per half percent, with an outline in its colour against gaps between them
    fine = alt.Chart(pd.DataFrame({"c": [round(analysis.MIN_CONFIDENCE + i / 200, 3)
                                         for i in range(round((1 - analysis.MIN_CONFIDENCE) * 200))]}))
    colours = fine.transform_calculate(**{SHADE: shade("c"), SCALE_X: x("c"), "end": f"{x('c')} + "
                                          f"{scale_width} / {(1 - analysis.MIN_CONFIDENCE) * 200}"})
    bar = colours.mark_rect(strokeWidth=1, clip=False).encode(
        x=pixels, x2=alt.X2(field="end"), y=alt.value(-44), y2=alt.value(-32),
        color=alt.Color(field=SHADE, type="quantitative", scale=shades, legend=None),
        stroke=alt.Stroke(field=SHADE, type="quantitative", scale=shades, legend=None))
    tens = alt.Chart(pd.DataFrame({"c": [round(i / 10, 1) for i in range(round(analysis.MIN_CONFIDENCE * 10), 11)]}))
    tens = tens.transform_calculate(**{SCALE_X: x("c")}).encode(x=pixels)
    tick_marks = tens.mark_rule(color=MUTED_COLOR, clip=False).encode(y=alt.value(-32), y2=alt.value(-28))
    tick_labels = tens.mark_text(color=MUTED_COLOR, baseline="top", fontSize=10, clip=False).encode(
        y=alt.value(-26), text=alt.Text(field="c", type="quantitative", format=".0%"))

    threshold_param = alt.selection_point(
        fields=[STEP], toggle=False, clear=False, name="threshold",
        on=f"pointerdown[{on_scale}], pointermove[event.buttons && {on_scale}]",
        **({"value": [{STEP: threshold}]} if threshold is not None else {}))
    steps = alt.Chart(pd.DataFrame({STEP: CONFIDENCE_EDGES})).transform_calculate(**{SCALE_X: x(STEP)})
    # transparent, but they receive the events: each covers the scale half a step to both sides of its threshold
    half_step = f"{scale_width} * {CONFIDENCE_STEP / 2 / (1 - analysis.MIN_CONFIDENCE)}"
    targets = steps.transform_calculate(start=f"max(datum.{SCALE_X} - {half_step}, 0)",
                                        end=f"min(datum.{SCALE_X} + {half_step}, {scale_width})"
                                        ).mark_rect(fill="transparent", cursor="pointer", clip=False).encode(
        x=alt.X(field="start", type="quantitative", scale=None), x2=alt.X2(field="end"),
        y=alt.value(-48), y2=alt.value(-14)).add_params(threshold_param)
    selected = steps.transform_filter({"param": "threshold", "empty": False}).encode(x=pixels)
    handle = selected.mark_rule(color="currentColor", strokeWidth=2.5, clip=False).encode(
        y=alt.value(-48), y2=alt.value(-28))
    title = selected.transform_calculate(title=f"{json.dumps(t('threshold') + ': ')} + format(datum.{STEP}, '.0%')"
                                         ).mark_text(align="left", baseline="bottom", fontWeight="bold",
                                                     color="currentColor", clip=False).encode(
        x=alt.value(0), y=alt.value(-52), text=alt.Text(field="title", type="nominal"))
    return [bar, tick_marks, tick_labels, targets, handle, title]


def capture_times(zoom: list[float]) -> tuple[datetime, datetime]:
    """The visible part of the time axis as capture times.

    The browser reports it in milliseconds since 1970. It read the capture times as its local time (see
    timeline_chart()), so they are converted back with its time zone, not the server's (UTC in Docker).
    """
    timezone = st.context.timezone

    def capture_time(ms: float) -> datetime:
        ms = round(ms)  # the camera's times have whole seconds anyway
        if timezone:
            return pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(timezone).tz_localize(None).to_pydatetime()
        return datetime.fromtimestamp(ms / 1000)

    return capture_time(zoom[0]), capture_time(zoom[1])


def browser_time(taken: datetime) -> float:
    """A capture time in milliseconds since 1970, as the browser reads it, the reverse of capture_times()."""
    timezone = st.context.timezone
    if timezone:
        return pd.Timestamp(taken).tz_localize(timezone, ambiguous=True, nonexistent="shift_forward").timestamp() * 1000
    return taken.timestamp() * 1000


def period_text(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start:{t('day_format')}} {start:%H:%M:%S}–{end:%H:%M:%S}"
    return f"{start:{t('time_format')}} – {end:{t('time_format')}}"


def new_timeline() -> None:
    """Let the next run draw a new timeline, which starts with the zoom and threshold in its spec. A new key, as
    Streamlit would restore the visible part of the old one, see show_timeline()."""
    st.session_state.timeline_charts = st.session_state.get("timeline_charts", 0) + 1
    st.session_state.get("timeline", {}).pop("version", None)


def timeline_reported(key: str) -> None:
    """Takes over what the timeline reports: the visible part, the threshold, and a click on a row, which ticks or
    unticks it.

    The selection of rows holds the row clicked last, with the number of the click. Streamlit restores it when it
    draws the chart again, and it comes along with later reports, so only a new number means a new click. The number
    also lets Streamlit report a second click on the same row, which it would take as no change otherwise.
    """
    selection = st.session_state[key].selection
    state = st.session_state.timeline
    if "zoom" in selection:  # not before the first zoom of a new chart, which starts with the zoom in its spec
        state["zoom"] = next(iter(selection["zoom"].values()), None)  # {} after a double click
    steps = selection.get("threshold")
    if isinstance(steps, list) and steps:
        st.session_state.threshold = steps[-1][STEP]
    rows = selection.get("rows")
    if isinstance(rows, list) and rows and rows[-1][CLICK] == state["clicks"]:  # {} before the first click
        state["clicks"] += 1
        name = rows[-1][CLASS_ID]
        if name == ALL_ROWS:
            state["hidden"] = set(state["classes"]) if ALL_ROWS in state["ticked"] else set()
        else:
            state["hidden"] ^= {name}


def switch_axis() -> None:
    """Carries the visible part over to the other axis: the images in it, as far as they have a capture time."""
    state = st.session_state.timeline
    by_order = st.session_state.timeline_axis == "order"
    zoom, takens = state["zoom"], state["takens"]
    state.update(zoom=None, axis="order" if by_order else "time")
    new_timeline()
    if not zoom:
        return
    if by_order:
        start, end = capture_times(zoom)
        inside = [i for i, taken in enumerate(takens, 1) if taken and start <= taken <= end]
        if inside:
            state["zoom"] = [inside[0] - 0.5, inside[-1] + 0.5]
    else:
        inside = [taken for i, taken in enumerate(takens, 1) if taken and zoom[0] <= i <= zoom[1]]
        if inside:
            first, last = browser_time(min(inside)), browser_time(max(inside))
            # Half a second, as the times have whole seconds, so that the neighbours stay outside. A single image
            # gets a minute, the axis can't show less than a second.
            margin = 500 if last > first else 30_000
            state["zoom"] = [first - margin, last + margin]


def show_all() -> None:
    st.session_state.timeline["zoom"] = None
    new_timeline()


def tick_all_classes() -> None:
    st.session_state.timeline["hidden"] = set()


def show_timeline(results: list[ImageResult], label: Callable[[ImageResult], str]) -> tuple[list[ImageResult],
                                                                                              set[str]]:
    """Show the timeline of all readable images, and return the images in its visible part (all if nothing was
    zoomed or moved) and the classes that aren't ticked. The threshold set in it is in st.session_state.threshold.

    The axis shows the capture times or the order of the images, which also covers images without capture time. The
    timeline shows all detections, below the threshold in other colours.

    Streamlit draws a chart anew when its spec changes, e.g. with new images, another language or after a click on a
    class. It keeps the chart's state then, e.g. the visible part and the threshold, as long as the key stays the
    same. A new chart (see new_timeline()) starts with them in its spec instead. They are the ones reported last when
    the spec changes for another reason, but not each report, as that would draw it anew while zooming or dragging.
    """
    file, taken, position, klass, confidence = (t("col_file"), t("col_taken"), t("col_position"), t("col_class"),
                                                t("col_confidence"))
    state = st.session_state.setdefault("timeline", {"zoom": None, "hidden": set(), "clicks": 0, "axis": "time"})
    threshold = st.session_state.setdefault("threshold", DEFAULT_THRESHOLD)
    readable = [r for r in results if not r.error]
    if not readable:
        return results, state["hidden"]
    # the images, with the highest confidence per class
    timeline = []
    for i, r in enumerate(readable, 1):
        image = {file: label(r), taken: r.taken.isoformat() if r.taken else None, position: i}  # see timeline_chart()
        timeline.append({**image, klass: t("all_images"), CLASS_ID: ALL_ROWS, confidence: None})
        best: dict[str, float] = {}
        for d in r.detections:
            best[d.name] = max(best.get(d.name, 0), d.confidence)
        timeline += [{**image, klass: class_name(name), CLASS_ID: name, confidence: value}
                     for name, value in best.items()]
    timeline_df = pd.DataFrame(timeline, columns=[file, taken, position, klass, CLASS_ID, confidence])
    # the classes with the most images first, unlike the bar chart not depending on the threshold
    classes = list(timeline_df.loc[timeline_df[CLASS_ID] != ALL_ROWS, CLASS_ID].value_counts().index)
    hidden = state["hidden"] & set(classes)
    ticked = ({ALL_ROWS} if not hidden else set()) | (set(classes) - hidden)
    state.update(classes=classes, ticked=ticked, takens=[r.taken for r in readable])
    rows = pd.DataFrame([{klass: t("all_images"), CLASS_ID: ALL_ROWS},
                         *({klass: class_name(name), CLASS_ID: name} for name in classes)])
    rows[TICKED] = rows[CLASS_ID].isin(ticked)
    rows[CLICK] = state["clicks"]
    timed = sum(1 for r in readable if r.taken)

    with st.expander(t("filters"), expanded=True, key="timeline_expander"):
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                          key="timeline_controls"):
            if timed:
                st.segmented_control(t("timeline_axis"), ["time", "order"], format_func=lambda a: t(f"axis_{a}"),
                                     default="time", required=True, key="timeline_axis", on_change=switch_axis,
                                     label_visibility="collapsed")
            # The explanation is needed once, not each time, so it doesn't take room below the timeline.
            help_text = st.popover(t("help"), type="tertiary", icon=":material/help:")
        axis = st.session_state.get("timeline_axis", "time") if timed else "order"
        if state["axis"] != axis:  # e.g. the first image with capture time
            state.update(zoom=None, axis=axis)
            new_timeline()
        if axis == "time":
            timeline_df = timeline_df[timeline_df[taken].notna()]
        unset = timeline_chart(timeline_df, rows, axis == "order", None, None)  # without zoom and threshold
        version = hashlib.sha1(unset.to_json().encode()).hexdigest()
        if version != state.get("version"):
            state.update(version=version, shown_zoom=state["zoom"], shown_threshold=threshold)
        chart = timeline_chart(timeline_df, rows, axis == "order", state["shown_zoom"], state["shown_threshold"])
        key = f"timeline_{st.session_state.get('timeline_charts', 0)}"
        st.altair_chart(chart, width="stretch", on_select=lambda: timeline_reported(key), key=key)
        if axis == "time":
            help_text.markdown(t("timeline_time", len(readable), count=number(timed), total=number(len(readable))))
            if timed < len(readable):  # images are missing, which has to be seen
                st.caption(t("untimed", len(readable) - timed, count=number(len(readable) - timed),
                             order=t("axis_order")))
        else:
            help_text.markdown(t("timeline_order"))
        help_text.markdown(t("timeline_caption", minimum=f"{analysis.MIN_CONFIDENCE:.0%}"))

    # outside the expander, so that the filters show also when it is collapsed
    zoom = state["zoom"]
    if hidden:
        with st.container(horizontal=True, vertical_alignment="center"):
            names = ", ".join(class_name(name) for name in classes if name not in hidden)
            st.markdown(t("ticked_classes", classes=names or t("no_classes")))
            st.button(t("all_classes"), on_click=tick_all_classes, icon=":material/done_all:")
    if not zoom:
        return results, hidden
    if axis == "order":
        inside = [(i, r) for i, r in enumerate(readable, 1) if zoom[0] <= i <= zoom[1]]
        text = t("positions", len(results), positions=f"{inside[0][0]}–{inside[-1][0]}" if inside else "–",
                 count=number(len(inside)), total=number(len(results)))
        in_range = [r for _, r in inside]
    else:
        start, end = capture_times(zoom)
        in_range = [r for r in readable if r.taken and start <= r.taken <= end]
        text = t("period", len(results), period=period_text(start, end), count=number(len(in_range)),
                 total=number(len(results)))
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(text)
        st.button(t("whole_period") if axis == "time" else t("show_all"), on_click=show_all,
                  icon=":material/zoom_out_map:")
    return in_range, hidden


def common_folder(paths: list[str]) -> str:
    """The folders all paths start with, e.g. "A/" for "A/a.jpg" and "A/b.jpg", but "" for "A/a.jpg" and "B/a.jpg"."""
    common = []
    for parts in zip(*(path.split("/")[:-1] for path in paths)):
        if len(set(parts)) > 1:
            break
        common.append(parts[0])
    return "".join(part + "/" for part in common)


def show_results(results: list[ImageResult]) -> None:
    if not results:
        st.info(t("empty_hint"))
        return

    # the folders that all images share say nothing, e.g. "DCIM/100MEDIA/" when one SD card folder was uploaded
    prefix = common_folder([r.name for r in results])

    def label(result: ImageResult) -> str:
        return result.name.removeprefix(prefix)

    results, hidden = show_timeline(results, label)
    threshold = st.session_state.get("threshold", DEFAULT_THRESHOLD)

    def visible(result: ImageResult) -> list[Detection]:
        """Detections that pass the filters, most confident first."""
        return sorted((d for d in result.detections if d.confidence >= threshold and d.name not in hidden),
                      key=lambda d: -d.confidence)

    filtered = [(i, r, visible(r)) for i, r in enumerate(results)]
    errors = [r for r in results if r.error]

    def error_text(result: ImageResult) -> str | None:
        return t("error_unreadable") if result.error == analysis.UNREADABLE else result.error

    file, taken, klass, confidence = t("col_file"), t("col_taken"), t("col_class"), t("col_confidence")
    images, detections, max_confidence = t("col_images"), t("col_detections"), t("col_max_confidence")
    detections_df = pd.DataFrame(
        [{IMAGE_ID: i, file: label(r), taken: r.taken, klass: class_name(d.name), confidence: d.confidence}
         for i, r, dets in filtered for d in dets],
        columns=[IMAGE_ID, file, taken, klass, confidence])
    classes_df = (detections_df.groupby(klass)
                  .agg(**{images: (IMAGE_ID, "nunique"), detections: (IMAGE_ID, "size"),
                          max_confidence: (confidence, "max")})
                  .sort_values(images, ascending=False).reset_index())
    # all detections of the ticked classes, also below the threshold, for the histogram
    confidences_df = pd.DataFrame(
        [{file: label(r), taken: r.taken, klass: class_name(d.name), confidence: d.confidence,
          t("col_status"): t("detected") if d.confidence >= threshold else t("not_detected")}
         for r in results for d in r.detections if d.name not in hidden],
        columns=[file, taken, klass, confidence, t("col_status")])
    images_df = pd.DataFrame(
        [{file: label(r), taken: r.taken,
          t("col_detected_classes"): ", ".join(dict.fromkeys(class_name(d.name) for d in dets)),
          max_confidence: max((d.confidence for d in dets), default=None),
          t("col_duration"): round(r.duration * 1000) if r.duration is not None else None,
          t("col_error"): error_text(r)}
         for _, r, dets in filtered])
    durations = [r.duration for r in results if r.duration is not None]

    # for the export button in the sidebar, which can't be part of this fragment
    st.session_state.export.update(
        sheets={t("sheet_detections"): detections_df[[file, taken, klass, confidence]],
                t("sheet_classes"): classes_df, t("sheet_images"): images_df},
        percent_columns={confidence, max_confidence})

    readable = [(r, dets) for _, r, dets in filtered if not r.error]
    tab_gallery, tab_statistics = st.tabs([t("tab_gallery"), t("tab_statistics")])

    with tab_gallery:
        only_hits = st.checkbox(t("only_hits"), value=False, key="only_hits")
        gallery = [(r, dets) for _, r, dets in filtered if r.preview and (dets or not only_hits)]
        if not gallery:
            st.info(t("no_images"))
        columns = st.columns(GALLERY_COLUMNS)
        for i, (r, dets) in enumerate(gallery[:st.session_state.gallery_limit]):
            labels = tuple(f"{class_name(d.name)} {d.confidence:.0%}" for d in dets)
            caption = " · ".join([label(r), *([r.taken.strftime(t("date_format"))] if r.taken else []),
                                  ", ".join(labels) or "–"])
            columns[i % GALLERY_COLUMNS].image(annotated_preview(str(r.preview), tuple(dets), labels),
                                               caption=caption, width="stretch")
        if len(gallery) > st.session_state.gallery_limit:
            if st.button(t("more_images", count=number(len(gallery) - st.session_state.gallery_limit))):
                st.session_state.gallery_limit += GALLERY_STEP
                st.rerun(scope="fragment")

    # the data behind each chart can be viewed and downloaded as CSV from the chart's menu
    with tab_statistics:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric(t("metric_images"), len(results))
        m2.metric(t("metric_with_detection"), detections_df[IMAGE_ID].nunique())
        m3.metric(t("metric_detections"), len(detections_df))
        m4.metric(t("metric_unreadable"), len(errors))
        m5.metric(t("metric_duration"), f"{1000 * sum(durations) / len(durations):.0f} ms" if durations else "–",
                  help=t("metric_duration_help"))
        if errors:
            st.subheader(t("unreadable_title"))
            st.dataframe(pd.DataFrame({file: [label(r) for r in errors],
                                       t("col_error"): [error_text(r) for r in errors]}), hide_index=True)
        if readable:
            st.subheader(t("classes_title"))
            # as text, a bar would dwarf the classes as most images usually show nothing
            without_detection = sum(1 for _, dets in readable if not dets)
            st.markdown(t("without_detection_count", len(readable), count=number(without_detection),
                          total=number(len(readable))))
            if not classes_df.empty:
                st.altair_chart(bar_chart(classes_df), width="stretch")
            st.caption(t("classes_caption"))
        if not confidences_df.empty:
            st.subheader(t("confidence_title"))
            st.altair_chart(confidence_histogram(confidences_df, threshold), width="stretch")
            st.caption(t("confidence_caption", minimum=f"{analysis.MIN_CONFIDENCE:.0%}"))

        timed = pd.DataFrame([(r.taken.hour, t("with_detection") if dets else t("without_detection"))
                              for r, dets in readable if r.taken], columns=[t("col_hour"), t("col_detection")])
        if not timed.empty:
            st.subheader(t("hour_title"))
            hours = timed.value_counts().reset_index(name=images)
            st.altair_chart(hour_chart(hours), width="stretch")
            st.caption(t("hour_caption", len(readable), count=number(len(timed)), total=number(len(readable))))


def confirm_end(uploading: bool, has_results: bool) -> None:
    """Content of the dialog that asks before quitting."""
    if uploading:
        st.warning(t("quit_uploading"))
    if has_results:
        st.write(t("quit_results", export=t("export")))
    col_end, col_cancel = st.columns(2)
    if col_end.button(t("quit"), type="primary", width="stretch"):
        st.session_state.end = True
        st.rerun()
    if col_cancel.button(t("cancel"), width="stretch"):
        st.rerun()


init_language()
st.set_page_config(page_title=t("title"), layout="wide")
st.html(PAGE_CSS)
if st.session_state.get("end"):
    end_program(t("ended_title"), t("ended_text"))
if "session" not in st.session_state:
    st.session_state.session = analysis.Session()
    st.session_state.gallery_limit = GALLERY_STEP
session: analysis.Session = st.session_state.session

try:
    with st.spinner(t("loading_model")):
        detector = analysis.get_detector()
        analysis.get_display_names()  # an error in the file shows up here, not in the middle of the results
except Exception as e:
    st.error(t("model_error", error=e))
    st.stop()

# --- Upload: the images go directly to the upload route, which analyses them ----------------------------------------
st.title(t("title"))
# a single line once there are results, to leave the space to them
uploading = upload_field(session.api_url, upload_texts(), compact=bool(session.results))

# --- Sidebar ----------------------------------------------------------------------------------------------------------
# The file is only created when the button is clicked, not on every update during an upload. That happens in a thread
# without access to the session, so the results view below hands over its tables in this dict. It updates them during
# an upload, while the sidebar stays as it is.
export = st.session_state.setdefault("export", {})
st.sidebar.download_button(t("export"), lambda: excel_file(**export), file_name=t("export_file"),
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore",
                           icon=":material/download:", disabled=not session.results, help=t("export_help"),
                           width="stretch")
col_start_over, col_quit = st.sidebar.columns(2)
if col_start_over.button(t("start_over"), disabled=uploading or not session.results, help=t("start_over_help"),
                         width="stretch"):
    st.session_state.session = analysis.Session()
    st.session_state.gallery_limit = GALLERY_STEP
    st.session_state.pop("timeline", None)
    new_timeline()
    st.rerun()
if col_quit.button(t("quit"), help=t("quit_help"), width="stretch"):
    st.dialog(t("quit_title"))(confirm_end)(uploading, bool(session.results))
language_selector()
st.sidebar.caption(t("model_info", classes=len(detector.class_names), darkhelp=detector.versions["DarkHelp"],
                     darknet=detector.versions["Darknet"]))


# --- Results: updated periodically while images are coming in -------------------------------------------------------
@st.fragment(run_every=REFRESH_SECONDS if uploading else None)
def results_view() -> None:
    show_results(sorted(session.results, key=lambda r: r.name))


results_view()
