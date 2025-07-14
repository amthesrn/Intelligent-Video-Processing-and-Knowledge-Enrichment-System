import os
import json
import requests
import subprocess
from urllib.parse import urlparse, parse_qs
from jinja2 import Template
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError
from typing import Optional
from logger_utility import setup_logger, rotate_log_file
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from datetime import datetime
from dateutil import parser

# ----------------------------
# Logger Setup
# ----------------------------
logger = setup_logger()

# ----------------------------
# Config
# ----------------------------
class Config(BaseModel):
    api_key: str
    model: str
    youtube_api_key: str
    prompt_template_path: str
    output_dir: str

# ----------------------------
# Utility Functions
# ----------------------------
def read_prompt_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def detect_input_type(input_str: str) -> str:
    input_str = input_str.strip()
    if input_str.startswith("http"):
        parsed = urlparse(input_str)
        path = parsed.path.strip("/")
        if "playlist" in input_str:
            return "playlist"
        elif "watch?v=" in input_str or "youtu.be/" in input_str:
            return "video"
        elif path.startswith("@"):
            return "channel_handle"
        elif "/channel/" in path:
            return "channel_id"
        else:
            return "unknown_url"
    elif input_str.startswith("@"):
        return "channel_handle"
    elif len(input_str) == 24 and input_str.startswith("UC"):
        return "channel_id"
    else:
        return "unknown_text"

def extract_video_id(url: str) -> Optional[str]:
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    query = parse_qs(urlparse(url).query)
    return query.get("v", [None])[0]

def fetch_youtube_metadata(video_id: str, api_key: str) -> dict:
    url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={api_key}"
    try:
        logger.info(f"Fetching metadata for video ID: {video_id}")
        logger.info(f"API URL: {url}")
        response = requests.get(url)
        response.raise_for_status()
        items = response.json().get("items", [])
        if not items:
            return {}
        snippet = items[0].get("snippet", {})
        return {
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "tags": snippet.get("tags", []),
            "channelTitle": snippet.get("channelTitle"),
            "publishedAt": snippet.get("publishedAt"),
            "thumbnails": snippet.get("thumbnails", {}),
            "categoryId": snippet.get("categoryId", None),
            "channelId": snippet.get("channelId", None),
            "defaultAudioLanguage": snippet.get("defaultAudioLanguage", None),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch metadata for video ID {video_id}: {e}")
        return {}

def fetch_video_ids_from_playlist(playlist_id: str, api_key: str) -> list:
    video_ids = []
    page_token = ""
    while True:
        url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId={playlist_id}&key={api_key}"
        if page_token:
            url += f"&pageToken={page_token}"
        response = requests.get(url)
        data = response.json()
        video_ids.extend([item['contentDetails']['videoId'] for item in data.get('items', [])])
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    # Reverse to get oldest videos first
    return video_ids[::-1]

def get_uploads_playlist_id(channel_id: str, api_key: str) -> Optional[str]:
    url = f"https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id={channel_id}&key={api_key}"
    response = requests.get(url)
    items = response.json().get("items", [])
    if items:
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    return None

def resolve_handle_to_channel_id(handle: str, api_key: str) -> Optional[str]:
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={handle}&key={api_key}"
    response = requests.get(url)
    items = response.json().get("items", [])
    if items:
        return items[0]["snippet"].get("channelId")
    return None

def is_video_already_downloaded(video_id: str, config: Config) -> tuple[bool, str]:
    """
    Checks if a video is already downloaded anywhere in the output directory.
    Returns a tuple: (exists, location)
    """
    for root, dirs, files in os.walk(config.output_dir):
        if (f"{video_id}.json" in files) and (f"{video_id}.mkv" in files):
            return True, root
    return False, ""

def download_video(video_id: str, output_folder: str):
    output_path = os.path.join(output_folder, f"{video_id}.mkv")
    if os.path.exists(output_path):
        logger.info(f"🎥 Video already exists: {output_path}")
        return output_path
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        logger.info(f"📥 Downloading video to: {output_path}")
        subprocess.run([
            "yt-dlp", "-f", "bv+ba",
            "-o", os.path.join(output_folder, f"{video_id}.%(ext)s"),
            "--merge-output-format", "mkv", url
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Downloaded video: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ yt-dlp failed: {e}", exc_info=True)
        return None

def download_transcript(video_id: str, output_folder: str):
    transcript_path = os.path.join(output_folder, f"{video_id}_transcript.txt")
    if os.path.exists(transcript_path):
        logger.info(f"📝 Transcript already exists: {transcript_path}")
        return transcript_path
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in transcript:
                start_seconds = int(entry['start'])
                hours = start_seconds // 3600
                minutes = (start_seconds % 3600) // 60
                seconds = start_seconds % 60
                timestamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
                f.write(f"{timestamp} {entry['text']}\n")
        logger.info(f"✅ Transcript with timestamps saved: {transcript_path}")
        return transcript_path
    except (TranscriptsDisabled, NoTranscriptFound):
        logger.warning(f"⚠️ Transcript not available for video ID: {video_id}")
        return None
    except Exception as e:
        logger.error(f"Error downloading transcript for {video_id}: {e}", exc_info=True)
        return None

def process_video(video_id: str, config: Config, base_folder: str):
    logger.info(f"🎥 Processing video ID: {video_id}")
    # First check if the video exists anywhere
    already_exists, existing_location = is_video_already_downloaded(video_id, config)
    if already_exists:
        logger.info(f"🟡 Video {video_id} already exists at: {existing_location}")
        print(f"✅ Video already downloaded at: {existing_location}")
        return
    # If not found, proceed with normal download
    output_folder = os.path.join(base_folder, video_id)
    os.makedirs(output_folder, exist_ok=True)
    output_path = download_video(video_id, output_folder)
    if output_path:
        print(f"✅ Video downloaded successfully: {output_path}")
        transcript_path = download_transcript(video_id, output_folder)
        if transcript_path:
            print(f"✅ Transcript saved successfully: {transcript_path}")
        metadata = fetch_youtube_metadata(video_id, config.youtube_api_key)
        metadata_path = os.path.join(output_folder, f"{video_id}_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as meta_file:
            json.dump(metadata, meta_file, indent=2)
        logger.info(f"✅ Metadata saved: {metadata_path}")
        print(f"✅ Metadata saved successfully: {metadata_path}")
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        prompt_template = read_prompt_template(config.prompt_template_path)
        prompt = Template(prompt_template).render(
            video_url=video_url,
            video_metadata=json.dumps(metadata, indent=2)
        )
        client = genai.Client(api_key=config.api_key)
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(file_uri=video_url, mime_type="video/*"),
                    types.Part.from_text(text=prompt),
                ],
            )
        ]
        generate_content_config = types.GenerateContentConfig(response_mime_type="text/plain")
        output_text = ""
        try:
            for chunk in client.models.generate_content_stream(
                model=config.model,
                contents=contents,
                config=generate_content_config,
            ):
                output_text += chunk.text
            json_path = os.path.join(output_folder, f"{video_id}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                try:
                    parsed_json = json.loads(output_text)
                    json.dump(parsed_json, f, indent=2)
                    logger.info(f"✅ Output saved: {json_path}")
                except json.JSONDecodeError:
                    f.write(output_text)
                    logger.warning(f"⚠️ Fallback saved (invalid JSON): {json_path}")
            if os.path.exists(json_path):
                print(f"✅ JSON summary saved successfully: {json_path}")
        except Exception as e:
            logger.error(f"Error processing video {video_id}: {e}", exc_info=True)

# ----------------------------
# Channel Selection Logic
# ----------------------------
def get_channel_selection() -> dict:
    print("\n📅 Select Channel Content Range:")
    print("1. Videos between specific dates")
    print("2. Latest N videos")
    print("3. Earliest N videos")
    print("4. All videos")
    print("5. Topic-wise video download")
    choice = input("Enter your choice (1-5): ").strip()
    selection = {"type": "", "params": {}}
    if choice == "1":
        while True:
            try:
                start_date = input("Enter start date (YYYY-MM-DD): ")
                end_date = input("Enter end date (YYYY-MM-DD): ")
                start_dt = parser.parse(start_date).date()
                end_dt = parser.parse(end_date).date()
                if start_dt > end_dt:
                    raise ValueError
                selection["type"] = "date_range"
                selection["params"] = {
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat()
                }
                break
            except (ValueError, TypeError):
                print("Invalid date format or range. Please use YYYY-MM-DD format.")
    elif choice in ("2", "3"):
        while True:
            try:
                n = int(input("Enter number of videos: "))
                if n <= 0:
                    raise ValueError
                selection["type"] = "latest" if choice == "2" else "earliest"
                selection["params"] = {"count": n}
                break
            except ValueError:
                print("Please enter a positive integer.")
    elif choice == "4":
        selection["type"] = "all"
    elif choice == "5":
        topic = input("Enter topic or keyword to search: ").strip()
        selection["type"] = "topic"
        selection["params"] = {"topic": topic}
    else:
        raise ValueError("Invalid selection")
    return selection

def fetch_channel_videos(channel_id: str, api_key: str, selection: dict) -> list:
    if selection["type"] == "date_range":
        url = f"https://www.googleapis.com/youtube/v3/search?key={api_key}&channelId={channel_id}&part=snippet,id&type=video&order=date&maxResults=50"
        url += f"&publishedAfter={selection['params']['start']}T00:00:00Z"
        url += f"&publishedBefore={selection['params']['end']}T23:59:59Z"
        video_ids = []
        while True:
            response = requests.get(url)
            data = response.json()
            video_ids += [item['id']['videoId'] for item in data.get('items', []) if 'videoId' in item['id']]
            next_page = data.get('nextPageToken')
            if not next_page:
                break
            url = f"{url.split('&pageToken')[0]}&pageToken={next_page}"
        return video_ids
    elif selection["type"] in ("latest", "earliest"):
        if selection["type"] == "latest":
            url = f"https://www.googleapis.com/youtube/v3/search?key={api_key}&channelId={channel_id}&part=snippet,id&type=video&order=date&maxResults={selection['params']['count']}"
            response = requests.get(url)
            return [item['id']['videoId'] for item in response.json().get('items', []) if 'videoId' in item['id']]
        if selection["type"] == "earliest":
            playlist_id = get_uploads_playlist_id(channel_id, api_key)
            all_videos = fetch_video_ids_from_playlist(playlist_id, api_key)
            return all_videos[:selection['params']['count']]
    elif selection["type"] == "all":
        playlist_id = get_uploads_playlist_id(channel_id, api_key)
        return fetch_video_ids_from_playlist(playlist_id, api_key)
    elif selection["type"] == "topic":
        return fetch_videos_by_topic(channel_id, api_key, selection["params"]["topic"])
    return []



def fetch_videos_by_topic(channel_id: str, api_key: str, topic: str, max_results=100):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": api_key,
        "channelId": channel_id,
        "part": "snippet",
        "type": "video",
        "order": "date",
        "q": topic,
        "maxResults": 50
    }
    video_list = []
    total = 0
    while True:
        resp = requests.get(url, params=params)
        data = resp.json()
        for item in data.get('items', []):
            # Only add items that are videos and have a videoId
            if item.get('id', {}).get('kind') == 'youtube#video' and 'videoId' in item['id']:
                video_list.append({
                    "videoId": item['id']['videoId'],
                    "title": item['snippet']['title']
                })
                total += 1
                if total >= max_results:
                    return video_list
        if 'nextPageToken' in data and total < max_results:
            params['pageToken'] = data['nextPageToken']
        else:
            break
    return video_list



def select_videos_from_list(video_list):
    print("\nVideos found for the topic:")
    for idx, vid in enumerate(video_list, 1):
        print(f"{idx}. {vid['title']}")
    print("\nWhich videos do you want to download?")
    print("Enter numbers separated by commas (e.g., 1,3,5), a range (e.g., 2-6), or 'all':")
    selection = input("Your choice: ").strip().lower()
    selected_indices = []
    if selection == "all":
        selected_indices = list(range(len(video_list)))
    elif '-' in selection:
        try:
            start, end = map(int, selection.split('-'))
            selected_indices = list(range(start-1, end))
        except:
            print("Invalid range.")
    else:
        try:
            selected_indices = [int(x)-1 for x in selection.split(',') if x.strip().isdigit()]
        except:
            print("Invalid input.")
    return [video_list[i]["videoId"] for i in selected_indices if 0 <= i < len(video_list)]

# ----------------------------
# Menu Function
# ----------------------------
def menu():
    print("\n📥 Select Input Type:")
    print("1. YouTube Video URL (e.g. https://www.youtube.com/watch?v=VIDEO_ID)")
    print("2. Channel Handle (e.g. @channelname)")
    print("3. Channel ID (e.g. UCxxxxxx...)")
    print("4. Playlist URL (e.g. https://www.youtube.com/playlist?list=LIST_ID)")
    choice = input("Enter your choice (1–4): ").strip()
    input_str = input("Paste your input: ").strip()
    return detect_input_type(input_str), input_str

# ----------------------------
# Main
# ----------------------------
def main():
    try:
        rotate_log_file(log_dir="video_log", log_file="logger.log", max_size_mb=10)
        logger = setup_logger(log_dir="video_log", log_file="logger.log")
        config = Config(
            api_key="Gemini_api_key",
            youtube_api_key="youtube_api_key",
            model="gemini-2.0-flash",
            prompt_template_path="E:\\autogen_folder\\video_analyis\\prompt.jinja",
            output_dir="output_folder"
        )
        os.makedirs(config.output_dir, exist_ok=True)
        while True:
            detected_type, user_input = menu()
            logger.info(f"User input: {user_input}")
            logger.info(f"Detected input type: {detected_type}")
            print(f"\n🔍 Detected input type: {detected_type}")

            if detected_type == "video":
                video_id = extract_video_id(user_input)
                if video_id:
                    process_video(video_id, config, os.path.join(config.output_dir, "videos"))

            elif detected_type == "playlist":
                playlist_id = parse_qs(urlparse(user_input).query).get("list", [None])[0]
                if playlist_id:
                    video_ids = fetch_video_ids_from_playlist(playlist_id, config.youtube_api_key)
                    playlist_folder = os.path.join(config.output_dir, "playlists", playlist_id)
                    for idx, vid in enumerate(video_ids, 1):
                        logger.info(f"\n📦 Processing ({idx}/{len(video_ids)}): {vid}")
                        print(f"📦 Processing ({idx}/{len(video_ids)}): {vid}")
                        process_video(vid, config, playlist_folder)

            elif detected_type in ("channel_id", "channel_handle"):
                if detected_type == "channel_handle":
                    channel_id = resolve_handle_to_channel_id(user_input, config.youtube_api_key)
                    if not channel_id:
                        logger.warning(f"⚠️ Could not resolve handle '{user_input}' to a channel ID.")
                        print(f"⚠️ Could not resolve handle '{user_input}' to a channel ID.")
                        continue
                else:
                    channel_id = user_input
                try:
                    selection = get_channel_selection()
                except ValueError as e:
                    print(f"❌ Invalid selection: {e}")
                    continue

                # Topic-wise download logic
                if selection["type"] == "topic":
                    topic = selection["params"]["topic"]
                    video_list = fetch_videos_by_topic(channel_id, config.youtube_api_key, topic)
                    if not video_list:
                        print("❌ No videos found for this topic.")
                        continue
                    selected_video_ids = select_videos_from_list(video_list)
                    if not selected_video_ids:
                        print("❌ No videos selected.")
                        continue
                    topic_folder = os.path.join(
                        config.output_dir,
                        "channels",
                        f"{channel_id}_topic_{topic.replace(' ', '_')}"
                    )
                    os.makedirs(topic_folder, exist_ok=True)
                    for idx, vid in enumerate(selected_video_ids, 1):
                        logger.info(f"\n📦 Processing ({idx}/{len(selected_video_ids)}): {vid}")
                        print(f"📦 Processing ({idx}/{len(selected_video_ids)}): {vid}")
                        process_video(vid, config, topic_folder)
                else:
                    folder_suffix = ""
                    if selection["type"] == "date_range":
                        start = selection["params"]["start"].replace("-", "")
                        end = selection["params"]["end"].replace("-", "")
                        folder_suffix = f"date_{start}_{end}"
                    elif selection["type"] in ("latest", "earliest"):
                        folder_suffix = f"{selection['type']}_{selection['params']['count']}"
                    else:
                        folder_suffix = "all"

                    video_ids = fetch_channel_videos(channel_id, config.youtube_api_key, selection)
                    if not video_ids:
                        print("❌ No videos found matching the criteria")
                        continue
                    channel_folder = os.path.join(
                        config.output_dir,
                        "channels",
                        f"{channel_id}_{folder_suffix}"
                    )
                    os.makedirs(channel_folder, exist_ok=True)
                    for idx, vid in enumerate(video_ids, 1):
                        logger.info(f"\n📦 Processing ({idx}/{len(video_ids)}): {vid}")
                        print(f"📦 Processing ({idx}/{len(video_ids)}): {vid}")
                        process_video(vid, config, channel_folder)
            else:
                logger.warning(f"⚠️ Support for '{detected_type}' is not implemented.")
                print(f"⚠️ Support for '{detected_type}' is not implemented.")

            again = input("\n🔁 Do you want to process another input? (y/n): ").strip().lower()
            if again not in ["y", "yes"]:
                print("👋 Exiting.")
                break

    except ValidationError as e:
        logger.error("Validation Error: %s", e)
        print("❌ Validation Error:", e)

if __name__ == "__main__":
    main()
