echo -e "$content" | mail -s "$subject" -r "$sender" \
                         -a "Content-Type: text/html; charset=UTF-8" \
                         -a "/home/user/k8_health_report/k8s_health_report_b01-prd-tfb-prd-w2.html" \
                         "$recipient"
