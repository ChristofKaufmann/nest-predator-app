"""Streamlit UI that classifies uploaded camera trap images with a Darknet/YOLO model.

Start it with `streamlit run server.py`, which adds the route that receives the uploaded images.
"""

import colorsys
import functools
import hashlib
import io
import json
import unicodedata
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
ALL_IMAGES_OPACITY = 0.25  # of one image in the row "all images" of the timeline
IMAGE_ID = "_image"  # internal column to count images, never shown
# Bin edges of the confidence histogram. The threshold slider uses the same 5 % steps (rounded the same way), so a bin
# never holds detections from both sides of the threshold.
CONFIDENCE_STEP = 0.05
CONFIDENCE_EDGES = [round(analysis.MIN_CONFIDENCE + i * CONFIDENCE_STEP, 2)
                    for i in range(round((1 - analysis.MIN_CONFIDENCE) / CONFIDENCE_STEP) + 1)]


# The charts take their colours from the theme (see .streamlit/config.toml), so they change with it without a rerun:
# the default mark colour and the first two categorical colours stand for "detected" and "not detected", the
# sequential colours for confidence. Text and annotations use this grey, readable on light and dark background.
MUTED_COLOR = "#898781"

# Layout that Streamlit has no options for. If an update changes the structure, the rules just have no effect.
PAGE_CSS = """<style>
/* less space above the title than Streamlit's 6rem */
[data-testid="stMainBlockContainer"] { padding-top: 2rem; }
/* The sidebar's content is only as high as itself, which leaves a stretch space no room to grow. These rules let it
   fill the height (and take back most of the large padding below), so everything after the space sits at the bottom. */
[data-testid="stSidebarContent"] { display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"], [data-testid="stSidebarUserContent"] > div {
    flex-grow: 1; display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"] { padding-bottom: 1.5rem; }
</style>"""
# Streamlit cuts axis labels at 100 px, which would cut long class names like "Krähen (verschiedene)"
CLASS_AXIS = alt.Axis(labelLimit=200)


def bin_start(field: str) -> str:
    """Start of a detection's bin in the confidence histogram, as Vega-Lite expression. Confidences have 4 decimals
    (see DarkHelpDetector), so the tiny addition only affects confidences exactly on an edge: they belong to the bin
    starting there, just like a detection counts from the threshold on. 100 % goes into the last bin."""
    return (f"min(floor((datum[{json.dumps(field)}] - {analysis.MIN_CONFIDENCE}) / {CONFIDENCE_STEP} + 1e-9), "
            f"{len(CONFIDENCE_EDGES) - 2}) * {CONFIDENCE_STEP} + {analysis.MIN_CONFIDENCE}")


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


def timeline_chart(df: pd.DataFrame, rows: list[str]) -> alt.LayerChart:
    """The images on a time axis: one row with all images, then one row per class, coloured by its confidence.

    Every image gets a line of fixed width, so images taken seconds apart stay visible when zoomed out. Where they
    overlap, the most confident one is drawn on top.

    The time axis zooms with Ctrl + wheel or a pinch on the touchpad (the plain wheel keeps scrolling the page) and
    moves by dragging. Streamlit reports the visible part, which filters the results, see show_timeline(). Vega-Lite
    would place a tick every 40 px, too close for the labels: it would hide every second one, over several days
    possibly all dates, leaving only "12:00". With a tick every 90 px, no label has to be hidden. The first label also
    shows the date, unless it is one already (midnight).

    The times are ISO strings without time zone, which the browser reads as local time, so they appear as the camera
    wrote them.
    """
    file, taken, klass, confidence = t("col_file"), t("col_taken"), t("col_class"), t("col_confidence")
    day = t("axis_day")
    has_confidence = f"isValid(datum[{json.dumps(confidence)}])"
    zoom = alt.selection_interval(bind="scales", encodings=["x"], zoom="wheel![event.ctrlKey]", name="zoom")
    file_and_time = [alt.Tooltip(field=file, type="nominal"),
                     alt.Tooltip(field=taken, type="temporal", format=t("time_format"))]
    base = alt.Chart(df).encode(
        x=alt.X(field=taken, type="temporal", title=None, scale=alt.Scale(nice=False, padding=8),
                axis=alt.Axis(format={"year": "%Y", "quarter": "%B", "month": "%B", "week": day, "date": day,
                                      "hours": "%H:%M", "minutes": "%H:%M", "seconds": "%H:%M:%S",
                                      "milliseconds": "%H:%M:%S.%L"},
                              tickCount=alt.ExprRef("ceil(width / 90)"),
                              labelExpr="datum.index == 0 && hours(datum.value) + minutes(datum.value) "
                                        "+ seconds(datum.value) > 0 ? [datum.label, timeFormat(datum.value, "
                                        f"{json.dumps(t('day_format'))})] : datum.label")),
        y=alt.Y(field=klass, type="nominal", sort=rows, title=None, axis=CLASS_AXIS),
        tooltip=file_and_time)
    # All images in the text colour of the page (black or white, following the theme) and translucent, so that images
    # close together add up to a stronger line than a single one
    images = base.transform_filter(f"!{has_confidence}").mark_tick(
        color="currentColor", opacity=ALL_IMAGES_OPACITY, thickness=2, size=TIMELINE_STEP - 6).add_params(zoom)
    # opaque, ticks are drawn with 70 % opacity by default
    detections = base.transform_filter(has_confidence).mark_tick(
        opacity=1, thickness=3, size=TIMELINE_STEP - 6).encode(
        color=alt.Color(field=confidence, type="quantitative", title=confidence,
                        scale=alt.Scale(domain=[analysis.MIN_CONFIDENCE, 1], range="ramp"),
                        legend=alt.Legend(orient="top", format=".0%")),
        order=alt.Order(field=confidence, type="quantitative", sort="ascending"),
        tooltip=[*file_and_time, alt.Tooltip(field=klass, type="nominal"),
                 alt.Tooltip(field=confidence, type="quantitative", format=".0%")])
    chart = alt.layer(images, detections).properties(height=alt.Step(TIMELINE_STEP))
    locale = time_locale()
    return chart.configure(locale={"time": locale}) if locale else chart


def selected_period(selection: dict) -> tuple[datetime, datetime] | None:
    """The visible part of the timeline as capture times, None if nothing was zoomed or moved.

    The browser reports it in milliseconds since 1970. It read the capture times as its local time (see
    timeline_chart()), so they are converted back with its time zone, not the server's (UTC in Docker).
    """
    period = next(iter(selection.get("zoom", {}).values()), None)
    if not period:
        return None
    timezone = st.context.timezone

    def capture_time(ms: float) -> datetime:
        if timezone:
            return pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(timezone).tz_localize(None).to_pydatetime()
        return datetime.fromtimestamp(ms / 1000)

    return capture_time(period[0]), capture_time(period[1])


def period_text(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start:{t('day_format')}} {start:%H:%M:%S}–{end:%H:%M:%S}"
    return f"{start:{t('time_format')}} – {end:{t('time_format')}}"


def reset_timeline() -> None:
    st.session_state.timeline_resets = st.session_state.get("timeline_resets", 0) + 1


def show_timeline(results: list[ImageResult], label: Callable[[ImageResult], str]) -> list[ImageResult]:
    """Show the timeline of all images and return those in its visible period, all if nothing was zoomed or moved.
    Images without capture time are only part of the latter.

    The timeline ignores the threshold and the class filter. Otherwise it would change with them, and a new chart
    starts without zoom.
    """
    file, taken, klass, confidence = t("col_file"), t("col_taken"), t("col_class"), t("col_confidence")
    # the images with capture time, with the highest confidence per class
    timeline = []
    for r in results:
        if r.taken:
            when = r.taken.isoformat()  # see timeline_chart()
            timeline.append({file: label(r), taken: when, klass: t("all_images"), confidence: None})
            best: dict[str, float] = {}
            for d in r.detections:
                best[d.name] = max(best.get(d.name, 0), d.confidence)
            timeline += [{file: label(r), taken: when, klass: class_name(name), confidence: value}
                         for name, value in best.items()]
    timeline_df = pd.DataFrame(timeline, columns=[file, taken, klass, confidence])
    # the classes with the most images first, unlike the bar chart not depending on the threshold
    rows = [t("all_images"), *timeline_df.loc[timeline_df[confidence].notna(), klass].value_counts().index]
    readable = sum(1 for r in results if not r.error)
    timed = sum(1 for r in results if r.taken)

    period = None
    with st.expander(t("timeline"), expanded=True, key="timeline_expander"):
        if not timed:
            st.info(t("no_capture_times"))
        else:
            chart = timeline_chart(timeline_df, rows)
            # Another chart (new images, language, "Whole period") starts without zoom, so it gets a new key.
            # Otherwise the zoom of the old one would still filter the results, without being visible.
            version = hashlib.sha1(chart.to_json().encode()).hexdigest()[:16]
            event = st.altair_chart(chart, width="stretch", on_select="rerun",
                                    key=f"timeline_{version}_{st.session_state.get('timeline_resets', 0)}")
            period = selected_period(event.selection)
            st.caption(t("timeline_caption", readable, count=number(timed), total=number(readable),
                         minimum=f"{analysis.MIN_CONFIDENCE:.0%}"))
    if not period:
        return results
    start, end = period
    in_period = [r for r in results if r.taken and start <= r.taken <= end]
    # outside the expander, so that the filter shows also when it is collapsed
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(t("period", len(results), period=period_text(start, end), count=number(len(in_period)),
                      total=number(len(results))))
        st.button(t("whole_period"), on_click=reset_timeline, icon=":material/zoom_out_map:")
    return in_period


def common_folder(paths: list[str]) -> str:
    """The folders all paths start with, e.g. "A/" for "A/a.jpg" and "A/b.jpg", but "" for "A/a.jpg" and "B/a.jpg"."""
    common = []
    for parts in zip(*(path.split("/")[:-1] for path in paths)):
        if len(set(parts)) > 1:
            break
        common.append(parts[0])
    return "".join(part + "/" for part in common)


def show_results(results: list[ImageResult], threshold: float, selected_classes: list[str]) -> None:
    if not results:
        st.info(t("empty_hint"))
        return

    def visible(result: ImageResult) -> list[Detection]:
        """Detections that pass the filters, most confident first."""
        return sorted((d for d in result.detections
                       if d.confidence >= threshold and (not selected_classes or d.name in selected_classes)),
                      key=lambda d: -d.confidence)

    # the folders that all images share say nothing, e.g. "DCIM/100MEDIA/" when one SD card folder was uploaded
    prefix = common_folder([r.name for r in results])

    def label(result: ImageResult) -> str:
        return result.name.removeprefix(prefix)

    results = show_timeline(results, label)
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
    # all detections of the selected classes, also below the threshold, for the histogram
    confidences_df = pd.DataFrame(
        [{file: label(r), taken: r.taken, klass: class_name(d.name), confidence: d.confidence,
          t("col_status"): t("detected") if d.confidence >= threshold else t("not_detected")}
         for r in results for d in r.detections if not selected_classes or d.name in selected_classes],
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

# --- Sidebar: filters at the top, the rest at the bottom -------------------------------------------------------------
# The widgets have keys, so that they keep their values when their labels change with the language.
# rounded like CONFIDENCE_EDGES, the slider would give e.g. 0.30000000000000004
threshold = round(st.sidebar.slider(t("threshold"), analysis.MIN_CONFIDENCE, 1.0, 0.5, CONFIDENCE_STEP, format="%.2f",
                                    help=t("threshold_help"), key="threshold"), 2)
# The options are the class names of the model, so the selection stays when the language changes. They are sorted by
# display name with umlauts like their base letters ("Gänse" before "Greifvögel").
class_options = sorted(detector.class_names,
                       key=lambda name: unicodedata.normalize("NFKD", class_name(name).casefold()))
selected_classes = st.sidebar.multiselect(t("classes"), class_options, format_func=class_name,
                                          placeholder=t("all_classes"), key="classes")
st.sidebar.space("stretch")  # see PAGE_CSS
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
    st.rerun()
if col_quit.button(t("quit"), help=t("quit_help"), width="stretch"):
    st.dialog(t("quit_title"))(confirm_end)(uploading, bool(session.results))
language_selector()
st.sidebar.caption(t("model_info", classes=len(detector.class_names), darkhelp=detector.versions["DarkHelp"],
                     darknet=detector.versions["Darknet"]))


# --- Results: updated periodically while images are coming in -------------------------------------------------------
@st.fragment(run_every=REFRESH_SECONDS if uploading else None)
def results_view() -> None:
    show_results(sorted(session.results, key=lambda r: r.name), threshold, selected_classes)


results_view()
