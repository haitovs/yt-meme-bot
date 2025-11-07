import os
from typing import Dict, List, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def list_channel_credentials(channels_dir: str) -> List[str]:
    if not os.path.isdir(channels_dir):
        return []
    entries = []
    for filename in os.listdir(channels_dir):
        if not filename.lower().endswith(".json"):
            continue
        full_path = os.path.join(channels_dir, filename)
        if os.path.isfile(full_path):
            entries.append(full_path)
    return sorted(entries)


def _build_service(cred_file: str):
    creds = Credentials.from_authorized_user_file(cred_file, scopes=YOUTUBE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_to_all(local_mp4_path: str, title: str, description: str, tags: List[str], channels_dir: str) -> Tuple[int, Dict[str, str]]:
    """Returns (num_success, results_per_channelfile)."""
    channel_files = list_channel_credentials(channels_dir)
    results: Dict[str, str] = {}
    successes = 0

    for cred_file in channel_files:
        chan_key = os.path.basename(cred_file)
        try:
            service = _build_service(cred_file)
            body = {
                "snippet": {
                    "title": title[:100],
                    "description": description[:4999],
                    "tags": tags,
                    "categoryId": "23",  # Comedy
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False
                }
            }
            media = MediaFileUpload(local_mp4_path, mimetype="video/mp4", resumable=True)
            request = service.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
                # (optional) you could log `status.progress()` here
            video_id = response.get("id", "")
            results[chan_key] = f"ok:{video_id}"
            successes += 1
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", getattr(e, "status_code", "unknown"))
            results[chan_key] = f"http_error:{status}:{e}"
        except Exception as e:
            results[chan_key] = f"error:{e}"

    return successes, results
