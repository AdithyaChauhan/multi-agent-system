# Postgres 15 (Alpine, same base as before) plus pgvector for hybrid search (ADR 0006, 0014).
# Built from source on the same musl base, so existing data volumes stay compatible: the
# pgvector/pgvector images are Debian (glibc), whose text sort order differs from Alpine's.
FROM postgres:15-alpine

ARG PGVECTOR_VERSION=0.8.0
RUN apk add --no-cache --virtual .build-deps git build-base \
    && git clone --branch "v${PGVECTOR_VERSION}" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make OPTFLAGS="" with_llvm=no \
    && make install with_llvm=no \
    && cd / && rm -rf /tmp/pgvector \
    && apk del .build-deps
