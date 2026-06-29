FROM python:3.11-slim

WORKDIR /app

# Lightpanda install
RUN apt-get update && apt-get install -y curl && \
    curl -L -o /usr/local/bin/lightpanda \
    https://github.com/lightpanda-io/browser/releases/download/nightly/lightpanda-x86_64-linux && \
    chmod +x /usr/local/bin/lightpanda && \
    apt-get clean

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
