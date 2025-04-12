from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
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
import aioredis
from functools import lru_cache
import smtplib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Redis connection pool for rate limiting and caching
redis_pool = None

async def get_redis():
    global redis_pool
    if redis_pool is None:
        redis_pool = await aioredis.from_url(
            "redis://localhost",
            encoding="utf-8",
            decode_responses=True
        )
    return redis_pool

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
instance_email = os.getenv("INSTANCE_EMAIL")

if not instance_email:
    raise ValueError("INSTANCE_EMAIL environment variable must be set")

# Find the instance configuration
instance_config = None
for form_name, form_data in config["forms"].items():
    if form_data["to_email"][0] == instance_email:
        instance_config = form_data
        break

if not instance_config:
    raise ValueError(f"No configuration found for email {instance_email}")

# Get the response configuration for this instance
response_config = responses.get(instance_email)
if not response_config:
    raise ValueError(f"No response configuration found for email {instance_email}")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=instance_config.get("allowed_domains", []),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FormSubmission(BaseModel):
    name: str
    email: str
    subject: str
    content: str

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

def send_form_submission_email(form_data: dict, form_config: dict, responses: dict) -> bool:
    """Send form submission email using the template from responses.json"""
    try:
        # Get the form's email address
        to_email = form_config['to_email'][0]  # First email in the list
        
        # Get the form submission template
        template = responses[to_email]['form_submission_template']
        
        # Format the email body
        body = template['body'] % (
            form_data['name'],
            form_data['email'],
            form_data['subject'],
            form_data['content'].replace('\n', '<br>')
        )
        
        # Create the email
        msg = MIMEMultipart()
        msg['From'] = f"{form_config['from_name']} <{to_email}>"
        msg['To'] = to_email
        
        # Set subject based on the template
        msg['Subject'] = template['subject'] % form_data['subject']
        
        msg['Reply-To'] = f"{form_data['name']} <{form_data['email']}>"
        msg.attach(MIMEText(body, 'html'))
        
        # Send the email
        with smtplib.SMTP(config['global']['smtp']['host'], config['global']['smtp']['port']) as server:
            if not config['global']['smtp']['disable_tls']:
                server.starttls()
            server.login(
                config['global']['smtp']['user'],
                config['global']['smtp']['password']
            )
            server.send_message(msg)
        
        return True
    except Exception as e:
        logger.error(f"Error sending form submission email: {str(e)}")
        return False

@app.post("/api/v1/form/{form_key}")
@limiter.limit("5/minute")
async def handle_form_submission(form_key: str, request: Request, submission: FormSubmission):
    """Handle form submissions"""
    try:
        # Validate form key and get form config
        form_config = next((f for f in config['forms'].values() if f['key'] == form_key), None)
        if not form_config:
            raise HTTPException(status_code=404, detail="Form not found")
        
        # Validate origin
        origin = request.headers.get('origin', '')
        if not any(domain in origin for domain in form_config['allowed_domains']):
            raise HTTPException(status_code=403, detail="Domain not allowed")
        
        # Rate limiting
        client_ip = request.client.host
        if not rate_limiter.check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Too many requests")
        
        # Send form submission email
        if not send_form_submission_email(submission.dict(), form_config, responses):
            raise HTTPException(status_code=500, detail="Failed to send email")
        
        return {"status": "success", "message": "Form submitted successfully"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error handling form submission: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(instance_port),
        workers=4  # Adjust based on CPU cores
    ) 