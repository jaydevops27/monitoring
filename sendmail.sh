attachment_path="/home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html"

# Create proper MIME email
temp_email="/tmp/k8s_html_email_$$.eml"

cat > "$temp_email" << EOF
To: $recipient
From: $sender
Subject: $subject
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="htmlboundary123"

--htmlboundary123
Content-Type: text/html; charset=UTF-8

$content

--htmlboundary123
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="$(basename "$attachment_path")"
Content-Transfer-Encoding: base64

$(base64 "$attachment_path")
--htmlboundary123--
EOF

# Send using sendmail
/usr/sbin/sendmail "$recipient" < "$temp_email"

# Clean up
rm "$temp_email"
