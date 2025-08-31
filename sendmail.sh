#!/bin/bash

DeploymentDate=$(date +"%Y-%m-%d")

# Read HTML content from the files
content=$(cat /home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html)

# Email settings
recipient=""  # Add your recipient email
sender=""     # Add your sender email
subject=""    # Add your subject

# Create proper HTML email body - THIS IS THE KEY CHANGE
email_body="<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <title>K8s Health Report</title>
</head>
<body>
    <p>Please find health check reports from above builds for AHUB.</p>
    
    $content
    
    <p><br>Best Regards,<br>Jay Patel</p>
</body>
</html>"

# Send the email with proper headers
echo "$email_body" | mail -s "$subject" \
    -a "From: $sender" \
    -a "Content-Type: text/html; charset=utf-8" \
    -a "MIME-Version: 1.0" \
    "$recipient"
