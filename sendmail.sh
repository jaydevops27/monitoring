temp_file="/tmp/html_email_$$.txt"
cat > "$temp_file" << EOF
MIME-Version: 1.0
Content-Type: text/html; charset=UTF-8

$content
EOF

# Use your working command with the MIME file
echo -e "$(cat $temp_file)" | mail -s "$subject" -r "$sender" \
                                  -a "/home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html" \
                                  "$recipient"
