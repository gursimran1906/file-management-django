FROM python:3.12-slim

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies for WeasyPrint and Rust toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
    apt-transport-https \
    ca-certificates \
    libffi-dev \
    libcairo2 \
    libcairo2-dev \
    libpango1.0-0 \
    libpangocairo-1.0-0 \
    libjpeg62-turbo-dev \
    libpng-dev \
    fontconfig \
    fonts-dejavu \
    libglib2.0-0 \
    libpangoft2-1.0-0 \
    gir1.2-harfbuzz-0.0 \
    gcc \
    libpq-dev \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Rust and Cargo (Rust toolchain)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && \
    export PATH="$HOME/.cargo/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Set working directory
WORKDIR /app

# Copy application dependencies
COPY requirements.txt /app/requirements.txt

# Install Python dependencies (WeasyPrint and others)
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the entire application to the container
COPY . /app

# Ensure the entrypoint script is executable
RUN chmod +x /app/entrypoint.sh

# Define entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]