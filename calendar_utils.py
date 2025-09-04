from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from datetime import datetime, timedelta
import os

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

def get_calendar_service():
    """Return an authenticated Calendar service, re-consenting if scope is missing."""
    creds = None
    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            # Re-consent to ensure calendar scope is granted
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def add_event_to_calendar(summary, description, date_str, time_str, venue):
    service = get_calendar_service()

    # parse date + time; support all-day events when time is not provided
    if time_str:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")
        end_dt = start_dt + timedelta(hours=1)
        start_payload = {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"}
        end_payload = {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Kolkata"}
    else:
        start_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        end_date = start_date + timedelta(days=1)
        # For all-day events, use date-only without timeZone
        start_payload = {"date": start_date.isoformat()}
        end_payload = {"date": end_date.isoformat()}

    event = {
        "summary": summary,
        "location": venue or "TBD",
        "description": description,
        "start": start_payload,
        "end": end_payload,
    }

    try:
        event = service.events().insert(calendarId="primary", body=event).execute()
        link = event.get("htmlLink")
        print("✅ Event created:", link)
        return link
    except Exception as e:
        print("❌ Failed to create event:", e)
        return None
