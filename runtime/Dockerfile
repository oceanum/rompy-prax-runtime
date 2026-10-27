# Generation/verification image only. SWAN runs in its unchanged upstream image.
FROM ghcr.io/astral-sh/uv@sha256:b2c1f5fad200728ab3681991a148c55cace40eab81a17077d8914097663a0201 AS uv
# Resolved public multi-platform index; local target is linux/amd64.
FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 HOME=/tmp XDG_CACHE_HOME=/tmp/cache \
    PYTHONPATH=/opt/runtime/src PATH=/opt/rompy/bin:/usr/local/bin:/usr/bin:/bin
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && uv venv --python /usr/local/bin/python /opt/rompy
WORKDIR /opt/runtime
COPY runtime/requirements.lock runtime/build-constraints.txt ./runtime/
RUN uv pip sync --python /opt/rompy/bin/python --require-hashes runtime/requirements.lock \
    && git clone --filter=blob:none https://github.com/rom-py/rompy.git /opt/sources/rompy \
    && git -C /opt/sources/rompy checkout --detach cf80d0d03dddf032bc27282a1f8a1607d69b4184 \
    && git clone --filter=blob:none https://github.com/rom-py/rompy-swan.git /opt/sources/rompy-swan \
    && git -C /opt/sources/rompy-swan checkout --detach f5ed326f6287a9f0f884efd2498d20ee7948c47d \
    && uv pip install --python /opt/rompy/bin/python --no-deps --build-constraints runtime/build-constraints.txt /opt/sources/rompy /opt/sources/rompy-swan \
    && /opt/rompy/bin/python -c 'import platform,importlib.metadata as m; assert platform.python_version()=="3.12.13"; assert m.version("rompy")=="2.0.0a0"; assert m.version("rompy-swan")=="0.11.1"; assert m.version("pydantic")=="2.13.5"' \
    && rm -rf /root/.cache /tmp/cache /opt/sources
COPY src/ ./src/
COPY reference/ ./reference/
RUN mkdir /work && chown 10001:10001 /work
USER 10001:10001
WORKDIR /work
CMD ["/opt/rompy/bin/python", "-m", "rompy_prax_runtime", "--help"]
