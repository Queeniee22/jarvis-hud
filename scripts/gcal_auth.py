"""One-time Google Calendar consent flow.

Run it once, sign in with the browser window it opens, and it saves
token.json in the repo root. jarvis.services.gcal reads that token on every
poll after that -- this script never runs as part of the app itself.

    .venv/Scripts/python scripts/gcal_auth.py     # Windows
    .venv/bin/python scripts/gcal_auth.py         # macOS
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from jarvis import config

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_PATH = config.ROOT / "credentials.json"

if not CREDENTIALS_PATH.exists():
    print("credentials.json not found in the repo root.\n")
    print("To create it:")
    print("  1. Go to https://console.cloud.google.com/ and create (or pick) a project")
    print("  2. APIs & Services > Library > enable 'Google Calendar API'")
    print("  3. APIs & Services > Credentials > Create Credentials > OAuth client ID")
    print("  4. Application type: Desktop app")
    print("  5. Download the JSON and save it as 'credentials.json' in the jarvis-hud repo root")
    print(f"     ({CREDENTIALS_PATH})")
    print("\nThen re-run this script.")
    sys.exit(1)

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
creds = flow.run_local_server(port=0)
(config.ROOT / "token.json").write_text(creds.to_json())
print("Saved token.json")
