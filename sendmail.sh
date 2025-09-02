# Create MIME formatted body that mail command can handle
email_body=$(cat << EOF
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

This is a multi-part message in MIME format.

--boundary123
Content-Type: text/plain; charset=UTF-8

Please view this email in an HTML-capable email client to see the formatted report.

--boundary123
Content-Type: text/html; charset=UTF-8

$content

--boundary123--
EOF
)

# Use your working mail command with MIME formatted body
echo -e "$email_body" | mail -s "$subject" -r "$sender" -a "$attachment_path" "$recipient"
