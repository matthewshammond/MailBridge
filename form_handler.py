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
instance_port = os.getenv("PORT", "1234")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    name: str = Form(None),
    email: str = Form(None),
    subject: str = Form(None),
    content: str = Form(None),
    captcha_token: Optional[str] = Form(None),
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
    
    # Check if origin is in allowed domains
    origin_domain = origin.replace("https://", "").replace("http://", "")
    if not any(domain in origin_domain for domain in form_config.get("allowed_domains", [])):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    # If form data is provided, use it; otherwise try to parse JSON
    if name and email and subject and content:
        submission = FormSubmission(
            name=name,
            email=email,
            subject=subject,
            content=content,
            captcha_token=captcha_token
        )
    else:
        try:
            json_data = await request.json()
            submission = FormSubmission(**json_data)
        except:
            raise HTTPException(status_code=422, detail="Invalid request format")

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

async def send_form_submission_email(form_config: Dict[str, Any], submission: FormSubmission):
    # Get email configuration
    email_config = responses.get(form_config["to_email"][0])  # Get first email from to_email list
    if not email_config:
        raise ValueError(f"No email configuration found for {form_config['to_email'][0]}")

    # Create message
    msg = MIMEMultipart()
    msg["From"] = form_config["to_email"][0]  # Use the form's to_email as the From address
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

async def process_email(email_data: Dict[str, Any], responses: Dict[str, Any]) -> None:
    """Process a single email and send appropriate response."""
    try:
        logger.info("🔍 Processing email:")
        logger.info("   To: %s", email_data["to"])
        logger.info("   Subject: %s", email_data["subject"])

        # Get response configuration for this email
        response_config = responses.get(email_data["to"])
        if not response_config:
            logger.warning("⚠️  No response configuration found for %s", email_data["to"])
            return

        # Check if we have a matching subject
        matching_subject = None
        for subject in response_config.get("subjects", {}).keys():
            if email_data["subject"].startswith(subject):
                matching_subject = subject
                break

        if not matching_subject:
            logger.warning("⚠️  No matching response for subject: %s", email_data["subject"])
            return

        # Get the response template
        response_template = response_config["subjects"][matching_subject]
        logger.info("📝 Using response template: %s", matching_subject)

        # Extract the original subject from the email subject
        original_subject = email_data["subject"].replace(matching_subject, "").strip()

        # Format the response
        response_body = response_template["body"] % (
            email_data["from_name"],
            email_data["from_email"],
            original_subject,
            email_data["content"]
        )
        response_subject = response_template["subject"] % original_subject

        # Send the response
        await send_response_email(
            to_email=email_data["from_email"],
            to_name=email_data["from_name"],
            subject=response_subject,
            body=response_body
        )
        logger.info("✅ Response sent successfully")

    except Exception as e:
        logger.error("❌ Error processing email: %s", str(e))
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "form_handler:app",
        host="0.0.0.0",
        port=int(instance_port),
        workers=4  # Adjust based on CPU cores
    ) 