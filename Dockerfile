FROM python:3.13-slim

# A numeric UID/GID, so a runtime enforcing "must not run as root" can check it
# without a passwd lookup. 65532 matches the fsGroup the deployment mounts the
# data volume with, which is what makes DATA_DIR writable.
RUN groupadd --gid 65532 kada \
  && useradd --uid 65532 --gid 65532 --no-create-home --system kada

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

WORKDIR /app
COPY kada /app/kada

# The version is stamped in at build time, because it is not knowable from inside
# the source tree: semantic-release decides it from the commits, AFTER this repo
# has been written. pyproject.toml says 0.0.0 for the same reason. The default is
# "dev" -- a deployed image that says "dev" is telling you its build was wrong,
# which is more use than a confident lie.
ARG VERSION=dev
ENV APP_VERSION=${VERSION}

# Bake the bytecode now, so the image still works with a read-only root
# filesystem, where Python could not write __pycache__ on import.
RUN python -m compileall -q /app/kada

USER 65532
EXPOSE 8080

CMD ["uvicorn", "kada.main:app", "--host", "0.0.0.0", "--port", "8080"]
