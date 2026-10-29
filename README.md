# Predator Detection

The program detects which animals can be seen on images from nest and wildlife cameras, e.g. fox, badger, raccoon dog or gulls. You drag single images, whole folders or the complete content of an SD card into the program, and it analyses them right away. You see the results as an image gallery with the detections drawn in and as statistics, and you can download them as an Excel file.

The program runs on your own computer and is used in the browser. The images don't leave your computer. The user interface is available in English and German.

## Starting the program

The model isn't part of this repository. Before building the Docker image or starting the program, copy its files into the folder `model/`: exactly one `.cfg`, `.names` and `.weights` file, and optionally the display names of the classes, see [model/README.md](model/README.md).

### With Docker

The Docker image runs on Linux, Windows and macOS, on computers with an Intel or AMD processor with AVX2 (most since about 2015).

1. Install [Docker](https://docs.docker.com/get-started/get-docker/), on Windows and macOS e.g. Docker Desktop.
2. Build the image once: open a terminal in the folder of this repository and enter:

   ```bash
   docker build -t quay.io/christofkaufmann/nest-predator-app .
   ```

   This takes about a minute. The first time, the base image with Darknet and the Python packages (about 240 MB) is downloaded from quay.io.
3. Start the program:

   ```bash
   docker run --rm -p 127.0.0.1:8501:8501 quay.io/christofkaufmann/nest-predator-app
   ```

4. Open <http://localhost:8501> in the browser.

Next time, steps 3 and 4 are enough. After changes to the program, build the image again (step 2).

### Without Docker (Linux)

1. Install [Darknet](https://github.com/hank-ai/darknet#linux-cmake-method) and [DarkHelp](https://github.com/stephanecharette/DarkHelp#building-darkhelp-linux) as described there. Their instructions also install OpenCV. Notes on versions and possible problems are in [CONTRIBUTING.md](CONTRIBUTING.md#installing-darknet-and-darkhelp).
2. Create a Python environment with the packages of the program, either with conda or mamba:

   ```bash
   mamba env create -f environment.yml
   ```

   or with venv and pip, which needs Python 3.11 or newer. On Ubuntu/Debian, the package `python3-venv` brings venv and pip:

   ```bash
   sudo apt install python3-venv
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

3. Activate the environment (`mamba activate nest-predator` or `source .venv/bin/activate`) and start the program:

   ```bash
   streamlit run server.py
   ```

4. Open <http://localhost:8501> in the browser.

## Usage

1. **Language:** The program starts in the language of your browser (German or English, otherwise English). You can switch it at the bottom of the sidebar under **Sprache · Language**. The choice is kept in the address, e.g. <http://localhost:8501/?lang=en>.
2. **Add images:** Drag images, folders or the content of an SD card into the field, or use **Select images** or **Select folder**. The analysis starts right away, the progress is shown below the field. Videos and other files are skipped.
3. **More images:** You can add more images at any time, they are added to the previous results. Images that were already analysed are skipped. So you can try a few images first and then drag in the whole folder.
4. **View results:** The **Timeline** below the field shows all images at their capture time, with one row per class and the confidence as colour. Series of images and uncertain detections become visible there. Zoom in to look at a series: the results below then only cover the visible period. Use Ctrl + mouse wheel or two fingers on the touchpad to zoom, drag to move the period, and double-click or use **Whole period** to show everything again. Below, the **Gallery** shows the images with the detections. **Statistics** shows key figures (images, detections, unreadable files, processing time) and charts (images per class, confidence of the detections, time of day). **Download results** at the bottom of the sidebar saves all results as an Excel file.
5. **Filter:** In the sidebar, the **Confidence threshold** sets how sure the program has to be for a detection to count. With **Classes** you can limit the results to certain animals. Gallery, statistics and Excel file follow these settings.
6. **Start over** in the sidebar discards all results, e.g. for a new SD card.
7. **Quit** in the sidebar closes the program. Afterwards the browser window can be closed.

## Good to know

- **Save your results:** The results are only kept while the program is running. So use **Download results** before **Start over** or **Quit**.
- **Keep the page open:** While images are uploaded, the page has to stay open. The browser asks before closing it.
- **Duration:** Depending on the computer, the program needs about 0.2–0.3 seconds per image, so about a quarter of an hour for 4000 images. The size of the SD card doesn't matter.
- **Duplicate images** are recognized by file name, size and modification date. A copy saved with a different date counts as a new image.
- **File names:** The paths are shown from the dragged-in folder on, without the folders that all images have in common. The browser doesn't reveal where the files are stored on your computer, so two images with the same name that were chosen on their own can't be told apart.
- **Capture time:** It is read from the image files, if the camera stores it there.
- **Class names** are shown in the language of the user interface, e.g. "Red fox" or "Fuchs". In the classes list of the sidebar they are sorted alphabetically.
- **Quit** closes the program for all browser windows in which it is currently open.

Technical details and notes on development are in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

BSD 3-Clause License, see [LICENSE](LICENSE). `DarkHelp.py` is part of [DarkHelp](https://github.com/stephanecharette/DarkHelp) and licensed under the MIT License, see [LICENSE-DarkHelp.txt](LICENSE-DarkHelp.txt). The Docker base image contains the license texts of OpenCV, Darknet and DarkHelp in `/usr/share/doc/`.
