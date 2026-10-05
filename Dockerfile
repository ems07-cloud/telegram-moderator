FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir aiogram
COPY moderator ./moderator
COPY rules.example.toml ./rules.toml
ENV DB_PATH=/data/moderator.sqlite RULES_PATH=/app/rules.toml
VOLUME /data
CMD ["python", "-m", "moderator"]
