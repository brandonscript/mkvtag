# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /usr/src/app

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

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir poetry
RUN poetry install

# Run the script when the container launches
ENV PYTHONUNBUFFERED=1
CMD ["poetry", "run", "mkvtag", "/watchdir"]