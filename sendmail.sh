#!/bin/bash

DeploymentDate=$(date +"%Y-%m-%d")

# Your actual working email settings
recipient="your-working-email@company.com"
sender="your-working-sender@company.com"  
subject="K8s Health Report - $DeploymentDate"

# Read HTML content
content=$(cat /home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html)

# Try different approaches based on what's available on your system

# Method 1: Try with mailx if available
if command -v mailx >/dev/null 2>&1; then
    echo "$content" | mailx -a "Content-Type: text/html" -s "$subject" -r "$sender" "$recipient"
elif command -v sendmail >/dev/null 2>&1; then
    # Method 2: Use sendmail directly
    {
        echo "To: $recipient"
        echo "From: $sender" 
        echo "Subject: $subject"
        echo "Content-Type: text/html; charset=utf-8"
        echo "MIME-Version: 1.0"
        echo ""
        echo "$content"
    } | sendmail "$recipient"
else
    # Method 3: Fall back to basic mail with headers in body
    {
        echo "Content-Type: text/html; charset=utf-8"
        echo ""
        echo "$content"
    } | mail -s "$subject" -r "$sender" "$recipient"
fi

echo "HTML email sent to $recipient"
