# YouSpotter Docker Setup

## Quick Start

1. **Build and run with docker-compose:**
   ```bash
   docker-compose up --build
   ```

2. **Access the application:**
   - Open http://localhost:5000 in your browser

3. **Stop the application:**
   ```bash
   docker-compose down
   ```

## Directory Structure

After running, you'll have:
```
./data/           # Database and app data (persistent)
./downloads/      # Downloaded music files (persistent)
```

## Configuration

### Environment Variables

You can override environment variables in `docker-compose.yml`:

```yaml
environment:
  - PORT=8080                    # Change port
  - YOUSPOTTER_DB=/app/data/youspotter.db
  - TZ=America/New_York         # Set timezone
```

### Custom Download Path

To change where music is downloaded:

```yaml
volumes:
  - ./data:/app/data
  - /your/music/path:/app/downloads  # Custom download path
```

## Build Only (without compose)

```bash
# Build image
docker build -t youspotter .

# Run container
docker run -d \
  --name youspotter \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/downloads:/app/downloads \
  youspotter
```

## Traefik Integration

The docker-compose includes Traefik labels for reverse proxy setup:
- Access via: `http://youspotter.localhost` (when Traefik is configured)

## Data Persistence

- **Database**: Stored in `./data/youspotter.db`
- **Downloads**: Stored in `./downloads/`
- **Configuration**: Saved in database (Spotify credentials, settings)

## Security

- Runs as non-root user (`youspotter`)
- No sensitive data in image
- Database and downloads mounted as volumes
- Health checks included