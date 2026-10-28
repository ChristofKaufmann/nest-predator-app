# Model

This folder holds the trained Darknet/YOLO model. It isn't part of the repository. The program expects these files here:

- **`.cfg`:** the network configuration, exactly one file
- **`.names`:** the class names, one per line, exactly one file
- **`.weights`:** the trained weights, exactly one file
- **`.toml` (optional):** the display names of the classes per language, with the name of the `.names` file, e.g. `species.toml` for `species.names`. One line per class, e.g. `Fuchs = { de = "Fuchs", en = "Red fox" }`. Classes and languages missing there are shown with their name from the `.names` file.

The Docker build copies the files into the app image and stops if they are missing. Without Docker, another folder can be set with the environment variable `MODEL_DIR`.
