#!/bin/bash

watchdir=$1

if [ -z "$watchdir" ]; then
  echo "Usage: $0 <watchdir>"
  exit 1
fi

env_args=()

while [[ $# -gt 1 ]]; do
  arg="$2"
  if [[ "$arg" == *=* ]]; then
    key="${arg%%=*}"
    value="${arg#*=}"
    shift
  else
    key="$2"
    value="$3"
    shift 2
  fi

  case $key in
  --log)
    env_args+=("-e" "MKVTAG_LOGFILE=$value")
    ;;
  --timer | -t)
    env_args+=("-e" "MKVTAG_TIMER=$value")
    ;;
  --loops | -l)
    env_args+=("-e" "MKVTAG_LOOPS=$value")
    ;;
  --clean | -x)
    env_args+=("-e" "MKVTAG_CLEAN=$value")
    ;;
  *)
    echo "Unknown option: $key"
    exit 1
    ;;
  esac

done

docker stop --time=30 mkvtag 1>/dev/null 2>&1
docker rm mkvtag 1>/dev/null 2>&1

docker build -t mkvtag .
docker run -v "$watchdir":/watchdir "${env_args[@]}" --restart unless-stopped --name mkvtag -d mkvtag
