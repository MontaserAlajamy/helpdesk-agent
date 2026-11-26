# Cloudflare front door

`worker.js` is deployed as the Worker `helpdesk-demo` with the custom domain `helpdesk.alajamy.site`.
It forwards every request to `ORIGIN` (the demo server, `http://<server-ip>.sslip.io:8080`), streams the reply
(Server-Sent Events included), and sets `X-Forwarded-For` to the visitor's IP so the per-IP limits work.
If the server is down it shows a small "starting or offline" page.

Deploy by API (token with the "Edit Cloudflare Workers" template): upload the script with a plain-text binding
`ORIGIN`, then add the custom domain (`PUT /accounts/{account}/workers/domains`). Or with Wrangler:
`npx wrangler deploy deploy/cloudflare/worker.js --name helpdesk-demo --var ORIGIN:http://<ip>.sslip.io:8080`.
