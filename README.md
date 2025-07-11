# MailBridge

<div align="center">
  <a href="https://github.com/matthewshammond/mailbridge">
    <img src="mailbridge-wide.png" alt="MailBridge Logo" width="500"/>
  </a>
  <h3>A modern, secure, and efficient form submission and email response system</h3>
</div>

## Table of Contents

- [Features](#features)
- [Setup](#setup)
  - [Environment Variables](#environment-variables)
  - [Configuration Files](#configuration-files)
    - [config.yml](#configyml)
    - [responses.json](#responsesjson)
    - [compose.yaml](#composeyaml)
  - [Website Integration](#website-integration)
    - [CAPTCHA Setup](#captcha-setup)
    - [Form Implementations](#form-implementations)
      - [Basic Form Implementation](#basic-form-implementation)
      - [Simple jQuery Implementation](#simple-jquery-implementation)
      - [Complete Form Implementation (without CAPTCHA)](#complete-form-implementation-without-captcha)
      - [Complete Form Implementation (with CAPTCHA)](#complete-form-implementation-with-captcha)
  - [Running Services](#running-services)
  - [Testing](#testing)
- [License](#license)

## Features

- FastAPI backend with async support
- Docker containerization
- Redis for rate limiting and caching
- iCloud SMTP integration
- Automated email responses
- Form submission handling
- Rate limiting
- CORS support
- Gzip compression
- CAPTCHA support (optional)
- Multiple email alias support
- **Mode switching between iCloud and Postmark integrations**
- **Postmark-specific email formatting and branding**

## Setup

1. Clone the repository:
```bash
git clone https://github.com/matthewshammond/mailbridge.git
cd mailbridge
```

2. Update the `.env` file with your settings:

For iCloud mode:
```bash
# iCloud settings (set in .env)
ICLOUD_EMAIL=your_icloud_email@icloud.com
ICLOUD_PASSWORD=your_app_specific_password
```

For Postmark mode:
```bash
# Postmark settings (set in .env) - used as fallback if not specified per-form
POSTMARK_API_KEY=your_postmark_api_key
POSTMARK_SENDER_EMAIL=your_verified_sender@yourdomain.com
```

**Note:** You can also specify Postmark credentials per-form in `config.yml` (see example above). If a form has its own `postmark` section, it will use those credentials instead of the environment variables.

For both modes:
```bash
# Pushover integration (for push notifications)
PUSHOVER_ENABLED=true                # Set to 'true' to enable, 'false' to disable
PUSHOVER_USER_KEY=your_user_key      # Your Pushover user key
PUSHOVER_API_TOKEN=your_api_token    # Your Pushover application API token
```

> **Note:**
> - `PORT` and `INSTANCE_EMAILS` are typically set in `compose.yaml` as environment variables for the container, not in `.env` directly.
> - Use `.env.sample` as a starting point for your own `.env` file.
> - Per-form branding for outgoing emails (name and email) is set in `config/config.yml` under each form's `from_name` and `to_email`.

### Configuration Files

1. **config.yml** - Form and domain configuration:

```yaml
forms:
  contact_form:
    key: "your-form-key"
    to_email: ["contact@example.com"]
    allowed_domains: ["https://example.com"]
    from_name: "Your Name"
    rate_limit: 5  # requests per minute

  another_form:
    key: "another-form-key"
    to_email: ["info@example.com"]
    allowed_domains: ["https://example.com"]
    from_name: "Your Name"
    rate_limit: 5  # requests per minute

  # Optional: Add postmark section for per-form Postmark credentials
  # Only needed when using postmark mode and you want different API keys per form
  postmark_form:
    key: "postmark-form-key"
    to_email: ["hello@yourdomain.com"]
    allowed_domains: ["https://yourdomain.com"]
    from_name: "Your Name"
    postmark:
      api_key: "your-postmark-api-key-for-this-form"
      sender_email: "hello@yourdomain.com"
```

2. **responses.json** - Email templates and responses:

```json
{
  "contact@example.com": {
    "subjects": {
      "general": "Re: %s",
      "support": "Re: Support Request - %s",
      "feedback": "Re: Feedback - %s"
    },
    "form_submission_template": {
      "subject": "New Submission with subject: %s",
      "body": "<p>Name: %s<br>Email: %s<br>Subject: %s<br><br>%s</p>"
    },
    "response_templates": {
      "general": "<p>Thank you for your message. We will get back to you soon.</p>",
      "support": "<p>Thank you for contacting support. We will address your issue shortly.</p>",
      "feedback": "<p>Thank you for your feedback. We appreciate your input.</p>"
    },
    "signature": "<p>Best regards,<br>Your Name</p>"
  },
  "info@example.com": {
    "subjects": {
      "general": "Re: %s",
      "inquiry": "Re: Inquiry - %s"
    },
    "form_submission_template": {
      "subject": "New Submission with subject: %s",
      "body": "<p>Name: %s<br>Email: %s<br>Subject: %s<br><br>%s</p>"
    },
    "response_templates": {
      "general": "<p>Thank you for your message. We will get back to you soon.</p>",
      "inquiry": "<p>Thank you for your inquiry. We will respond shortly.</p>"
    },
    "signature": "<p>Best regards,<br>Your Name</p>"
  }
}
```

3. **compose.yaml** - Docker services configuration:

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: mailbridge-redis
    restart: unless-stopped
    volumes:
      - redis_data:/data
    deploy:
      resources:
        limits:
          cpus: '0.25'
          memory: 256M

  mailbridge:
    build: .
    container_name: mailbridge
    restart: unless-stopped
    env_file: .env
    environment:
      - PORT=2525
      - INSTANCE_EMAILS=info@example.com,contact@website.com
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config:/config
    ports:
      - "2525:2525"
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
      restart_policy:
        condition: on-failure
        max_attempts: 3
        window: 120s

volumes:
  redis_data:
```

### Mode Configuration

MailBridge supports multiple integration modes that can be easily switched using the provided utility script.

#### Available Modes

1. **iCloud Mode** (default): Standard MailBridge functionality using iCloud
   - Regular email formatting
   - Standard auto-reply system
   - Traditional form processing using iCloud SMTP

2. **Postmark Mode**: Postmark-specific integration
   - Postmark-branded email formatting
   - Subject lines prefixed with "Postmark Inquiry:"
   - Styled auto-replies with Postmark branding
   - Enhanced Pushover notifications
   - Uses Postmark API for email delivery

#### Switching Modes

Use the provided utility script to switch between modes:

```bash
# Switch to Postmark mode
python switch_mode.py postmark

# Switch back to iCloud mode
python switch_mode.py icloud

# Check current mode status
python switch_mode.py status
```

#### Configuration

The mode is configured in your `config.yml` file under the global section:

```yaml
global:
    # Mode configuration: "iCloud" for existing setup, "postmark" for Postmark integration
    mode: iCloud  # Options: iCloud, postmark
    smtp:
        host: smtp.mail.me.com
        port: 587
        user: ${ICLOUD_EMAIL}
        password: ${ICLOUD_PASSWORD}
        disable_tls: false
```

#### Postmark Mode Features

When in Postmark mode, the following changes occur:

- **Form Submissions**: Emails are formatted with Postmark-specific styling and branding
- **Subject Lines**: All subjects are prefixed with "Postmark Inquiry:"
- **Auto-Replies**: Responses include Postmark branding and styled formatting
- **Notifications**: Pushover notifications indicate Postmark mode
- **Email Processing**: The system looks for Postmark-specific subject patterns
- **Email Delivery**: Uses Postmark API instead of iCloud SMTP
- **Per-Form Credentials**: Supports different Postmark API keys per form (optional)

### Website Integration

#### CAPTCHA Setup

Before implementing the form, you need to set up CAPTCHA protection. Both options are free for personal and small business use:

1. **reCAPTCHA (by Google) - Recommended**:
   - Free for up to 10,000 assessments per month
   - Invisible to users (better user experience)
   - Better spam detection
   - Go to https://www.google.com/recaptcha/admin
   - Sign in with your Google account
   - Click "Register a new site"
   - Choose "reCAPTCHA v3" (recommended)
   - Add your domain(s)
   - You'll receive two keys:
     - Site Key: Use this in your website code
     - Secret Key: Add this to your MailBridge configuration

2. **hCaptcha**:
   - Free for personal and small business use
   - Privacy-focused alternative to Google
   - Requires users to complete a visual challenge
   - Go to https://dashboard.hcaptcha.com/
   - Create an account
   - Add your website
   - You'll receive two keys:
     - Site Key: Use this in your website code
     - Secret Key: Add this to your MailBridge configuration

After getting your keys, update your MailBridge configuration:

```yaml
# In config.yml
forms:
    your-form-key:
        # ... other settings ...
        captcha:
            provider: "recaptcha"  # or "hcaptcha"
            secret_key: "your-secret-key-here"
```

#### Form Implementations

##### Basic Form Implementation

Add this HTML to your website:

```html
<form id="contact" method="post">
    <input type="text" name="name" required placeholder="Your Name">
    <input type="email" name="email" required placeholder="Your Email">
    <input type="text" name="subject" required placeholder="Subject">
    <textarea name="content" required placeholder="Your Message"></textarea>
    <button type="submit">Send Message</button>
</form>
```

##### Simple jQuery Implementation

```javascript
$(document).ready(function() {
    $("#contact").submit(function(e) {
        e.preventDefault();
        $.ajax({
            url: "https://your-mailbridge-server:2525/api/v1/form/your-form-key",
            method: "POST",
            data: $(this).serialize(),
            dataType: "json",
            success: function(data) {
                alert("Message sent successfully!");
            },
            error: function(err) {
                alert("Error sending message");
            }
        });
    });
});
```

##### Complete Form Implementation (without CAPTCHA)

```html
<form id="contact" method="post">
    <div class="form-group">
        <input type="text" name="name" required placeholder="Your Name">
    </div>
    <div class="form-group">
        <input type="email" name="email" required placeholder="Your Email">
    </div>
    <div class="form-group">
        <input type="text" name="subject" required placeholder="Subject">
    </div>
    <div class="form-group">
        <textarea name="content" required placeholder="Your Message"></textarea>
    </div>
    <button type="submit">Send Message</button>
    <div class="overlay">
        <div></div>
    </div>
</form>

<style>
.form-group {
    margin-bottom: 1rem;
}
input, textarea {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid #ddd;
    border-radius: 4px;
}
textarea {
    height: 150px;
    resize: vertical;
}
button {
    background: #007bff;
    color: white;
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
}
.overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: none;
    justify-content: center;
    align-items: center;
}
.overlay > div {
    background: white;
    padding: 2rem;
    border-radius: 4px;
    max-width: 400px;
    width: 100%;
}
</style>

<script>
$(document).ready(function() {
    var $contactForm = $("#contact");
    $contactForm.submit(function(e) {
        e.preventDefault();
        $.ajax({
            url: "https://your-mailbridge-server:2525/api/v1/form/your-form-key",
            method: "POST",
            data: $(this).serialize(),
            dataType: "json",
            beforeSend: function() {
                $contactForm.find(".overlay div")
                    .html('<div class="alert alert--loading"><i class="fa fa-circle-o-notch fa-spin"></i> Sending message...</div>');
                $contactForm.find(".overlay").fadeIn();
            },
            success: function(data) {
                $contactForm.find(".alert--loading").hide();
                $contactForm.find(".overlay div")
                    .html('<div class="alert alert--success"><i class="fa fa-check"></i> Message sent successfully!</div>');
                $contactForm.find(".overlay").fadeIn();
                setTimeout(function() {
                    window.location.href = "https://your-website.com/thank-you";
                }, 3000);
            },
            error: function(err) {
                $contactForm.find(".alert--loading").hide();
                $contactForm.find(".overlay div")
                    .html('<div class="alert alert--error"><i class="fa fa-warning"></i> Error sending message</div>');
                $contactForm.find(".overlay").fadeIn();
            }
        });
    });
    $contactForm.find(".overlay").click(function(e) {
        $(this).fadeOut();
    });
});
</script>
```

##### Complete Form Implementation (with CAPTCHA)

1. Add this to your website's HTML:
```html
<!-- Add reCAPTCHA script (choose one) -->
<script src="https://www.google.com/recaptcha/api.js?render=your-site-key"></script>
<!-- OR hCaptcha script -->
<script src="https://js.hcaptcha.com/1/api.js" async defer></script>

<!-- Add jQuery -->
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>

<!-- Add Font Awesome for icons -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">

<!-- Form HTML -->
<form id="contact-form" class="pure-form">
    <div class="meta">
        <input type="text" name="name" placeholder="Name" required>
        <input type="email" name="email" placeholder="Email" required>
        <input type="text" name="subject" placeholder="Subject" required>
    </div>
    <textarea name="content" placeholder="Your message" rows="7" required></textarea>
    
    <!-- Add hCaptcha widget (if using hCaptcha) -->
    <div class="h-captcha" data-sitekey="your-site-key"></div>
    
    <button type="submit">
        <i class="fa fa-send-o"></i> Send
    </button>
    <div class="overlay">
        <div></div>
    </div>
</form>
```

2. Add the CSS:
```css
#contact-form {
    max-width: 600px;
    margin: 0 auto;
    padding: 20px;
    position: relative;
}

#contact-form .meta {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 10px;
    margin-bottom: 10px;
}

#contact-form input,
#contact-form textarea {
    width: 100%;
    padding: 10px;
    border: 1px solid #ddd;
    border-radius: 4px;
}

#contact-form textarea {
    height: 150px;
    resize: vertical;
}

#contact-form button {
    background: #007bff;
    color: white;
    padding: 10px 20px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    margin-top: 10px;
}

#contact-form button:disabled {
    background: #ccc;
    cursor: not-allowed;
}

#contact-form .overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: none;
    justify-content: center;
    align-items: center;
}

#contact-form .overlay > div {
    background: white;
    padding: 20px;
    border-radius: 4px;
    max-width: 400px;
    width: 100%;
}

.alert {
    padding: 10px;
    border-radius: 4px;
    margin: 10px 0;
}

.alert--loading {
    background: #e3f2fd;
    color: #1976d2;
}

.alert--success {
    background: #e8f5e9;
    color: #2e7d32;
}

.alert--error {
    background: #ffebee;
    color: #c62828;
}

.fa {
    margin-right: 5px;
}

.fa-spin {
    animation: fa-spin 2s infinite linear;
}

@keyframes fa-spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
```

3. Add the JavaScript (choose one based on your CAPTCHA provider):

#### With reCAPTCHA:
```javascript
$(document).ready(function() {
    var $contactForm = $("#contact-form");
    
    $contactForm.submit(function(e) {
        e.preventDefault();
        
        // Get reCAPTCHA token
        grecaptcha.execute('your-site-key', {action: 'submit'}).then(function(token) {
            $.ajax({
                url: "http://your-mailbridge-server:2525/api/v1/form/your-form-key",
                method: "POST",
                data: {
                    name: $contactForm.find('[name="name"]').val(),
                    email: $contactForm.find('[name="email"]').val(),
                    subject: $contactForm.find('[name="subject"]').val(),
                    content: $contactForm.find('[name="content"]').val(),
                    captcha_token: token
                },
                dataType: "json",
                beforeSend: function() {
                    $contactForm.find(".overlay div").html(
                        '<div class="alert alert--loading">' +
                        '<i class="fa fa-circle-o-notch fa-spin"></i> &nbsp; Sending message...</div>'
                    );
                    $contactForm.find(".overlay").fadeIn();
                },
                success: function(data) {
                    $contactForm.find(".alert--loading").hide();
                    $contactForm.find(".overlay div").html(
                        '<div class="alert alert--success">' +
                        '<i class="fa fa-check"></i> &nbsp; Your message was sent successfully!</div>'
                    );
                    $contactForm.find(".overlay").fadeIn();
                    
                    // Clear form after success
                    $contactForm.find("input, textarea").val("");
                },
                error: function(xhr) {
                    $contactForm.find(".alert--loading").hide();
                    var errorMessage = xhr.responseJSON?.detail || "Oops, something went wrong.";
                    $contactForm.find(".overlay div").html(
                        '<div class="alert alert--error">' +
                        '<i class="fa fa-warning"></i> &nbsp; ' + errorMessage + '</div>'
                    );
                    $contactForm.find(".overlay").fadeIn();
                }
            });
        });
    });
    
    // Close overlay when clicked
    $contactForm.find(".overlay").click(function(e) {
        $(this).fadeOut();
    });
});
```

#### With hCaptcha:
```javascript
$(document).ready(function() {
    var $contactForm = $("#contact-form");
    
    $contactForm.submit(function(e) {
        e.preventDefault();
        
        var hcaptchaResponse = hcaptcha.getResponse();
        if (!hcaptchaResponse) {
            alert("Please complete the CAPTCHA");
            return;
        }
        
        $.ajax({
            url: "http://your-mailbridge-server:2525/api/v1/form/your-form-key",
            method: "POST",
            data: {
                name: $contactForm.find('[name="name"]').val(),
                email: $contactForm.find('[name="email"]').val(),
                subject: $contactForm.find('[name="subject"]').val(),
                content: $contactForm.find('[name="content"]').val(),
                hcaptcha: hcaptchaResponse
            },
            dataType: "json",
            beforeSend: function() {
                $contactForm.find(".overlay div").html(
                    '<div class="alert alert--loading">' +
                    '<i class="fa fa-circle-o-notch fa-spin"></i> &nbsp; Sending message...</div>'
                );
                $contactForm.find(".overlay").fadeIn();
            },
            success: function(data) {
                $contactForm.find(".alert--loading").hide();
                $contactForm.find(".overlay div").html(
                    '<div class="alert alert--success">' +
                    '<i class="fa fa-check"></i> &nbsp; Your message was sent successfully!</div>'
                );
                $contactForm.find(".overlay").fadeIn();
                
                // Clear form after success
                $contactForm.find("input, textarea").val("");
                hcaptcha.reset(); // Reset CAPTCHA
            },
            error: function(xhr) {
                $contactForm.find(".alert--loading").hide();
                var errorMessage = xhr.responseJSON?.detail || "Oops, something went wrong.";
                $contactForm.find(".overlay div").html(
                    '<div class="alert alert--error">' +
                    '<i class="fa fa-warning"></i> &nbsp; ' + errorMessage + '</div>'
                );
                $contactForm.find(".overlay").fadeIn();
            }
        });
    });
    
    // Close overlay when clicked
    $contactForm.find(".overlay").click(function(e) {
        $(this).fadeOut();
    });
});
```

### Running Services

1. Build and start the services:
```bash
docker compose build
docker compose up -d
```

2. Check the logs:
```bash
docker compose logs -f
```

### Testing

1. Submit a test form to verify the submission process
2. Check your email to confirm receipt of the form submission
3. Verify that the automated response is sent correctly
4. Test rate limiting by submitting multiple forms quickly
5. Test CAPTCHA functionality if enabled

## License

MIT License

Copyright (c) 2025 Matt Hammond

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
