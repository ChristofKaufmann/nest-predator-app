# Development

Technical details of Predator Detection. Usage and starting the program are described in the [README.md](README.md).

## Structure

| File | Content |
| --- | --- |
| `server.py` | Entry point (`streamlit run server.py`). Starts the Streamlit app `app.py` as `st.App` together with the routes `/api/<token>/upload` (receives the images one by one) and `/api/<token>/paths` (further paths of images that were already analysed). Removes the previews when shutting down. |
| `app.py` | The user interface: timeline (its confidence scale, class boxes and zoom filter the results), gallery, statistics, Excel export. During an upload a fragment updates the results every 2 seconds. |
| `i18n.py` | All texts of the user interface in German and English, and the language selection. |
| `analysis.py` | Model, analysis of a single image, results and previews per browser session, and the two routes. |
| `detector.py` | Connection to Darknet via DarkHelp. |
| `upload_field/` | The upload field as Streamlit component (`st.components.v2`, HTML/CSS/JavaScript). |
| `shutdown.py` | "Quit": shows a final page and stops the server afterwards. |
| `LICENSE` | BSD 3-Clause License of this program. |
| `DarkHelp.py` | Unmodified copy of the Python bindings from `DarkHelp/src-python/` (MIT license, see `LICENSE-DarkHelp.txt`), for running without Docker. The base image brings its own copy. |
| `model/` | The model, not part of the repository (see `model/README.md`): exactly one `.cfg`, `.names` and `.weights`, and optionally the display names of the classes (`species.toml`, see below). Another folder can be set with the environment variable `MODEL_DIR`. |
| `.streamlit/config.toml` | Hides the deploy button and the developer menu, switches off the file watcher and sets the chart colours for light and dark mode. The charts refer to these colours instead of fixed ones, so they follow a change of the theme right away. |
| `environment.yml`, `requirements.txt` | Python packages for conda and pip. |
| `Dockerfile.base` | The base image: builds OpenCV, Darknet and DarkHelp and adds Python with the packages from `requirements.txt`. |
| `Dockerfile` | The app image: app and model on top of the base image. |

## Installing Darknet and DarkHelp

Without Docker, Darknet ([CCodeRun/darknet](https://codeberg.org/CCodeRun/darknet), mirrored as [hank-ai/darknet](https://github.com/hank-ai/darknet)) and [DarkHelp](https://github.com/stephanecharette/DarkHelp) have to be installed system-wide (`libdarknet.so`, `/usr/lib/libdarkhelp.so`), see their instructions for [Darknet](https://github.com/hank-ai/darknet#linux-cmake-method) and [DarkHelp](https://github.com/stephanecharette/DarkHelp#building-darkhelp-linux). Without GPU, Darknet is faster with OpenBLAS, which the Darknet instructions also describe.

- **No conda environment while building:** No conda environment may be active during `cmake` (`conda deactivate`). Otherwise CMake finds `protoc` and OpenCV of the environment instead of the system ones, and the build fails, e.g. on `google/protobuf/runtime_version.h`. If that happened: run `cmake -U OpenCV_DIR -U 'Protobuf_*' ..` without an active environment and delete the generated `src-onnx/onnx.proto3.pb.*`.
- **Matching `DarkHelp.py`:** `DarkHelp.py` in this repository is from the DarkHelp commit that the Docker image uses (`DARKHELP_REF` in `Dockerfile.base`). It has to match the installed DarkHelp version. With another version, copy `src-python/DarkHelp.py` from its checkout.
- **Model version:** The current model was trained with Darknet v5.1-104. The versions used in the Docker image are set in `Dockerfile.base` (`DARKNET_REF`, `DARKHELP_REF`).

## Developing

- **Start** with `streamlit run server.py`. `streamlit run app.py` starts only the user interface without the routes, so uploaded images don't arrive.
- **Restart after changes:** Streamlit's file watcher is switched off, because reloading the modules would separate the app from the routes. The app would get a new `analysis` module, while the routes would keep the old one with the old list of sessions.
- **Tiling:** If a model was trained on image tiles (e.g. DarkMark tiling), set `USE_TILES = True` in `analysis.py`.
- **Texts:** All texts of the user interface are in `i18n.py`, as pairs of singular and plural form where a count is involved. The upload field gets its texts from there via the component's data. The routes answer errors with codes (`analysis.SESSION_EXPIRED` etc.), which the upload field translates. Widgets have keys, so that they keep their values when their labels change with the language.
- **Class names:** The names in `species.names` are the model's identifiers (German, without umlauts). The display names per language are in a TOML file with the same name, `species.toml`, one line per class: `Fuchs = { de = "Fuchs", en = "Red fox" }`. A class or language missing there is shown with its name from `species.names`, unknown classes are reported as error when the model is loaded. Internally (filter, colours) the app keeps using the identifiers, so a selection of classes stays when the language changes. For a new model, adapt the file to its `.names` file. The labels in the previews are drawn with DejaVu Sans if it is installed, since Pillow's own font has no umlauts.

## Docker images

The program consists of two images:

- **Base image** [`quay.io/christofkaufmann/nest-predator-base`](https://quay.io/repository/christofkaufmann/nest-predator-base) (`Dockerfile.base`): Ubuntu with OpenCV, Darknet, DarkHelp (including `DarkHelp.py`) and all Python packages. Building it takes about 15–20 minutes. It is public and changes rarely.
- **App image** `quay.io/christofkaufmann/nest-predator-app` (`Dockerfile`): app and model on top of the base image. Building it takes a few seconds.

   ```bash
   # base image: only after changes to Dockerfile.base or requirements.txt, then with a new version
   docker build -f Dockerfile.base -t quay.io/christofkaufmann/nest-predator-base:0.1 .
   docker push quay.io/christofkaufmann/nest-predator-base:0.1

   # app image
   docker build -t quay.io/christofkaufmann/nest-predator-app .
   docker run --rm -p 127.0.0.1:8501:8501 quay.io/christofkaufmann/nest-predator-app
   ```

- **Base image versions:** A new version of the base image gets a new tag, which goes into `BASE_IMAGE` in the `Dockerfile` as well. So every app image says which base image it was built on, and an app image built later doesn't change by accident. A different base image can also be given with `--build-arg BASE_IMAGE=...`.
- **Port only on `127.0.0.1`:** With `-p 127.0.0.1:8501:8501` the program can only be reached from the computer itself. This also makes <http://localhost:8501> work with rootless Podman: with `-p 8501:8501`, its port forwarding also accepts IPv6 connections to `localhost` (`::1`), but can't pass them on to the container, which has no IPv6. The browser then shows an error instead of trying IPv4. To reach the program from other computers, use `-p 8501:8501` and the IPv4 address of the computer.
- **Minimal OpenCV:** OpenCV is built in the build stage of the base image, only with the modules that Darknet and DarkHelp need (`core`, `imgproc`, `imgcodecs`, `videoio`, `highgui`, `video`, `dnn`), with JPEG/PNG, but without GUI, ffmpeg and GDAL. Ubuntu's OpenCV packages would bring about 680 MB of dependencies. Therefore the command line tools of Darknet and DarkHelp can't open windows or read videos in the container.
- **Include patches:** Darknet and DarkHelp rely on the full OpenCV headers to bring some standard headers along. `Dockerfile.base` adds the missing includes with `sed`.
- **CPU architecture:** Darknet would be built with `-march=native` and then only run on CPUs like the one of the build machine. The base image is therefore built for `x86-64-v3` (AVX2). For a machine-specific build: `--build-arg DARKNET_MARCH=native`. On Macs with Apple chips, the images only run emulated.
- **Python packages** come from Ubuntu as far as their versions fit Streamlit. pip installs only Streamlit, pydeck, protobuf, python-multipart and pyarrow, in a venv with `--system-site-packages`. Ubuntu's pyarrow would pull in LLVM and another 260 MB or so via Gandiva. `DarkHelp.py` is in `/usr/lib/python3/dist-packages`, like a module from a Debian package.
- **Licenses:** The base image contains the license texts of OpenCV, Darknet and DarkHelp in `/usr/share/doc/`.
- **Model:** It is part of the app image. For a new model, replace the files in `model/` and rebuild the app image. Without model files, the build stops with an error.

### Image as file

To pass the app image on without a registry, e.g. to computers without internet access, save it as compressed file and load it there:

```bash
docker save quay.io/christofkaufmann/nest-predator-app | gzip > nest-predator-app.tar.gz
docker load -i nest-predator-app.tar.gz
```

- **Size:** The file contains all layers, including those of the base image and of Ubuntu (about 235 MB). `docker load` can't fetch missing layers from a registry, so the file has to be complete, and the base image in the registry doesn't make it smaller.
- **Full image names:** Podman names local images `localhost/<name>`, and this name ends up in the file. With the full name `quay.io/christofkaufmann/...` the image has the same name with Docker and Podman, also after loading.
- **Previews** are stored under `/tmp` in the container (about 100–200 KB per image).
- **`HEALTHCHECK` with Podman:** Podman keeps the `HEALTHCHECK` only with `podman build --format docker`.

## Technical notes

- **Upload:** The upload field reads dropped folders recursively, filters the images and sends them one by one with two parallel requests to `/api/<token>/upload`. The route analyses each image right away in a worker thread. Only the result and a preview (1024 px) are kept, so the memory doesn't grow with the amount of data. A test with 3922 images (5 GB) took 12.5 minutes with 560–980 MB of memory. Streamlit's own `st.file_uploader`, in contrast, keeps the whole batch in memory.
- **Sessions:** `analysis.Session` holds the results and previews of one browser session. The routes find it by a token. The registry only holds weak references, so a session and its previews disappear together with Streamlit's session state.
- **Duplicate images:** The key is `file name|size|modification time`, without folders. The upload field sorts out known images before uploading, and the server checks again. If a known image comes again with more of its folders (first `a.jpg`, then `A/a.jpg`), the field reports the new path to `/api/<token>/paths`. The paths are displayed without the folders that all images have in common.
- **Thresholds:** Darknet reports all detections from 10 % on (`MIN_CONFIDENCE` in `analysis.py`). The confidence threshold only filters these, so the images aren't needed anymore after the analysis. Confidences are rounded to 4 decimals and the threshold to 2. The confidence scale above the timeline sets the threshold in 5 % steps, the same edges as the bins of the histogram (`bin_start()` in `app.py`). A confidence exactly at the threshold counts as detected everywhere.
- **Processing time:** It covers reading, detection and preview of an image. Waiting for the image that is uploaded in parallel doesn't count.
- **Locale:** When loading, Darknet sets the locale of the process to "C". Afterwards Python reads and writes text files without explicit encoding as ASCII. The code therefore always gives the encoding, and in the Docker image `PYTHONUTF8=1` additionally makes UTF-8 the default.
- **`.cfg` stays unchanged:** When loading, DarkHelp sets `batch=1` and `subdivisions=1` directly in the `.cfg`. `detector.py` therefore passes a temporary copy to DarkHelp.
- **Errors aren't passed on:** DarkHelp's `PredictFN(filename)` doesn't report loading errors and then returns the results of the previous image. The images are therefore decoded with Pillow (including EXIF rotation, like `cv2.imread`) and passed with `Predict`.
- **libxml2 conflict in conda:** Some conda environments bring a `libxml2` that doesn't fit the system OpenCV used by Darknet (`undefined symbol: xmlNanoHTTPCleanup`). If there is a `libxml2` in the Python prefix, `detector.py` looks up the system one with `ldconfig -p` and loads it first.
- **Quit:** "Quit" sends `SIGTERM` to its own process. uvicorn shuts down in an orderly way, but then ends the process with the signal, so Python's exit handlers don't run. The previews are therefore removed by the `lifespan` hook in `server.py`. The final page replaces the content of the page, so that the browser doesn't show Streamlit's "Connection error".
