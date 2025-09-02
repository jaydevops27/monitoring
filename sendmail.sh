#!/bin/bash
DeploymentDate=$(date +"%Y-%m-%d")

# Accept parameters for GitLab info
# Usage: ./send-health-report.sh [GITLAB_URL] [PROJECT_PATH] [JOB_ID] [PIPELINE_ID]
GITLAB_URL="${1:-${CI_SERVER_URL}}"
PROJECT_PATH="${2:-${CI_PROJECT_PATH}}" 
JOB_ID="${3:-${CI_JOB_ID}}"
PIPELINE_ID="${4:-${CI_PIPELINE_ID}}"
COMMIT_SHA="${5:-${CI_COMMIT_SHORT_SHA:-latest}}"

# Email settings
recipient="your-email@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"

echo "=== EMAIL SCRIPT PARAMETERS ==="
echo "GITLAB_URL: '$GITLAB_URL'"
echo "PROJECT_PATH: '$PROJECT_PATH'"
echo "JOB_ID: '$JOB_ID'"
echo "PIPELINE_ID: '$PIPELINE_ID'"
echo "COMMIT_SHA: '$COMMIT_SHA'"
echo "==============================="

# Check if we have the minimum required info for links
if [[ -n "$GITLAB_URL" && -n "$PROJECT_PATH" && -n "$JOB_ID" ]]; then
    ENABLE_LINKS=true
    echo "✅ GitLab links will be generated"
else
    ENABLE_LINKS=false
    echo "⚠️  Missing GitLab info - links will be disabled"
    echo "   Usage: $0 <gitlab_url> <project_path> <job_id> [pipeline_id] [commit_sha]"
fi

echo "Current directory: $(pwd)"

# Report directory and files
REPORT_DIR="reports"
REPORT_FILES=(
    "k8s_health_report_b01-prd-tfb-prd-w2.html"
    "k8s_health_report_b02-prd-tfb-prd-w2.html"  
    "k8s_health_report_b03-prd-tfb-prd-w2.html"
)

# Check what files actually exist
echo "=== CHECKING REPORT FILES ==="
ls -la $REPORT_DIR/ 2>/dev/null || echo "Reports directory not found"
echo "=============================="

# Create email body
email_body="K8s Health Report - $DeploymentDate

Dear Team,

Your Kubernetes health check reports are ready! 🎉"

if [[ "$ENABLE_LINKS" == "true" ]]; then
    email_body+="

🔗 DIRECT REPORT LINKS (click to view):"
    
    # Add each report link
    report_count=0
    report_count=0
    for report in "${REPORT_FILES[@]}"; do
        if [[ -f "$REPORT_DIR/$report" ]]; then
            report_url="${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}/artifacts/file/${REPORT_DIR}/${report}"
            cluster_name=$(echo "$report" | sed 's/k8s_health_report_//; s/.html//')
            email_body+="
📊 Cluster $cluster_name: $report_url"
            ((report_count++))
        fi
    done
    
    # If no specific reports found, list all HTML files
    if [[ $report_count -eq 0 ]]; then
        email_body+="
📊 Generated Reports:"
        for html_file in $REPORT_DIR/*.html; do
            if [[ -f "$html_file" ]]; then
                filename=$(basename "$html_file")
                report_url="${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}/artifacts/file/${REPORT_DIR}/${filename}"
                email_body+="
📄 $filename: $report_url"
                ((report_count++))
            fi
        done
    fi

    email_body+="

📁 Browse All Artifacts: ${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}/artifacts/browse/${REPORT_DIR}
🔧 Job Details: ${GITLAB_URL}/${PROJECT_PATH}/-/jobs/${JOB_ID}
💻 Pipeline: ${GITLAB_URL}/${PROJECT_PATH}/-/pipelines/${PIPELINE_ID}"
else
    email_body+="

📎 Please find the health reports in the attached files.
📊 The reports contain detailed cluster status information."
fi

email_body+="

═══════════════════════════════════════════════════════════
📋 Build Info:"
if [[ "$ENABLE_LINKS" == "true" ]]; then
    email_body+="
• Pipeline ID: $PIPELINE_ID  
• Job ID: $JOB_ID
• Commit: $COMMIT_SHA"
fi
email_body+="
• Generated: $DeploymentDate
═══════════════════════════════════════════════════════════

📊 Available Reports:
$(ls -la $REPORT_DIR/*.html 2>/dev/null | awk '{print "• " $9 " (" $5 " bytes)"}' || echo "• No HTML reports found")"

if [[ "$ENABLE_LINKS" == "true" ]]; then
    email_body+="

💡 TIP: Click the links above to view reports directly in your browser!"
else
    email_body+="

💡 TIP: Download and open the attached HTML files in your browser to view the reports."
fi

email_body+="

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

# If no predefined reports, use first HTML file found
if [[ -z "$main_attachment" ]]; then
    for html_file in $REPORT_DIR/*.html; do
        if [[ -f "$html_file" ]]; then
            main_attachment="$html_file"
            break
        fi
    done
fi

# Send email with attachment
if [[ -n "$main_attachment" ]]; then
    echo -e "$email_body" | mail -s "$subject" -r "$sender" -a "$main_attachment" "$recipient"
    echo "✅ Email sent successfully with attachment: $main_attachment"
else
    echo -e "$email_body" | mail -s "$subject" -r "$sender" "$recipient"
    echo "✅ Email sent successfully (no attachments found)"
fi

# Show sample of email content for verification
echo "=== EMAIL CONTENT PREVIEW ==="
echo "$email_body" | head -20
echo "... (truncated)"
echo "=============================="

# Show usage if no parameters provided and no CI variables
if [[ -z "$1" && -z "$CI_SERVER_URL" ]]; then
    echo ""
    echo "USAGE for SFTP server:"
    echo "$0 <gitlab_url> <project_path> <job_id> [pipeline_id] [commit_sha]"
    echo ""
    echo "Example:"
    echo "$0 https://gitlab.company.com group-name/project-name 12345 67890 abc123"
    echo ""
fi
