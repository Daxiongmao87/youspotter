#!/bin/bash
set -e

# Fix permissions for mounted volumes
# This ensures that the youspotter user can write to mounted directories
if [ -d "/app/data" ]; then
    chown -R youspotter:youspotter /app/data
fi

if [ -d "/app/downloads" ]; then
    chown -R youspotter:youspotter /app/downloads
fi

# Create directories if they don't exist
mkdir -p /app/data /app/downloads
chown youspotter:youspotter /app/data /app/downloads

# Switch to youspotter user and execute the command
exec gosu youspotter "$@"