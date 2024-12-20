# Base build
FROM python:3.12-alpine as base
RUN apk add --update --virtual .build-deps \
    build-base \
    postgresql-dev \
    python3-dev \
    libpq \
    linux-headers \
    gdb 

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Now multistage build
FROM python:3.12-alpine
RUN apk add libpq weasyprint fontconfig font-noto
COPY --from=base /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=base /usr/local/bin/ /usr/local/bin/
WORKDIR /app
COPY . /app
RUN chmod +x /app/entrypoint.sh

RUN echo "ulimit -s unlimited" >> /etc/profile.d/ulimit.sh

ENV PYTHONUNBUFFERED 1
ENTRYPOINT [ "/app/entrypoint.sh" ]
