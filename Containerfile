FROM docker.io/library/python:3.14.7-slim-trixie

ARG KERNEL_TRACKER_VERSION='v0.1'

# git: tree fetching and the test suite
# nginx: front end for gunicorn
# default-libmysqlclient-dev: headers needed to build mysqlclient
# netcat-openbsd: contrib/start waits for the database with it
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git nginx netcat-openbsd gcc pkg-config default-libmysqlclient-dev procps && \
    rm -rf /var/lib/apt/lists/*

COPY --chmod=0755 contrib/fix-permissions /usr/bin/fix-permissions

COPY . /opt/kernel-tracker/

ARG VENV="/opt/kernel-tracker-venv"

RUN python -m venv ${VENV} && \
    ${VENV}/bin/pip install --upgrade pip setuptools && \
    ${VENV}/bin/pip install -e '/opt/kernel-tracker[mysql]'

# /data is a volume: it holds the bare repository, db.sqlite3 (without
# MariaDB), logs, temporary files and the collected static files. /git is
# where local git trees get bind mounted. Nothing but the code lives
# outside those two directories.
RUN mkdir -p /data/tmp /data/log /data/static /git

COPY contrib/settings_local.py /opt/kernel-tracker/src/kernel_tracker/
COPY contrib/nginx.conf /etc/nginx/nginx.conf

RUN sed -i "s/^# %__version__%$/__version__ = \"${KERNEL_TRACKER_VERSION}\"/" \
    /opt/kernel-tracker/src/kernel_tracker/settings_local.py

RUN ${VENV}/bin/manage collectstatic --noinput
RUN git config --system --add safe.directory '*'

RUN /usr/bin/fix-permissions /opt/kernel-tracker /data /git /var/log/

WORKDIR /opt/kernel-tracker

CMD ["/opt/kernel-tracker/contrib/start"]
