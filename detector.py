"""Darknet/YOLO inference via the DarkHelp Python bindings."""

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np
from PIL import Image, ImageOps


def _preload_system_libxml2() -> None:
    """Make Darknet/DarkHelp use the system libxml2 when running from a conda env.

    The system OpenCV used by Darknet/DarkHelp depends (via GDAL and libspatialite) on the system libxml2. A conda
    Python finds the env's own libxml2 first, which may lack symbols such as the nanohttp API. Loading the system
    library first makes the dynamic linker reuse it. Without a libxml2 in the Python prefix (e.g. the system Python in
    a Docker image) this does nothing.
    """
    sonames = {p.name for p in Path(sys.base_prefix, "lib").glob("libxml2.so.*")
               if re.fullmatch(r"libxml2\.so\.\d+", p.name)}
    ldconfig = shutil.which("ldconfig") or "/sbin/ldconfig"
    if not sonames or not os.path.exists(ldconfig):
        return
    arch = {"x86_64": "x86-64", "aarch64": "AArch64"}.get(platform.machine(), platform.machine())
    # Darknet switches the process locale to "C", so be explicit about the output language and encoding
    cache = subprocess.run([ldconfig, "-p"], capture_output=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "LC_ALL": "C"}).stdout
    for line in cache.splitlines():
        # e.g. "	libxml2.so.16 (libc6,x86-64) => /lib/x86_64-linux-gnu/libxml2.so.16"
        match = re.match(r"\s*(\S+) \(([^)]*)\) => (.+)", line)
        if match and match[1] in sonames and arch in match[2]:
            ctypes.CDLL(match[3], ctypes.RTLD_GLOBAL)
            return


def _import_darkhelp():
    _preload_system_libxml2()
    import DarkHelp
    return DarkHelp


@dataclass(frozen=True)
class Detection:
    """One bounding box, in normalized YOLO coordinates (center x/y, width, height in 0..1)."""
    class_id: int
    name: str
    confidence: float
    cx: float
    cy: float
    w: float
    h: float

    def to_yolo(self) -> str:
        return f"{self.class_id} {self.cx:.6f} {self.cy:.6f} {self.w:.6f} {self.h:.6f}"

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Return (x0, y0, x1, y1) in pixel coordinates of an image with the given size."""
        return (round((self.cx - self.w / 2) * width), round((self.cy - self.h / 2) * height),
                round((self.cx + self.w / 2) * width), round((self.cy + self.h / 2) * height))


def read_image(file: Path | BinaryIO) -> np.ndarray:
    """Read an image as BGR array with EXIF orientation applied, i.e. like cv2.imread() used by Darknet and DarkMark.

    DarkHelp's PredictFN() could read the file itself, but on errors it keeps the results of the previous image.
    """
    with Image.open(file) as image:
        return to_bgr(ImageOps.exif_transpose(image))


def to_bgr(image: Image.Image) -> np.ndarray:
    """Convert a PIL image (already rotated according to its EXIF orientation) to the BGR array Darknet expects."""
    return np.ascontiguousarray(np.asarray(image.convert("RGB"))[..., ::-1])


def find_model_files(model_dir: Path) -> tuple[Path, Path, Path]:
    """Find the single .cfg, .names and .weights file in a model directory."""
    found = []
    for suffix in (".cfg", ".names", ".weights"):
        files = sorted(model_dir.glob(f"*{suffix}"))
        if len(files) != 1:
            raise FileNotFoundError(f"Expected exactly one {suffix} file in {model_dir}, found {len(files)}")
        found.append(files[0])
    return tuple(found)


class DarkHelpDetector:
    def __init__(self, cfg: Path, names: Path, weights: Path):
        self._dh = _import_darkhelp()
        # DarkHelp rewrites batch/subdivisions in the .cfg it loads, so give it a copy to keep the original intact.
        # Cleanup via finalize instead of __del__: at interpreter exit it runs while the modules are still intact.
        tmp_dir = tempfile.mkdtemp(prefix="darkhelp-")
        weakref.finalize(self, shutil.rmtree, tmp_dir, ignore_errors=True)
        cfg_copy = shutil.copy(cfg, tmp_dir)
        self._nn = self._dh.CreateDarkHelpNN(str(cfg_copy).encode(), str(names).encode(), str(weights).encode())
        if not self._nn:
            raise RuntimeError(f"DarkHelp could not load the network from {cfg}, {names}, {weights}")
        weakref.finalize(self, self._dh.DestroyDarkHelpNN, self._nn)
        self._dh.EnableNamesIncludePercentage(self._nn, False)
        # explicit encoding: Darknet has switched the process locale to "C" (ASCII) by now
        self.class_names = [line.strip() for line in names.read_text(encoding="utf-8").splitlines() if line.strip()]
        # DarkHelp's DarknetVersion() reports the version DarkHelp was compiled against, so ask libdarknet directly
        version_short = ctypes.CDLL("libdarknet.so").darknet_version_short
        version_short.restype = ctypes.c_char_p
        self.versions = {"DarkHelp": self._dh.DarkHelpVersion().decode(), "Darknet": version_short().decode()}
        # GetPredictionResults() returns a static buffer, so predictions must not run concurrently.
        self._lock = threading.Lock()

    def detect(self, image: np.ndarray, threshold: float = 0.25, tiles: bool = False) -> list[Detection]:
        """Detect objects in a BGR image (as returned by read_image() or cv2.imread())."""
        image = np.ascontiguousarray(image)
        with self._lock:
            self._dh.SetThreshold(self._nn, threshold)
            self._dh.EnableTiles(self._nn, tiles)
            self._dh.Predict(self._nn, image.shape[1], image.shape[0], image.tobytes(), image.nbytes)
            result = json.loads(self._dh.GetPredictionResults(self._nn).decode())
        return [self._to_detection(p) for p in result["file"][0]["prediction"]]

    def _to_detection(self, prediction: dict) -> Detection:
        # original_point is the normalized box center; clip the box to the image, since YOLO labels must lie within it
        cx, cy = prediction["original_point"]["x"], prediction["original_point"]["y"]
        w, h = prediction["original_size"]["width"], prediction["original_size"]["height"]
        x0, x1 = max(cx - w / 2, 0.0), min(cx + w / 2, 1.0)
        y0, y1 = max(cy - h / 2, 0.0), min(cy + h / 2, 1.0)
        class_id = prediction["best_class"]
        return Detection(class_id=class_id, name=self.class_names[class_id],
                         # rounded, so that comparisons with thresholds give the same result wherever they are done
                         confidence=round(prediction["best_probability"], 4),
                         cx=(x0 + x1) / 2, cy=(y0 + y1) / 2, w=x1 - x0, h=y1 - y0)
