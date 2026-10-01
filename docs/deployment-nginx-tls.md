# Deploying ReelOrganizer behind nginx with TLS

This assumes: Ubuntu/Debian VM, nginx already installed and serving other
sites (e.g. WordPress) on their own domains, and a domain/subdomain you
control already pointing (DNS A record) at this VM's IP. Replace
`reels.yourdomain.com` below with your actual domain everywhere it appears.

This adds one new, isolated nginx server block for this app only — it does
not touch your existing sites' server blocks or `nginx.conf`.

(If your VM uses Apache instead, see [`docs/deployment-apache-tls.md`](deployment-apache-tls.md) — same steps, different config syntax.)

## 1. Run the app container bound to localhost only

Follow the README's Docker section, making sure the port is published as
`-p 127.0.0.1:8000:8000` (not `-p 8000:8000`) — this is what makes nginx the
only way to reach the app from outside the VM.

## 2. Create a minimal HTTP server block for the new domain

```bash
sudo tee /etc/nginx/sites-available/reelorganizer > /dev/null <<'EOF'
server {
    listen 80;
    server_name reels.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/reelorganizer /etc/nginx/sites-enabled/reelorganizer
sudo nginx -t
sudo systemctl reload nginx
```

Two features in this app make long-running requests, so nginx's default
`proxy_read_timeout` (60s) is too tight — set it to `210s` inside the
`location /` block above:

```nginx
proxy_read_timeout 210s;
```

- The Instagram auto-import feature (`POST /ui/ai/import`) downloads and
  transcribes a reel, capped at 180 seconds internally
  (`IMPORT_TIMEOUT_SECONDS` in `app/routers/instagram_import.py`). The proxy
  timeout must stay comfortably above this — if the two are equal, the
  app's own timeout firing and the proxy's own clock expiring at the same
  instant is a real race, not just a theoretical one.
- The multi-place reel import (when a reel lists several distinct places —
  `POST /ui/ai/message` and `POST /ui/ai/multi/message`) can make up to 15
  AI provider calls in one request (up to 5 running concurrently at a time
  — see `MAX_CONCURRENT_CATEGORIZE_CALLS` in
  `app/routers/ai_multi_categorize.py`), each place resolved independently
  and some involving a web search round trip. This is usually well under a
  minute, but a single slow call (each bounded to ~15s plus one automatic
  retry) can still push a real "10+ places" reel past a minute in the
  worst case, regardless of which provider (`AI_PROVIDER`) is active.

`210s` comfortably covers both. Also note: the **very first** Instagram
import after a fresh deploy additionally downloads the ~140MB Whisper
speech-to-text model (cached afterwards in the `/data` volume, so this only
happens once, not on every restart) — that first request can be
noticeably slower than later ones. If you want to avoid a slow/timed-out
first real import, trigger one yourself right after deploying to warm the
cache.

Unlike the more common `$proxy_add_x_forwarded_for`, this uses `$remote_addr`
directly so nginx always overwrites the header rather than appending to it —
the app trusts this header for its login rate-limiter, so it must not be
spoofable by a client-supplied `X-Forwarded-For` value.

At this point `http://reels.yourdomain.com` should already proxy to the app
(over plain HTTP) — confirm with `curl -I http://reels.yourdomain.com/health`
before moving on to TLS. Login won't work yet at this point (the session
cookie requires HTTPS) — that's expected until step 3 adds TLS.

## 3. Get a TLS certificate with certbot

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d reels.yourdomain.com
```

Certbot will ask for an email address, ask you to agree to Let's Encrypt's
terms, and ask whether to redirect HTTP to HTTPS — choose **redirect**.
It edits only `/etc/nginx/sites-available/reelorganizer` (the file created
in step 2): it adds a `listen 443 ssl` block with the certificate paths, and
turns the port-80 block into a redirect to HTTPS. Your existing WordPress
server blocks are untouched.

## 4. Add security headers

Certbot doesn't add these. Edit `/etc/nginx/sites-available/reelorganizer`
and inside the `server { listen 443 ssl; ... }` block (the one certbot just
created), add:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options DENY always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
```

Then:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5. Confirm auto-renewal works

```bash
sudo certbot renew --dry-run
```

Certbot installs its own systemd timer on Ubuntu/Debian — no cron job needed.
The nginx plugin's renewal hook reloads nginx automatically after a real
renewal.

## 6. Firewall

Only allow SSH, HTTP, and HTTPS in — **run the SSH rule first** so you don't
lock yourself out if you're connected over SSH:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 7. Verify end-to-end

- `https://reels.yourdomain.com/login` loads the login form.
- `http://reels.yourdomain.com/login` redirects to the `https://` version.
- `curl -I http://<vm-ip>:8000` (hitting the app's port directly, bypassing
  nginx) times out or is refused — confirming the app isn't reachable
  except through nginx.

## Out of scope here

General VM/SSH hardening (e.g. `fail2ban` on SSH) is a VM-wide concern, not
specific to this app, and isn't covered by this guide.
