# MailBridge

A Python-based form submission handler and automated email response system that works with multiple websites and email addresses.

## Table of Contents

- [Features](#features)
- [Setup Instructions](#setup-instructions)
  - [Environment Variables](#1-environment-variables)
  - [Configuration Files](#2-configuration-files)
  - [Website Integration](#3-website-integration)
    - [CAPTCHA Setup](#captcha-setup)
    - [Complete Form Implementation](#complete-form-implementation-with-captcha)
  - [Running the Services](#4-running-the-services)
  - [Testing](#5-testing)
- [Running with Docker](#running-with-docker)
- [Using the Form Handler](#using-the-form-handler)
- [Form Submission Requirements](#form-submission-requirements)
- [Response Format](#response-format)
- [Error Handling](#error-handling)
- [Development](#development)
- [Security Considerations](#security-considerations)
  - [Environment Variables](#environment-variables)
  - [Form Submission Security](#form-submission-security)
  - [Email Security](#email-security)
  - [Docker Security](#docker-security)
- [Performance Tuning](#performance-tuning)
  - [Form Handler](#form-handler)
  - [iCloud Mail Daemon](#icloud-mail-daemon)
  - [Docker Configuration](#docker-configuration)
  - [Monitoring](#monitoring)
- [License](#license)

## Features

- Handle form submissions from multiple websites
- Send form submissions to different email addresses
- Automated email responses using templates
- CORS protection for form submissions
- Docker-based deployment
- iCloud email integration

## Setup Instructions

### 1. Environment Variables

Copy `.env.sample` to `.env` and update it with your iCloud credentials:

```bash
cp .env.sample .env
```

Update the `.env` file with your iCloud credentials:
```env
# iCloud SMTP settings
ICLOUD_EMAIL=your_icloud_email@icloud.com
ICLOUD_APP_PASSWORD=your_app_specific_password
```

### 2. Configuration Files

#### config.yml

Update the `config/config.yml` file with your form configurations:

```yaml
global:
    smtp:
        host: smtp.mail.me.com  # iCloud SMTP server
        port: 587
        user: ${ICLOUD_EMAIL}
        password: ${ICLOUD_APP_PASSWORD}
        disable_tls: false

forms:
    # Example for personal website
    personal-contact:
        key: your-unique-key-here  # Generate a secure random key
        allowed_domains:
            - yourdomain.com
            - www.yourdomain.com
        to_email:
            - your-email@yourdomain.com
        from_name: Your Name

    # Example for business website
    business-contact:
        key: another-unique-key-here
        allowed_domains:
            - business.com
            - www.business.com
        to_email:
            - contact@business.com
        from_name: Business Team
```

#### responses.json

Update the `config/responses.json` file with your email templates and automated responses:

```json
{
  "your-email@yourdomain.com": {
    "subjects": {
      "Contact Request": "Thank you for reaching out! I'll review your message and get back to you as soon as possible."
    },
    "signature": "<p><strong>Your Name</strong><br>your-email@yourdomain.com<br><a href='https://yourdomain.com'>yourdomain.com</a></p>",
    "form_submission_template": {
      "subject": "New Submission with subject: %s",
      "body": "<p>Your Name,</p><p>Someone has just submitted a new form on your website.</p><p>Thank you,<br>YourDomain.com</p><p><br></p><p><b>Name:</b> %s</p><p><b>Email:</b> %s</p><p><b>Subject:</b> %s</p><p><b>Content:</b><br><br>%s</p>"
    }
  },
  "contact@business.com": {
    "subjects": {
      "Business: Access Request": "Thank you for requesting access! I'll review your message and reach out promptly if I have any questions.",
      "Business: General Inquiry": "Thank you for reaching out! I'll review your message and get back to you promptly with more information."
    },
    "signature": "<p><strong>Business Team</strong><br>contact@business.com<br><a href='https://business.com'>business.com</a></p>",
    "form_submission_template": {
      "subject": "Business: %s",
      "body": "<p>Team,</p><p>Someone has just submitted a new form on the website.</p><p>Thank you,<br>Business Team</p><p><br></p><p><b>Name:</b> %s</p><p><b>Email:</b> %s</p><p><b>Subject:</b> %s</p><p><b>Content:</b><br><br>%s</p>"
    }
  }
}
```

#### compose.yaml

Update the `compose.yaml` file with your service configurations:

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

  mailbridge-personal:
    build: .
    container_name: mailbridge-personal
    restart: unless-stopped
    env_file: .env
    environment:
      - PORT=1234
      - INSTANCE_EMAIL=your-email@yourdomain.com
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config:/config
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

  mailbridge-business:
    build: .
    container_name: mailbridge-business
    restart: unless-stopped
    env_file: .env
    environment:
      - PORT=1235
      - INSTANCE_EMAIL=contact@business.com
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config:/config
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

### 3. Website Integration

#### CAPTCHA Setup

Before implementing the form, you need to set up CAPTCHA protection. Both options are free for personal and small business use:

1. **reCAPTCHA (by Google) - Recommended**:
   - Free for up to 1 million assessments per month
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

#### Complete Form Implementation (with CAPTCHA)

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
                url: "http://your-mailbridge-server:1234/api/v1/form/your-form-key",
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
            url: "http://your-mailbridge-server:1234/api/v1/form/your-form-key",
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
                hcaptcha.reset(); // Reset CAPTCHA
            }
        });
    });
    
    // Close overlay when clicked
    $contactForm.find(".overlay").click(function(e) {
        $(this).fadeOut();
    });
});
```

### 4. Running the Services

1. Start all services:
```bash
docker compose up -d
```

2. Check the logs:
```bash
docker compose logs -f
```

3. Stop all services:
```bash
docker compose down
```

### 5. Testing

1. Test form submission:
```bash
curl -X POST http://localhost:1234/api/v1/form/your-form-key \
  -H "Content-Type: application/json" \
  -H "Origin: http://yourdomain.com" \
  -d '{
    "name": "Test User",
    "email": "test@example.com",
    "subject": "Test Subject",
    "content": "This is a test message"
  }'
```

2. Check Redis connection:
```bash
docker exec -it mailbridge-redis redis-cli ping
```

## Running with Docker

The system uses Docker Compose to run multiple instances, one for each form/email address:

```bash
docker compose up -d
```

This will start:
- `mailbridge-example` on port 1234 for info@example.com
- `mailbridge-example2` on port 1235 for contact@website.com

## Using the Form Handler

To submit a form, send a POST request to the appropriate endpoint:

```javascript
fetch('http://your-server:1234/api/v1/form/example-contact-key', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
    },
    body: JSON.stringify({
        name: 'User Name',
        email: 'user@example.com',
        subject: 'Form Subject',
        content: 'Message content'
    })
});
```

## Form Submission Requirements

- The form key must match the one in your `config.yml`
- The request must come from an allowed domain
- The request must include:
  - name
  - email
  - subject
  - content

## Response Format

Successful submissions return:
```json
{
    "status": "success",
    "message": "Form submitted successfully"
}
```

## Error Handling

The API returns appropriate HTTP status codes:
- 404: Form not found
- 403: Origin not allowed
- 500: Failed to process form submission

## Development

To run the system locally:

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the form handler:
```bash
PORT=1234 INSTANCE_EMAIL=info@example.com python form_handler.py
```

3. Run the iCloud mail daemon:
```bash
python icloud_mail_daemon.py
```

## Security Considerations

### Environment Variables
- Never commit your `.env` file to version control
- Use strong, unique app-specific passwords for iCloud
- Consider using a secrets management service in production

### Form Submission Security
- CORS is configured to only allow requests from specified domains
- Form keys should be long, random strings
- Consider implementing rate limiting for form submissions
- Validate and sanitize all form inputs
- Use HTTPS for all API endpoints in production

### Email Security
- SMTP connections use TLS by default
- Email addresses are validated before sending
- Consider implementing SPF, DKIM, and DMARC records for your domains
- Monitor for suspicious activity in your email logs

### Docker Security
- Run containers with non-root users
- Keep your base images updated
- Use Docker secrets for sensitive information
- Consider using a reverse proxy (like Nginx) in front of your API

## Performance Tuning

### Form Handler
- The FastAPI server is configured for async operations
- Consider adjusting the number of workers based on your server's CPU cores
- Implement connection pooling for SMTP connections
- Cache frequently accessed configuration data

### iCloud Mail Daemon
- The default check interval is 30 seconds
- Adjust the check interval based on your needs:
  ```python
  # In icloud_mail_daemon.py
  CHECK_INTERVAL = 30  # seconds
  ```
- Consider implementing exponential backoff for failed connections
- Use connection pooling for IMAP connections

### Docker Configuration
- Set appropriate resource limits in your compose file:
  ```yaml
  services:
    mailbridge-example:
      # ... other config ...
      deploy:
        resources:
          limits:
            cpus: '0.5'
            memory: 512M
  ```
- Consider using Docker's healthcheck feature
- Monitor container resource usage

### Monitoring
- Enable logging for both services
- Consider implementing Prometheus metrics
- Set up alerts for:
  - Failed form submissions
  - SMTP/IMAP connection issues
  - High resource usage
  - Unusual activity patterns

## License

[Your License Here]
