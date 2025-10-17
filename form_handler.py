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
import aiohttp

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("✅ Loaded response config with %d email aliases",
                len(responses))
    for email, config in responses.items():
        logger.info(
            "📋 %s has %d response templates", email, len(
                config.get("subjects", {}))
        )
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
    decode_responses=True,
)


# Cache configuration
@lru_cache(maxsize=128)
def get_form_config(form_key: str):
    for form_name, form_data in config["forms"].items():
        if form_data["key"] == form_key:
            return form_data
    return None


def expand_env_vars(obj):
    """Recursively expand environment variables in config objects"""
    if isinstance(obj, dict):
        return {k: expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars(item) for item in obj]
    elif isinstance(obj, str) and obj.startswith('${') and obj.endswith('}'):
        env_var = obj[2:-1]
        return os.getenv(env_var, obj)
    else:
        return obj

# Load configuration
config_path = Path("/config/config.yml")
if not config_path.exists():
    config_path = Path("config/config.yml")

with open(config_path, "r") as f:
    config_raw = yaml.safe_load(f)
    config = expand_env_vars(config_raw)

# Load responses
responses_path = Path("/config/responses.json")
if not responses_path.exists():
    responses_path = Path("config/responses.json")

with open(responses_path, "r") as f:
    responses = json.load(f)

# Get instance-specific configuration
instance_port = os.getenv("PORT", "2525")
instance_emails = os.getenv("INSTANCE_EMAILS", "").split(
    ",")  # Allow multiple emails

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
    website: Optional[str] = None  # Honeypot field

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
        
        # Honeypot validation - if filled, it's likely a bot
        if self.website and self.website.strip():
            raise ValueError("Bot detected")
        
        # Basic spam detection for obvious keyboard smashing
        if self._is_spam():
            raise ValueError("Spam detected")

    def _is_spam(self) -> bool:
        """Detect obvious spam patterns like keyboard smashing and random string generation"""
        import re
        import math
        from collections import Counter
        
        # Check for random character patterns (keyboard smashing)
        # Look for strings with high ratio of consonants to vowels
        name_clean = re.sub(r'[^a-zA-Z]', '', self.name.lower())
        content_clean = re.sub(r'[^a-zA-Z]', '', self.content.lower())
        
        if len(name_clean) > 3:
            consonants = len(re.sub(r'[aeiou]', '', name_clean))
            vowels = len(re.sub(r'[^aeiou]', '', name_clean))
            if consonants > 0 and vowels > 0:
                consonant_ratio = consonants / (consonants + vowels)
                # If more than 80% consonants, likely keyboard smashing
                if consonant_ratio > 0.8:
                    return True
        
        # Check for repeated character patterns
        if len(name_clean) > 5:
            # Look for 3+ consecutive same characters
            if re.search(r'(.)\1{2,}', name_clean):
                return True
        
        # Check content for similar patterns
        if len(content_clean) > 5:
            consonants = len(re.sub(r'[aeiou]', '', content_clean))
            vowels = len(re.sub(r'[^aeiou]', '', content_clean))
            if consonants > 0 and vowels > 0:
                consonant_ratio = consonants / (consonants + vowels)
                if consonant_ratio > 0.8:
                    return True
            
            # Look for repeated character patterns in content
            if re.search(r'(.)\1{2,}', content_clean):
                return True
        
        # Additional patterns for keyboard smashing
        # Check for very short names with mostly consonants (but not common names)
        if len(name_clean) >= 3 and len(name_clean) <= 8:
            consonants = len(re.sub(r'[aeiou]', '', name_clean))
            vowels = len(re.sub(r'[^aeiou]', '', name_clean))
            # More restrictive: need high consonant ratio AND few vowels
            if consonants >= 4 and vowels <= 2 and consonants / (consonants + vowels) > 0.6:
                return True
        
        # Check for content with similar patterns
        if len(content_clean) >= 4 and len(content_clean) <= 15:
            consonants = len(re.sub(r'[aeiou]', '', content_clean))
            vowels = len(re.sub(r'[^aeiou]', '', content_clean))
            # More restrictive: need high consonant ratio AND few vowels
            if consonants >= 5 and vowels <= 3 and consonants / (consonants + vowels) > 0.6:
                return True
        
        # Check for obvious keyboard patterns (like "asdf", "qwer", "zxcv")
        keyboard_patterns = ['asdf', 'qwer', 'zxcv', 'hjkl', 'fdsa', 'rewq', 'vcxz', 'lkjh']
        if name_clean in keyboard_patterns or content_clean in keyboard_patterns:
            return True
        
        # ENHANCED DETECTION FOR SOPHISTICATED ATTACKS
        
        # 1. Entropy-based detection for random string generation
        if self._is_high_entropy_random(name_clean) or self._is_high_entropy_random(content_clean):
            return True
        
        # 2. Mixed case pattern detection (random generators often use mixed case)
        if self._has_suspicious_case_pattern(self.name) or self._has_suspicious_case_pattern(self.content):
            return True
        
        # 3. Character distribution analysis
        if self._has_unusual_character_distribution(name_clean) or self._has_unusual_character_distribution(content_clean):
            return True
        
        # 4. Length-based random string detection
        if self._is_random_length_pattern(name_clean) or self._is_random_length_pattern(content_clean):
            return True
        
        return False
    
    def _calculate_entropy(self, text: str) -> float:
        """Calculate Shannon entropy of a string"""
        from collections import Counter
        import math
        
        if not text or len(text) < 2:
            return 0
        
        counts = Counter(text.lower())
        entropy = 0
        for count in counts.values():
            p = count / len(text)
            entropy -= p * math.log2(p)
        
        return entropy
    
    def _is_high_entropy_random(self, text: str) -> bool:
        """Detect high-entropy strings that look randomly generated"""
        if len(text) < 6:
            return False
        
        # For longer text, check if it contains common English words
        # If it does, it's likely legitimate content, not random
        if len(text) > 15:
            common_words = ['the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'among', 'would', 'like', 'request', 'access', 'platform', 'please', 'thank', 'you', 'your', 'help', 'need', 'want', 'get', 'can', 'will', 'should', 'could', 'may', 'might', 'must', 'have', 'has', 'had', 'do', 'does', 'did', 'be', 'am', 'is', 'are', 'was', 'were', 'been', 'being']
            text_lower = text.lower()
            word_count = sum(1 for word in common_words if word in text_lower)
            # If it contains 3+ common words, it's likely legitimate
            if word_count >= 3:
                return False
        
        entropy = self._calculate_entropy(text)
        # Random strings typically have entropy > 3.5
        # But we need to be careful not to block legitimate names
        if entropy > 3.8 and len(text) >= 8:
            return True
        
        # Additional check: very high entropy with mixed case
        if entropy > 3.6 and any(c.isupper() for c in text) and any(c.islower() for c in text):
            return True
        
        return False
    
    def _has_suspicious_case_pattern(self, text: str) -> bool:
        """Detect suspicious mixed case patterns typical of random generators"""
        if len(text) < 8:
            return False
        
        # Count case transitions
        case_transitions = 0
        for i in range(len(text) - 1):
            if text[i].isupper() != text[i+1].isupper():
                case_transitions += 1
        
        # If more than 60% of transitions are case changes, likely random
        transition_ratio = case_transitions / (len(text) - 1)
        if transition_ratio > 0.6:
            return True
        
        # Check for alternating case patterns (very suspicious)
        alternating_count = 0
        for i in range(len(text) - 2):
            if (text[i].isupper() != text[i+1].isupper() and 
                text[i+1].isupper() != text[i+2].isupper()):
                alternating_count += 1
        
        # If more than 40% alternating patterns, likely random
        if len(text) > 2 and alternating_count / (len(text) - 2) > 0.4:
            return True
        
        return False
    
    def _has_unusual_character_distribution(self, text: str) -> bool:
        """Detect unusual character distributions typical of random generation"""
        import re
        
        if len(text) < 6:
            return False
        
        # Check for very unusual consonant clusters (6+ consonants in a row)
        consonant_clusters = re.findall(r'[bcdfghjklmnpqrstvwxyz]{6,}', text.lower())
        if len(consonant_clusters) > 0:
            return True
        
        # Check for unusual vowel patterns (5+ vowels in a row)
        vowel_patterns = re.findall(r'[aeiou]{5,}', text.lower())
        if len(vowel_patterns) > 0:
            return True
        
        # Check for unusual character frequency (too many rare letters)
        rare_letters = 'qxzjk'
        rare_count = sum(1 for c in text.lower() if c in rare_letters)
        if rare_count > len(text) * 0.4:  # More than 40% rare letters
            return True
        
        # Check for very unusual patterns that are clearly random
        # Look for patterns like "bcdfgh" or "qwerty" type sequences
        unusual_patterns = [
            r'[bcdfghjklmnpqrstvwxyz]{5,}',  # 5+ consonants
            r'[aeiou]{4,}',  # 4+ vowels
            r'qwerty',  # Exact QWERTY sequence
            r'asdfgh',  # Exact ASDF sequence
            r'zxcvbn',  # Exact ZXCV sequence
            r'qwer',  # QWER sequence
            r'asdf',  # ASDF sequence
            r'zxcv',  # ZXCV sequence
        ]
        
        for pattern in unusual_patterns:
            if re.search(pattern, text.lower()):
                return True
        
        return False
    
    def _is_random_length_pattern(self, text: str) -> bool:
        """Detect patterns typical of random string generators"""
        from collections import Counter
        import math
        
        if len(text) < 6:
            return False
        
        # Random generators often create strings of specific lengths
        # Check for lengths that are powers of 2 or common random lengths
        suspicious_lengths = [8, 10, 12, 14, 16, 20, 24, 32]
        if len(text) in suspicious_lengths:
            # Additional check: if it's a suspicious length AND has high entropy
            entropy = self._calculate_entropy(text)
            if entropy > 3.2:
                return True
        
        return False


async def _is_suspicious_behavior(redis_client: redis.Redis, ip: str, submission: FormSubmission) -> bool:
    """Detect suspicious behavioral patterns across submissions"""
    import json
    import time
    
    # Track submission patterns for this IP
    pattern_key = f"behavior:{ip}"
    
    # Get existing pattern data
    existing_data = await redis_client.get(pattern_key)
    if existing_data:
        pattern_data = json.loads(existing_data)
    else:
        pattern_data = {
            "submissions": [],
            "random_names": 0,
            "random_content": 0,
            "email_domains": set(),
            "first_seen": time.time()
        }
    
    # Analyze current submission
    is_random_name = _is_random_looking_string(submission.name)
    is_random_content = _is_random_looking_string(submission.content)
    
    # Count random patterns
    if is_random_name:
        pattern_data["random_names"] += 1
    if is_random_content:
        pattern_data["random_content"] += 1
    
    # Track email domains
    email_domain = submission.email.split('@')[1] if '@' in submission.email else ''
    pattern_data["email_domains"].add(email_domain)
    
    # Add current submission to history
    pattern_data["submissions"].append({
        "timestamp": time.time(),
        "name": submission.name,
        "email": submission.email,
        "content": submission.content,
        "is_random_name": is_random_name,
        "is_random_content": is_random_content
    })
    
    # Keep only last 10 submissions
    if len(pattern_data["submissions"]) > 10:
        pattern_data["submissions"] = pattern_data["submissions"][-10:]
    
    # Convert set to list for JSON serialization
    pattern_data["email_domains"] = list(pattern_data["email_domains"])
    
    # Save updated pattern data
    await redis_client.setex(pattern_key, 86400, json.dumps(pattern_data))  # 24 hour expiry
    
    # Analyze patterns for suspicious behavior
    total_submissions = len(pattern_data["submissions"])
    
    # Suspicious if:
    # 1. Multiple submissions with random-looking names/content
    # 2. Using multiple different email domains (email rotation)
    # 3. Consistent pattern of random strings
    
    if total_submissions >= 2:
        random_name_ratio = pattern_data["random_names"] / total_submissions
        random_content_ratio = pattern_data["random_content"] / total_submissions
        unique_domains = len(pattern_data["email_domains"])
        
        # High ratio of random names/content + multiple domains = suspicious
        if (random_name_ratio >= 0.8 and random_content_ratio >= 0.8 and 
            unique_domains >= 2):
            return True
        
        # Very high random content ratio (90%+) is suspicious regardless
        if random_content_ratio >= 0.9:
            return True
    
    return False


def _is_random_looking_string(text: str) -> bool:
    """Quick check if a string looks randomly generated"""
    import re
    import math
    from collections import Counter
    
    if len(text) < 6:
        return False
    
    # For longer text, check if it contains common English words
    if len(text) > 15:
        common_words = ['the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'among', 'would', 'like', 'request', 'access', 'platform', 'please', 'thank', 'you', 'your', 'help', 'need', 'want', 'get', 'can', 'will', 'should', 'could', 'may', 'might', 'must', 'have', 'has', 'had', 'do', 'does', 'did', 'be', 'am', 'is', 'are', 'was', 'were', 'been', 'being']
        text_lower = text.lower()
        word_count = sum(1 for word in common_words if word in text_lower)
        # If it contains 3+ common words, it's likely legitimate
        if word_count >= 3:
            return False
    
    # Clean the text
    clean_text = re.sub(r'[^a-zA-Z]', '', text.lower())
    
    # Check entropy
    if len(clean_text) >= 6:
        counts = Counter(clean_text)
        entropy = 0
        for count in counts.values():
            p = count / len(clean_text)
            entropy -= p * math.log2(p)
        
        # High entropy suggests randomness
        if entropy > 3.5:
            return True
    
    # Check for unusual character patterns
    consonant_clusters = re.findall(r'[bcdfghjklmnpqrstvwxyz]{6,}', clean_text)
    if len(consonant_clusters) > 0:
        return True
    
    # Check for unusual vowel patterns
    vowel_patterns = re.findall(r'[aeiou]{5,}', clean_text)
    if len(vowel_patterns) > 0:
        return True
    
    # Check for keyboard patterns
    keyboard_patterns = [
        r'qwerty',  # Exact QWERTY sequence
        r'asdfgh',  # Exact ASDF sequence
        r'zxcvbn',  # Exact ZXCV sequence
        r'qwer',  # QWER sequence
        r'asdf',  # ASDF sequence
        r'zxcv',  # ZXCV sequence
    ]
    
    for pattern in keyboard_patterns:
        if re.search(pattern, clean_text):
            return True
    
    return False


async def verify_recaptcha_v3(token: str, secret_key: str) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": secret_key, "response": token},
        ) as response:
            result = await response.json()
            return result.get("success", False)


@app.post("/api/v1/form/{form_key}")
@limiter.limit("5/minute")
async def submit_form(
    request: Request,
    form_key: str,
    redis_client: redis.Redis = Depends(lambda: redis_client),
):
    # Check global mode configuration
    global_mode = config.get("global", {}).get("mode", "current")
    
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
    if not any(
        domain in origin_domain for domain in form_config.get("allowed_domains", [])
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    # Get form data
    form_data = await request.form()
    submission = FormSubmission(
        name=form_data.get("name"),
        email=form_data.get("email"),
        subject=form_data.get("subject"),
        content=form_data.get("content"),
        captcha_token=form_data.get("captcha_token"),
        website=form_data.get("website"),  # Honeypot field
    )

    # Get the real IP address (handle reverse proxies)
    def get_real_ip(request: Request) -> str:
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # Fallback to direct client IP
        return request.client.host

    # Log the submission attempt with real IP address
    real_ip = get_real_ip(request)
    logger.info(f"Form submission attempt from IP {real_ip}: {submission.name} <{submission.email}> - {submission.subject}")

    # Validate the submission (includes honeypot and spam checks)
    try:
        submission.validate()
    except ValueError as e:
        logger.warning(f"Form validation failed from IP {real_ip}: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid form submission")
    
    # Additional behavioral analysis for sophisticated attackers
    if await _is_suspicious_behavior(redis_client, real_ip, submission):
        logger.warning(f"Suspicious behavior detected from IP {real_ip}: {submission.name} <{submission.email}>")
        raise HTTPException(status_code=400, detail="Suspicious submission pattern detected")

    # Check rate limit (use real IP for consistency)
    key = f"rate_limit:{real_ip}:{form_key}"
    current = await redis_client.get(key)
    if current and int(current) >= 5:  # 5 requests per minute
        raise HTTPException(status_code=429, detail="Too many requests")
    await redis_client.incr(key)
    await redis_client.expire(key, 60)  # Reset after 1 minute

    # Verify reCAPTCHA if enabled
    if form_config.get("captcha", {}).get("provider") == "recaptcha":
        if not submission.captcha_token:
            raise HTTPException(
                status_code=400, detail="reCAPTCHA token required")

        is_valid = await verify_recaptcha_v3(
            submission.captcha_token, form_config["captcha"]["secret_key"]
        )

        if not is_valid:
            raise HTTPException(
                status_code=400, detail="Invalid reCAPTCHA token")

    # Handle different modes
    if global_mode == "postmark":
        # Start Postmark-specific email processing in background
        asyncio.create_task(send_postmark_form_submission_email(form_config, submission))
    else:
        # Start iCloud email sending in background
        asyncio.create_task(send_form_submission_email(form_config, submission))
    
    # Return success response immediately
    return {"status": "success", "message": "Form submitted successfully"}


def save_to_sent_folder(msg: MIMEMultipart, smtp_user: str, smtp_password: str):
    """Save a copy of the email to the Sent Messages folder."""
    try:
        logger.info(
            "🔐 Attempting to connect to IMAP server to save to Sent folder")
        with imaplib.IMAP4_SSL("imap.mail.me.com", 993) as imap:
            logger.info("🔑 Logging in to IMAP server")
            imap.login(smtp_user, smtp_password)
            logger.info("📤 Appending message to Sent Messages folder")
            imap.append(
                '"Sent Messages"',  # iCloud's sent folder name
                "",  # Flags
                imaplib.Time2Internaldate(time.time()),  # Date
                msg.as_bytes(),  # Message
            )
            logger.info("✅ Successfully saved email to Sent Messages folder")
    except Exception as e:
        logger.error(
            "❌ Failed to save email to Sent Messages folder: %s", str(e))
        logger.error("❌ Error details: %s", str(e.__class__.__name__))
        if hasattr(e, "args"):
            logger.error("❌ Error args: %s", str(e.args))


async def send_form_submission_email(
    form_config: Dict[str, Any], submission: FormSubmission
):
    """Send form submission email using iCloud SMTP."""
    try:
        # Get email configuration
        email_config = responses.get(
            form_config["to_email"][0]
        )  # Get first email from to_email list
        if not email_config:
            raise ValueError(
                f"No email configuration found for {
                    form_config['to_email'][0]}"
            )

        # Create message
        msg = MIMEMultipart()
        msg["From"] = (
            # Use the form's to_email as the From address
            f"{form_config['from_name']} <{form_config['to_email'][0]}>"
        )
        # Use first email from to_email list
        msg["To"] = form_config["to_email"][0]
        msg["Subject"] = (
            email_config["form_submission_template"]["subject"] % submission.subject
        )

        # Add body
        body = email_config["form_submission_template"]["body"] % (
            submission.name,
            submission.email,
            submission.subject,
            submission.content,
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
            start_tls=True,  # Use STARTTLS instead
        ) as smtp:
            await smtp.login(smtp_user, smtp_password)
            await smtp.send_message(msg)
            logger.info("📨 Email sent successfully via SMTP")

            # Save copy to Sent Messages folder in a separate thread
            await asyncio.to_thread(save_to_sent_folder, msg, smtp_user, smtp_password)

    except Exception as e:
        logger.error("❌ Failed to send email: %s", str(e))
        logger.error("❌ Error details: %s", str(e.__class__.__name__))
        if hasattr(e, "args"):
            logger.error("❌ Error args: %s", str(e.args))
        raise


async def send_postmark_form_submission_email(
    form_config: Dict[str, Any], submission: FormSubmission
):
    """Send form submission email using Postmark-specific formatting and logic."""
    try:
        # Get email configuration
        email_config = responses.get(
            form_config["to_email"][0]
        )  # Get first email from to_email list
        if not email_config:
            raise ValueError(
                f"No email configuration found for {
                    form_config['to_email'][0]}"
            )

        # Create message with Postmark-specific formatting
        msg = MIMEMultipart()
        msg["From"] = (
            f"{form_config['from_name']} <{form_config['to_email'][0]}>"
        )
        msg["To"] = form_config["to_email"][0]
        # Format the subject using the email configuration template (same as iCloud mode)
        formatted_subject = email_config["form_submission_template"]["subject"] % submission.subject
        msg["Subject"] = formatted_subject
        postmark_body = f"""
        <html>
        <body>
            <h2>Postmark Inquiry Received</h2>
            <p><strong>Customer Name:</strong> {submission.name}</p>
            <p><strong>Customer Email:</strong> {submission.email}</p>
            <p><strong>Inquiry Subject:</strong> {submission.subject}</p>
            <p><strong>Message:</strong></p>
            <div style="background-color: #f5f5f5; padding: 15px; border-left: 4px solid #ff6b6b; margin: 10px 0;">
                {submission.content}
            </div>
            <hr>
            <p><em>This inquiry was received through your Postmark integration.</em></p>
        </body>
        </html>
        """
        msg.attach(MIMEText(postmark_body, "html"))

        # Use per-form Postmark credentials if present, else fallback to env
        postmark_api_key = form_config.get("postmark", {}).get("api_key") or os.getenv("POSTMARK_API_KEY")
        postmark_sender_email = form_config.get("postmark", {}).get("sender_email") or os.getenv("POSTMARK_SENDER_EMAIL")

        if not postmark_api_key or not postmark_sender_email:
            raise ValueError("Missing Postmark API key or sender email")

        from postmarker.core import PostmarkClient
        postmark = PostmarkClient(server_token=postmark_api_key)
        response = postmark.emails.send(
            From=postmark_sender_email,
            To=form_config["to_email"][0],
            Subject=formatted_subject,
            HtmlBody=postmark_body
        )
        logger.info("📨 Postmark email sent successfully via API")
        logger.info(f"📧 Postmark Message ID: {response.get('MessageID')}")

    except Exception as e:
        logger.error("❌ Failed to send Postmark email: %s", str(e))
        logger.error("❌ Error details: %s", str(e.__class__.__name__))
        if hasattr(e, "args"):
            logger.error("❌ Error args: %s", str(e.args))
        raise


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "form_handler:app",
        host="0.0.0.0",
        port=int(instance_port),
        workers=4,  # Adjust based on CPU cores
    )
