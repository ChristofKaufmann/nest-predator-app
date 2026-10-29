"""Streamlit UI that classifies uploaded camera trap images with a Darknet/YOLO model.

Start it with `streamlit run server.py`, which adds the route that receives the uploaded images.
"""

import colorsys
import functools
import io
import json
import unicodedata
from typing import NamedTuple

import altair as alt
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

import analysis
from analysis import ImageResult
from detector import Detection
from i18n import init_language, language_selector, number, t, upload_texts
from shutdown import end_program
from upload_field import upload_field

GALLERY_STEP = 24
GALLERY_COLUMNS = 3
REFRESH_SECONDS = 2  # how often the results are updated during an upload
IMAGE_ID = "_image"  # internal column to count images, never shown
# Bin edges of the confidence histogram. The threshold slider uses the same 5 % steps (rounded the same way), so a bin
# never holds detections from both sides of the threshold.
CONFIDENCE_STEP = 0.05
CONFIDENCE_EDGES = [round(analysis.MIN_CONFIDENCE + i * CONFIDENCE_STEP, 2)
                    for i in range(round((1 - analysis.MIN_CONFIDENCE) / CONFIDENCE_STEP) + 1)]


class ChartColors(NamedTuple):
    detected: str      # categorical slot 1
    not_detected: str  # categorical slot 2
    text: str          # secondary text


CHART_COLORS = {"light": ChartColors("#2a78d6", "#eb6834", "#52514e"),
                "dark": ChartColors("#3987e5", "#d95926", "#c3c2b7")}
MUTED_COLOR = "#898781"  # readable on light and dark background, for annotations like the threshold


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


def bar_chart(df: pd.DataFrame, colors: ChartColors) -> alt.LayerChart:
    """Horizontal bars of images per class, largest first, with the value at the tip."""
    images, klass = t("col_images"), t("col_class")
    base = alt.Chart(df).encode(
        y=alt.Y(field=klass, type="nominal", sort="-x", title=None),
        x=alt.X(field=images, type="quantitative", title=images, axis=alt.Axis(tickMinStep=1)),
        tooltip=[alt.Tooltip(field=klass, type="nominal"), alt.Tooltip(field=images, type="quantitative"),
                 alt.Tooltip(field=t("col_detections"), type="quantitative")])
    bars = base.mark_bar(color=colors.detected, size=18, cornerRadiusEnd=4)
    labels = base.mark_text(align="left", dx=4, color=colors.text).encode(
        text=alt.Text(field=images, type="quantitative"))
    return (bars + labels).properties(height=alt.Step(28))


def confidence_histogram(df: pd.DataFrame, threshold: float, colors: ChartColors) -> alt.LayerChart:
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
                        scale=alt.Scale(domain=[t("detected"), t("not_detected")],
                                        range=[colors.detected, colors.not_detected])),
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


def hour_chart(df: pd.DataFrame, colors: ChartColors) -> alt.LayerChart:
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
                        scale=alt.Scale(domain=[with_detection, without_detection],
                                        range=[colors.detected, colors.not_detected])),
        tooltip=[alt.Tooltip(field=hour, type="ordinal"), alt.Tooltip(field=detection, type="nominal"),
                 alt.Tooltip(field=images, type="quantitative")])
    layers = [base.mark_bar(size=16, cornerRadiusTopLeft=radius, cornerRadiusTopRight=radius, y2Offset=offset)
              .transform_filter(f"(datum.top == datum.total) == {top} && (datum.bottom > 0) == {stacked}")
              for top, radius in (("true", 4), ("false", 0)) for stacked, offset in (("true", -2), ("false", 0))]
    return alt.layer(*layers)


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

    filtered = [(i, r, visible(r)) for i, r in enumerate(results)]
    errors = [r for r in results if r.error]
    # the folders that all images share say nothing, e.g. "DCIM/100MEDIA/" when one SD card folder was uploaded
    prefix = common_folder([r.name for r in results])

    def label(result: ImageResult) -> str:
        return result.name.removeprefix(prefix)

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

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(t("metric_images"), len(results))
    m2.metric(t("metric_with_detection"), detections_df[IMAGE_ID].nunique())
    m3.metric(t("metric_detections"), len(detections_df))
    m4.metric(t("metric_unreadable"), len(errors))
    m5.metric(t("metric_duration"), f"{1000 * sum(durations) / len(durations):.0f} ms" if durations else "–",
              help=t("metric_duration_help"))

    # for the export button in the sidebar, which can't be part of this fragment
    st.session_state.export.update(
        sheets={t("sheet_detections"): detections_df[[file, taken, klass, confidence]],
                t("sheet_classes"): classes_df, t("sheet_images"): images_df},
        percent_columns={confidence, max_confidence})

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
        if errors:
            st.subheader(t("unreadable_title"))
            st.dataframe(pd.DataFrame({file: [label(r) for r in errors],
                                       t("col_error"): [error_text(r) for r in errors]}), hide_index=True)
        colors = CHART_COLORS.get(st.context.theme.type or "light", CHART_COLORS["light"])
        readable = [(r, dets) for _, r, dets in filtered if not r.error]
        if readable:
            st.subheader(t("classes_title"))
            # as text, a bar would dwarf the classes as most images usually show nothing
            without_detection = sum(1 for _, dets in readable if not dets)
            st.markdown(t("without_detection_count", len(readable), count=number(without_detection),
                          total=number(len(readable))))
            if not classes_df.empty:
                st.altair_chart(bar_chart(classes_df, colors), width="stretch")
            st.caption(t("classes_caption"))
        if not confidences_df.empty:
            st.subheader(t("confidence_title"))
            st.altair_chart(confidence_histogram(confidences_df, threshold, colors), width="stretch")
            st.caption(t("confidence_caption", minimum=f"{analysis.MIN_CONFIDENCE:.0%}"))

        timed = pd.DataFrame([(r.taken.hour, t("with_detection") if dets else t("without_detection"))
                              for r, dets in readable if r.taken], columns=[t("col_hour"), t("col_detection")])
        if not timed.empty:
            st.subheader(t("hour_title"))
            hours = timed.value_counts().reset_index(name=images)
            st.altair_chart(hour_chart(hours, colors), width="stretch")
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
uploading = upload_field(session.api_url, upload_texts())

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
# The sidebar's content is only as high as itself, which leaves a stretch space no room to grow. These rules let it fill
# the height (and take back most of the large padding below), so the rest sits at the bottom. If a Streamlit update
# changes the structure, the rest just follows the filters.
st.html("""<style>
[data-testid="stSidebarContent"] { display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"], [data-testid="stSidebarUserContent"] > div {
    flex-grow: 1; display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"] { padding-bottom: 1.5rem; }
</style>""")
st.sidebar.space("stretch")
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
