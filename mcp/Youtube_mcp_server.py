import os
import sys
import re
import json
import traceback
from typing import Tuple, Dict, Any
import logging
from jinja2 import Template
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import requests
import subprocess
from urllib.parse import urlparse, parse_qs
import asyncio

# --------------------------------
# Configuration
# --------------------------------
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("youtube_mcp_server.log"), 
                              logging.StreamHandler()])
logger = logging.getLogger("youtube-mcp-server")

# Enable asyncio debug mode if using Python 3.8+
if sys.version_info >= (3, 8):
    asyncio.get_event_loop().set_debug(True)

GEMINI_API_KEY = "your_gemini_api_key"
GEMINI_MODEL_NAME = "gemini-1.5-flash-latest"
YOUTUBE_API_KEY = "your_youtube_api_key"

# Get script directory for relative paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "prompt.jinja")
if not os.path.exists(PROMPT_TEMPLATE_PATH):
    PROMPT_TEMPLATE_PATH = "E:\\autogen_folder\\Youtube-Vision-MCP-main\\dist\\prompt.jinja"
    # Fall back to absolute path if relative path doesn't exist
    logger.warning(f"Using fallback prompt template path: {PROMPT_TEMPLATE_PATH}")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(SCRIPT_DIR, "output"))
os.makedirs(OUTPUT_DIR, exist_ok=True)
logger.info(f"Using output directory: {OUTPUT_DIR}")

mcp = FastMCP(name="youtube-vision-mcp-server", version="0.2.0")

# --------------------------------
# Utilities
# --------------------------------
def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    if not url or not isinstance(url, str):
        raise ValueError(f"Invalid YouTube URL: {url}")
        
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    query = parse_qs(urlparse(url).query)
    video_id = query.get("v", [None])[0]
    
    if not video_id:
        raise ValueError(f"Could not extract video ID from URL: {url}")
    
    return video_id

def is_video_downloaded(video_id: str) -> str:
    """Check if video is already downloaded and return folder path."""
    if not os.path.exists(OUTPUT_DIR):
        return ""
        
    for root, dirs, files in os.walk(OUTPUT_DIR):
        if f"{video_id}.mkv" in files:
            logger.info(f"Found existing video {video_id} in {root}")
            return root
    return ""

def check_yt_dlp_installed() -> bool:
    """Check if yt-dlp is installed."""
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, capture_output=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.error("yt-dlp not found. Please install it with: pip install yt-dlp")
        return False

def download_video(video_id: str, folder: str) -> str:
    """Download YouTube video using yt-dlp."""
    if not check_yt_dlp_installed():
        raise RuntimeError("yt-dlp is not installed or not available in PATH")
    
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{video_id}.mkv")
    if os.path.exists(path):
        logger.info(f"✅ Video already exists at {path}")
        return path

    url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info(f"📥 Starting download for video {video_id} to folder {folder}")

    try:
        result = subprocess.run(
            [
                "yt-dlp", "-f", "bv+ba",
                "-o", os.path.join(folder, f"{video_id}.%(ext)s"),
                "--merge-output-format", "mkv", url
            ],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"✅ yt-dlp stdout for {video_id}:\n{result.stdout}")
        logger.info(f"✅ yt-dlp stderr for {video_id}:\n{result.stderr}")
        logger.info(f"🎬 Download completed for {video_id}")
        return path

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ yt-dlp failed for {video_id}: {e}")
        logger.error(f"❌ yt-dlp stderr: {e.stderr}")
        logger.error(f"❌ yt-dlp stdout: {e.stdout}")
        raise RuntimeError(f"Failed to download video '{video_id}': {e.stderr.strip()}")

def download_transcript(video_id: str, folder: str) -> str:
    """Download video transcript."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{video_id}_transcript.txt")
    if os.path.exists(path):
        logger.info(f"Transcript already exists at {path}")
        return path
        
    try:
        logger.info(f"Downloading transcript for {video_id}")
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        with open(path, "w", encoding="utf-8") as f:
            for entry in transcript:
                start_seconds = int(entry['start'])
                timestamp = str(datetime.utcfromtimestamp(start_seconds).strftime('%H:%M:%S'))
                f.write(f"[{timestamp}] {entry['text']}\n")
        logger.info(f"Transcript downloaded to {path}")
        return path
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        logger.warning(f"No transcript available for {video_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error downloading transcript for {video_id}: {e}")
        return None

def fetch_metadata(video_id: str, folder: str) -> str:
    """Fetch video metadata using YouTube API."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{video_id}_metadata.json")
    if os.path.exists(path):
        logger.info(f"Metadata already exists at {path}")
        return path
        
    try:
        logger.info(f"Fetching metadata for {video_id}")
        url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={YOUTUBE_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        data = response.json()
        if not data.get("items"):
            raise ValueError(f"No video data found for ID {video_id}")
            
        snippet = data["items"][0]["snippet"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snippet, f, indent=2)
        logger.info(f"Metadata saved to {path}")
        return path
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed for video {video_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        raise RuntimeError(f"Failed to fetch video metadata: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching metadata for {video_id}: {e}")
        raise

def generate_summary(video_id: str, folder: str) -> str:
    """Generate a summary of the video using Gemini API."""
    json_path = os.path.join(folder, f"{video_id}.json")
    if os.path.exists(json_path):
        logger.info(f"Summary already exists at {json_path}")
        return json_path

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        # Load metadata
        with open(os.path.join(folder, f"{video_id}_metadata.json"), "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        # Load template
        if not os.path.exists(PROMPT_TEMPLATE_PATH):
            raise FileNotFoundError(f"Prompt template not found at {PROMPT_TEMPLATE_PATH}")
            
        with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            template = Template(f.read())
            
        prompt = template.render(video_url=video_url, video_metadata=json.dumps(metadata, indent=2))
        
        # Call Gemini API
        logger.info(f"Calling Gemini API for video {video_id}")
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_NAME}:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "fileData": {
                                "mimeType": "video/youtube",
                                "fileUri": video_url
                            }
                        }
                    ]
                }]
            }
        )
        
        # Log raw response for debugging
        response_json = response.json()
        logger.debug(f"Gemini raw response: {json.dumps(response_json, indent=2)}")
        
        # Check for API errors
        if response.status_code != 200:
            raise RuntimeError(f"Gemini API returned status code {response.status_code}: {response.text}")
            
        # Parse response
        if "candidates" not in response_json or not response_json["candidates"]:
            raise ValueError(f"No candidates in Gemini API response: {response_json}")
            
        # Extract text content
        text = response_json["candidates"][0]["content"]["parts"][0]["text"]
        
        # Save summary
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        logger.info(f"Summary generated and saved to {json_path}")
        return json_path
        
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception(f"❌ Failed to generate summary for {video_id}: {e}")
        logger.error(f"Traceback:\n{tb}")
        raise RuntimeError(f"Failed to generate summary: {str(e)}")


async def ensure_video_content(video_url: str) -> Tuple[str, str]:
    try:
        video_id = extract_video_id(video_url)
        logger.info(f"🔍 Extracted video ID: {video_id} from URL: {video_url}")

        folder = is_video_downloaded(video_id)
        if not folder:
            folder = os.path.join(OUTPUT_DIR, "videos", video_id)
            logger.info(f"📥 Creating new folder for content: {folder}")
            os.makedirs(folder, exist_ok=True)

            # 🆕 Ensure each step completes in sequence and logs outcome
            logger.info(f"📥 Downloading video for {video_id}")
            video_path = await asyncio.to_thread(download_video, video_id, folder)
            logger.info(f"📼 Video downloaded successfully to {video_path}")

            logger.info(f"📥 Downloading transcript for {video_id}")
            transcript_path = await asyncio.to_thread(download_transcript, video_id, folder)
            logger.info(f"📝 Transcript downloaded: {transcript_path}")

            logger.info(f"📥 Fetching metadata for {video_id}")
            metadata_path = await asyncio.to_thread(fetch_metadata, video_id, folder)
            logger.info(f"📋 Metadata fetched: {metadata_path}")

            logger.info(f"📥 Generating summary for {video_id}")
            summary_path = await asyncio.to_thread(generate_summary, video_id, folder)
            logger.info(f"🧠 Summary generated at: {summary_path}")

        else:
            logger.info(f"📦 Content already exists. Skipping download.")

        return video_id, folder

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"❌ Exception in `ensure_video_content` for video URL {video_url}: {e}")
        logger.error(f"Traceback:\n{tb}")
        raise RuntimeError(f"Failed to ensure video content: {str(e)}")



# --------------------------------
# MCP Tools
# --------------------------------
@mcp.tool()
async def download_youtube_content(youtube_url: str) -> Dict[str, Any]:
    """Download YouTube video content."""
    try:
        logger.info(f"🛠️ Tool `download_youtube_content` received: {youtube_url}")
        
        # Validate URL
        if not youtube_url or not isinstance(youtube_url, str):
            raise ValueError(f"Invalid YouTube URL provided: {youtube_url}")
            
        # Process video content
        video_id, folder = await ensure_video_content(youtube_url)
        
        # Return success response
        return {
            "content": [{
                "type": "text",
                "text": f"✅ Successfully downloaded and saved content for video ID {video_id} in {folder}"
            }]
        }
    except Exception as e:
        # Capture full traceback
        tb = traceback.format_exc()
        logger.error(f"❌ Exception in `download_youtube_content`: {e}")
        logger.error(f"Traceback:\n{tb}")
        
        # Return error response
        return {
            "content": [{
                "type": "text",
                "text": f"❌ Failed to download YouTube content: {str(e)}\n\nDebug information for developer:\n{tb}"
            }],
            "isError": True
        }

@mcp.tool()
async def summarize_youtube_video(youtube_url: str) -> Dict[str, Any]:
    """Summarize YouTube video content."""
    try:
        logger.info(f"🛠️ Tool `summarize_youtube_video` received: {youtube_url}")
        
        # Process video content
        video_id, folder = await ensure_video_content(youtube_url)
        
        # Get summary file
        summary_path = os.path.join(folder, f"{video_id}.json")
        if not os.path.exists(summary_path):
            logger.warning(f"Summary not found for {video_id}. Generating now.")
            summary_path = generate_summary(video_id, folder)
            
        # Read summary content
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_content = f.read()
            
        # Return summary response
        return {
            "content": [{
                "type": "text", 
                "text": f"Summary of video {video_id}:\n\n{summary_content}"
            }]
        }
    except Exception as e:
        # Capture full traceback
        tb = traceback.format_exc()
        logger.error(f"❌ Exception in `summarize_youtube_video`: {e}")
        logger.error(f"Traceback:\n{tb}")
        
        # Return error response
        return {
            "content": [{
                "type": "text",
                "text": f"❌ Failed to summarize YouTube video: {str(e)}\n\nDebug information for developer:\n{tb}"
            }],
            "isError": True
        }

@mcp.tool()
async def extract_key_moments(youtube_url: str) -> Dict[str, Any]:
    """Extract key moments from YouTube video transcript."""
    try:
        logger.info(f"🛠️ Tool `extract_key_moments` received: {youtube_url}")
        
        # Process video content
        video_id, folder = await ensure_video_content(youtube_url)
        
        # Check for transcript
        transcript_path = os.path.join(folder, f"{video_id}_transcript.txt")
        if not os.path.exists(transcript_path):
            warning_msg = f"⚠️ Transcript not available for video {video_id}. Cannot extract key moments."
            logger.warning(warning_msg)
            return {
                "content": [{"type": "text", "text": warning_msg}],
                "isError": True
            }
            
        # Read transcript
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_lines = f.readlines()
            
        # TODO: Implement better key moment extraction logic
        # Currently just returning the first few lines as a placeholder
        key_lines = transcript_lines[:10] if len(transcript_lines) >= 10 else transcript_lines
        key_moments = "".join(key_lines)
        
        # Return key moments
        return {
            "content": [{
                "type": "text",
                "text": f"Key moments from video {video_id}:\n\n{key_moments}"
            }]
        }
    except Exception as e:
        # Capture full traceback
        tb = traceback.format_exc()
        logger.error(f"❌ Exception in `extract_key_moments`: {e}")
        logger.error(f"Traceback:\n{tb}")
        
        # Return error response
        return {
            "content": [{
                "type": "text",
                "text": f"❌ Failed to extract key moments: {str(e)}\n\nDebug information for developer:\n{tb}"
            }],
            "isError": True
        }

@mcp.tool()
async def ask_about_youtube_video(youtube_url: str, question: str = None) -> Dict[str, Any]:
    """Ask questions about a YouTube video."""
    try:
        logger.info(f"🛠️ Tool `ask_about_youtube_video` received: {youtube_url}, Question: {question}")
        
        # Process video content
        video_id, folder = await ensure_video_content(youtube_url)
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Set default question if none provided
        if not question:
            question = "What is this video about?"
            
        # Load available data
        metadata = {}
        transcript = ""
        summary = ""
        
        # Load metadata
        metadata_path = os.path.join(folder, f"{video_id}_metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
                
        # Load transcript
        transcript_path = os.path.join(folder, f"{video_id}_transcript.txt")
        if os.path.exists(transcript_path):
            with open(transcript_path, "r", encoding="utf-8") as f:
                transcript = f.read()
                
        # Load summary
        summary_path = os.path.join(folder, f"{video_id}.json")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = f.read()
                
        # Prepare context for Gemini
        context_parts = []
        if summary:
            context_parts.append(f"📄 Summary:\n{summary}")
        if transcript:
            # Limit transcript length to avoid token limits
            context_parts.append(f"📝 Transcript (excerpt):\n{transcript[:3000]}")
        if metadata:
            context_parts.append(f"📋 Metadata:\n{json.dumps(metadata, indent=2)}")
            
        combined_context = "\n\n".join(context_parts)
        
        # Prepare prompt
        prompt = (
            f"You are provided with content from a YouTube video.\n\n"
            f"{combined_context}\n\n"
            f"Now please answer the following question:\n"
            f"❓ Question: {question}"
        )
        
        # Call Gemini API
        logger.info(f"Sending query to Gemini API for video {video_id}")
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_NAME}:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "fileData": {
                                "mimeType": "video/youtube",
                                "fileUri": video_url
                            }
                        }
                    ]
                }]
            }
        )
        
        # Log raw response for debugging
        response_json = response.json()
        logger.debug(f"Gemini raw response: {json.dumps(response_json, indent=2)}")
        
        # Check for API errors
        if response.status_code != 200:
            raise RuntimeError(f"Gemini API returned status code {response.status_code}: {response.text}")
            
        # Parse response
        if "candidates" not in response_json or not response_json["candidates"]:
            raise ValueError(f"No candidates in Gemini API response: {response_json}")
            
        # Extract answer text
        answer = response_json["candidates"][0]["content"]["parts"][0]["text"]
        
        # Return answer
        return {
            "content": [{
                "type": "text",
                "text": f"Answer to '{question}':\n\n{answer}"
            }]
        }
    except Exception as e:
        # Capture full traceback
        tb = traceback.format_exc()
        logger.error(f"❌ Exception in `ask_about_youtube_video`: {e}")
        logger.error(f"Traceback:\n{tb}")
        
        # Return error response
        return {
            "content": [{
                "type": "text",
                "text": f"❌ Failed to answer question about video: {str(e)}\n\nDebug information for developer:\n{tb}"
            }],
            "isError": True
        }

# --------------------------------
# Run MCP Server
# --------------------------------
if __name__ == "__main__":
    logger.info("🚀 Starting YouTube MCP server...")
    try:
        # Create necessary directories
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        videos_dir = os.path.join(OUTPUT_DIR, "videos")
        os.makedirs(videos_dir, exist_ok=True)
        
        # Verify paths
        logger.info(f"📂 Output directory: {OUTPUT_DIR}")
        logger.info(f"📝 Prompt template path: {PROMPT_TEMPLATE_PATH}")
        if not os.path.exists(PROMPT_TEMPLATE_PATH):
            logger.warning(f"⚠️ Prompt template not found at: {PROMPT_TEMPLATE_PATH}")
            
        # Check for dependencies
        check_yt_dlp_installed()
        
        # Start MCP server
        logger.info("🔄 Starting MCP server with stdio transport")
        mcp.run(transport="stdio")
    except Exception as e:
        logger.critical(f"❌ Failed to start MCP server: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)


