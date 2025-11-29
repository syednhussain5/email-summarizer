from flask import Flask, render_template, request, redirect, url_for
import os, json
from summarizer import summarize_text
from extractor import extract_text_from_file, extract_event_details
from gmail_utils import fetch_latest_notices   # ✅ import Gmail fetcher
from calendar_utils import add_event_to_calendar

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "docx", "png", "jpg", "jpeg"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

SUMMARIES_FILE = "summaries.json"


def save_summary(summary):
    if os.path.exists(SUMMARIES_FILE):
        with open(SUMMARIES_FILE, "r") as f:
            summaries = json.load(f)
    else:
        summaries = []

    summaries.append(summary)

    with open(SUMMARIES_FILE, "w") as f:
        json.dump(summaries, f, indent=4)


def load_summaries():
    if os.path.exists(SUMMARIES_FILE):
        with open(SUMMARIES_FILE, "r") as f:
            return json.load(f)
    return []


def clear_summaries():
    try:
        with open(SUMMARIES_FILE, "w") as f:
            json.dump([], f)
    except Exception:
        pass


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/", methods=["GET", "POST"])
def dashboard():
    if request.args.get("clear") == "1":
        clear_summaries()
    summaries = load_summaries()
    return render_template("dashboard.html", summaries=summaries)


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return redirect(url_for("dashboard"))

    file = request.files["file"]
    if file.filename == "":
        return redirect(url_for("dashboard"))

    if not allowed_file(file.filename):
        print("Unsupported file type uploaded.")
        return redirect(url_for("dashboard"))

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(filepath)

    try:
        text = extract_text_from_file(filepath)
    except Exception as e:
        print(f"Extraction error: {e}")
        return redirect(url_for("dashboard"))

    try:
        # Provide filename as lightweight subject context for better abstractive summaries
        summary_data = summarize_text(f"{file.filename}. {text}")
    except Exception as e:
        print(f"Summarization error: {e}")
        summary_data = {"summary": [], "links": [], "date": None, "time": None}

    try:
        date_str, time_str, venue = extract_event_details(text)
    except Exception as e:
        print(f"Event extraction error: {e}")
        date_str, time_str, venue = None, None, None

    # Render preview page (do not create calendar or save yet)
    preview = {
        "source": file.filename,
        "subject": file.filename,
        "summary_lines": summary_data.get("summary", []),
        "links": summary_data.get("links", []),
        "event_date": date_str or summary_data.get("date"),
        "event_time": time_str or summary_data.get("time"),
        "venue": venue,
    }
    return render_template("preview.html", preview=preview)


@app.route("/save_summary", methods=["POST"])
def save_summary_route():
    try:
        subject = request.form.get("subject")
        source = request.form.get("source")
        summary_lines = json.loads(request.form.get("summary_lines") or "[]")
        links = json.loads(request.form.get("links") or "[]")
        event_date = request.form.get("event_date") or None
        event_time = request.form.get("event_time") or None
        venue = request.form.get("venue") or None

        calendar_link = None
        try:
            if event_date:
                calendar_link = add_event_to_calendar(
                    subject or source or "Notice",
                    "\n".join(summary_lines),
                    event_date,
                    event_time,
                    venue,
                )
        except Exception as e:
            print(f"Calendar error: {e}")

        save_summary({
            "source": source,
            "subject": subject,
            "summary_lines": summary_lines,
            "links": links,
            "event_date": event_date,
            "event_time": event_time,
            "venue": venue,
            "calendar_link": calendar_link,
        })
    except Exception as e:
        print(f"Save summary error: {e}")
    return redirect(url_for("dashboard"))


# ✅ New route for Gmail fetch
@app.route("/fetch_gmail", methods=["POST"])
def fetch_gmail():
    try:
        notices = fetch_latest_notices()
    except FileNotFoundError as e:
        print(f"Gmail setup required: {e}")
        # You could redirect to a setup page or show a message
        return redirect(url_for("dashboard"))
    except Exception as e:
        print(f"Gmail fetch failed: {e}")
        return redirect(url_for("dashboard"))

    for notice in notices:
        content = notice.get("content") or ""
        try:
            # Include subject context to help summarizer infer topic
            subject_ctx = notice.get("subject") or ""
            # Include email date in content to ensure it's captured in summary
            email_date = notice.get("date") or ""
            summary_data = summarize_text(f"{subject_ctx}. {email_date}. {content}")
        except Exception as e:
            print(f"Summarization error: {e}")
            summary_data = {"summary": [], "links": []}

        try:
            date_str, time_str, venue = extract_event_details(content)
        except Exception as e:
            print(f"Event extraction error: {e}")
            date_str, time_str, venue = None, None, None

        calendar_link = None
        try:
            # Use deadline extracted either by regex heuristics or summarizer hint
            detected_date = date_str or summary_data.get("date")
            detected_time = time_str or summary_data.get("time")
            if detected_date:
                calendar_link = add_event_to_calendar(
                    notice.get("subject") or "Notice",
                    "\n".join(summary_data.get("summary", [])),
                    detected_date,
                    detected_time,
                    venue,
                )
        except Exception as e:
            print(f"Calendar error: {e}")

        save_summary({
            "source": "Gmail",
            "subject": notice.get("subject"),
            "raw_date": notice.get("date"),
            "summary_lines": summary_data["summary"],
            "links": summary_data["links"],
            "event_date": date_str or summary_data.get("date"),
            "event_time": time_str or summary_data.get("time"),
            "venue": venue,
            "calendar_link": calendar_link,
            "email_link": notice.get("web_link"),
        })
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
