import imaplib
import smtplib
import email
import time
import re
import os
import json
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

EMAIL_LOGIN = os.getenv("ICLOUD_EMAIL")
EMAIL_PASSWORD = os.getenv("ICLOUD_PASSWORD")

# Hardcoded config paths
RESPONSE_MAP_PATH = "/config/responses.json"

IMAP_SERVER = "imap.mail.me.com"
IMAP_PORT = 993  # SSL/TLS
SMTP_SERVER = "smtp.mail.me.com"
SMTP_PORT = 587  # STARTTLS

# Load response map
with open(RESPONSE_MAP_PATH, "r") as f:
    RESPONSE_CONFIG = json.load(f)
    print(f"✅ Loaded response config with {len(RESPONSE_CONFIG)} email aliases", flush=True)
    for alias in RESPONSE_CONFIG:
        print(f"📋 {alias} has {len(RESPONSE_CONFIG[alias]['subjects'])} response templates", flush=True)

def extract_fields(body):
    print(f"📧 Raw email body:\n{body}", flush=True)
    # Updated regex to handle HTML formatting
    name_match = re.search(r"<b>Name:</b>\s*(.+?)</p>", body)
    email_match = re.search(r"<b>Email:</b>\s*(.+?)</p>", body)
    subject_match = re.search(r"<b>Subject:</b>\s*(.+?)</p>", body)
    
    # Extract first name only
    full_name = name_match.group(1).strip()
    first_name = full_name.split()[0]
    
    fields = {
        "name": first_name,
        "email": email_match.group(1).strip() if email_match else None,
        "subject": subject_match.group(1).strip() if subject_match else None
    }
    print(f"📝 Extracted fields: {fields}", flush=True)
    return fields

def send_reply(to_email, subject_line_from_body, name, response_body, signature, from_email):
    print(f"📤 Attempting to send reply to {to_email}", flush=True)
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = f"Re: {subject_line_from_body}"

    html_body = f"<p>{name},</p><p>{response_body}</p>{signature}"
    msg.set_content(html_body, subtype="html")

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            print(f"🔐 Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}", flush=True)
            server.starttls()  # STARTTLS for SMTP
            print("🔑 Logging in to SMTP server", flush=True)
            server.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            print("📨 Sending message", flush=True)
            server.send_message(msg)
            print(f"✔ Sent reply to {to_email}", flush=True)
            return True
    except Exception as e:
        print(f"❌ SMTP Error: {e}", flush=True)
        return False

def process_new_emails():
    try:
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

            if header_subject not in RESPONSE_CONFIG[matching_alias]['subjects']:
                print(f"⚠️  No matching response for subject: {header_subject}", flush=True)
                continue

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode()
                        break
            else:
                body = msg.get_payload(decode=True).decode()

            fields = extract_fields(body)
            if fields["email"] and fields["subject"]:
                if send_reply(
                    fields["email"],
                    fields["subject"],
                    fields["name"],
                    RESPONSE_CONFIG[matching_alias]['subjects'][header_subject],
                    RESPONSE_CONFIG[matching_alias]['signature'],
                    matching_alias
                ):
                    print(f"✅ Successfully processed email, marking as read", flush=True)
                    mail.store(num, '+FLAGS', '\\Seen')
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
