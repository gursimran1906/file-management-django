# Base build
FROM python:3.12-alpine as base
RUN apk add --update --virtual .build-deps \
    build-base \
    postgresql-dev \
    python3-dev \
    libpq \
    linux-headers \
    gdb  # Add gdb for debugging

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Now multistage build
FROM python:3.12-alpine
RUN apk add libpq weasyprint fontconfig font-noto

# Enable core dumps
RUN echo "ulimit -c unlimited" >> /etc/profile.d/core-dump.sh
RUN mkdir -p /app/core-dumps && chmod 777 /app/core-dumps
RUN echo "/app/core-dumps/core.%e.%p.%t" > /proc/sys/kernel/core_pattern

COPY --from=base /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=base /usr/local/bin/ /usr/local/bin/
WORKDIR /app
COPY . /app
RUN chmod +x /app/entrypoint.sh
ENV PYTHONUNBUFFERED 1
ENTRYPOINT [ "/app/entrypoint.sh" ]
