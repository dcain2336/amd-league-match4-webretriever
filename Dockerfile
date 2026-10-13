FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY webretriever/ ./webretriever/

# Optional: bake in provider keys at run time, not build time.
# ENV TINYFISH_API_KEY=""

ENTRYPOINT ["python", "-m", "webretriever"]
CMD ["--help"]
