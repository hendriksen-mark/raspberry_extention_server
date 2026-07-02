# This image just moves the correct bins to a specific folder.
# Can also be used to compile the binaries (for an even better experience)
FROM busybox AS binselector
WORKDIR /opt/raspberry_extension_server

# Architecture automatically set by docker eg. linux/amd64, linux/arm/v7, linux/arm64
ARG TARGETPLATFORM
ARG BRANCH
ENV BRANCH=$BRANCH

# ============================ Actual image from here ====================
FROM debian:stable-slim AS prod
WORKDIR /opt/raspberry_extension_server
ARG TARGETPLATFORM
ARG BRANCH
ENV BRANCH=$BRANCH

COPY requirements.txt ./

## Install requirements
RUN apt-get update && dpkg --configure -a \
    && apt-get install --no-install-recommends -y \
        curl unzip python3 python3-pip python3-dev python3-setuptools gcc bluez git util-linux dbus \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install -r requirements.txt --no-cache-dir --break-system-packages --ignore-installed

## Install Raspberry Extension Server
COPY ./flask_ui/ /opt/raspberry_extension_server/flask_ui/
COPY ./server_objects/ /opt/raspberry_extension_server/server_objects/
COPY ./services/ /opt/raspberry_extension_server/services/
COPY ./config_manager/ /opt/raspberry_extension_server/config_manager/
COPY ./api.py /opt/raspberry_extension_server/

## Install the web interface
RUN curl -sL -A "Mozilla/5.0" https://github.com/hendriksen-mark/raspberry_extension_server_ui/releases/latest/download/raspberry_extension_server_ui-release.zip -o serverUI.zip \
    && if ! unzip -tq serverUI.zip > /dev/null; then \
         echo "Downloaded file is not a valid zip. Showing first 20 lines:"; \
         head -20 serverUI.zip; \
         exit 1; \
       fi \
    && mkdir serverUI \
    && unzip -qo serverUI.zip -d serverUI \
    && rm serverUI.zip \
    && mv serverUI/dist/index.html flask_ui/templates/ \
    && cp -r serverUI/dist/assets flask_ui/ \
    && rm -r serverUI

## Expose ports
EXPOSE 5002

CMD [ "python3", "-u", "/opt/raspberry_extension_server/api.py" ]
