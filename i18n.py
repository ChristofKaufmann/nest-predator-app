"""Texts of the user interface in German and English.

The language follows the browser and can be switched in the sidebar. The choice is kept in the URL (?lang=en), so it
survives reloading the page. Texts with a count are pairs of singular and plural form.
"""

import streamlit as st

LANGUAGES = {"de": "Deutsch", "en": "English"}
DEFAULT_LANGUAGE = "en"  # for browsers in any other language
# Month and day names in the time axes of charts (d3 time format locale). Charts use English without one.
TIME_LOCALES = {
    "de": {
        "dateTime": "%A, %e. %B %Y, %X",
        "date": "%d.%m.%Y",
        "time": "%H:%M:%S",
        "periods": ["AM", "PM"],
        "days": ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"],
        "shortDays": ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"],
        "months": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                   "November", "Dezember"],
        "shortMonths": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
    },
}

TEXTS = {
    "de": {
        "title": "Prädatoren-Erkennung",
        "language": "Sprache · Language",
        "loading_model": "Lade Modell …",
        "model_error": "Das Modell konnte nicht geladen werden: {error}",
        "threshold": "Konfidenzschwelle",
        "all_classes": "Alle Klassen",
        "start_over": "Neu beginnen",
        "start_over_help": "Alle Ergebnisse verwerfen, z. B. für eine neue Serie von Bildern.",
        "quit": "Beenden",
        "quit_help": "Das Programm beenden. Danach kann das Browserfenster geschlossen werden.",
        "model_info": "Modell mit {classes} Klassen · DarkHelp {darkhelp} · Darknet {darknet}",
        "quit_title": "Programm beenden?",
        "quit_uploading": "Es werden gerade noch Bilder ausgewertet.",
        "quit_results": "Die Ergebnisse gehen dabei verloren. Wenn du sie behalten möchtest, klicke vorher auf "
                        "„{export}“.",
        "cancel": "Abbrechen",
        "ended_title": "Prädatoren-Erkennung wurde beendet",
        "ended_text": "Du kannst dieses Fenster jetzt schließen. Zum Weiterarbeiten das Programm neu starten.",
        "empty_hint": "Ziehe einzelne Bilder, ganze Ordner oder den Inhalt einer SD-Karte in das Feld oben. Die "
                      "Auswertung startet automatisch.",
        "metric_images": "Bilder ausgewertet",
        "metric_with_detection": "Bilder mit Erkennung",
        "metric_detections": "Erkennungen",
        "metric_unreadable": "Nicht lesbar",
        "metric_duration": "Mittlere Verarbeitungszeit",
        "metric_duration_help": "Pro Bild für Einlesen, Erkennung und Vorschau, ohne die Übertragung.",
        "export": "Ergebnisse herunterladen",
        "export_help": "Als Excel-Datei: die Erkennungen, eine Übersicht pro Klasse und alle Bilder. "
                       "Die unter „Filter“ eingestellte Konfidenzschwelle, die angehakten Klassen und der "
                       "sichtbare Bereich gelten auch hier.",
        "export_file": "erkennungen.xlsx",
        "sheet_detections": "Erkennungen",
        "sheet_classes": "Pro Klasse",
        "sheet_images": "Bilder",
        "tab_gallery": "Galerie",
        "filters": "Filter",
        "help": "Hilfe",
        "tab_statistics": "Statistik",
        "only_hits": "Nur Bilder mit Erkennungen",
        "no_images": "Keine Bilder für die aktuelle Auswahl.",
        "more_images": "Weitere Bilder anzeigen (noch {count})",
        "unreadable_title": "Nicht lesbare Dateien",
        "error_unreadable": "Kein lesbares Bild",
        "classes_title": "Bilder pro Klasse",
        "without_detection_count": ["Ohne Erkennung: **{count} von {total} Bild**",
                                    "Ohne Erkennung: **{count} von {total} Bildern**"],
        "classes_caption": "Bilder: Anzahl der Bilder, auf denen die Klasse erkannt wurde. Erkennungen: einzelne "
                           "Erkennungen, ein Bild mit zwei Füchsen zählt doppelt. Beides und „ohne Erkennung“ "
                           "richten sich nach Konfidenzschwelle und Klassenauswahl.",
        "confidence_title": "Konfidenz der Erkennungen",
        "confidence_caption": "Alle Erkennungen ab {minimum} Konfidenz. Als erkannt zählen sie erst ab der Schwelle, "
                              "eine Konfidenz genau auf der Schwelle zählt mit.",
        "detected": "erkannt",
        "not_detected": "nicht erkannt",
        "threshold_label": "Schwelle {value}",
        "from": "von",
        "to": "bis",
        "hour_title": "Tageszeit der Bilder",
        "hour_axis": "Uhrzeit (Stunde)",
        "with_detection": "mit Erkennung",
        "without_detection": "ohne Erkennung",
        "hour_caption": ["Aus den Aufnahmezeiten in den Bilddateien ({count} von {total} Bild hat eine). „Mit "
                         "Erkennung“ richtet sich nach Konfidenzschwelle und Klassenauswahl.",
                         "Aus den Aufnahmezeiten in den Bilddateien ({count} von {total} Bildern haben eine). „Mit "
                         "Erkennung“ richtet sich nach Konfidenzschwelle und Klassenauswahl."],
        "all_images": "Alle",
        "time_format": "%d.%m.%Y %H:%M:%S",
        "day_format": "%d.%m.%Y",
        "axis_day": "%-d. %b",
        "period": ["**Zeitraum {period}:** {count} von {total} Bild",
                   "**Zeitraum {period}:** {count} von {total} Bildern"],
        "whole_period": "Ganzer Zeitraum",
        "positions": ["**Bilder {positions}:** {count} von {total} Bild",
                      "**Bilder {positions}:** {count} von {total} Bildern"],
        "show_all": "Alles zeigen",
        "ticked_classes": "**Klassen:** {classes}",
        "no_classes": "keine",
        "timeline_axis": "Achse",
        "axis_time": "Aufnahmezeit",
        "axis_order": "Reihenfolge",
        "timeline_time": ["Jeder Strich ist ein Bild zu seiner Aufnahmezeit ({count} von {total} Bild hat eine).",
                          "Jeder Strich ist ein Bild zu seiner Aufnahmezeit ({count} von {total} Bildern haben "
                          "eine)."],
        "untimed": ["Das Bild ohne Aufnahmezeit ist nur unter „{order}“ zu sehen.",
                    "Die {count} Bilder ohne Aufnahmezeit sind nur unter „{order}“ zu sehen."],
        "timeline_order": "Jeder Strich ist ein Bild, in derselben Reihenfolge wie in der Galerie (nach Ordner und "
                          "Dateiname).",
        "timeline_caption": "In der Zeile „{all}“ wird ein Strich kräftiger, je mehr Bilder dicht "
                            "beieinanderliegen. Die Farbe in den Klassen zeigt die höchste Konfidenz der Klasse im "
                            "Bild, alle Erkennungen ab {minimum}: blau ab der Konfidenzschwelle, orange darunter. "
                            "Galerie, Statistik und Excel-Datei zeigen nur die Erkennungen ab der Schwelle, die "
                            "angehakten Klassen und den sichtbaren Bereich. Ein Klick auf die Farbskala oder Ziehen "
                            "darauf setzt die Schwelle. Ein Klick auf eine Klasse hakt sie an oder ab, bei „{all}“ "
                            "alle Klassen. Ziehen in der Zeitachse verschiebt den Bereich, Strg + Mausrad "
                            "oder zwei Finger auf dem Touchpad zoomen, ein Doppelklick zeigt wieder alles.",
        "col_file": "Datei",
        "col_taken": "Aufnahmezeit",
        "col_position": "Bild Nr.",
        "col_class": "Klasse",
        "col_confidence": "Konfidenz",
        "col_max_confidence": "Höchste Konfidenz",
        "col_status": "Status",
        "col_images": "Bilder",
        "col_detections": "Erkennungen",
        "col_detected_classes": "Erkannte Klassen",
        "col_duration": "Verarbeitungszeit (ms)",
        "col_error": "Fehler",
        "col_hour": "Stunde",
        "col_detection": "Erkennung",
        "upload": {
            "locale": "de-DE",
            "title": "Bilder oder Ordner hierher ziehen",
            "titleCompact": "Weitere Bilder oder Ordner hierher ziehen",
            "hint": "Zum Beispiel den ganzen Inhalt der SD-Karte. Videos und andere Dateien werden übersprungen.",
            "pickFiles": "Bilder auswählen",
            "pickFolder": "Ordner auswählen",
            "cancel": "Abbrechen",
            "dismiss": "Hinweise ausblenden",
            "searching": "Dateien werden gesucht …",
            "progress": ["{done} von {total} Bild ausgewertet", "{done} von {total} Bildern ausgewertet"],
            "remainingSeconds": " · noch ca. {count} s",
            "remainingMinutes": " · noch ca. {count} min",
            "cancelled": ["Abgebrochen nach {done} von {total} Bild.", "Abgebrochen nach {done} von {total} Bildern."],
            "noNew": "Keine neuen Bilder.",
            "done": ["Fertig: {count} Bild ausgewertet.", "Fertig: {count} Bilder ausgewertet."],
            "skipped": ["{count} andere Datei (z. B. Videos) übersprungen",
                        "{count} andere Dateien (z. B. Videos) übersprungen"],
            "duplicates": ["{count} bereits ausgewertetes Bild übersprungen",
                           "{count} bereits ausgewertete Bilder übersprungen"],
            "unreadable": ["{count} Datei ist nicht lesbar:", "{count} Dateien sind nicht lesbar:"],
            "failed": ["{count} Datei konnte nicht hochgeladen werden:",
                       "{count} Dateien konnten nicht hochgeladen werden:"],
            "folderError": "Ordner konnte nicht gelesen werden: {error}",
            "errors": {
                "session_expired": "Sitzung abgelaufen, bitte die Seite neu laden.",
                "file_too_large": "Datei zu groß",
                "bad_request": "Ungültige Anfrage",
                "unreadable": "Kein lesbares Bild",
            },
        },
    },
    "en": {
        "title": "Predator Detection",
        "language": "Sprache · Language",
        "loading_model": "Loading model …",
        "model_error": "The model could not be loaded: {error}",
        "threshold": "Confidence threshold",
        "all_classes": "All classes",
        "start_over": "Start over",
        "start_over_help": "Discard all results, e.g. for a new series of images.",
        "quit": "Quit",
        "quit_help": "Quit the program. Afterwards the browser window can be closed.",
        "model_info": "Model with {classes} classes · DarkHelp {darkhelp} · Darknet {darknet}",
        "quit_title": "Quit the program?",
        "quit_uploading": "Images are still being analysed.",
        "quit_results": "The results will be lost. If you want to keep them, click “{export}” first.",
        "cancel": "Cancel",
        "ended_title": "Predator Detection has been closed",
        "ended_text": "You can close this window now. To continue working, start the program again.",
        "empty_hint": "Drag single images, whole folders or the content of an SD card into the field above. The "
                      "analysis starts automatically.",
        "metric_images": "Images analysed",
        "metric_with_detection": "Images with detection",
        "metric_detections": "Detections",
        "metric_unreadable": "Unreadable",
        "metric_duration": "Mean processing time",
        "metric_duration_help": "Per image for reading, detection and preview, without the upload.",
        "export": "Download results",
        "export_help": "As an Excel file: the detections, an overview per class and all images. The confidence "
                       "threshold, the ticked classes and the visible part set under “Filters” apply here too.",
        "export_file": "detections.xlsx",
        "sheet_detections": "Detections",
        "sheet_classes": "Per class",
        "sheet_images": "Images",
        "tab_gallery": "Gallery",
        "filters": "Filters",
        "help": "Help",
        "tab_statistics": "Statistics",
        "only_hits": "Only images with detections",
        "no_images": "No images for the current selection.",
        "more_images": "Show more images ({count} left)",
        "unreadable_title": "Unreadable files",
        "error_unreadable": "Not a readable image",
        "classes_title": "Images per class",
        "without_detection_count": ["Without detection: **{count} of {total} image**",
                                    "Without detection: **{count} of {total} images**"],
        "classes_caption": "Images: number of images in which the class was detected. Detections: single "
                           "detections, an image with two foxes counts twice. Both and “without detection” depend on "
                           "the confidence threshold and the selected classes.",
        "confidence_title": "Confidence of the detections",
        "confidence_caption": "All detections from {minimum} confidence on. They only count as detected from the "
                              "threshold on, a confidence exactly at the threshold counts.",
        "detected": "detected",
        "not_detected": "not detected",
        "threshold_label": "Threshold {value}",
        "from": "from",
        "to": "to",
        "hour_title": "Time of day",
        "hour_axis": "Time of day (hour)",
        "with_detection": "with detection",
        "without_detection": "without detection",
        "hour_caption": ["From the capture times in the image files ({count} of {total} image has one). “With "
                         "detection” depends on the confidence threshold and the selected classes.",
                         "From the capture times in the image files ({count} of {total} images have one). “With "
                         "detection” depends on the confidence threshold and the selected classes."],
        "all_images": "All",
        "time_format": "%Y-%m-%d %H:%M:%S",
        "day_format": "%Y-%m-%d",
        "axis_day": "%-d %b",
        "period": ["**Period {period}:** {count} of {total} image", "**Period {period}:** {count} of {total} images"],
        "whole_period": "Whole period",
        "positions": ["**Images {positions}:** {count} of {total} image",
                      "**Images {positions}:** {count} of {total} images"],
        "show_all": "Show all",
        "ticked_classes": "**Classes:** {classes}",
        "no_classes": "none",
        "timeline_axis": "Axis",
        "axis_time": "Capture time",
        "axis_order": "Order",
        "timeline_time": ["Each line is an image at its capture time ({count} of {total} image has one).",
                          "Each line is an image at its capture time ({count} of {total} images have one)."],
        "untimed": ["The image without capture time is only shown under “{order}”.",
                    "The {count} images without capture time are only shown under “{order}”."],
        "timeline_order": "Each line is an image, in the same order as in the gallery (by folder and file name).",
        "timeline_caption": "In the row “{all}”, a line gets stronger the more images lie close together. The "
                            "colour in the classes shows the highest confidence of the class in the image, all "
                            "detections from {minimum} on: blue from the confidence threshold on, orange below. "
                            "Gallery, statistics and Excel file only show the detections from the threshold on, the "
                            "ticked classes and the visible part. A click on the colour scale or dragging on it sets "
                            "the threshold. A click on a class ticks or unticks it, on “{all}” all classes. "
                            "Dragging in the timeline moves the visible part, Ctrl + mouse wheel or two fingers on "
                            "the touchpad zoom, a double click shows everything again.",
        "col_file": "File",
        "col_taken": "Taken",
        "col_position": "Image no.",
        "col_class": "Class",
        "col_confidence": "Confidence",
        "col_max_confidence": "Highest confidence",
        "col_status": "Status",
        "col_images": "Images",
        "col_detections": "Detections",
        "col_detected_classes": "Detected classes",
        "col_duration": "Processing time (ms)",
        "col_error": "Error",
        "col_hour": "Hour",
        "col_detection": "Detection",
        "upload": {
            "locale": "en-GB",
            "title": "Drag images or folders here",
            "titleCompact": "Drag more images or folders here",
            "hint": "For example the whole content of the SD card. Videos and other files are skipped.",
            "pickFiles": "Select images",
            "pickFolder": "Select folder",
            "cancel": "Cancel",
            "dismiss": "Hide notes",
            "searching": "Looking for files …",
            "progress": ["{done} of {total} image analysed", "{done} of {total} images analysed"],
            "remainingSeconds": " · about {count} s left",
            "remainingMinutes": " · about {count} min left",
            "cancelled": ["Cancelled after {done} of {total} image.", "Cancelled after {done} of {total} images."],
            "noNew": "No new images.",
            "done": ["Done: {count} image analysed.", "Done: {count} images analysed."],
            "skipped": ["{count} other file (e.g. videos) skipped", "{count} other files (e.g. videos) skipped"],
            "duplicates": ["{count} already analysed image skipped", "{count} already analysed images skipped"],
            "unreadable": ["{count} file is not readable:", "{count} files are not readable:"],
            "failed": ["{count} file could not be uploaded:", "{count} files could not be uploaded:"],
            "folderError": "The folder could not be read: {error}",
            "errors": {
                "session_expired": "Session expired, please reload the page.",
                "file_too_large": "File too large",
                "bad_request": "Invalid request",
                "unreadable": "Not a readable image",
            },
        },
    },
}


def init_language() -> None:
    """Choose the language once per session: from the URL, else from the browser, else the default."""
    if "language" not in st.session_state:
        requested = st.query_params.get("lang") or (st.context.locale or "")[:2]
        st.session_state.language = requested if requested in LANGUAGES else DEFAULT_LANGUAGE


def language_selector() -> None:
    st.sidebar.segmented_control(TEXTS[st.session_state.language]["language"], list(LANGUAGES),
                                 format_func=LANGUAGES.get, key="language", required=True, width="stretch")
    st.query_params["lang"] = st.session_state.language


def t(key: str, n: int | None = None, **values) -> str:
    """The text in the current language. For texts with singular and plural, n is the count that decides."""
    text = TEXTS[st.session_state.language][key]
    if isinstance(text, list):
        text = text[0 if n == 1 else 1]
    return text.format(**values)


def upload_texts() -> dict:
    return TEXTS[st.session_state.language]["upload"]


def time_locale() -> dict | None:
    """Month and day names for charts in the current language, None for English."""
    return TIME_LOCALES.get(st.session_state.language)


def number(value: int) -> str:
    """A count with thousands separator."""
    return f"{value:,}".replace(",", "." if st.session_state.language == "de" else ",")
