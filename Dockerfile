# BatiCalc — application web (serveur d'équipe)
# Construction : docker build -t baticalc .
# Lancement    : docker run -p 8000:8000 -v baticalc_donnees:/donnees baticalc

# --- LibreDWG (lecture des fichiers DWG)
FROM python:3.12-slim AS libredwg
RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential autoconf automake libtool pkg-config texinfo ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/LibreDWG/libredwg /src && cd /src \
    && git submodule update --init --depth 1 \
    && sh autogen.sh && ./configure --disable-bindings --disable-docs --prefix=/opt/libredwg \
    && make -j"$(nproc)" && make install

# --- Application
FROM python:3.12-slim
COPY --from=libredwg /opt/libredwg /opt/libredwg
ENV PATH="/opt/libredwg/bin:${PATH}" LD_LIBRARY_PATH="/opt/libredwg/lib" BATICALC_DATA=/donnees
WORKDIR /app
COPY pyproject.toml README.md ./
COPY baticalc ./baticalc
RUN pip install --no-cache-dir .
VOLUME /donnees
EXPOSE 8000
CMD ["baticalc", "serveur", "--port", "8000", "--hote", "0.0.0.0", "--donnees", "/donnees"]
