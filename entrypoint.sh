#!/bin/bash
set -e

echo "Starting entrypoint as $(whoami)"

# Create directories if they don't exist (as root)
mkdir -p /app/data /app/downloads

# Fix permissions for mounted volumes
echo "Fixing permissions for /app/data and /app/downloads"
chown -R youspotter:youspotter /app/data /app/downloads

# Verify permissions were set correctly
echo "Permissions set - checking:"
ls -la /app/data /app/downloads || true

# Switch to youspotter user and execute the command
echo "Switching to youspotter user and executing: $@"
exec gosu youspotter "$@"