"""
Download handler for Terabox videos
"""
import os
import re
import logging
import aiohttp
import asyncio
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
import config

logger = logging.getLogger(__name__)


async def extract_terabox_url(url: str) -> Optional[str]:
    """
    Extract valid Terabox URL from user input
    Supports:
    - Direct Terabox links
    - Share links
    - Folder links
    - Auto-corrects common domain typos (teraboxlink.com -> terabox.com)
    """
    url = url.strip()
    
    # Quick check that it looks like a URL
    if not url.lower().startswith(('http://', 'https://')):
        return None

    # Correct common domain typos/redirects
    # Many shortlinks or old links use teraboxlink.com which should be terabox.com
    url = re.sub(r'teraboxlink\.com', 'terabox.com', url, flags=re.IGNORECASE)
    
    # Ensure it's a terabox domain
    if 'terabox' in url.lower():
        return url

    return None


async def fetch_stream_url(terabox_url: str) -> Optional[Tuple[str, str]]:
    """
    Fetch streaming URL from iTeraPlay API
    Returns: (stream_url, filename) or (None, None) if failed
    """
    api_url = config.TERABOX_API.format(url=terabox_url)
    logger.info(f"Fetching stream URL for: {terabox_url} -> {api_url}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=config.TIMEOUT)) as response:
                logger.info(f"API Response Status: {response.status}")
                
                if response.status == 404:
                    logger.error(f"API returned 404 - Link may be invalid or expired")
                    return None, None
                    
                if response.status != 200:
                    logger.error(f"API returned status code {response.status}")
                    # Try to fallback to response URL if it redirected
                    if response.url and str(response.url) != api_url:
                        candidate = str(response.url)
                        logger.info(f"Using redirect URL as candidate stream: {candidate}")
                        return candidate, os.path.basename(urlparse(candidate).path) or 'terabox_video.mp4'
                    return None, None

                # Try JSON first
                try:
                    data = await response.json()
                except Exception as e:
                    logger.debug(f"Response is not JSON: {e}")
                    data = None

                # If JSON present, try a few common shapes
                if isinstance(data, dict):
                    # common keys in different APIs
                    stream_url = None
                    filename = None

                    # Direct url fields
                    for key in ("url", "stream_url", "play_url", "video_url"):
                        if key in data and data[key]:
                            stream_url = data[key]
                            break

                    # Some APIs wrap values under 'data' or 'result'
                    if not stream_url and isinstance(data.get('data'), dict):
                        for key in ("url", "stream_url", "play_url", "video_url"):
                            if key in data['data'] and data['data'][key]:
                                stream_url = data['data'][key]
                                break

                    # filename/title
                    for key in ("filename", "title", "name"):
                        if key in data and data[key]:
                            filename = data[key]
                            break
                    if not filename and isinstance(data.get('data'), dict):
                        for key in ("filename", "title", "name"):
                            if key in data['data'] and data['data'][key]:
                                filename = data['data'][key]
                                break

                    if stream_url:
                        filename = filename or os.path.basename(urlparse(stream_url).path) or 'terabox_video.mp4'
                        filename = re.sub(r'[<>:\"/\\|?*]', '', filename)
                        if not filename.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                            filename += '.mp4'
                        logger.info(f"Stream URL fetched from JSON: {stream_url[:80]}")
                        return stream_url, filename

                # If not JSON or couldn't extract, try to read text and search for video URLs
                text = await response.text()
                logger.debug(f"Response text length: {len(text)} bytes")
                
                # First priority: Look for videoQualities (standard TeraBox player format)
                # Try different resolution options in order of preference
                for resolution in ["360p", "480p", "720p", "1080p", "playUrl"]:
                    pattern = rf'"{resolution}"\s*:\s*"([^"]+)"'
                    match = re.search(pattern, text)
                    if match:
                        stream_url = match.group(1)
                        # Unescape forward slashes
                        stream_url = stream_url.replace('\\/', '/')
                        filename = f'terabox_video_{resolution}.mp4'
                        logger.info(f"Found {resolution} stream URL: {stream_url[:80]}")
                        return stream_url, filename
                
                # Search for m3u8 (HLS stream) URLs - handle escaped JSON strings too
                m3u8_patterns = [
                    r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)',  # plain URL
                    r'"([^"]*\.m3u8[^"]*)"',  # m3u8 inside quotes
                ]
                for pattern in m3u8_patterns:
                    m3u8_match = re.search(pattern, text)
                    if m3u8_match:
                        stream_url = m3u8_match.group(1)
                        # Unescape if necessary
                        stream_url = stream_url.replace('\\/', '/').replace('\\:', ':')
                        filename = 'terabox_video.mp4'
                        logger.info(f"Found m3u8 stream URL: {stream_url[:80]}")
                        return stream_url, filename
                
                # Search for mp4 URLs
                mp4_patterns = [
                    r'(https?://[^\s"\'<>]*\.mp4[^\s"\'<>]*)',  # plain URL
                    r'"([^"]*\.mp4[^"]*)"',  # mp4 inside quotes
                ]
                for pattern in mp4_patterns:
                    mp4_match = re.search(pattern, text)
                    if mp4_match:
                        stream_url = mp4_match.group(1)
                        stream_url = stream_url.replace('\\/', '/').replace('\\:', ':')
                        filename = os.path.basename(urlparse(stream_url).path) or 'terabox_video.mp4'
                        logger.info(f"Found mp4 stream URL: {stream_url[:80]}")
                        return stream_url, filename

                logger.warning(f"Unable to extract stream URL from API response (response length: {len(text)})")
                return None, None

    except asyncio.TimeoutError:
        logger.error("API request timed out")
        return None, None
    except Exception as e:
        logger.error(f"Error fetching stream URL: {e}", exc_info=True)
        return None, None


async def download_video(stream_url: str, filename: str) -> Optional[str]:
    """
    Download video from stream URL
    Returns: file path if successful, None otherwise
    """
    try:
        # Ensure download directory exists
        Path(config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        file_path = os.path.join(config.DOWNLOAD_DIR, filename)
        
        logger.info(f"Starting download: {filename} from {stream_url[:100]}")
        
        # Headers to mimic a browser and improve compatibility
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://iteraplay.com/',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=600), ssl=False, allow_redirects=True) as response:
                logger.info(f"Download Response Status: {response.status}")
                logger.info(f"Content-Length: {response.content_length}")
                
                if response.status != 200:
                    logger.error(f"Stream returned status code {response.status}")
                    return None
                
                # Check file size before downloading
                content_length = response.content_length
                if content_length and content_length > config.MAX_FILE_SIZE:
                    logger.error(f"File too large: {content_length} bytes (max: {config.MAX_FILE_SIZE})")
                    return None
                
                # Download file with progress tracking
                downloaded_size = 0
                with open(file_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(65536):  # 64KB chunks
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if downloaded_size % (1024 * 1024) == 0:  # Log every 1MB
                                logger.debug(f"Downloaded {downloaded_size / (1024*1024):.1f}MB")
                
                file_size = os.path.getsize(file_path)
                
                # Validate that we got a real video file
                if file_size < 1000:  # Less than 1KB is almost certainly not a real video
                    logger.error(f"Downloaded file is suspiciously small: {file_size} bytes - likely dummy/error response")
                    os.remove(file_path)
                    return None
                
                logger.info(f"Download complete: {filename} ({file_size} bytes / {file_size/(1024*1024):.1f}MB)")
                return file_path
                    
    except asyncio.TimeoutError:
        logger.error("Download timed out")
        if os.path.exists(file_path):
            os.remove(file_path)
        return None
    except Exception as e:
        logger.error(f"Error downloading video: {e}", exc_info=True)
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        return None


async def process_terabox_link(url: str) -> Optional[Tuple[str, str]]:
    """
    Complete pipeline: validate -> fetch stream -> download
    Returns: (file_path, filename) or (None, None)
    """
    # Validate URL
    terabox_url = await extract_terabox_url(url)
    if not terabox_url:
        logger.warning(f"Invalid Terabox URL: {url}")
        return None, None
    
    # Fetch stream URL
    stream_url, filename = await fetch_stream_url(terabox_url)
    if not stream_url:
        logger.warning("Failed to fetch stream URL")
        return None, None
    
    # Download video
    file_path = await download_video(stream_url, filename)
    if not file_path:
        logger.warning("Failed to download video")
        return None, None
    
    return file_path, filename
