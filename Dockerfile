FROM python:3.11-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY pyserve/ ./pyserve/
COPY examples/ ./examples/

# Install pyserve + yaml support
RUN pip install --no-cache-dir -e ".[yaml]"

# Default port
ENV PORT=8000
EXPOSE 8000

# Run pyserve
CMD ["pyserve", "--host", "0.0.0.0", "--port", "8000", "--static", "examples/public", "--no-color"]