FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Zavisnosti odvojeno od koda, da izmena koda ne obara keš instalacije.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY docformat/ ./docformat/
COPY presets/ ./presets/
COPY mate_agent/ ./mate_agent/
COPY .streamlit/ ./.streamlit/
COPY app.py cli.py ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Biblioteka pravila je jedini trajni podatak aplikacije -- montira se kao
# volume, inače svaki redeploy briše sve sačuvane setove.
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /data/rules_library

ENV RULES_LIBRARY_DIR=/data/rules_library

# Kontejner ne radi kao root; /data mora pripadati tom korisniku da bi
# biblioteka bila upisiva.
RUN useradd --create-home --uid 10001 formatter \
    && chown -R formatter:formatter /app /data
USER formatter

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).read().strip()==b'ok' else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
