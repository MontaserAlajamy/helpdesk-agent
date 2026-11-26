---
id: disk-full-server
category: server
---
# Linux server disk full
Arabic: القرص ممتلئ، المساحة خلصت، السيرفر، الخادم، لينكس
1. Find what is large: `df -h` then `sudo du -xh / --max-depth=2 | sort -h | tail -20`.
2. Old logs: `sudo journalctl --vacuum-time=7d`; check that logrotate runs for application logs.
3. Docker hosts: `docker system df`, then `docker image prune` (never `docker system prune -a` on production without approval).
4. Never delete database files or anything under /var/lib/postgresql by hand.
Escalate: if a service stopped because of the full disk, open a ticket (category server, priority critical).
