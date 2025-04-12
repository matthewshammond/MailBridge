FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create a startup script that runs both services
RUN echo '#!/bin/bash\n\
python form_handler.py &\n\
python icloud_mail_daemon.py\n\
wait' > /app/start.sh && \
chmod +x /app/start.sh

CMD ["/app/start.sh"]
