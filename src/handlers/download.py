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
    patterns = [
        r'https?://(?:www\.)?terabox\.com/s/',
        r'https?://(?:www\.)?terabox\.com/folder/',
        r'https?://(?:www\.)?terabox\.com/web/',
    ]
    
    url = url.strip()
    for pattern in patterns:
        if re.match(pattern, url):
            return url
    
    # If no pattern matches, return None
    return None


async def fetch_stream_url(terabox_url: str) -> Optional[Tuple[str, str]]:
    """
    Fetch streaming URL from iTeraPlay API
    Returns: (stream_url, filename) or (None, None) if failed
    """
    try:
        api_url = config.TERABOX_API.format(url=terabox_url)
        logger.info(f"Fetching stream URL for: {terabox_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=config.TIMEOUT)) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Parse the response (adjust based on actual API response structure)
                    if data.get("status") == "success" or "url" in data:
                        stream_url = data.get("url") or data.get("stream_url")
                        filename = data.get("filename") or data.get("title", "terabox_video.mp4")
                        
                        # Sanitize filename
                        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
                        if not filename.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                            filename += '.mp4'
                        
                        logger.info(f"Stream URL fetched successfully: {stream_url[:50]}...")
                        return stream_url, filename
                    else:
                        logger.warning(f"API response indicates failure: {data}")
                        return None, None
                else:
                    logger.error(f"API returned status code {response.status}")
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
