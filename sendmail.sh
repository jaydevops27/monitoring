#!/bin/bash
DeploymentDate=$(date +"%Y-%m-%d")

# Email settings
content=$(cat /home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html)
recipient="your-email@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"
attachment_path="/home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html"

# Create temporary file for email content
temp_email_file="/tmp/k8s_email_$$.txt"

# Generate MIME email with HTML content and attachment
cat << EOF > "$temp_email_file"
To: $recipient
From: $sender
Subject: $subject
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="boundary123"

--boundary123
Content-Type: text/html; charset=UTF-8
Content-Disposition: inline

$content

--boundary123
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="$(basename "$attachment_path")"
Content-Transfer-Encoding: base64

$(base64 "$attachment_path")
--boundary123--
EOF

# Send email
sendmail "$recipient" < "$temp_email_file"

# Clean up
rm "$temp_email_file"
