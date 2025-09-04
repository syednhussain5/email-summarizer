from gmail_utils import get_gmail_service, fetch_emails, get_email_content, get_calendar_service, add_event_to_calendar

def main():
    gmail_service = get_gmail_service()
    cal_service = get_calendar_service()

    messages = fetch_emails(gmail_service, max_results=3)

    for msg in messages:
        subject, date, content = get_email_content(gmail_service, msg["id"])
        print("📧 Subject:", subject)
        print("⏰ Date:", date)
        print("📝 Content:", content)
        print("-" * 80)

        # Add to calendar
        add_event_to_calendar(cal_service, subject, date, content)

if __name__ == "__main__":
    main()
