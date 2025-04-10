# Use an official Python runtime as a parent image
FROM python:3.12-slim AS base
ENV VENV_PATH=/mkvtag/.venv \
  POETRY_PATH=/usr/local/bin


# Set the working directory in the container
WORKDIR /mkvtag

# Install system dependencies
RUN apt-get update && \
  apt-get install -y build-essential curl file git wget && \
  rm -rf /var/lib/apt/lists/*

# Add gpg key for mkvtoolnix
RUN wget -O /usr/share/keyrings/gpg-pub-moritzbunkus.gpg https://mkvtoolnix.download/gpg-pub-moritzbunkus.gpg

# Add mkvtoolnix repository to /etc/apt/sources.list.d/mkvtoolnix.download.list
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/gpg-pub-moritzbunkus.gpg] https://mkvtoolnix.download/ubuntu/ jammy main" > /etc/apt/sources.list.d/mkvtoolnix.download.list
RUN echo "deb-src [arch=amd64 signed-by=/usr/share/keyrings/gpg-pub-moritzbunkus.gpg] https://mkvtoolnix.download/ubuntu/ jammy main" > /etc/apt/sources.list.d/mkvtoolnix.download.list

# Install mkvtoolnix
RUN apt-get update && \
  apt-get install -y mkvtoolnix && \
  rm -rf /var/lib/apt/lists/*

FROM base as poetry

ENV PATH="$POETRY_PATH/bin:$VENV_PATH/bin:$PATH"

# Install poetry
RUN curl -sSL https://install.python-poetry.org | python - \
  && mv /root/.local/bin $POETRY_PATH \
  && poetry --version \
  && python -m venv $VENV_PATH \
  && poetry config virtualenvs.in-project true \
  && poetry config virtualenvs.create false

COPY poetry.lock pyproject.toml README.md ./
COPY ./mkvtag ./mkvtag

RUN poetry install --no-interaction

FROM poetry as app
WORKDIR /mkvtag

COPY --from=poetry $VENV_PATH $VENV_PATH

# Run the script when the container launches
ENV PYTHONUNBUFFERED=1
# CMD ["poetry", "run", "mkvtag", "/watchdir"]
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT [ "/entrypoint.sh" ]
