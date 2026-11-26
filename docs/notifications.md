# Notification inbox and scheduled work

Notifications are stored transactionally with feedback creation and relevant status changes. The durable inbox is per recipient, with an unread count and read acknowledgement. Notification text is intentionally generic: the learner's name or feedback is not exposed in desktop banners. Revoked cohort access hides old notifications. The browser polls every 15 seconds while signed in. Desktop alerts are opt-in (browser permission and an account preference); loopback/HTTPS and an open tab are required. The browser and OS can suppress alerts. This is not background Web Push or a Teams activity notification; no Microsoft Graph delivery is enabled yet.

Run the review reminder command with the same explicit database URL as the web application. For example, in a separate PowerShell terminal in a local demo:

```powershell
$env:FEEDBACK_LOOP_DEMO_MODE="1"
$env:FEEDBACK_LOOP_DB_URL="sqlite:///./feedback_loop_mvp.db"
python -m mvp.reminders --after-hours 24 --interval-seconds 3600
```

Stop with Ctrl+C. Omit --interval-seconds for one run from a service manager or Windows Task Scheduler. Checks use the most recent ready-for-review status event (legacy seed records fall back to the record update timestamp). One reminder is inserted for a feedback version and UTC day; opting out disables scheduled review reminders. Closed items and revoked tutor enrolments are excluded. The worker has no automatic startup or external calls, so configure and monitor it explicitly. No background service is started by these code changes. More reminder kinds (IV deadlines, overdue/missing feedback, document tasks) need the corresponding due dates and lifecycle records.

Teams desktop notification delivery still requires a College-approved Teams application, permissions, recipient mapping and a separate adapter with durable delivery/retry tracking. Do not connect real learner data to the demo.
