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
    """
    # Basic validation for Terabox URLs
    # Accept a broader set of terabox URLs to be more forgiving with formats
    url = url.strip()
    # Quick check that it looks like a URL and contains terabox
    if not url.lower().startswith(('http://', 'https://')):
        return None

    if 'terabox' in url.lower():
        return url

    # fallback: try to extract an http(s) URL from the text
    match = re.search(r'(https?://[^\s]+)', url)
    if match and 'terabox' in match.group(1).lower():
        return match.group(1)

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
                except Exception:
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
                        logger.info(f"Stream URL fetched successfully: {stream_url[:80]}")
                        return stream_url, filename

                # If not JSON or couldn't extract, try to read text and search for an URL
                text = await response.text()
                # Search for first http(s) URL in the response body
                url_match = re.search(r"(https?://[^\s\"'<>]+)", text)
                if url_match:
                    candidate = url_match.group(1)
                    filename = os.path.basename(urlparse(candidate).path) or 'terabox_video.mp4'
                    logger.info(f"Found candidate stream URL in response body: {candidate}")
                    return candidate, filename

                # Last fallback: use final response URL (after redirects)
                final_url = str(response.url)
                if final_url and final_url != api_url:
                    filename = os.path.basename(urlparse(final_url).path) or 'terabox_video.mp4'
                    logger.info(f"Using final response URL as stream: {final_url}")
                    return final_url, filename

                logger.warning("Unable to extract stream URL from API response")
                return None, None

    except asyncio.TimeoutError:
        logger.error("API request timed out")
        return None, None
    except Exception as e:
        logger.error(f"Error fetching stream URL: {e}")
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
        
        logger.info(f"Starting download: {filename}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                if response.status == 200:
                    # Check file size
                    content_length = response.content_length
                    if content_length and content_length > config.MAX_FILE_SIZE:
                        logger.error(f"File too large: {content_length} bytes")
                        return None
                    
                    # Download file
                    with open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                    
                    file_size = os.path.getsize(file_path)
                    logger.info(f"Download complete: {filename} ({file_size} bytes)")
                    return file_path
                else:
                    logger.error(f"Stream returned status code {response.status}")
                    return None
                    
    except asyncio.TimeoutError:
        logger.error("Download timed out")
        return None
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        if os.path.exists(file_path):
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
