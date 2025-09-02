#!/bin/bash
DeploymentDate=$(date +"%Y-%m-%d")

# Email settings
content=$(cat /home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html)
recipient="your-email@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"
attachment_path="/home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html"

# Send HTML email with mutt
echo "$content" | mutt -e "set content_type=text/html" \
                       -s "$subject" \
                       -a "$attachment_path" \
                       -- "$recipient"
