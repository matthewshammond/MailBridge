from fastapi import FastAPI, HTTPException, Request, Response, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
import yaml
import os
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from pathlib import Path
import json
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.gzip import GZipMiddleware
import asyncio
import redis.asyncio as redis
from functools import lru_cache
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import imaplib
import time

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("✅ Loaded response config with %d email aliases", len(responses))
    for email, config in responses.items():
        logger.info("📋 %s has %d response templates", email, len(config.get("subjects", {})))
    yield
    # Shutdown
    await redis_client.close()

app = FastAPI(lifespan=lifespan)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True
)

# Cache configuration
@lru_cache(maxsize=128)
def get_form_config(form_key: str):
    for form_name, form_data in config["forms"].items():
        if form_data["key"] == form_key:
            return form_data
    return None

# Load configuration
config_path = Path("/config/config.yml")
if not config_path.exists():
    config_path = Path("config/config.yml")

with open(config_path, "r") as f:
    config = yaml.safe_load(f)

# Load responses
responses_path = Path("/config/responses.json")
if not responses_path.exists():
    responses_path = Path("config/responses.json")

with open(responses_path, "r") as f:
    responses = json.load(f)

# Get instance-specific configuration
instance_port = os.getenv("PORT", "2525")
instance_emails = os.getenv("INSTANCE_EMAILS", "").split(",")  # Allow multiple emails

if not instance_emails:
    raise ValueError("INSTANCE_EMAILS environment variable must be set")

# Find the instance configurations
instance_configs = []
for form_name, form_data in config["forms"].items():
    if form_data["to_email"][0] in instance_emails:
        instance_configs.append(form_data)

if not instance_configs:
    raise ValueError(f"No configuration found for emails {instance_emails}")

# Get the response configurations for these instances
response_configs = {}
for email in instance_emails:
    response_config = responses.get(email)
    if not response_config:
        raise ValueError(f"No response configuration found for email {email}")
    response_configs[email] = response_config

# Configure CORS
allowed_origins = []
for form_name, form_data in config["forms"].items():
    allowed_origins.extend(form_data.get("allowed_domains", []))

# Convert domains to full origins with https://
allowed_origins = [f"https://{domain}" for domain in allowed_origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Only allow specific origins
    allow_credentials=True,
    allow_methods=["POST"],  # Only allow POST method
    allow_headers=["Content-Type", "Origin"],  # Only allow necessary headers
)

class FormSubmission(BaseModel):
    name: str
    email: EmailStr
    subject: str
    content: str
    captcha_token: Optional[str] = None

    def validate(self):
        # Basic input validation
        if not self.name.strip() or len(self.name) > 100:
            raise ValueError("Invalid name")
        if not self.email.strip() or "@" not in self.email or len(self.email) > 254:
            raise ValueError("Invalid email")
        if not self.subject.strip() or len(self.subject) > 200:
            raise ValueError("Invalid subject")
        if not self.content.strip() or len(self.content) > 10000:
            raise ValueError("Invalid content")

@app.post("/api/v1/form/{form_key}")
@limiter.limit("5/minute")
async def submit_form(
    request: Request,
    form_key: str,
    redis_client: redis.Redis = Depends(lambda: redis_client)
):
    # Validate form key and get form config
    form_config = None
    for form_name, form_data in config["forms"].items():
        if form_data.get("key") == form_key:
            form_config = form_data
            break

    if not form_config:
        raise HTTPException(status_code=404, detail="Form not found")

    # Validate origin
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status_code=403, detail="Origin header required")
    
    # Check if origin is in allowed domains for this specific form
    origin_domain = origin.replace("https://", "").replace("http://", "")
    if not any(domain in origin_domain for domain in form_config.get("allowed_domains", [])):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    # Get form data
    form_data = await request.form()
    submission = FormSubmission(
        name=form_data.get("name"),
        email=form_data.get("email"),
        subject=form_data.get("subject"),
        content=form_data.get("content"),
        captcha_token=form_data.get("captcha_token")
    )

    # Check rate limit
    ip = request.client.host
    key = f"rate_limit:{ip}:{form_key}"
    current = await redis_client.get(key)
    if current and int(current) >= 5:  # 5 requests per minute
        raise HTTPException(status_code=429, detail="Too many requests")
    await redis_client.incr(key)
    await redis_client.expire(key, 60)  # Reset after 1 minute

    # Start email sending in background
    asyncio.create_task(send_form_submission_email(form_config, submission))
    
    # Return success response immediately
    return {"status": "success", "message": "Form submitted successfully"}

def save_to_sent_folder(msg: MIMEMultipart, smtp_user: str, smtp_password: str):
    """Save a copy of the email to the Sent Messages folder."""
    try:
        logger.info("🔐 Attempting to connect to IMAP server to save to Sent folder")
        with imaplib.IMAP4_SSL("imap.mail.me.com", 993) as imap:
            logger.info("🔑 Logging in to IMAP server")
            imap.login(smtp_user, smtp_password)
            logger.info("📤 Appending message to Sent Messages folder")
            imap.append(
                '"Sent Messages"',  # iCloud's sent folder name
                "",  # Flags
                imaplib.Time2Internaldate(time.time()),  # Date
                msg.as_bytes()  # Message
            )
            logger.info("✅ Successfully saved email to Sent Messages folder")
    except Exception as e:
        logger.error("❌ Failed to save email to Sent Messages folder: %s", str(e))
        logger.error("❌ Error details: %s", str(e.__class__.__name__))
        if hasattr(e, 'args'):
            logger.error("❌ Error args: %s", str(e.args))

async def send_form_submission_email(form_config: Dict[str, Any], submission: FormSubmission):
    """Send form submission email using iCloud SMTP."""
    try:
        # Get email configuration
        email_config = responses.get(form_config["to_email"][0])  # Get first email from to_email list
        if not email_config:
            raise ValueError(f"No email configuration found for {form_config['to_email'][0]}")

        # Create message
        msg = MIMEMultipart()
        msg["From"] = f"{form_config['from_name']} <{form_config['to_email'][0]}>"  # Use the form's to_email as the From address
        msg["To"] = form_config["to_email"][0]  # Use first email from to_email list
        msg["Subject"] = email_config["form_submission_template"]["subject"] % submission.subject

        # Add body
        body = email_config["form_submission_template"]["body"] % (
            submission.name,
            submission.email,
            submission.subject,
            submission.content
        )
        msg.attach(MIMEText(body, "html"))

        # Send email using iCloud SMTP
        smtp_user = os.getenv("ICLOUD_EMAIL")
        smtp_password = os.getenv("ICLOUD_PASSWORD")

        if not smtp_user or not smtp_password:
            raise ValueError("Missing iCloud email or password")

        async with aiosmtplib.SMTP(
            hostname="smtp.mail.me.com",
            port=587,
            use_tls=False,  # Don't use TLS initially
            start_tls=True  # Use STARTTLS instead
        ) as smtp:
            await smtp.login(smtp_user, smtp_password)
            await smtp.send_message(msg)
            logger.info("📨 Email sent successfully via SMTP")
            
            # Save copy to Sent Messages folder in a separate thread
            await asyncio.to_thread(save_to_sent_folder, msg, smtp_user, smtp_password)
            
    except Exception as e:
        logger.error("❌ Failed to send email: %s", str(e))
        logger.error("❌ Error details: %s", str(e.__class__.__name__))
        if hasattr(e, 'args'):
            logger.error("❌ Error args: %s", str(e.args))
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "form_handler:app",
        host="0.0.0.0",
        port=int(instance_port),
        workers=4  # Adjust based on CPU cores
    ) 
