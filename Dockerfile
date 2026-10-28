# The app and its model on top of the base image (Dockerfile.base), which brings Darknet, DarkHelp and the Python
# packages. Building it takes a few seconds.
#
#   docker build -t quay.io/christofkaufmann/nest-predator-app .
#   docker run --rm -p 127.0.0.1:8501:8501 quay.io/christofkaufmann/nest-predator-app

ARG BASE_IMAGE=quay.io/christofkaufmann/nest-predator-base:0.1
FROM ${BASE_IMAGE}

WORKDIR /app
# The model is part of the image (as last but one layer, so a new model only replaces this and the app layer)
COPY model/ model/
# The model isn't part of the repository, so stop here rather than build an image without it
RUN ls model/*.cfg model/*.names model/*.weights > /dev/null \
    || { echo "The model files are missing in model/, see README.md" >&2; exit 1; }
COPY .streamlit/ .streamlit/
COPY upload_field/ upload_field/
# DarkHelp.py isn't copied: the base image has the version that matches its DarkHelp library
COPY server.py app.py analysis.py detector.py i18n.py shutdown.py README.md LICENSE ./

USER ubuntu
EXPOSE 8501
# Failed checks while Streamlit is starting don't count (Podman checks right at the start)
HEALTHCHECK --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "server.py", "--server.address=0.0.0.0"]
