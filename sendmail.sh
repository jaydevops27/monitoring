#!/bin/bash
DeploymentDate=$(date +"%Y-%m-%d")

# Email settings
recipient="your-email@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"

# GitLab CI variables
GITLAB_URL="${CI_SERVER_URL}"
PROJECT_PATH="${CI_PROJECT_PATH}"
JOB_ID="${CI_JOB_ID}"
PIPELINE_ID="${CI_PIPELINE_ID}"

# Report files (update these paths as needed)
REPORT_FILES=(
    "k8s_health_report_b01-prd-tfb-prd-w2.html"
    "k8s_health_report_b02-prd-tfb-prd-w2.html"  
    "k8s_health_report_b03-prd-tfb-prd-w2.html"
)

# Create email body
email_body="K8s Health Report - $DeploymentDate

Dear Team,

Your Kubernetes health check reports are ready! 🎉

🔗 DIRECT REPORT LINKS (click to view):
"

# Add each report link
for report in "${REPORT_FILES[@]}"; do
    if [[ -f "/home/user/k8_health_report/$report" ]]; then
        report_url="${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}/artifacts/file/home/user/k8_health_report/${report}"
        cluster_name=$(echo "$report" | sed 's/k8s_health_report_//; s/.html//')
        email_body+="📊 $cluster_name: $report_url
"
    fi
done

email_body+="
📁 Browse All Artifacts: ${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}/artifacts/browse
🔧 Job Details: ${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}

═══════════════════════════════════════════════════════════
Pipeline: $PIPELINE_ID | Job: $JOB_ID | Date: $DeploymentDate
═══════════════════════════════════════════════════════════

Best Regards,
Jay Patel
DevOps Team"

# Send email with first report as attachment (backup)
main_attachment="/home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html"
echo -e "$email_body" | mail -s "$subject" -r "$sender" -a "$main_attachment" "$recipient"
