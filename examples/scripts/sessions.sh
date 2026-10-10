#!/bin/sh
# Example command for the `custom` card: prints one JSON object on stdout.
# Card config:
#   - type: custom
#     command: ["/usr/local/bin/sessions.sh"]
#     refresh: 60
set -eu
users=$(who | wc -l | tr -d ' ')
load=$(cut -d ' ' -f 1 /proc/loadavg 2>/dev/null || echo "?")
status=ok
[ "$users" -gt 5 ] && status=warn
printf '{"title": "SESSIONS", "value": "%s", "label": "load %s", "status": "%s"}\n' \
  "$users" "$load" "$status"
