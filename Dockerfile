FROM python:3.10-slim

# Set working directory inside container
WORKDIR /app

# Install necessary system packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Run the main processor script
CMD ["python", "process_pdfs.py"]
