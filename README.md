# render&CodeSandBox対応　これからvercelとかにも対応させる予定


# choco-tube (チョコTube)

## Overview
choco-tube is a YouTube alternative viewing application that allows users to search, watch, and download videos using various APIs including Invidious and YouTube Education.

## Features
- Video search and playback
- Channel and playlist viewing
- Video downloading (MP3/MP4)
- Chat functionality
- Theme switching (light/dark)
- History and favorites management

## Project Structure
```
├── app.py              # Main Flask application
├── templates/          # HTML templates
│   ├── base.html       # Base template with navigation
│   ├── index.html      # Landing/login intro page
│   ├── login.html      # Login page
│   ├── home.html       # Home page with trending videos
│   ├── search.html     # Search results page
│   ├── watch.html      # Video player page
│   ├── channel.html    # Channel page
│   ├── playlist.html   # Playlist page
│   ├── downloader.html # Download page
│   ├── chat.html       # Chat page
│   ├── setting.html    # Settings page
│   └── ...
├── static/
│   ├── style.css       # Main stylesheet
│   └── script.js       # Client-side JavaScript
└── requirements.txt    # Python dependencies
```

## Running the App
The app runs on Flask with the following command:
```bash
python app.py
```
Server binds to `0.0.0.0:5000`

## Default Login
- Password: `choco` (can be changed via APP_PASSWORD environment variable)

## Environment Variables
- `APP_PASSWORD` - Login password (default: "choco")
- `SESSION_SECRET` - Flask session secret key
- `YOUTUBE_API_KEY` - Optional YouTube Data API key

## CodeSandbox Deployment
This project is configured for CodeSandbox deployment with:
- `.codesandbox/tasks.json` - Auto-start configuration
- `.codesandbox/Dockerfile` - Docker container setup
- `.devcontainer/devcontainer.json` - Dev container configuration

To deploy on CodeSandbox:
1. Import this GitHub repo to CodeSandbox
2. The container will auto-build with Python 3.11 and ffmpeg
3. Flask server starts automatically on port 5000

## Recent Changes
- 2025-12-14: Added CodeSandbox deployment configuration
- 2025-12-14: Initial setup on Replit with all dependencies installed
