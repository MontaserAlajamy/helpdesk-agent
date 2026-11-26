// Cloudflare Worker: serves helpdesk.alajamy.site by proxying to the demo server (claude-vps, port 8080).
// Streams responses (the live trace uses Server-Sent Events) and passes the visitor's IP for the rate limits.
const OFFLINE = `<!doctype html><meta name=viewport content="width=device-width"><title>Helpdesk Agent</title>
<body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#0a2540;color:#f4f8fc;font:18px system-ui">
<div style="max-width:520px;padding:24px"><h1 style="font-weight:300">Helpdesk Agent</h1>
<p style="color:#9fb6cc">The live demo server is starting or offline. Please try again in a minute.</p>
<p><a style="color:#8fd3ff" href="https://github.com/MontaserAlajamy/helpdesk-agent">Code on GitHub</a></p></div>`;

export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);
    const target = new URL(incoming.pathname + incoming.search, env.ORIGIN);
    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-For", request.headers.get("CF-Connecting-IP") || "");
    headers.set("X-Forwarded-Proto", "https");
    headers.set("X-Forwarded-Host", incoming.host);
    headers.delete("Host");
    try {
      const res = await fetch(target, {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        redirect: "manual",
      });
      if (res.status >= 520 && res.status <= 530) throw new Error("origin " + res.status);
      return new Response(res.body, res);
    } catch (e) {
      return new Response(OFFLINE, { status: 503, headers: { "content-type": "text/html; charset=utf-8" } });
    }
  },
};
