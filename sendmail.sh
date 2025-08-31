#!/bin/bash

DeploymentDate=$(date +"%Y-%m-%d")

# Email settings
recipient="recipient@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"

# Read HTML content
content=$(cat /home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html)

# Send HTML email using sendmail
{
    echo "To: $recipient"
    echo "From: $sender"
    echo "Subject: $subject"
    echo "MIME-Version: 1.0"
    echo "Content-Type: text/html; charset=UTF-8"
    echo ""
    echo "$content"
} | sendmail "$recipient"
