import os
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib.parse
import datetime
import random
import time
import tempfile
import subprocess
import re
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session, send_file
from functools import wraps
import yt_dlp

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = os.environ.get('SESSION_SECRET', os.environ.get('SECRET_KEY', 'choco-tube-secret-key-2025'))

@app.after_request
def add_cache_headers(response):
    """Add cache headers to improve performance"""
    if response.content_type:
        if 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        elif 'application/json' in response.content_type:
            response.headers['Cache-Control'] = 'public, max-age=600'  # API results 10 min
        elif any(x in response.content_type for x in ['css', 'javascript', 'font', 'image']):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response

# セッションクッキーの設定（Render等のHTTPS環境で必要）
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('RENDER', 'true').lower() == 'true' or os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

PASSWORD = os.environ.get('APP_PASSWORD', 'choco')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', '')

# YouTube API Keys for rotation
YOUTUBE_API_KEYS = [
    "AIzaSyCz7f0X_giaGyC9u1EfGZPBuAC9nXiL5Mo",
    "AIzaSyBmzCw7-sX1vm-uL_u2Qy3LuVZuxye4Wys",
    "AIzaSyBWScla0K91jUL6qQErctN9N2b3j9ds7HI",
    "AIzaSyA17CdOQtQRC3DQe7rgIzFwTUjwAy_3CAc",
    "AIzaSyDdk_yY0tN4gKsm4uyMYrIlv1RwXIYXrnw",
    "AIzaSyDeU5zpcth2OgXDfToyc7-QnSJsDc41UGk",
    "AIzaSyClu2V_22XpCG2GTe1euD35_Mh5bn4eTjA"
]

# ユーザー指定のキーがあれば追加
if YOUTUBE_API_KEY and YOUTUBE_API_KEY not in YOUTUBE_API_KEYS:
    YOUTUBE_API_KEYS.insert(0, YOUTUBE_API_KEY)
_current_api_key_index = 0

EDU_VIDEO_API = "https://siawaseok.duckdns.org/api/video2/"
EDU_CONFIG_URL = "https://raw.githubusercontent.com/siawaseok3/wakame/master/video_config.json"
STREAM_API = "https://ytdl-0et1.onrender.com/stream/"
M3U8_API = "https://ytdl-0et1.onrender.com/m3u8/"

EDU_PARAM_SOURCES = {
    'siawaseok': {
        'name': '幸せok',
        'url': 'https://raw.githubusercontent.com/siawaseok3/wakame/master/video_config.json',
        'type': 'json_params'
    },
    'woolisbest1': {
        'name': 'woolisbest1',
        'url': 'https://raw.githubusercontent.com/woolisbest-4520/about-youtube/refs/heads/main/edu.json',
        'type': 'json_params'
    },
    'woolisbest2': {
        'name': 'woolisbest2',
        'url': 'https://raw.githubusercontent.com/woolisbest-4520/about-youtube/refs/heads/main/parameter.json',
        'type': 'json_params'
    },
    'kahoot': {
        'name': 'その他',
        'url': 'https://apis.kahoot.it/media-api/youtube/key',
        'type': 'kahoot_key'
    }
}

_edu_params_cache = {}
_edu_cache_timestamp = {}
_trending_cache = {'data': None, 'timestamp': 0}
_thumbnail_cache = {}

http_session = requests.Session()
retry_strategy = Retry(total=2, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
http_session.mount("http://", adapter)
http_session.mount("https://", adapter)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:92.0) Gecko/20100101 Firefox/92.0',
]

# Invidious instances - optimized selection with custom server support
DEFAULT_INVIDIOUS_INSTANCES = [
    'https://inv.vern.cc/',
    'https://invidious.nerdvpn.de/',
    'https://inv.skynetz.xyz/',
    'https://invidious.projectsegfau.lt/',
    'https://yewtu.be/',
]

# Custom Invidious instances from environment variable (takes priority)
CUSTOM_INVIDIOUS = [
    server.strip() for server in os.environ.get('CUSTOM_INVIDIOUS_INSTANCES', '').split(',')
    if server.strip()
]
INVIDIOUS_INSTANCES = CUSTOM_INVIDIOUS + DEFAULT_INVIDIOUS_INSTANCES if CUSTOM_INVIDIOUS else DEFAULT_INVIDIOUS_INSTANCES

# Piped API instances - optimized selection with custom server support
DEFAULT_PIPED_SERVERS = [
    'https://pipedapi.kavin.rocks',
    'https://api.piped.projectsegfau.lt',
    'https://pipedapi.ggtyler.dev',
    'https://api.piped.yt',
    'https://pipedapi.lunar.icu',
    'https://pipedapi.rivo.cc',
]

# Custom Piped instances from environment variable (takes priority)
CUSTOM_PIPED = [
    server.strip() for server in os.environ.get('CUSTOM_PIPED_SERVERS', '').split(',')
    if server.strip()
]
PIPED_SERVERS = CUSTOM_PIPED + DEFAULT_PIPED_SERVERS if CUSTOM_PIPED else DEFAULT_PIPED_SERVERS

# Download service endpoints from woolisbest-4520/about-youtube repository
DOWNLOAD_SERVICES = {
    'cobalt': {
        'name': 'Cobalt',
        'endpoint': 'https://api.cobalt.tools/api/json',
        'method': 'POST',
        'enabled': True
    },
    'y2mate': {
        'name': 'Y2Mate',
        'endpoints': [
            'https://www.y2mate.com/mates/analyzeV2/ajax',
            'https://www.y2mate.com/mates/convertV2/index'
        ],
        'enabled': True
    },
    'loader_to': {
        'name': 'Loader.to',
        'endpoint': 'https://loader.to/ajax/download.php',
        'enabled': True
    },
    'y2down': {
        'name': 'Y2Down',
        'endpoint': 'https://y2down.cc/api/ajaxSearch',
        'enabled': True
    },
    'savefrom': {
        'name': 'SaveFrom',
        'endpoint': 'https://worker.sf-tools.net/savefrom.net',
        'enabled': True
    }
}

def get_random_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS)
    }

def request_piped_api(path, timeout=(3, 7)):
    """Request API from Piped servers with better rotation and error handling"""
    # Use a fresh shuffle every time
    servers = list(PIPED_SERVERS)
    random.shuffle(servers)
    
    for server in servers[:4]:
        try:
            url = server.rstrip('/') + path
            res = http_session.get(url, headers=get_random_headers(), timeout=timeout)
            if res.status_code == 200:
                data = res.json()
                if data: return data
        except:
            continue
    return None

def get_download_service(service_name='cobalt'):
    """Get download service configuration from woolisbest-4520/about-youtube repository"""
    return DOWNLOAD_SERVICES.get(service_name, DOWNLOAD_SERVICES.get('cobalt', {}))

def _parse_piped_video_info(video_id, piped_data):
    """Parse Piped API video data into standard format"""
    # 関連動画を取得して処理（複数の形式に対応）
    related = []
    try:
        related_streams = piped_data.get('relatedStreams', [])
        for rel in related_streams[:20]:
            try:
                # videoIdの取得方法を複数サポート
                rel_video_id = None
                if rel.get('id'):
                    rel_video_id = rel.get('id')
                elif rel.get('url') and '=' in rel.get('url'):
                    rel_video_id = rel.get('url').split('=')[-1]
                elif rel.get('url'):
                    # URLの最後の部分がvideoId
                    rel_video_id = rel.get('url').split('/')[-1]
                
                if rel_video_id:
                    related.append({
                        'id': rel_video_id,
                        'title': rel.get('title', ''),
                        'author': rel.get('uploader', ''),
                        'authorId': rel.get('uploaderUrl', '').split('/')[-1] if '/' in rel.get('uploaderUrl', '') else '',
                        'views': str(rel.get('views', '')),
                        'thumbnail': rel.get('thumbnail', ''),
                        'length': str(datetime.timedelta(seconds=rel.get('duration', 0))) if rel.get('duration') else ''
                    })
            except Exception as e:
                print(f"Error parsing Piped related video: {e}")
                continue
    except Exception as e:
        print(f"Error processing Piped relatedStreams: {e}")
    
    return {
        'title': piped_data.get('title', ''),
        'description': piped_data.get('description', '').replace('\n', '<br>'),
        'author': piped_data.get('uploader', ''),
        'authorId': piped_data.get('uploaderUrl', '').split('/')[-1] if '/' in piped_data.get('uploaderUrl', '') else '',
        'authorThumbnail': piped_data.get('uploaderAvatar', ''),
        'views': piped_data.get('views', 0),
        'likes': piped_data.get('likes', 0),
        'subscribers': piped_data.get('uploaderSubscriber', False),
        'published': piped_data.get('uploadedDate', ''),
        'lengthText': str(datetime.timedelta(seconds=piped_data.get('duration', 0))),
        'related': related,
        'videoUrls': [],
        'streamUrls': [],
        'highstreamUrl': None,
        'audioUrl': None
    }

def get_cobalt_download(video_id, is_audio_only=False, quality='720'):
    """Get video download using Cobalt API (woolisbest-4520/about-youtube integration)"""
    try:
        cobalt_service = get_download_service('cobalt')
        if not cobalt_service.get('enabled'):
            return None
        
        endpoint = cobalt_service.get('endpoint', '')
        if not endpoint:
            return None
        
        payload = {
            'url': f'https://www.youtube.com/watch?v={video_id}',
            'vCodec': 'h264',
            'vQuality': quality,
            'aFormat': 'mp3',
            'isAudioOnly': is_audio_only,
            'filenamePattern': 'basic'
        }
        res = http_session.post(
            endpoint,
            json=payload,
            headers=get_random_headers(),
            timeout=10
        )
        
        if res.status_code == 200:
            data = res.json()
            if data.get('url'):
                return {
                    'url': data.get('url'),
                    'filename': data.get('filename', 'video'),
                    'service': 'cobalt'
                }
    except Exception as e:
        print(f"Cobalt API error: {e}")
    
    return None

def try_download_services(video_id, format_type='video', quality='720'):
    """Try multiple download services from woolisbest-4520/about-youtube repository"""
    is_audio_only = (format_type == 'audio' or format_type == 'mp3')
    
    # 優先順位: Cobalt → Y2Mate → Loader.to
    services_to_try = ['cobalt', 'y2mate']
    
    for service_name in services_to_try:
        service = get_download_service(service_name)
        if not service.get('enabled'):
            continue
        
        if service_name == 'cobalt':
            download = get_cobalt_download(video_id, is_audio_only, quality)
            if download:
                return download
        
        # Y2Mate フォールバック
        if service_name == 'y2mate':
            try:
                format_param = 'mp3' if is_audio_only else 'mp4'
                quality_param = '128' if is_audio_only else quality
                fallback_url = f"https://dl.y2mate.is/mates/convert?id={video_id}&format={format_param}&quality={quality_param}"
                return {
                    'url': fallback_url,
                    'filename': f'video_{video_id}',
                    'service': 'y2mate'
                }
            except Exception as e:
                print(f"Y2Mate service error: {e}")
                continue
    
    return None

def get_edu_params(source='siawaseok'):
    cache_duration = 300
    current_time = time.time()

    if source in _edu_params_cache and source in _edu_cache_timestamp:
        if (current_time - _edu_cache_timestamp[source]) < cache_duration:
            return _edu_params_cache[source]

    source_config = EDU_PARAM_SOURCES.get(source, EDU_PARAM_SOURCES['siawaseok'])
    
    try:
        res = http_session.get(source_config['url'], headers=get_random_headers(), timeout=3)
        res.raise_for_status()
        
        if source_config['type'] == 'kahoot_key':
            data = res.json()
            api_key = data.get('key', '')
            if api_key:
                params = f"autoplay=1&rel=0&modestbranding=1&key={api_key}"
            else:
                params = "autoplay=1&rel=0&modestbranding=1"
        else:
            data = res.json()
            params = data.get('params', '')
            if params.startswith('?'):
                params = params[1:]
            params = params.replace('&amp;', '&')
        
        _edu_params_cache[source] = params
        _edu_cache_timestamp[source] = current_time
        return params
    except Exception as e:
        print(f"Failed to fetch edu params from {source}: {e}")
        return "autoplay=1&rel=0&modestbranding=1"

def safe_request(url, timeout=(2, 5)):
    try:
        res = http_session.get(url, headers=get_random_headers(), timeout=timeout)
        res.raise_for_status()
        return res.json()
    except:
        return None

def request_invidious_api(path, timeout=(2, 5)):
    random_instances = random.sample(INVIDIOUS_INSTANCES, min(3, len(INVIDIOUS_INSTANCES)))
    for instance in random_instances:
        try:
            url = instance + 'api/v1' + path
            res = http_session.get(url, headers=get_random_headers(), timeout=timeout)
            if res.status_code == 200:
                return res.json()
        except:
            continue
    return None

def get_youtube_search(query, max_results=20, use_api_keys=True):
    global _current_api_key_index
    
    if use_api_keys and YOUTUBE_API_KEYS:
        for attempt in range(len(YOUTUBE_API_KEYS)):
            key_index = (_current_api_key_index + attempt) % len(YOUTUBE_API_KEYS)
            api_key = YOUTUBE_API_KEYS[key_index]
            url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&q={urllib.parse.quote(query)}&maxResults={max_results}&key={api_key}"
            try:
                res = http_session.get(url, timeout=5)
                if res.status_code == 403:
                    print(f"YouTube API key {key_index + 1} quota exceeded, trying next...")
                    continue
                res.raise_for_status()
                data = res.json()
                results = []
                for item in data.get('items', []):
                    snippet = item.get('snippet', {})
                    results.append({
                        'type': 'video',
                        'id': item.get('id', {}).get('videoId', ''),
                        'title': snippet.get('title', ''),
                        'author': snippet.get('channelTitle', ''),
                        'authorId': snippet.get('channelId', ''),
                        'thumbnail': f"https://i.ytimg.com/vi/{item.get('id', {}).get('videoId', '')}/hqdefault.jpg",
                        'published': snippet.get('publishedAt', ''),
                        'description': snippet.get('description', ''),
                        'views': '',
                        'length': ''
                    })
                _current_api_key_index = (key_index + 1) % len(YOUTUBE_API_KEYS)
                return results
            except Exception as e:
                print(f"YouTube API key {key_index + 1} error: {e}")
                continue
        
        print("All YouTube API keys failed, falling back to Invidious")
    
    return invidious_search(query)

def get_invidious_search_first(query, max_results=20):
    global _current_api_key_index
    
    results = invidious_search(query)
    if results:
        return results
    
    print("Invidious search failed, falling back to YouTube API")
    
    if YOUTUBE_API_KEYS:
        for attempt in range(len(YOUTUBE_API_KEYS)):
            key_index = (_current_api_key_index + attempt) % len(YOUTUBE_API_KEYS)
            api_key = YOUTUBE_API_KEYS[key_index]
            url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&q={urllib.parse.quote(query)}&maxResults={max_results}&key={api_key}"
            try:
                res = http_session.get(url, timeout=5)
                if res.status_code == 403:
                    print(f"YouTube API key {key_index + 1} quota exceeded, trying next...")
                    continue
                res.raise_for_status()
                data = res.json()
                results = []
                for item in data.get('items', []):
                    snippet = item.get('snippet', {})
                    results.append({
                        'type': 'video',
                        'id': item.get('id', {}).get('videoId', ''),
                        'title': snippet.get('title', ''),
                        'author': snippet.get('channelTitle', ''),
                        'authorId': snippet.get('channelId', ''),
                        'thumbnail': f"https://i.ytimg.com/vi/{item.get('id', {}).get('videoId', '')}/hqdefault.jpg",
                        'published': snippet.get('publishedAt', ''),
                        'description': snippet.get('description', ''),
                        'views': '',
                        'length': ''
                    })
                _current_api_key_index = (key_index + 1) % len(YOUTUBE_API_KEYS)
                return results
            except Exception as e:
                print(f"YouTube API key {key_index + 1} error: {e}")
                continue
    
    return []

def piped_search(query, page=1):
    """Search using Piped API (woolisbest-4520/about-youtube integration)"""
    path = f"/search?q={urllib.parse.quote(query)}&filter=videos"
    data = request_piped_api(path)

    if not data:
        return []

    results = []
    for item in data.get('items', []):
        if item.get('type') == 'stream':
            results.append({
                'type': 'video',
                'id': item.get('url', '').split('=')[-1] if '=' in item.get('url', '') else '',
                'title': item.get('title', ''),
                'author': item.get('uploader', ''),
                'authorId': item.get('uploaderUrl', '').split('/')[-1] if '/' in item.get('uploaderUrl', '') else '',
                'thumbnail': item.get('thumbnail', ''),
                'published': item.get('uploadedDate', ''),
                'views': str(item.get('views', '')),
                'length': str(datetime.timedelta(seconds=item.get('duration', 0))) if item.get('duration') else ''
            })
        elif item.get('type') == 'channel':
            results.append({
                'type': 'channel',
                'id': item.get('url', '').split('/')[-1] if '/' in item.get('url', '') else '',
                'author': item.get('name', ''),
                'thumbnail': item.get('avatar', ''),
                'subscribers': item.get('subscribers', 0)
            })

    return results

def invidious_search(query, page=1):
    path = f"/search?q={urllib.parse.quote(query)}&page={page}&hl=jp"
    data = request_invidious_api(path)

    if not data:
        return []

    results = []
    for item in data:
        item_type = item.get('type', '')

        if item_type == 'video':
            length_seconds = item.get('lengthSeconds', 0)
            results.append({
                'type': 'video',
                'id': item.get('videoId', ''),
                'title': item.get('title', ''),
                'author': item.get('author', ''),
                'authorId': item.get('authorId', ''),
                'thumbnail': f"https://i.ytimg.com/vi/{item.get('videoId', '')}/hqdefault.jpg",
                'published': item.get('publishedText', ''),
                'views': item.get('viewCountText', ''),
                'length': str(datetime.timedelta(seconds=length_seconds)) if length_seconds else ''
            })
        elif item_type == 'channel':
            thumbnails = item.get('authorThumbnails', [])
            thumb_url = thumbnails[-1].get('url', '') if thumbnails else ''
            if thumb_url and not thumb_url.startswith('https'):
                thumb_url = 'https:' + thumb_url
            results.append({
                'type': 'channel',
                'id': item.get('authorId', ''),
                'author': item.get('author', ''),
                'thumbnail': thumb_url,
                'subscribers': item.get('subCount', 0)
            })
        elif item_type == 'playlist':
            results.append({
                'type': 'playlist',
                'id': item.get('playlistId', ''),
                'title': item.get('title', ''),
                'thumbnail': item.get('playlistThumbnail', ''),
                'count': item.get('videoCount', 0)
            })

    return results

def get_ytdlp_video_info(video_id):
    """Get video info using yt-dlp (MIN-Tube2 integration) - tried first"""
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'socket_timeout': 20,
            'retries': 2,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            'geo_bypass': True,
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            if not info:
                return None
            
            # 関連動画情報の取得
            related_videos = []
            if 'related_videos' in info and info['related_videos']:
                for item in info['related_videos'][:20]:
                    try:
                        rel_video_id = item.get('id') or item.get('url', '').split('?v=')[-1].split('&')[0]
                        if rel_video_id:
                            related_videos.append({
                                'id': rel_video_id,
                                'title': item.get('title', ''),
                                'author': item.get('uploader', ''),
                                'authorId': item.get('channel_id', ''),
                                'views': str(item.get('view_count', '')),
                                'thumbnail': item.get('thumbnail', f"https://i.ytimg.com/vi/{rel_video_id}/mqdefault.jpg"),
                                'length': str(datetime.timedelta(seconds=item.get('duration', 0))) if item.get('duration') else ''
                            })
                    except Exception as e:
                        print(f"Error processing yt-dlp related video: {e}")
                        continue
            
            return {
                'title': info.get('title', ''),
                'description': info.get('description', '').replace('\n', '<br>'),
                'author': info.get('uploader', ''),
                'authorId': info.get('channel_id', ''),
                'authorThumbnail': info.get('uploader_url', ''),
                'views': info.get('view_count', 0),
                'likes': info.get('like_count', 0),
                'subscribers': '',
                'published': info.get('upload_date', ''),
                'lengthText': str(datetime.timedelta(seconds=info.get('duration', 0))),
                'related': related_videos,
                'videoUrls': [],
                'streamUrls': [],
                'highstreamUrl': None,
                'audioUrl': None,
                'duration': info.get('duration', 0),
                'source': 'yt-dlp'
            }
    except Exception as e:
        print(f"yt-dlp video info error for {video_id}: {e}")
    
    return None

def get_video_info(video_id):
    """Get video info with fallback support - yt-dlp first (MIN-Tube2 integration)"""
    # Try yt-dlp first (MIN-Tube2 integration)
    ydlp_data = get_ytdlp_video_info(video_id)
    if ydlp_data:
        return ydlp_data
    
    # Fallback to Invidious API
    path = f"/videos/{urllib.parse.quote(video_id)}"
    data = request_invidious_api(path, timeout=(5, 15))

    # Fallback to Piped API if Invidious fails
    if not data:
        piped_path = f"/streams/{urllib.parse.quote(video_id)}"
        piped_data = request_piped_api(piped_path, timeout=(5, 15))
        if piped_data:
            return _parse_piped_video_info(video_id, piped_data)

    if not data:
        try:
            res = http_session.get(f"{EDU_VIDEO_API}{video_id}", headers=get_random_headers(), timeout=(2, 6))
            res.raise_for_status()
            edu_data = res.json()

            related_videos = []
            for item in edu_data.get('related', [])[:20]:
                try:
                    vid_id = item.get('videoId', '')
                    if not vid_id:
                        continue
                    related_videos.append({
                        'id': vid_id,
                        'title': item.get('title', ''),
                        'author': item.get('channel', ''),
                        'authorId': item.get('channelId', ''),
                        'views': item.get('views', ''),
                        'thumbnail': f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg",
                        'length': ''
                    })
                except Exception as e:
                    print(f"Error processing EDU related video: {e}")
                    continue

            return {
                'title': edu_data.get('title', ''),
                'description': edu_data.get('description', {}).get('formatted', ''),
                'author': edu_data.get('author', {}).get('name', ''),
                'authorId': edu_data.get('author', {}).get('id', ''),
                'authorThumbnail': edu_data.get('author', {}).get('thumbnail', ''),
                'views': edu_data.get('views', ''),
                'likes': edu_data.get('likes', ''),
                'subscribers': edu_data.get('author', {}).get('subscribers', ''),
                'published': edu_data.get('relativeDate', ''),
                'related': related_videos,
                'streamUrls': [],
                'highstreamUrl': None,
                'audioUrl': None,
                'm3u8Url': None
            }
        except Exception as e:
            print(f"EDU Video API error: {e}")
            return None

    # 複数の形式の関連動画フィールドに対応
    recommended = data.get('recommendedVideos', data.get('recommendedvideo', data.get('recommended', [])))
    related_videos = []
    
    if recommended and isinstance(recommended, list):
        for item in recommended[:20]:
            try:
                if not isinstance(item, dict):
                    continue
                
                # videoIdを複数の形式でサポート
                rel_video_id = item.get('videoId', item.get('id', ''))
                if not rel_video_id:
                    continue
                
                length_seconds = item.get('lengthSeconds', item.get('duration', 0))
                
                # サムネイルURLの取得
                thumbnail = item.get('thumbnail', f"https://i.ytimg.com/vi/{rel_video_id}/mqdefault.jpg")
                if not thumbnail or thumbnail.startswith('http') is False:
                    thumbnail = f"https://i.ytimg.com/vi/{rel_video_id}/mqdefault.jpg"
                
                related_videos.append({
                    'id': rel_video_id,
                    'title': item.get('title', ''),
                    'author': item.get('author', item.get('uploader', '')),
                    'authorId': item.get('authorId', ''),
                    'views': item.get('viewCountText', item.get('views', '')),
                    'thumbnail': thumbnail,
                    'length': str(datetime.timedelta(seconds=length_seconds)) if length_seconds else ''
                })
            except Exception as e:
                print(f"Error processing Invidious related video: {e}")
                continue
    
    # If Invidious returned data but has no related videos, try Piped API for related videos
    if not related_videos:
        try:
            piped_path = f"/streams/{urllib.parse.quote(video_id)}"
            piped_data = request_piped_api(piped_path, timeout=(5, 15))
            if piped_data:
                piped_related = piped_data.get('relatedStreams', [])
                for rel in piped_related[:20]:
                    try:
                        rel_video_id = rel.get('id') or (rel.get('url').split('=')[-1] if '=' in rel.get('url', '') else rel.get('url', '').split('/')[-1])
                        if rel_video_id:
                            related_videos.append({
                                'id': rel_video_id,
                                'title': rel.get('title', ''),
                                'author': rel.get('uploader', ''),
                                'authorId': rel.get('uploaderUrl', '').split('/')[-1] if '/' in rel.get('uploaderUrl', '') else '',
                                'views': str(rel.get('views', '')),
                                'thumbnail': rel.get('thumbnail', ''),
                                'length': str(datetime.timedelta(seconds=rel.get('duration', 0))) if rel.get('duration') else ''
                            })
                    except Exception as e:
                        print(f"Error processing Piped related video from fallback: {e}")
                        continue
        except Exception as e:
            print(f"Error fetching Piped related videos as fallback: {e}")

    adaptive_formats = data.get('adaptiveFormats', [])
    stream_urls = []
    highstream_url = None
    audio_url = None

    for stream in adaptive_formats:
        if stream.get('container') == 'webm' and stream.get('resolution'):
            stream_urls.append({
                'url': stream.get('url', ''),
                'resolution': stream.get('resolution', '')
            })
            if stream.get('resolution') == '1080p' and not highstream_url:
                highstream_url = stream.get('url')
            elif stream.get('resolution') == '720p' and not highstream_url:
                highstream_url = stream.get('url')

    for stream in adaptive_formats:
        if stream.get('container') == 'm4a' and stream.get('audioQuality') == 'AUDIO_QUALITY_MEDIUM':
            audio_url = stream.get('url')
            break

    format_streams = data.get('formatStreams', [])
    video_urls = [stream.get('url', '') for stream in reversed(format_streams)][:2]

    author_thumbnails = data.get('authorThumbnails', [])
    author_thumbnail = author_thumbnails[-1].get('url', '') if author_thumbnails else ''

    return {
        'title': data.get('title', ''),
        'description': data.get('descriptionHtml', '').replace('\n', '<br>'),
        'author': data.get('author', ''),
        'authorId': data.get('authorId', ''),
        'authorThumbnail': author_thumbnail,
        'views': data.get('viewCount', 0),
        'likes': data.get('likeCount', 0),
        'subscribers': data.get('subCountText', ''),
        'published': data.get('publishedText', ''),
        'lengthText': str(datetime.timedelta(seconds=data.get('lengthSeconds', 0))),
        'related': related_videos,
        'videoUrls': video_urls,
        'streamUrls': stream_urls,
        'highstreamUrl': highstream_url,
        'audioUrl': audio_url
    }

def get_playlist_info(playlist_id):
    path = f"/playlists/{urllib.parse.quote(playlist_id)}"
    data = request_invidious_api(path, timeout=(5, 15))

    if not data:
        return None

    videos = []
    for item in data.get('videos', []):
        length_seconds = item.get('lengthSeconds', 0)
        videos.append({
            'type': 'video',
            'id': item.get('videoId', ''),
            'title': item.get('title', ''),
            'author': item.get('author', ''),
            'authorId': item.get('authorId', ''),
            'thumbnail': f"https://i.ytimg.com/vi/{item.get('videoId', '')}/hqdefault.jpg",
            'length': str(datetime.timedelta(seconds=length_seconds)) if length_seconds else ''
        })

    return {
        'id': playlist_id,
        'title': data.get('title', ''),
        'author': data.get('author', ''),
        'authorId': data.get('authorId', ''),
        'description': data.get('description', ''),
        'videoCount': data.get('videoCount', 0),
        'viewCount': data.get('viewCount', 0),
        'videos': videos
    }

def get_channel_info(channel_id):
    path = f"/channels/{urllib.parse.quote(channel_id)}"
    data = request_invidious_api(path, timeout=(5, 15))

    # リトライ機構：最初の試行が失敗した場合、別のインスタンスから再度試す
    if not data:
        try:
            random_instances = random.sample(INVIDIOUS_INSTANCES, min(2, len(INVIDIOUS_INSTANCES)))
            for instance in random_instances:
                try:
                    url = instance + 'api/v1' + path
                    res = http_session.get(url, headers=get_random_headers(), timeout=(4, 12))
                    if res.status_code == 200:
                        data = res.json()
                        break
                except:
                    continue
        except Exception as e:
            print(f"Channel info retry error: {e}")
    
    if not data:
        return None

    latest_videos = data.get('latestVideos', data.get('latestvideo', []))
    videos = []
    for item in latest_videos:
        try:
            length_seconds = item.get('lengthSeconds', 0)
            videos.append({
                'type': 'video',
                'id': item.get('videoId', ''),
                'title': item.get('title', ''),
                'author': data.get('author', ''),
                'authorId': data.get('authorId', ''),
                'published': item.get('publishedText', ''),
                'views': item.get('viewCountText', ''),
                'length': str(datetime.timedelta(seconds=length_seconds)) if length_seconds else ''
            })
        except Exception as e:
            print(f"Error processing channel video: {e}")
            continue

    author_thumbnails = data.get('authorThumbnails', [])
    author_thumbnail = author_thumbnails[-1].get('url', '') if author_thumbnails else ''

    author_banners = data.get('authorBanners', [])
    author_banner = urllib.parse.quote(author_banners[0].get('url', ''), safe='-_.~/:'
    ) if author_banners else ''

    return {
        'videos': videos,
        'channelName': data.get('author', ''),
        'channelIcon': author_thumbnail,
        'channelProfile': data.get('descriptionHtml', ''),
        'authorBanner': author_banner,
        'subscribers': data.get('subCount', 0),
        'tags': data.get('tags', []),
        'videoCount': data.get('videoCount', 0)
    }

def get_channel_videos(channel_id, continuation=None):
    path = f"/channels/{urllib.parse.quote(channel_id)}/videos"
    if continuation:
        path += f"?continuation={urllib.parse.quote(continuation)}"

    data = request_invidious_api(path, timeout=(5, 15))

    # リトライ機構：最初の試行が失敗した場合、別のインスタンスから再度試す
    if not data:
        try:
            random_instances = random.sample(INVIDIOUS_INSTANCES, min(2, len(INVIDIOUS_INSTANCES)))
            for instance in random_instances:
                try:
                    url = instance + 'api/v1' + path
                    res = http_session.get(url, headers=get_random_headers(), timeout=(4, 12))
                    if res.status_code == 200:
                        data = res.json()
                        break
                except:
                    continue
        except Exception as e:
            print(f"Channel videos retry error: {e}")
    
    if not data:
        return None

    videos = []
    for item in data.get('videos', []):
        try:
            length_seconds = item.get('lengthSeconds', 0)
            videos.append({
                'type': 'video',
                'id': item.get('videoId', ''),
                'title': item.get('title', ''),
                'author': item.get('author', ''),
                'authorId': item.get('authorId', ''),
                'published': item.get('publishedText', ''),
                'views': item.get('viewCountText', ''),
                'length': str(datetime.timedelta(seconds=length_seconds)) if length_seconds else ''
            })
        except Exception as e:
            print(f"Error processing channel video: {e}")
            continue

    return {
        'videos': videos,
        'continuation': data.get('continuation', '')
    }

def get_ytdlp_stream_url(video_id):
    """Get stream URL using yt-dlp (MIN-Tube2 integration) - tried first"""
    try:
        # Use more robust options to bypass bot detection
        opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'best[ext=mp4]/best',
            'socket_timeout': 30,
            'retries': 5,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
            },
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
            'geo_bypass': True,
            'geo_bypass_country': 'JP',
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Try to get direct info
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            if info:
                # Check for manifest_url (m3u8) or direct url
                url = info.get('url') or info.get('manifest_url')
                if url:
                    return {
                        'url': url,
                        'source': 'yt-dlp',
                        'title': info.get('title', ''),
                        'ext': info.get('ext', 'mp4'),
                        'is_m3u8': '.m3u8' in url
                    }
    except Exception as e:
        print(f"yt-dlp stream URL error for {video_id}: {e}")
    
    return None

def get_stream_url(video_id, edu_source='siawaseok'):
    edu_params = get_edu_params(edu_source)
    urls = {
        'primary': None,
        'fallback': None,
        'm3u8': None,
        'embed': f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1",
        'education': f"https://www.youtubeeducation.com/embed/{video_id}?{edu_params}"
    }

    # 1. Try yt-dlp with updated robust options (MIN-Tube2 style)
    ydlp_result = get_ytdlp_stream_url(video_id)
    if ydlp_result and ydlp_result.get('url'):
        if ydlp_result.get('is_m3u8'):
            urls['m3u8'] = ydlp_result['url']
        urls['primary'] = ydlp_result['url']
        # If we got a good URL, we can return early
        return urls

    # 2. Try Piped API for streams as fallback
    try:
        piped_data = request_piped_api(f"/streams/{video_id}")
        if piped_data:
            if piped_data.get('hls'):
                urls['m3u8'] = piped_data['hls']
            
            formats = piped_data.get('formats', [])
            for fmt in formats:
                if fmt.get('videoOnly') is False:
                    urls['fallback'] = fmt.get('url')
                    if not urls['primary']:
                        urls['primary'] = fmt.get('url')
                    break
    except:
        pass

    # 3. Last resort fallback to other APIs
    if not urls['primary']:
        try:
            res = http_session.get(f"{STREAM_API}{video_id}", headers=get_random_headers(), timeout=(3, 6))
            if res.status_code == 200:
                data = res.json()
                formats = data.get('formats', [])
                for fmt in formats:
                    if fmt.get('itag') == '18':
                        urls['primary'] = fmt.get('url')
                        break
        except:
            pass

    return urls

def get_ytdlp_comments(video_id):
    """Get comments using yt-dlp (MIN-Tube2 integration) - tried first"""
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'getcomments': True,
            'socket_timeout': 15,
            'retries': 2,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            'geo_bypass': True,
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            if info and 'comments' in info and info['comments']:
                comments = []
                for item in info['comments'][:50]:
                    try:
                        comments.append({
                            'author': item.get('author', {}).get('name') if isinstance(item.get('author'), dict) else item.get('author', ''),
                            'authorThumbnail': item.get('author', {}).get('thumbnails', [{}])[0].get('url', '') if isinstance(item.get('author'), dict) else '',
                            'authorId': item.get('author', {}).get('id', '') if isinstance(item.get('author'), dict) else '',
                            'content': item.get('text', '').replace('\n', '<br>'),
                            'likes': item.get('like_count', 0),
                            'published': item.get('time_text', '')
                        })
                    except Exception as e:
                        print(f"Error processing yt-dlp comment: {e}")
                        continue
                
                if comments:
                    return comments
    except Exception as e:
        print(f"yt-dlp comments error for {video_id}: {e}")
    
    return None

def get_comments(video_id):
    """Get comments - Piped first, then yt-dlp, then Invidious"""
    # 1. Try Piped API
    piped_data = request_piped_api(f"/comments/{video_id}")
    if piped_data and piped_data.get('comments'):
        comments = []
        for item in piped_data['comments'][:50]:
            comments.append({
                'author': item.get('author', ''),
                'authorThumbnail': item.get('thumbnail', ''),
                'authorId': item.get('authorId', ''),
                'content': item.get('commentText', '').replace('\n', '<br>'),
                'likes': item.get('likeCount', 0),
                'published': item.get('commentedText', '')
            })
        if comments: return comments

    # 2. Try yt-dlp
    ydlp_comments = get_ytdlp_comments(video_id)
    if ydlp_comments: return ydlp_comments
    
    # 3. Try Invidious
    path = f"/comments/{video_id}?hl=jp"
    data = request_invidious_api(path)
    if data and data.get('comments'):
        comments = []
        for item in data['comments'][:50]:
            comments.append({
                'author': item.get('author', ''),
                'authorThumbnail': item.get('authorThumbnails', [{}])[-1].get('url', ''),
                'authorId': item.get('authorId', ''),
                'content': item.get('contentHtml', '').replace('\n', '<br>'),
                'likes': item.get('likeCount', 0),
                'published': item.get('publishedText', '')
            })
        return comments
    
    return []

def get_trending():
    cache_duration = 300
    current_time = time.time()

    if _trending_cache['data'] and (current_time - _trending_cache['timestamp']) < cache_duration:
        return _trending_cache['data']

    path = "/popular"
    data = request_invidious_api(path, timeout=(2, 4))

    if data:
        results = []
        for item in data[:24]:
            if item.get('type') in ['video', 'shortVideo']:
                results.append({
                    'type': 'video',
                    'id': item.get('videoId', ''),
                    'title': item.get('title', ''),
                    'author': item.get('author', ''),
                    'thumbnail': f"https://i.ytimg.com/vi/{item.get('videoId', '')}/hqdefault.jpg",
                    'published': item.get('publishedText', ''),
                    'views': item.get('viewCountText', '')
                })
        if results:
            _trending_cache['data'] = results
            _trending_cache['timestamp'] = current_time
            return results

    default_videos = [
        {'type': 'video', 'id': 'dQw4w9WgXcQ', 'title': 'Rick Astley - Never Gonna Give You Up', 'author': 'Rick Astley', 'thumbnail': 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg', 'published': '', 'views': '17億 回視聴'},
        {'type': 'video', 'id': 'kJQP7kiw5Fk', 'title': 'Luis Fonsi - Despacito ft. Daddy Yankee', 'author': 'Luis Fonsi', 'thumbnail': 'https://i.ytimg.com/vi/kJQP7kiw5Fk/hqdefault.jpg', 'published': '', 'views': '80億 回視聴'},
        {'type': 'video', 'id': 'JGwWNGJdvx8', 'title': 'Ed Sheeran - Shape of You', 'author': 'Ed Sheeran', 'thumbnail': 'https://i.ytimg.com/vi/JGwWNGJdvx8/hqdefault.jpg', 'published': '', 'views': '64億 回視聴'},
        {'type': 'video', 'id': 'RgKAFK5djSk', 'title': 'Wiz Khalifa - See You Again ft. Charlie Puth', 'author': 'Wiz Khalifa', 'thumbnail': 'https://i.ytimg.com/vi/RgKAFK5djSk/hqdefault.jpg', 'published': '', 'views': '60億 回視聴'},
        {'type': 'video', 'id': 'OPf0YbXqDm0', 'title': 'Mark Ronson - Uptown Funk ft. Bruno Mars', 'author': 'Mark Ronson', 'thumbnail': 'https://i.ytimg.com/vi/OPf0YbXqDm0/hqdefault.jpg', 'published': '', 'views': '50億 回視聴'},
        {'type': 'video', 'id': '9bZkp7q19f0', 'title': 'PSY - Gangnam Style', 'author': 'PSY', 'thumbnail': 'https://i.ytimg.com/vi/9bZkp7q19f0/hqdefault.jpg', 'published': '', 'views': '50億 回視聴'},
        {'type': 'video', 'id': 'XqZsoesa55w', 'title': 'Baby Shark Dance', 'author': 'Pinkfong', 'thumbnail': 'https://i.ytimg.com/vi/XqZsoesa55w/hqdefault.jpg', 'published': '', 'views': '150億 回視聴'},
        {'type': 'video', 'id': 'fJ9rUzIMcZQ', 'title': 'Queen - Bohemian Rhapsody', 'author': 'Queen Official', 'thumbnail': 'https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg', 'published': '', 'views': '16億 回視聴'},
    ]
    return default_videos

def get_suggestions(keyword):
    try:
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={urllib.parse.quote(keyword)}"
        res = http_session.get(url, headers=get_random_headers(), timeout=2)
        if res.status_code == 200:
            data = res.json()
            return data[1] if len(data) > 1 else []
    except:
        pass
    return []

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = 'パスワードが間違っています'

    return render_template('login.html', error=error)

@app.route('/')
@login_required
def index():
    theme = request.cookies.get('theme', 'dark')
    return render_template('home.html', theme=theme)

@app.route('/trend')
@login_required
def trend():
    theme = request.cookies.get('theme', 'dark')
    trending = get_trending()
    return render_template('index.html', videos=trending, theme=theme)

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    page = request.args.get('page', '1')
    vc = request.cookies.get('vc', '1')
    proxy = request.cookies.get('proxy', 'False')
    theme = request.cookies.get('theme', 'dark')
    search_mode = request.cookies.get('search_mode', 'youtube')

    if not query:
        return render_template('search.html', results=[], query='', vc=vc, proxy=proxy, theme=theme, next='', search_mode=search_mode)

    if page == '1':
        if search_mode == 'invidious':
            results = get_invidious_search_first(query)
        else:
            results = get_youtube_search(query)
    else:
        results = invidious_search(query, int(page))
    
    next_page = f"/search?q={urllib.parse.quote(query)}&page={int(page) + 1}"

    return render_template('search.html', results=results, query=query, vc=vc, proxy=proxy, theme=theme, next=next_page, search_mode=search_mode)

@app.route('/watch')
@login_required
def watch():
    video_id = request.args.get('v', '')
    playlist_id = request.args.get('list', '')
    playlist_index = request.args.get('index', '0')
    theme = request.cookies.get('theme', 'dark')
    proxy = request.cookies.get('proxy', 'False')

    if not video_id:
        return render_template('index.html', videos=get_trending(), theme=theme)

    video_info = get_video_info(video_id)
    stream_urls = get_stream_url(video_id)
    comments = get_comments(video_id)

    playlist_videos = []
    playlist_title = ''
    if playlist_id:
        playlist_info = get_playlist_info(playlist_id)
        if playlist_info:
            playlist_videos = playlist_info.get('videos', [])
            playlist_title = playlist_info.get('title', '')

    return render_template('watch.html',
                         video_id=video_id,
                         video=video_info,
                         streams=stream_urls,
                         comments=comments,
                         mode='stream',
                         theme=theme,
                         proxy=proxy,
                         playlist_id=playlist_id,
                         playlist_index=int(playlist_index),
                         playlist_videos=playlist_videos,
                         playlist_title=playlist_title)

@app.route('/w')
@login_required
def watch_high_quality():
    video_id = request.args.get('v', '')
    playlist_id = request.args.get('list', '')
    playlist_index = request.args.get('index', '0')
    theme = request.cookies.get('theme', 'dark')
    proxy = request.cookies.get('proxy', 'False')

    if not video_id:
        return render_template('index.html', videos=get_trending(), theme=theme)

    video_info = get_video_info(video_id)
    stream_urls = get_stream_url(video_id)
    comments = get_comments(video_id)

    playlist_videos = []
    playlist_title = ''
    if playlist_id:
        playlist_info = get_playlist_info(playlist_id)
        if playlist_info:
            playlist_videos = playlist_info.get('videos', [])
            playlist_title = playlist_info.get('title', '')

    return render_template('watch.html',
                         video_id=video_id,
                         video=video_info,
                         streams=stream_urls,
                         comments=comments,
                         mode='high',
                         theme=theme,
                         proxy=proxy,
                         playlist_id=playlist_id,
                         playlist_index=int(playlist_index),
                         playlist_videos=playlist_videos,
                         playlist_title=playlist_title)

@app.route('/ume')
@login_required
def watch_embed():
    video_id = request.args.get('v', '')
    playlist_id = request.args.get('list', '')
    playlist_index = request.args.get('index', '0')
    theme = request.cookies.get('theme', 'dark')
    proxy = request.cookies.get('proxy', 'False')

    if not video_id:
        return render_template('index.html', videos=get_trending(), theme=theme)

    video_info = get_video_info(video_id)
    stream_urls = get_stream_url(video_id)
    comments = get_comments(video_id)

    playlist_videos = []
    playlist_title = ''
    if playlist_id:
        playlist_info = get_playlist_info(playlist_id)
        if playlist_info:
            playlist_videos = playlist_info.get('videos', [])
            playlist_title = playlist_info.get('title', '')

    return render_template('watch.html',
                         video_id=video_id,
                         video=video_info,
                         streams=stream_urls,
                         comments=comments,
                         mode='embed',
                         theme=theme,
                         proxy=proxy,
                         playlist_id=playlist_id,
                         playlist_index=int(playlist_index),
                         playlist_videos=playlist_videos,
                         playlist_title=playlist_title)

@app.route('/edu')
@login_required
def watch_education():
    video_id = request.args.get('v', '')
    playlist_id = request.args.get('list', '')
    playlist_index = request.args.get('index', '0')
    theme = request.cookies.get('theme', 'dark')
    proxy = request.cookies.get('proxy', 'False')
    edu_source = request.cookies.get('edu_source', 'siawaseok')

    if not video_id:
        return render_template('index.html', videos=get_trending(), theme=theme)

    video_info = get_video_info(video_id)
    stream_urls = get_stream_url(video_id, edu_source)
    comments = get_comments(video_id)

    playlist_videos = []
    playlist_title = ''
    if playlist_id:
        playlist_info = get_playlist_info(playlist_id)
        if playlist_info:
            playlist_videos = playlist_info.get('videos', [])
            playlist_title = playlist_info.get('title', '')

    return render_template('watch.html',
                         video_id=video_id,
                         video=video_info,
                         streams=stream_urls,
                         comments=comments,
                         mode='education',
                         theme=theme,
                         proxy=proxy,
                         playlist_id=playlist_id,
                         playlist_index=int(playlist_index),
                         playlist_videos=playlist_videos,
                         playlist_title=playlist_title,
                         edu_source=edu_source,
                         edu_sources=EDU_PARAM_SOURCES)

@app.route('/channel/<channel_id>')
@login_required
def channel(channel_id):
    theme = request.cookies.get('theme', 'dark')
    vc = request.cookies.get('vc', '1')
    proxy = request.cookies.get('proxy', 'False')

    channel_info = get_channel_info(channel_id)

    if not channel_info:
        return render_template('channel.html', channel=None, videos=[], theme=theme, vc=vc, proxy=proxy, channel_id=channel_id, continuation='', total_videos=0)

    channel_videos = get_channel_videos(channel_id)
    videos = channel_videos.get('videos', []) if channel_videos else channel_info.get('videos', [])
    continuation = channel_videos.get('continuation', '') if channel_videos else ''
    total_videos = channel_info.get('videoCount', 0)

    return render_template('channel.html',
                         channel=channel_info,
                         videos=videos,
                         theme=theme,
                         vc=vc,
                         proxy=proxy,
                         channel_id=channel_id,
                         continuation=continuation,
                         total_videos=total_videos)

@app.route('/tool')
@login_required
def tool_page():
    theme = request.cookies.get('theme', 'dark')
    return render_template('tool.html', theme=theme)

@app.route('/setting')
@login_required
def setting_page():
    theme = request.cookies.get('theme', 'dark')
    return render_template('setting.html', theme=theme, edu_sources=EDU_PARAM_SOURCES)

@app.route('/history')
@login_required
def history_page():
    theme = request.cookies.get('theme', 'dark')
    return render_template('history.html', theme=theme)

@app.route('/favorite')
@login_required
def favorite_page():
    theme = request.cookies.get('theme', 'dark')
    return render_template('favorite.html', theme=theme)

@app.route('/help')
@login_required
def help_page():
    theme = request.cookies.get('theme', 'dark')
    return render_template('help.html', theme=theme)

@app.route('/blog')
@login_required
def blog_page():
    theme = request.cookies.get('theme', 'dark')
    posts = [
         {
            'date': '2025-12-11',
            'category': 'お知らせ',
            'title': 'ついに公開',
            'excerpt': 'ついにチョコTubeが使えるように！',
            'content': '<p>エラーばっかり出るって？しゃーない僕の知識じゃな…詳しくいってくれないとわからん</p><p>あとは便利ツールとかゲームとか追加したいなぁ<br>何より使ってくれたらうれしい<br>ちなみに何か意見とか聞きたいこととかあったら<a href="https://scratch.mit.edu/projects/1252869725/">ここでコメント</a>してね。</p>'
        },
        {
            'date': '2025-11-30',
            'category': 'お知らせ',
            'title': 'チョコTubeへようこそ！',
            'excerpt': 'youtubeサイトを作ってみたよ～',
            'content': '<p>まだまだ実装には時間かかる</p><p>あとはbbs(チャット)とかゲームとか追加したいなぁ<br>ちなみに何か意見とか聞きたいこととかあったら<a href="https://scratch.mit.edu/projects/1252869725/">ここでコメント</a>してね。</p>'
        }
    ]
    return render_template('blog.html', theme=theme, posts=posts)

@app.route('/chat')
@login_required
def chat_page():
    theme = request.cookies.get('theme', 'dark')
    chat_server_url = os.environ.get('CHAT_SERVER_URL', '')
    return render_template('chat.html', theme=theme, chat_server_url=chat_server_url)

@app.route('/downloader')
@login_required
def downloader_page():
    theme = request.cookies.get('theme', 'dark')
    return render_template('downloader.html', theme=theme)

@app.route('/api/video-info/<video_id>')
@login_required
def api_video_info(video_id):
    info = get_video_info(video_id)
    if not info:
        return jsonify({'error': '動画情報を取得できませんでした'}), 404
    return jsonify(info)

@app.route('/api/download/<video_id>')
@login_required
def api_download(video_id):
    """Download endpoint using integrated download services (woolisbest-4520/about-youtube APIs)"""
    format_type = request.args.get('format', 'video')
    quality = request.args.get('quality', '720')

    # 実装したAPI関数を使用: 複数のダウンロードサービスを順に試す
    download = try_download_services(video_id, format_type, quality)
    
    if download and download.get('url'):
        return redirect(download['url'])
    
    # すべてのサービスが失敗した場合のフォールバック
    if format_type == 'audio' or format_type == 'mp3':
        fallback_url = f"https://dl.y2mate.is/mates/convert?id={video_id}&format=mp3&quality=128"
    else:
        fallback_url = f"https://dl.y2mate.is/mates/convert?id={video_id}&format=mp4&quality={quality}"
    
    return redirect(fallback_url)

DOWNLOAD_DIR = tempfile.gettempdir()

def sanitize_filename(filename):
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = filename.strip()
    if len(filename) > 100:
        filename = filename[:100]
    return filename

def cleanup_old_downloads():
    try:
        current_time = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith('chocotube_') and (f.endswith('.mp4') or f.endswith('.mp3')):
                filepath = os.path.join(DOWNLOAD_DIR, f)
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > 600:
                        os.remove(filepath)
    except Exception as e:
        print(f"Cleanup error: {e}")

def get_yt_dlp_base_opts(output_template, cookie_file=None):
    """YouTube bot対策を回避するための共通yt-dlpオプションを返す"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'outtmpl': output_template,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        },
        'socket_timeout': 60,
        'retries': 5,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'age_limit': None,
        'geo_bypass': True,
        'geo_bypass_country': 'JP',
    }
    if cookie_file:
        opts['cookiefile'] = cookie_file
    return opts

def create_youtube_cookies(cookie_file):
    """YouTube用のcookieファイルを作成する"""
    cookies_content = """# Netscape HTTP Cookie File
.youtube.com    TRUE    /       TRUE    2147483647      CONSENT PENDING+987
.youtube.com    TRUE    /       TRUE    2147483647      SOCS    CAESEwgDEgk2MjQyNTI1NzkaAmphIAEaBgiA_LyuBg
.youtube.com    TRUE    /       TRUE    2147483647      PREF    tz=Asia.Tokyo&hl=ja&gl=JP
.youtube.com    TRUE    /       TRUE    2147483647      GPS     1
.youtube.com    TRUE    /       TRUE    2147483647      YSC     DwKYllHNwuw
.youtube.com    TRUE    /       TRUE    2147483647      VISITOR_INFO1_LIVE      random_visitor_id
"""
    with open(cookie_file, 'w') as f:
        f.write(cookies_content)

@app.route('/api/internal-download/<video_id>')
@login_required
def api_internal_download(video_id):
    format_type = request.args.get('format', 'mp4')
    quality = request.args.get('quality', '720')

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    cleanup_old_downloads()

    unique_id = f"{video_id}_{int(time.time())}"
    cookie_file = os.path.join(DOWNLOAD_DIR, f'cookies_{unique_id}.txt')

    try:
        cookies_content = """# Netscape HTTP Cookie File
.youtube.com    TRUE    /       TRUE    2147483647      CONSENT PENDING+987
.youtube.com    TRUE    /       TRUE    2147483647      SOCS    CAESEwgDEgk2MjQyNTI1NzkaAmphIAEaBgiA_LyuBg
.youtube.com    TRUE    /       TRUE    2147483647      PREF    tz=Asia.Tokyo&hl=ja&gl=JP
.youtube.com    TRUE    /       TRUE    2147483647      GPS     1
.youtube.com    TRUE    /       TRUE    2147483647      YSC     DwKYllHNwuw
.youtube.com    TRUE    /       TRUE    2147483647      VISITOR_INFO1_LIVE      random_visitor_id
"""
        with open(cookie_file, 'w') as f:
            f.write(cookies_content)

        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'cookiefile': cookie_file,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
            },
            'socket_timeout': 60,
            'retries': 5,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
            'age_limit': None,
            'geo_bypass': True,
            'geo_bypass_country': 'JP',
        }

        if format_type == 'mp3':
            output_path = os.path.join(DOWNLOAD_DIR, f'chocotube_{unique_id}.mp3')
            ydl_opts = {
                **base_opts,
                'format': 'bestaudio',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f'chocotube_{unique_id}.%(ext)s'),
            }
        else:
            output_path = os.path.join(DOWNLOAD_DIR, f'chocotube_{unique_id}.mp4')
            format_string = f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best'
            ydl_opts = {
                **base_opts,
                'format': format_string,
                'outtmpl': os.path.join(DOWNLOAD_DIR, f'chocotube_{unique_id}.%(ext)s'),
                'merge_output_format': 'mp4',
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            title = sanitize_filename(info.get('title', video_id) if info else video_id)

        if os.path.exists(cookie_file):
            os.remove(cookie_file)

        if format_type == 'mp3':
            if os.path.exists(output_path):
                return send_file(
                    output_path,
                    as_attachment=True,
                    download_name=f"{title}.mp3",
                    mimetype='audio/mpeg'
                )
            for ext in ['mp3', 'webm', 'opus', 'm4a']:
                check_path = os.path.join(DOWNLOAD_DIR, f'chocotube_{unique_id}.{ext}')
                if os.path.exists(check_path):
                    if ext == 'm4a' and not os.path.exists(output_path):
                        converted_path = os.path.join(DOWNLOAD_DIR, f'chocotube_{unique_id}_converted.mp3')
                        try:
                            result = subprocess.run([
                                'ffmpeg', '-i', check_path, '-vn', '-ab', '192k', '-ar', '44100', '-y', converted_path
                            ], capture_output=True, timeout=300, check=False)
                            if os.path.exists(converted_path) and os.path.getsize(converted_path) > 0:
                                try:
                                    os.remove(check_path)
                                except:
                                    pass
                                return send_file(
                                    converted_path,
                                    as_attachment=True,
                                    download_name=f"{title}.mp3",
                                    mimetype='audio/mpeg'
                                )
                        except Exception as e:
                            print(f"MP3 conversion error: {e}")
                    if ext == 'mp3':
                        return send_file(
                            check_path,
                            as_attachment=True,
                            download_name=f"{title}.mp3",
                            mimetype='audio/mpeg'
                        )
        else:
            if os.path.exists(output_path):
                return send_file(
                    output_path,
                    as_attachment=True,
                    download_name=f"{title}.mp4",
                    mimetype='video/mp4'
                )
            for ext in ['mp4', 'mkv', 'webm']:
                check_path = os.path.join(DOWNLOAD_DIR, f'chocotube_{unique_id}.{ext}')
                if os.path.exists(check_path):
                    return send_file(
                        check_path,
                        as_attachment=True,
                        download_name=f"{title}.mp4",
                        mimetype='video/mp4'
                    )

        return jsonify({
            'success': False,
            'error': 'ファイルのダウンロードに失敗しました'
        }), 500

    except Exception as e:
        print(f"Internal download error: {e}")
        if os.path.exists(cookie_file):
            try:
                os.remove(cookie_file)
            except:
                pass
        return jsonify({
            'success': False,
            'error': f'ダウンロードエラー: {str(e)}'
        }), 500

@app.route('/api/stream/<video_id>')
@login_required
def api_stream(video_id):
    try:
        stream_url = f"https://siawaseok.duckdns.org/api/stream/{video_id}/type2"
        res = http_session.get(stream_url, headers=get_random_headers(), timeout=15)
        if res.status_code == 200:
            data = res.json()
            return jsonify(data)
        else:
            return jsonify({'error': 'ストリームデータの取得に失敗しました'}), res.status_code
    except Exception as e:
        print(f"Stream API error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/lite-download/<video_id>')
@login_required
def api_lite_download(video_id):
    format_type = request.args.get('format', 'mp4')
    quality = request.args.get('quality', '360')

    try:
        stream_url = f"https://siawaseok.duckdns.org/api/stream/{video_id}/type2"
        res = http_session.get(stream_url, headers=get_random_headers(), timeout=15)

        if res.status_code != 200:
            return jsonify({'error': 'ストリームデータの取得に失敗しました', 'success': False}), 500

        data = res.json()
        videourl = data.get('videourl', {})

        if format_type == 'mp3' or format_type == 'm4a':
            audio_url = None
            for q in ['144p', '240p', '360p', '480p', '720p']:
                if q in videourl and videourl[q].get('audio', {}).get('url'):
                    audio_url = videourl[q]['audio']['url']
                    break

            if audio_url:
                return jsonify({
                    'success': True,
                    'url': audio_url,
                    'format': 'mp3',
                    'quality': 'audio',
                    'actual_format': 'mp3'
                })
            else:
                return jsonify({'error': '音声URLが見つかりませんでした', 'success': False}), 404
        elif format_type == 'mp4':
            quality_order = [quality + 'p', '360p', '480p', '720p', '240p', '144p']
            video_url = None
            actual_quality = None

            for q in quality_order:
                if q in videourl and videourl[q].get('video', {}).get('url'):
                    video_url = videourl[q]['video']['url']
                    actual_quality = q
                    break

            if video_url:
                return jsonify({
                    'success': True,
                    'url': video_url,
                    'format': 'mp4',
                    'quality': actual_quality,
                    'actual_format': 'mp4'
                })
            else:
                return jsonify({'error': '動画URLが見つかりませんでした', 'success': False}), 404
        else:
            return jsonify({'error': '無効なフォーマットです', 'success': False}), 400

    except Exception as e:
        print(f"Lite download error: {e}")
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/thumbnail-download/<video_id>')
@login_required
def api_thumbnail_download(video_id):
    quality = request.args.get('quality', 'hq')

    quality_map = {
        'max': 'maxresdefault',
        'sd': 'sddefault',
        'hq': 'hqdefault',
        'mq': 'mqdefault',
        'default': 'default'
    }

    thumbnail_name = quality_map.get(quality, 'hqdefault')
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/{thumbnail_name}.jpg"

    try:
        res = http_session.get(thumbnail_url, headers=get_random_headers(), timeout=10)

        if res.status_code == 200 and len(res.content) > 1000:
            response = Response(res.content, mimetype='image/jpeg')
            response.headers['Content-Disposition'] = f'attachment; filename="{video_id}_{thumbnail_name}.jpg"'
            return response

        if quality != 'hq':
            fallback_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            res = http_session.get(fallback_url, headers=get_random_headers(), timeout=10)
            if res.status_code == 200:
                response = Response(res.content, mimetype='image/jpeg')
                response.headers['Content-Disposition'] = f'attachment; filename="{video_id}_hqdefault.jpg"'
                return response

        return jsonify({'error': 'サムネイルの取得に失敗しました', 'success': False}), 404

    except Exception as e:
        print(f"Thumbnail download error: {e}")
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/playlist')
@login_required
def playlist_page():
    playlist_id = request.args.get('list', '')
    theme = request.cookies.get('theme', 'dark')
    vc = request.cookies.get('vc', '1')

    if not playlist_id:
        return redirect(url_for('index'))

    playlist_info = get_playlist_info(playlist_id)

    if not playlist_info:
        return render_template('playlist.html', playlist=None, videos=[], theme=theme, vc=vc)

    return render_template('playlist.html',
                         playlist=playlist_info,
                         videos=playlist_info.get('videos', []),
                         theme=theme,
                         vc=vc)

@app.route('/thumbnail')
def thumbnail():
    video_id = request.args.get('v', '')
    if not video_id:
        return '', 404

    current_time = time.time()
    cache_key = video_id
    if cache_key in _thumbnail_cache:
        cached_data, cached_time = _thumbnail_cache[cache_key]
        if current_time - cached_time < 3600:
            response = Response(cached_data, mimetype='image/jpeg')
            response.headers['Cache-Control'] = 'public, max-age=3600'
            return response

    try:
        url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        res = http_session.get(url, headers=get_random_headers(), timeout=3)
        if len(_thumbnail_cache) > 500:
            oldest_key = min(_thumbnail_cache.keys(), key=lambda k: _thumbnail_cache[k][1])
            del _thumbnail_cache[oldest_key]
        _thumbnail_cache[cache_key] = (res.content, current_time)
        response = Response(res.content, mimetype='image/jpeg')
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response
    except:
        return '', 404

@app.route('/suggest')
def suggest():
    keyword = request.args.get('keyword', '')
    suggestions = get_suggestions(keyword)
    return jsonify(suggestions)

@app.route('/comments')
def comments_api():
    video_id = request.args.get('v', '')
    comments = get_comments(video_id)

    html = ''
    for comment in comments:
        html += f'''
        <div class="comment">
            <img src="{comment['authorThumbnail']}" alt="{comment['author']}" class="comment-avatar">
            <div class="comment-content">
                <div class="comment-header">
                    <a href="/channel/{comment['authorId']}" class="comment-author">{comment['author']}</a>
                    <span class="comment-date">{comment['published']}</span>
                </div>
                <div class="comment-text">{comment['content']}</div>
                <div class="comment-likes">👍 {comment['likes']}</div>
            </div>
        </div>
        '''

    return html if html else '<p class="no-comments">コメントはありません</p>'

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')
    if not query:
        return jsonify({'error': 'Query required'}), 400

    results = get_youtube_search(query)
    return jsonify(results)

@app.route('/api/video/<video_id>')
def api_video(video_id):
    info = get_video_info(video_id)
    streams = get_stream_url(video_id)
    return jsonify({'info': info, 'streams': streams})

@app.route('/api/trending')
def api_trending():
    videos = get_trending()
    return jsonify(videos)

@app.route('/api/channel/<channel_id>/videos')
def api_channel_videos(channel_id):
    continuation = request.args.get('continuation', '')
    result = get_channel_videos(channel_id, continuation if continuation else None)
    if not result:
        return jsonify({'videos': [], 'continuation': ''})
    return jsonify(result)

@app.route('/getcode')
@login_required
def getcode():
    theme = request.cookies.get('theme', 'dark')
    return render_template('getcode.html', theme=theme)

@app.route('/api/getcode')
@login_required
def api_getcode():
    url = request.args.get('url', '')

    if not url:
        return jsonify({'success': False, 'error': 'URLが必要です'})

    if not url.startswith('http://') and not url.startswith('https://'):
        return jsonify({'success': False, 'error': '有効なURLを入力してください'})

    try:
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

        res = http_session.get(url, headers=headers, timeout=15, allow_redirects=True)
        res.raise_for_status()

        content_type = res.headers.get('Content-Type', '')
        if 'text/html' in content_type or 'text/plain' in content_type or 'application/xml' in content_type or 'text/xml' in content_type:
            try:
                code = res.text
            except:
                code = res.content.decode('utf-8', errors='replace')
        else:
            code = res.content.decode('utf-8', errors='replace')

        return jsonify({
            'success': True,
            'url': url,
            'code': code,
            'status_code': res.status_code,
            'content_type': content_type
        })

    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'リクエストがタイムアウトしました'})
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': '接続エラーが発生しました'})
    except requests.exceptions.HTTPError as e:
        return jsonify({'success': False, 'error': f'HTTPエラー: {e.response.status_code}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'エラー: {str(e)}'})

CONVERTHUB_API_KEY = '155|hIxuoYFETaU54yeGE2zPWOw0NiSatCOhvJJYKy4Cb48c7d61'
TRANSLOADIT_API_KEY = 'R244EKuonluFkwhTYOu85vi6ZPm6mmZV'
TRANSLOADIT_SECRET = '4zVZ7eQm16qawPil8B4NJRr68kkCdMXQkd8NbNaq'
FREECONVERT_API_KEY = 'api_production_15cc009b9ac13759fb43f4946b3c950fee5e56e2f0214f242f6e9e4efc3093df.69393f3ea22aa85dd55c84ff.69393fa9142a194b36417393'
APIFY_API_TOKEN = 'apify_api_fpYkf6q1fqfJIz5S8bx4fcOeaP6CIM0iYpnu'

@app.route('/subscribed-channels')
@login_required
def subscribed_channels():
    return render_template('subscribed-channels.html')

@app.route('/proxy')
@login_required
def proxy_page():
    try:
        with open(os.path.join(os.path.dirname(__file__), 'templates', 'proxy.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        print(f"Proxy page error: {e}")
        return jsonify({'error': 'プロキシページの読み込みに失敗しました'}), 500

@app.route('/api/proxy')
@login_required
def api_proxy():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': '対象URLが指定されていません'}), 400
    
    if not url.startswith(('http://', 'https://')):
        return jsonify({'error': '有効なURLではありません'}), 400
    
    try:
        res = http_session.get(url, headers=get_random_headers(), timeout=(5, 15))
        return jsonify({'success': True, 'content': res.text}), 200
    except Exception as e:
        print(f"Proxy failed: {e}")
        return jsonify({'error': f'プロキシエラー: {str(e)}'}), 500

@app.route('/download-min-tube')
@login_required
def download_min_tube_page():
    """MIN-Tube2 style download UI using yt-dlp"""
    return render_template('download-min-tube.html')

@app.route('/api/download-info')
@login_required
def api_download_info():
    """Get video download information using yt-dlp (MIN-Tube2 integration)"""
    url = request.args.get('url', '')
    if not url:
        return jsonify({'error': 'URLが指定されていません'}), 400
    
    # Extract video ID if needed
    video_id = url
    if 'youtube.com' in url or 'youtu.be' in url:
        if 'v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
    
    try:
        # Use yt-dlp to get format information without downloading
        opts = {
            'quiet': True,
            'no_warnings': True,
            'dump_single_json': True,
            'simulate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            'socket_timeout': 30,
            'retries': 3,
            'geo_bypass': True,
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            if not info:
                return jsonify({'error': '動画情報を取得できませんでした'}), 404
            
            formats = []
            if 'formats' in info:
                for fmt in info['formats']:
                    if fmt.get('vcodec') != 'none' or fmt.get('acodec') != 'none':
                        formats.append({
                            'format_id': fmt.get('format_id', ''),
                            'format_note': fmt.get('format_note', f"{fmt.get('width', 'N/A')}x{fmt.get('height', 'N/A')}"),
                            'ext': fmt.get('ext', ''),
                            'width': fmt.get('width'),
                            'height': fmt.get('height'),
                            'fps': fmt.get('fps'),
                            'vcodec': fmt.get('vcodec'),
                            'acodec': fmt.get('acodec'),
                            'filesize': fmt.get('filesize', 0),
                        })
            
            return jsonify({
                'success': True,
                'video_id': video_id,
                'title': info.get('title', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', ''),
                'description': info.get('description', ''),
                'formats': formats[:20],
            })
    except Exception as e:
        print(f"Download info error: {e}")
        return jsonify({'error': f'エラー: {str(e)}'}), 500

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
