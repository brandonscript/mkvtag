#!/bin/bash

watchdir=$1

if [ -z "$watchdir" ]; then
  echo "Usage: $0 <watchdir>"
  exit 1
fi

docker stop --time=30 mkvtag 1>/dev/null 2>&1
docker rm mkvtag 1>/dev/null 2>&1

docker build -t mkvtag .
docker run -v "$watchdir":/watchdir --restart unless-stopped --name mkvtag -d mkvtag
