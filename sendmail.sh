#!/bin/bash
DeploymentDate=$(date +"%Y-%m-%d")

# Email settings
html_content=$(cat /home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html)
recipient="your-email@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"
attachment_path="/home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html"

# Convert HTML to readable plain text
plain_text_content=$(echo "$html_content" | \
    sed 's/<[^>]*>//g' | \                    # Remove HTML tags
    sed 's/&nbsp;/ /g' | \                   # Replace &nbsp; with space
    sed 's/&amp;/\&/g' | \                   # Replace &amp; with &
    sed 's/&lt;/</g' | \                     # Replace &lt; with 
    sed 's/&gt;/>/g' | \                     # Replace &gt; with >
    sed '/^[[:space:]]*$/d' | \              # Remove empty lines
    fold -s -w 80)                           # Wrap lines at 80 characters

# Create readable email body
email_body="K8s Health Report - $DeploymentDate

Please find the Kubernetes health check report below.
The detailed HTML report is also attached for reference.

===== HEALTH REPORT SUMMARY =====

$plain_text_content

===== END OF REPORT =====

Best Regards,
Jay Patel"

# Send using your working mail command
echo -e "$email_body" | mail -s "$subject" -r "$sender" -a "$attachment_path" "$recipient"
