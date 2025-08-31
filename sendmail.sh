#!/bin/bash

DeploymentDate=$(date +"%Y-%m-%d")

# Email settings - FILL THESE IN!
recipient="your-email@example.com"  # Replace with actual email
sender="sender@example.com"         # Replace with actual email
subject="K8s Health Report - $DeploymentDate"

# Read and wrap HTML content
content=$(cat /home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html)

# Send using sendmail (most reliable method)
cat << EOF | sendmail "$recipient"
To: $recipient
From: $sender
Subject: $subject
MIME-Version: 1.0
Content-Type: text/html; charset=UTF-8

<html>
<body>
<p>Please find health check reports from above builds for AHUB.</p>

$content

<p><br>Best Regards,<br>Jay Patel</p>
</body>
</html>
EOF

echo "HTML email sent successfully to $recipient"
