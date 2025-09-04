import os, base64, json
from email.utils import parsedate_to_datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/calendar.events"]

def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def fetch_emails(service, max_results=5):
    results = service.users().messages().list(
        userId="me",
        q="subject:Notice OR subject:Circular OR subject:Exam OR subject:Enroll",
        maxResults=max_results
    ).execute()
    return results.get("messages", [])

def _html_to_text(html_str: str) -> str:
    soup = BeautifulSoup(html_str, "html.parser")
    # Make links explicit
    for a in soup.find_all('a'):
        if a.get('href') and a.text and a.text.strip() not in a.get('href'):
            a.insert_after(soup.new_string(f" ({a.get('href')})"))
    text = soup.get_text("\n")
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()])

def get_email_content(service, msg_id):
    msg_data = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg_data["payload"]
    headers = payload["headers"]

    subject, date = None, None
    for header in headers:
        if header["name"] == "Subject":
            subject = header["value"]
        if header["name"] == "Date":
            date = header["value"]

    def decode_body(part):
        data = part.get("body", {}).get("data", "")
        if not data:
            return ""
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    snippet = msg_data.get("snippet", "")

    # Prefer text/html, then text/plain, then snippet
    body_text = None

    def walk_parts(p):
        parts = p.get("parts") or []
        for part in parts:
            mime = part.get("mimeType", "")
            if mime == "text/html":
                return _html_to_text(decode_body(part))
            if mime == "text/plain":
                body = decode_body(part)
                if body:
                    body_text_fallbacks.append(body)
            if part.get("parts"):
                nested = walk_parts(part)
                if nested:
                    return nested
        return None

    body_text_fallbacks = []
    if "parts" in payload:
        html_first = walk_parts(payload)
        if html_first:
            body_text = html_first
        elif body_text_fallbacks:
            body_text = body_text_fallbacks[0]
    else:
        mime = payload.get("mimeType")
        if mime == "text/html":
            body_text = _html_to_text(decode_body(payload))
        elif mime == "text/plain":
            body_text = decode_body(payload)

    if not body_text:
        body_text = snippet

    return subject, date, body_text
    

def get_calendar_service(creds=None):
    if creds is None:
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return build("calendar", "v3", credentials=creds)

def add_event_to_calendar(service, subject, date, content):
    event = {
        "summary": subject,
        "description": content,
        "start": {
            "dateTime": "2025-09-02T10:00:00",
            "timeZone": "Asia/Kolkata",
        },
        "end": {
            "dateTime": "2025-09-02T11:00:00",
            "timeZone": "Asia/Kolkata",
        },
    }

    event_result = service.events().insert(calendarId="primary", body=event).execute()
    print(f"✅ Event created: {event_result.get('htmlLink')}")

def fetch_latest_notices(service=None, max_results=5):
    """Fetch and return the latest notice emails with subject, date, content, and message web link."""
    if service is None:
        service = get_gmail_service()
    notices = []
    messages = fetch_emails(service, max_results=max_results)

    for msg in messages:
        subject, date, content = get_email_content(service, msg["id"])
        web_link = f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}"
        notices.append({
            "id": msg["id"],
            "subject": subject,
            "date": date,
            "content": content,
            "web_link": web_link,
        })

    # Ensure most recent emails are first based on the parsed Date header
    def _sort_key(n):
        d = n.get("date")
        try:
            return parsedate_to_datetime(d).timestamp() if d else 0
        except Exception:
            return 0

    notices.sort(key=_sort_key, reverse=True)
    return notices
