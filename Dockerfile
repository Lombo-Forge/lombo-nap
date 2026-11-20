FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --system --no-create-home app && mkdir /data && chown app /data
USER app
ENTRYPOINT ["lombo-nap"]
CMD ["run", "--loop"]
