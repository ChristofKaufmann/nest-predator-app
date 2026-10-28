"""Image analysis shared by the Streamlit script and the upload route: model, results and per-session storage."""

import functools
import io
import os
import shutil
import tempfile
import threading
import time
import tomllib
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from PIL import ExifTags, Image, ImageOps
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from detector import DarkHelpDetector, Detection, find_model_files, to_bgr

MODEL_DIR = Path(os.environ.get("MODEL_DIR", Path(__file__).parent / "model"))
# Darknet reports everything from this confidence on. The threshold in the app only filters these detections, so the
# images are not needed anymore after the analysis.
MIN_CONFIDENCE = 0.10
USE_TILES = False  # only for models trained on image tiles (e.g. DarkMark tiling)
PREVIEW_WIDTH = 1024
MAX_FILE_SIZE = 200 * 2**20
API_ROUTE = "/api/{token}/"  # + "upload" for images, + "paths" for further paths of known images
UNREADABLE = "unreadable"  # error of an image that isn't one; other errors are the decoder's message
# The routes answer errors with these codes, the upload field shows them in the user's language.
SESSION_EXPIRED, FILE_TOO_LARGE, BAD_REQUEST = "session_expired", "file_too_large", "bad_request"

_detector: DarkHelpDetector | None = None
_detector_lock = threading.Lock()
# Images arrive in parallel, but the model processes one at a time. Waiting for it is not part of the processing time.
_inference_lock = threading.Lock()
# The previews of all sessions of this server process. The server removes it when it shuts down, see server.py.
_preview_root = Path(tempfile.mkdtemp(prefix="previews-"))


def remove_previews() -> None:
    shutil.rmtree(_preview_root, ignore_errors=True)


@dataclass
class ImageResult:
    name: str                         # path relative to the uploaded folder, or file name
    preview: Path | None = None
    taken: datetime | None = None
    detections: list[Detection] = field(default_factory=list)
    error: str | None = None
    duration: float | None = None     # seconds for decoding, detection and preview, without waiting for the model


def get_detector() -> DarkHelpDetector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = DarkHelpDetector(*find_model_files(MODEL_DIR))
        return _detector


@functools.cache
def get_display_names() -> dict[str, dict[str, str]]:
    """Display names of the classes per language, e.g. {"Fuchs": {"de": "Fuchs", "en": "Red fox"}}.

    They come from an optional TOML file with the name of the model's .names file (species.toml for species.names).
    Classes and languages missing there are shown with their name from the .names file.
    """
    path = find_model_files(MODEL_DIR)[1].with_suffix(".toml")
    if not path.exists():
        return {}
    with path.open("rb") as f:
        try:
            names = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"{path.name}: {e}") from e
    for name, translations in names.items():
        if name not in get_detector().class_names:
            raise ValueError(f"{path.name}: {name!r} is not a class of the model")
        if not isinstance(translations, dict) or not all(isinstance(v, str) for v in translations.values()):
            raise ValueError(f'{path.name}: expected {name} = {{ de = "...", en = "..." }}')
    return names


def taken_at(image: Image.Image) -> datetime | None:
    """Capture time from the EXIF data, if the camera wrote one."""
    exif = image.getexif()
    value = exif.get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
    try:
        return datetime.strptime(str(value).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def analyse_image(name: str, data: bytes, preview_path: Path) -> ImageResult:
    start = time.perf_counter()
    try:
        with Image.open(io.BytesIO(data)) as image:
            taken = taken_at(image)
            image = ImageOps.exif_transpose(image).convert("RGB")
    except Image.UnidentifiedImageError:  # its message would show the internal file object
        return ImageResult(name, error=UNREADABLE)
    except (OSError, Image.DecompressionBombError) as e:  # truncated files raise OSError
        return ImageResult(name, error=str(e))
    bgr = to_bgr(image)
    queued = time.perf_counter()
    with _inference_lock:
        waited = time.perf_counter() - queued
        detections = get_detector().detect(bgr, MIN_CONFIDENCE, USE_TILES)
    image.thumbnail((PREVIEW_WIDTH, PREVIEW_WIDTH))
    image.save(preview_path, quality=85)
    return ImageResult(name, preview_path, taken, detections, duration=time.perf_counter() - start - waited)


class Session:
    """Results and preview images of one browser session.

    The upload route finds the session by its token. The registry only holds weak references, so the session and its
    preview directory go away together with Streamlit's session state.
    """

    def __init__(self):
        self.token = uuid.uuid4().hex
        self.results: list[ImageResult] = []
        self._paths: dict[str, str] = {}  # most complete path per image key
        self._results: dict[str, ImageResult] = {}  # per image key, once analysed
        self._lock = threading.Lock()
        self._dir = Path(tempfile.mkdtemp(prefix="session-", dir=_preview_root))
        weakref.finalize(self, shutil.rmtree, self._dir, ignore_errors=True)
        sessions[self.token] = self

    @property
    def api_url(self) -> str:
        return API_ROUTE.removeprefix("/").format(token=self.token)

    def analyse(self, name: str, key: str, data: bytes) -> ImageResult | None:
        """Analyse an image and keep the result. Returns None if an image with the same key was already analysed.

        The upload field uses file name (without folder), size and modification time as key, so an image counts as
        the same whether it was uploaded on its own or as part of a folder.
        """
        with self._lock:
            if key in self._paths:
                self._update_path(key, name)
                return None
            self._paths[key] = name
            preview_path = self._dir / f"{len(self._paths)}.jpg"
        result = analyse_image(name, data, preview_path)
        with self._lock:
            result.name = self._paths[key]  # a more complete path may have come in meanwhile
            self._results[key] = result
        self.results.append(result)
        return result

    def add_path(self, key: str, path: str) -> None:
        """Another path of an image that was already uploaded, see _update_path()."""
        with self._lock:
            if key in self._paths:
                self._update_path(key, path)

    def _update_path(self, key: str, path: str) -> None:
        """Keep the most complete path of an image. Browsers only tell the path within an uploaded folder, so an image
        uploaded on its own and later with its folder is shown with the folder ("a.jpg", then "A/a.jpg")."""
        if path.endswith("/" + self._paths[key]):
            self._paths[key] = path
            if key in self._results:
                self._results[key].name = path


sessions: weakref.WeakValueDictionary[str, Session] = weakref.WeakValueDictionary()


async def upload(request: Request) -> JSONResponse:
    """Receive one image per request (raw body, path and key in the X-File-Path and X-File-Key headers) and analyse
    it right away.

    The analysis runs in a worker thread so that the event loop, which also serves the Streamlit app, stays free.
    """
    session = sessions.get(request.path_params["token"])
    if session is None:
        return JSONResponse({"error": SESSION_EXPIRED}, status_code=404)
    if int(request.headers.get("content-length", 0)) > MAX_FILE_SIZE:
        return JSONResponse({"error": FILE_TOO_LARGE}, status_code=413)
    name = unquote(request.headers.get("x-file-path", "unnamed"))
    key = unquote(request.headers.get("x-file-key", name))
    result = await run_in_threadpool(session.analyse, name, key, await request.body())
    if result is None:
        return JSONResponse({"duplicate": True})
    return JSONResponse({"detections": len(result.detections), "error": result.error})


async def paths(request: Request) -> JSONResponse:
    """Receive further paths of already uploaded images, as JSON list of {"key": ..., "path": ...}."""
    session = sessions.get(request.path_params["token"])
    if session is None:
        return JSONResponse({"error": SESSION_EXPIRED}, status_code=404)
    try:
        for item in await request.json():
            session.add_path(str(item["key"]), str(item["path"]))
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"error": BAD_REQUEST}, status_code=400)
    return JSONResponse({})


routes = [Route(API_ROUTE + "upload", upload, methods=["POST"]), Route(API_ROUTE + "paths", paths, methods=["POST"])]
