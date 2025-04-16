import imaplib
import smtplib
import email
import time
import re
import os
import json
from email.message import EmailMessage
from dotenv import load_dotenv
import requests
from pathlib import Path
import yaml

load_dotenv()

EMAIL_LOGIN = os.getenv("ICLOUD_EMAIL")
EMAIL_PASSWORD = os.getenv("ICLOUD_PASSWORD")

# Hardcoded config paths
RESPONSE_MAP_PATH = "/config/responses.json"

IMAP_SERVER = "imap.mail.me.com"
IMAP_PORT = 993  # SSL/TLS
SMTP_SERVER = "smtp.mail.me.com"
SMTP_PORT = 587  # STARTTLS

PUSHOVER_ENABLED = os.getenv("PUSHOVER_ENABLED", "false").lower() == "true"
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Load configuration files
config_path = Path("/config/config.yml")
if not config_path.exists():
    config_path = Path("config/config.yml")

with open(config_path, "r") as f:
    CONFIG = yaml.safe_load(f)

# Load response map
with open(RESPONSE_MAP_PATH, "r") as f:
    RESPONSE_CONFIG = json.load(f)
    print(f"✅ Loaded response config with {len(RESPONSE_CONFIG)} email aliases", flush=True)
    for alias in RESPONSE_CONFIG:
        print(f"📋 {alias} has {len(RESPONSE_CONFIG[alias]['subjects'])} response templates", flush=True)

def send_pushover_notification(title, message):
    if not PUSHOVER_ENABLED:
        return
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        print("Pushover credentials not set.")
        return
    payload = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "title": title,
        "message": message
    }
    try:
        response = requests.post("https://api.pushover.net/1/messages.json", data=payload)
        response.raise_for_status()
        print("Pushover notification sent.")
    except Exception as e:
        print(f"Failed to send Pushover notification: {e}")

def extract_fields(body):
    print(f"📧 Raw email body:\n{body}", flush=True)
    # Updated regex to match the HTML format we're sending
    name_match = re.search(r"<b>Name:</b>\s*(.+?)</p>", body)
    email_match = re.search(r"<b>Email:</b>\s*(.+?)</p>", body)
    subject_match = re.search(r"<b>Subject:</b>\s*(.+?)</p>", body)
    
    if not name_match or not email_match or not subject_match:
        print("⚠️  Failed to extract fields from email body", flush=True)
        return {
            "name": None,
            "email": None,
            "subject": None
        }
    
    # Extract first name only
    full_name = name_match.group(1).strip()
    first_name = full_name.split()[0]
    
    fields = {
        "name": first_name,
        "email": email_match.group(1).strip(),
        "subject": subject_match.group(1).strip()
    }
    print(f"📝 Extracted fields: {fields}", flush=True)
    return fields

def save_to_sent_folder(msg: EmailMessage):
    """Save a copy of the email to the Sent Messages folder."""
    try:
        print("🔐 Attempting to connect to IMAP server to save to Sent folder", flush=True)
        with imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT) as imap:
            print("🔑 Logging in to IMAP server", flush=True)
            imap.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            print("📤 Appending message to Sent Messages folder", flush=True)
            imap.append(
                '"Sent Messages"',  # iCloud's sent folder name
                "",  # Flags
                imaplib.Time2Internaldate(time.time()),  # Date
                msg.as_bytes()  # Message
            )
            print("✅ Successfully saved email to Sent Messages folder", flush=True)
    except Exception as e:
        print(f"❌ Failed to save email to Sent Messages folder: {e}", flush=True)

def send_reply(to_email, subject_line_from_body, name, response_body, signature, from_email):
    print(f"📤 Attempting to send reply to {to_email}", flush=True)
    msg = EmailMessage()
    
    # Get form configuration for this email
    form_config = None
    for form_name, form_data in CONFIG["forms"].items():
        if form_data["to_email"][0] == from_email:
            form_config = form_data
            break
    
    # Set From header with name if found, otherwise just email
    if form_config:
        msg["From"] = f"{form_config['from_name']} <{from_email}>"
    else:
        msg["From"] = from_email
        
    msg["To"] = to_email
    msg["Subject"] = f"Re: {subject_line_from_body}"

    html_body = f"<p>{name},</p><p>{response_body}</p>{signature}"
    msg.set_content(html_body, subtype="html")

    try:
        print(f"🔐 Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}", flush=True)
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            print("🔒 Starting TLS", flush=True)
            server.starttls()  # STARTTLS for SMTP
            print("🔑 Logging in to SMTP server", flush=True)
            server.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            print("📨 Sending message", flush=True)
            server.send_message(msg)
            print(f"✔ Sent reply to {to_email}", flush=True)
            
            # Save copy to Sent Messages folder
            try:
                save_to_sent_folder(msg)
            except Exception as e:
                print(f"❌ Failed to save to Sent folder: {e}", flush=True)
            
            # Send pushover notification for response sent
            send_pushover_notification(
                "MailBridge: Auto-Reply Sent",
                f"Auto-reply sent to {to_email} with subject '{subject_line_from_body}'"
            )
            
            return True
    except Exception as e:
        print(f"❌ SMTP Error: {e}", flush=True)
        print(f"❌ Error details: {e.__class__.__name__}", flush=True)
        if hasattr(e, 'args'):
            print(f"❌ Error args: {e.args}", flush=True)
        return False

def process_new_emails():
    try:
        # Get the instance emails from environment
        instance_emails = os.getenv("INSTANCE_EMAILS", "").split(",")
        if not instance_emails:
            print("❌ INSTANCE_EMAILS environment variable not set", flush=True)
            return

        # IMAP with SSL
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        print(f"🔐 Connecting to IMAP server {IMAP_SERVER}:{IMAP_PORT}", flush=True)
        mail.login(EMAIL_LOGIN, EMAIL_PASSWORD)
        print("🔑 Logged in to IMAP server", flush=True)
        mail.select("inbox")
        print("📂 Selected inbox folder", flush=True)

        # Search for any unread emails
        search_query = 'UNSEEN'
        print(f"🔍 Searching for emails with query: {search_query}", flush=True)
        status, data = mail.search(None, search_query)
        
        if status != "OK" or not data[0]:  # Check if data[0] is None or empty
            print("No new matching messages.", flush=True)
            return

        email_ids = data[0].split()
        print(f"📬 Found {len(email_ids)} unread emails", flush=True)

        for num in email_ids:
            # Fetch without marking as read
            status, msg_data = mail.fetch(num, "(BODY.PEEK[])")
            if status != "OK":
                print(f"❌ Failed to fetch email {num}", flush=True)
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            header_subject = msg["Subject"]
            header_to = msg["To"]
            print(f"🔍 Processing email:", flush=True)
            print(f"   To: {header_to}", flush=True)
            print(f"   Subject: {header_subject}", flush=True)

            # Only process emails that match any of our instance emails
            if not any(email.lower() in header_to.lower() for email in instance_emails):
                print(f"⚠️  Skipping email not for any instance ({instance_emails})", flush=True)
                continue

            # Find which alias this email is for
            matching_alias = None
            for alias in RESPONSE_CONFIG:
                if alias.lower() in header_to.lower():
                    matching_alias = alias
                    break

            if not matching_alias:
                print(f"⚠️  No matching alias found for {header_to}", flush=True)
                continue

            print(f"📋 Checking against available responses for {matching_alias}: {list(RESPONSE_CONFIG[matching_alias]['subjects'].keys())}", flush=True)

            # Check if subject starts with any of the configured subjects
            matching_subject = None
            for subject in RESPONSE_CONFIG[matching_alias]['subjects'].keys():
                if header_subject.startswith(subject):
                    matching_subject = subject
                    break

            if not matching_subject:
                print(f"⚠️  No matching response for subject: {header_subject}", flush=True)
                continue

            # Try to get both HTML and plain text versions
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        body = part.get_payload(decode=True).decode()
                        break
                    elif content_type == "text/html":
                        body = part.get_payload(decode=True).decode()
            else:
                body = msg.get_payload(decode=True).decode()

            # If we got HTML, try to extract plain text
            if "<html" in body.lower():
                # Remove HTML tags and convert to plain text
                body = re.sub(r'<[^>]+>', '', body)
                body = re.sub(r'\n\s*\n', '\n\n', body)  # Normalize newlines

            fields = extract_fields(body)
            if fields["email"] and fields["subject"]:
                # Send pushover notification for message received
                send_pushover_notification(
                    "MailBridge: Message Received",
                    f"Message received at {header_to}\nFrom: {fields['name']} <{fields['email']}>\nSubject: {fields['subject']}\n---\n{body}"
                )
                if send_reply(
                    fields["email"],
                    fields["subject"],
                    fields["name"],
                    RESPONSE_CONFIG[matching_alias]['subjects'][matching_subject],
                    RESPONSE_CONFIG[matching_alias]['signature'],
                    matching_alias
                ):
                    print(f"✅ Successfully processed email, marking as read", flush=True)
                    mail.store(num, '+FLAGS', '\Seen')
                else:
                    print(f"❌ Failed to send reply, leaving email unread", flush=True)
            else:
                print("⚠️  Missing email or subject in body. Skipping reply.", flush=True)
    except Exception as e:
        print(f"❌ IMAP Error: {e}", flush=True)
    finally:
        try:
            mail.logout()
        except:
            pass

if __name__ == "__main__":
    print("📬 Mail Monitor running...", flush=True)
    while True:
        try:
            process_new_emails()
        except Exception as e:
            print(f"❌ Error: {e}", flush=True)
        time.sleep(30)
