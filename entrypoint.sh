#!/bin/bash

# Define cleanup procedure
cleanup() {
  echo "Container stopped, performing cleanup..."
  # Remove any orphaned pid files
  rm -f /watchdir/.mkvtag.pid
}

# Trap SIGTERM
trap 'cleanup' SIGTERM

# Execute a command
poetry run mkvtag /watchdir &

# Wait
wait $!

# Cleanup
cleanup
