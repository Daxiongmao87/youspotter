# YouSpotter

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

**YouSpotter** is a personal media automation tool that helps you manage and organize your music collection by automatically monitoring your Spotify playlists and acquiring corresponding audio files from YouTube Music. Similar to Lidarr for music discovery, YouSpotter automates the process of maintaining your personal music library.

## ✨ Features

### 🎵 **Intelligent Music Management**
- **Spotify Integration**: Monitor your personal playlists for new additions
- **Automated Discovery**: Automatically find and acquire music from YouTube Music
- **Quality Control**: Configurable audio quality and format preferences
- **Smart Matching**: Advanced matching algorithms for accurate track identification

### 🔄 **Automation & Monitoring**
- **Scheduled Sync**: Automatic 15-minute interval monitoring
- **Manual Triggers**: On-demand sync capability
- **Real-time Status**: Live progress tracking and queue management
- **Retry Logic**: Intelligent retry mechanisms with exponential backoff

### 🎛️ **Flexible Configuration**
- **Custom Organization**: Configurable file naming and folder structure
- **Quality Settings**: Bitrate and format preferences (MP3, etc.)
- **Concurrent Downloads**: Adjustable download limits
- **Path Templates**: Customizable file organization patterns

### 🔐 **Secure Authentication**
- **OAuth PKCE**: Secure Spotify authentication (no client secret required)
- **Token Management**: Automatic token refresh and secure storage
- **Privacy Focused**: Your credentials never leave your system

### 📊 **Modern Web Interface**
- **Real-time Dashboard**: Live status updates and progress tracking
- **Catalog Browser**: Browse your music collection with metadata
- **Queue Management**: View and manage download queues
- **Mobile Responsive**: Works on desktop and mobile devices

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Spotify Developer Account (free)
- Virtual environment (recommended)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/youspotter.git
   cd youspotter
   ```

2. **Set up virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python app.py
   ```

5. **Access the web interface**
   - Open http://localhost:5000 in your browser
   - Follow the setup wizard to configure Spotify integration

### Spotify App Setup

1. Visit the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Add redirect URI: `http://localhost:5000/auth/callback`
4. Copy your Client ID (no client secret needed)
5. Enter the Client ID in YouSpotter's settings

## 🐳 Docker Deployment

### Using Docker Compose (Recommended)

```bash
# Clone and start
git clone https://github.com/yourusername/youspotter.git
cd youspotter
docker-compose up -d

# Access at http://localhost:5000
```

### Manual Docker Build

```bash
docker build -t youspotter .
docker run -d \
  --name youspotter \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/downloads:/app/downloads \
  youspotter
```

See [DOCKER.md](DOCKER.md) for detailed Docker configuration options.

## 📖 Usage Guide

### Initial Setup

1. **Configure Spotify Authentication**
   - Enter your Spotify Client ID in settings
   - Complete OAuth authorization
   - Select playlists to monitor

2. **Set Download Preferences**
   - Choose download directory (must be absolute path)
   - Configure audio quality and format
   - Set concurrent download limits

3. **Start Monitoring**
   - Enable automatic sync or trigger manual sync
   - Monitor progress in the web interface

### Legitimate Use Cases

YouSpotter is designed for personal media management and supports various legitimate use cases:

- **Personal Collection Management**: Organize music you own or have rights to
- **Public Domain Content**: Archive classical music, traditional folk songs, and historical recordings
- **Creative Commons Music**: Collect CC-licensed content from independent artists
- **Educational Research**: Academic use of musical content for study and analysis
- **Format Conversion**: Convert between audio formats for compatibility
- **Backup Creation**: Create personal backups of legitimately accessed content

## ⚖️ Legal Considerations

**Important**: YouSpotter is a tool for personal media automation. Users are fully responsible for ensuring their use complies with applicable laws and service terms.

### Responsible Usage
- ✅ **Use for content you own or have rights to**
- ✅ **Public domain and Creative Commons content**
- ✅ **Personal backups and format shifting**
- ✅ **Educational and research purposes**
- ❌ **Avoid downloading copyrighted content without permission**
- ❌ **Respect platform Terms of Service**
- ❌ **Commercial redistribution of protected content**

### Platform Compliance
This tool may interact with YouTube and Spotify in ways that could violate their Terms of Service. Users assume full responsibility for compliance with all applicable terms and laws.

**Disclaimer**: This software is provided for educational and personal automation purposes. The developers do not encourage or condone copyright infringement or violation of service terms.

## 🛠️ Development

### Requirements
- Python 3.12+
- Flask web framework
- SQLite database
- Virtual environment

### Testing
```bash
# Run test suite
make test

# Check code quality
make lint

# Verify formatting
make format-check
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Application status and counters |
| `/queue` | GET | Download queue with pagination |
| `/sync-now` | POST | Trigger immediate sync |
| `/config` | GET/POST | User configuration management |
| `/catalog/<mode>` | GET | Browse music catalog |

## 🎯 Roadmap

- [ ] **Enhanced Matching**: Improved audio fingerprinting
- [ ] **Multiple Sources**: Support for additional music platforms
- [ ] **Playlist Export**: Export to various playlist formats
- [ ] **Advanced Filters**: Genre and mood-based filtering
- [ ] **Statistics Dashboard**: Download analytics and insights

## 🤝 Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests for any improvements.

### Development Setup
```bash
git clone https://github.com/yourusername/youspotter.git
cd youspotter
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

YouSpotter is an open-source personal automation tool. It does not host, store, or distribute copyrighted content. Users are solely responsible for ensuring their usage complies with applicable copyright laws, platform terms of service, and local regulations.

The developers provide this software "as-is" without warranty and disclaim any liability for user actions or legal consequences arising from the use of this software.

---

**Built with ❤️ for music enthusiasts who value automation and personal media management.**