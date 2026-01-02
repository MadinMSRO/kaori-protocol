FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements (if exists, or mock it)
# We assume we need to generate requirements.txt first? 
# For now, let's copy everything and install from manual list or generated file.

COPY . .

# Generate requirements.txt helper or just install directly
# Since we don't have a requirements.txt file, let's create one within the docker context or assume one exists.
# I'll write the requirements.txt as a separate step, but for now let's assume it's there.
# Wait, I should probably write requirements.txt first. 
# I will add a command to install dependencies manually in RUN to be safe for this artifact.

RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] python-multipart \
    pydantic requests pyyaml \
    sqlalchemy \
    # Google Cloud
    google-cloud-storage sqlalchemy-bigquery google-cloud-bigquery \
    # Validator Libs
    Pillow imagehash piexif \
    transformers torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu \
    scipy PyWavelets

# Expose port
ENV PORT=8080
EXPOSE 8080

# Run command
CMD ["uvicorn", "flow.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
