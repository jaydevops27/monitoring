#!/bin/bash
DeploymentDate=$(date +"%Y-%m-%d")

# DEBUG: Print all available CI variables (remove after testing)
echo "=== DEBUG: GitLab CI Variables ==="
echo "CI_SERVER_URL: '${CI_SERVER_URL}'"
echo "CI_PROJECT_PATH: '${CI_PROJECT_PATH}'"
echo "CI_JOB_ID: '${CI_JOB_ID}'"
echo "CI_PIPELINE_ID: '${CI_PIPELINE_ID}'"
echo "CI_COMMIT_SHORT_SHA: '${CI_COMMIT_SHORT_SHA}'"
echo "CI_PROJECT_URL: '${CI_PROJECT_URL}'"
echo "CI_JOB_URL: '${CI_JOB_URL}'"
echo "=================================="

# Email settings
recipient="your-email@example.com"
sender="sender@example.com"
subject="K8s Health Report - $DeploymentDate"

# GitLab CI variables with proper fallbacks
GITLAB_URL="${CI_SERVER_URL}"
PROJECT_PATH="${CI_PROJECT_PATH}"
JOB_ID="${CI_JOB_ID}"
PIPELINE_ID="${CI_PIPELINE_ID}"
COMMIT_SHA="${CI_COMMIT_SHORT_SHA:-latest}"

# Validate required variables
if [[ -z "$GITLAB_URL" || -z "$PROJECT_PATH" || -z "$JOB_ID" ]]; then
    echo "WARNING: Required GitLab CI variables are missing!"
    echo "GITLAB_URL: '$GITLAB_URL'"
    echo "PROJECT_PATH: '$PROJECT_PATH'" 
    echo "JOB_ID: '$JOB_ID'"
    
    # Try alternative variables
    GITLAB_URL="${CI_PROJECT_URL%/*/*/*}"  # Extract base URL from project URL
    if [[ -n "$CI_JOB_URL" ]]; then
        JOB_ID=$(echo "$CI_JOB_URL" | grep -o 'jobs/[0-9]*' | cut -d'/' -f2)
    fi
fi

# Show final values
echo "=== FINAL VALUES USED ==="
echo "GITLAB_URL: '$GITLAB_URL'"
echo "PROJECT_PATH: '$PROJECT_PATH'"
echo "JOB_ID: '$JOB_ID'"
echo "PIPELINE_ID: '$PIPELINE_ID'"
echo "Current directory: $(pwd)"
echo "========================="

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

Your Kubernetes health check reports are ready! 🎉

🔗 DIRECT REPORT LINKS (click to view):"

# Add each report link
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
💻 Pipeline: ${GITLAB_URL}/${PROJECT_PATH}/-/pipelines/${PIPELINE_ID}

═══════════════════════════════════════════════════════════
📋 Build Info:
• Pipeline ID: $PIPELINE_ID  
• Job ID: $JOB_ID
• Commit: $COMMIT_SHA
• Generated: $DeploymentDate
• Reports Found: $report_count
═══════════════════════════════════════════════════════════

📊 Available Reports:
$(ls -la $REPORT_DIR/*.html 2>/dev/null | awk '{print "• " $9 " (" $5 " bytes)"}' || echo "• No HTML reports found")

💡 TIP: Click the links above to view reports directly in your browser!

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
