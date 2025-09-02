#!/bin/bash
DeploymentDate=$(date +"%Y-%m-%d")

# Email settings
recipient="your-email@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"

# GitLab CI variables with fallbacks
GITLAB_URL="${CI_SERVER_URL:-https://your-gitlab-instance.com}"
PROJECT_PATH="${CI_PROJECT_PATH:-your-group/your-project}"
JOB_ID="${CI_JOB_ID:-unknown}"
PIPELINE_ID="${CI_PIPELINE_ID:-unknown}"
COMMIT_SHA="${CI_COMMIT_SHORT_SHA:-latest}"

# Report directory and files
REPORT_DIR="reports"
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
    if [[ -f "$REPORT_DIR/$report" ]]; then
        report_url="${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}/artifacts/file/${REPORT_DIR}/${report}"
        cluster_name=$(echo "$report" | sed 's/k8s_health_report_//; s/.html//')
        email_body+="📊 Cluster $cluster_name: $report_url
"
    fi
done

email_body+="
📁 Browse All Artifacts: ${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}/artifacts/browse/${REPORT_DIR}
🔧 Job Details: ${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}
💻 Pipeline: ${GITLAB_URL}/${PROJECT_PATH}/-/pipelines/${PIPELINE_ID}

═══════════════════════════════════════════════════════════
📋 Build Info:
- Pipeline ID: $PIPELINE_ID  
- Job ID: $JOB_ID
- Commit: $COMMIT_SHA
- Generated: $DeploymentDate
═══════════════════════════════════════════════════════════

📊 Available Reports:
$(ls -la $REPORT_DIR/*.html 2>/dev/null | awk '{print "• " $9 " (" $5 " bytes)"}' || echo "• No HTML reports found")

Best Regards,
Jay Patel
DevOps Team"

# Find first available report for attachment
main_attachment=""
for report in "${REPORT_FILES[@]}"; do
    if [[ -f "$REPORT_DIR/$report" ]]; then
        main_attachment="$REPORT_DIR/$report"
        break
    fi
done

# Send email with attachment
if [[ -n "$main_attachment" ]]; then
    echo -e "$email_body" | mail -s "$subject" -r "$sender" -a "$main_attachment" "$recipient"
    echo "Email sent successfully with attachment: $main_attachment"
else
    echo -e "$email_body" | mail -s "$subject" -r "$sender" "$recipient"
    echo "Email sent successfully (no attachments found)"
fi
