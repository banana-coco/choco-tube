#!/usr/bin/env python3
"""
Lightweight YouTube API Proxy Server (Invidious-compatible)
Provides video information via Piped API
"""

import os
import json
import requests
from flask import Flask, request, jsonify, abort
from functools import lru_cache
import datetime

app = Flask(__name__)

PIPED_SERVERS = [
    'https://pipedapi.kavin.rocks',
    'https://api.piped.projectsegfau.lt',
    'https://pipedapi.ggtyler.dev',
    'https://api.piped.yt',
]

@lru_cache(maxsize=100)
def get_piped_video(video_id, server_index=0):
    """Fetch video info from Piped API"""
    if server_index >= len(PIPED_SERVERS):
        return None
    
    server = PIPED_SERVERS[server_index]
    try:
        url = f"{server}/streams/{video_id}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json()
    except:
        return get_piped_video(video_id, server_index + 1)
    
    return get_piped_video(video_id, server_index + 1)

def piped_to_invidious_format(piped_data):
    """Convert Piped API response to Invidious-compatible format"""
    if not piped_data:
        return None
    
    return {
        'title': piped_data.get('title', ''),
        'description': piped_data.get('description', ''),
        'descriptionHtml': piped_data.get('description', '').replace('\n', '<br>'),
        'videoId': piped_data.get('id', ''),
        'viewCount': piped_data.get('views', 0),
        'likeCount': piped_data.get('likes', 0),
        'published': int(datetime.datetime.now().timestamp() * 1000),
        'publishedText': piped_data.get('uploadedDate', ''),
        'author': piped_data.get('uploader', ''),
        'authorId': piped_data.get('uploaderUrl', '').split('/')[-1] if '/' in piped_data.get('uploaderUrl', '') else '',
        'authorThumbnail': piped_data.get('uploaderAvatar', ''),
        'authorThumbnails': [
            {'url': piped_data.get('uploaderAvatar', ''), 'width': 48, 'height': 48}
        ],
        'subCount': 0,
        'lengthSeconds': piped_data.get('duration', 0),
        'allowedRegions': [],
        'isUpcoming': False,
        'isLiveContent': False,
        'isLive': False,
        'premiereDate': None,
    }

@app.route('/api/v1/videos/<video_id>', methods=['GET'])
def get_video(video_id):
    """Invidious-compatible /videos endpoint"""
    piped_data = get_piped_video(video_id)
    if not piped_data:
        abort(404)
    
    return jsonify(piped_to_invidious_format(piped_data))

@app.route('/api/v1/search', methods=['GET'])
def search():
    """Invidious-compatible /search endpoint"""
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    
    if not query:
        return jsonify({'items': []})
    
    # Try to search via Piped API
    try:
        server = PIPED_SERVERS[0]
        url = f"{server}/search?q={query}&filter=videos"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            piped_results = res.json().get('items', [])
            
            items = []
            for item in piped_results[:20]:
                if item.get('type') == 'stream':
                    items.append({
                        'type': 'video',
                        'videoId': item.get('url', '').split('=')[-1] if '=' in item.get('url', '') else item.get('id', ''),
                        'title': item.get('title', ''),
                        'videoThumbnails': [{'url': item.get('thumbnail', ''), 'width': 320, 'height': 180}],
                        'description': '',
                        'descriptionHtml': '',
                        'viewCountText': f"{item.get('views', 0)} views",
                        'viewCount': item.get('views', 0),
                        'published': 0,
                        'publishedText': item.get('uploadedDate', ''),
                        'author': item.get('uploader', ''),
                        'authorId': item.get('uploaderUrl', '').split('/')[-1] if '/' in item.get('uploaderUrl', '') else '',
                        'authorThumbnail': item.get('uploaderAvatar', ''),
                        'duration': item.get('duration', 0),
                        'durationText': f"{item.get('duration', 0) // 60}:{item.get('duration', 0) % 60:02d}",
                        'isUpcoming': False,
                    })
            
            return jsonify({'items': items})
    except:
        pass
    
    return jsonify({'items': []})

@app.route('/api/v1/trending', methods=['GET'])
def trending():
    """Invidious-compatible /trending endpoint"""
    return jsonify({'items': []})

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'service': 'YouTube Proxy (Piped-based)'})

if __name__ == '__main__':
    port = int(os.environ.get('INVIDIOUS_PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
