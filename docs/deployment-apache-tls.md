# Deploying ReelOrganizer behind Apache with TLS

This assumes: Ubuntu/Debian VM, Apache already installed and serving other
sites (e.g. WordPress) on their own domains, and a domain/subdomain you
control already pointing (DNS A record) at this VM's IP. Replace
`reels.yourdomain.com` below with your actual domain everywhere it appears.

This adds one new, isolated Apache virtual host for this app only — it does
not touch your existing sites' virtual hosts or `apache2.conf`.

(If your VM uses nginx instead, see [`docs/deployment-nginx-tls.md`](deployment-nginx-tls.md) — same steps, different config syntax.)

## 1. Run the app container bound to localhost only

Follow the README's Docker section, making sure the port is published as
`-p 127.0.0.1:8000:8000` (not `-p 8000:8000`) — this is what makes Apache the
only way to reach the app from outside the VM.

## 2. Enable the required modules and create a virtual host

```bash
sudo a2enmod proxy proxy_http headers
sudo systemctl restart apache2
```

```bash
sudo tee /etc/apache2/sites-available/reelorganizer.conf > /dev/null <<'EOF'
<VirtualHost *:80>
    ServerName reels.yourdomain.com

    ProxyRequests Off
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/
    ProxyTimeout 180

    RequestHeader set X-Forwarded-Proto "%{REQUEST_SCHEME}s"
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
</VirtualHost>
EOF

sudo a2ensite reelorganizer
sudo apache2ctl configtest
sudo systemctl reload apache2
```

`ProxyRequests Off` keeps this an isolated reverse proxy for this one app,
not an open forward proxy (mod_proxy's default, but worth setting
explicitly). `RequestHeader set` (not `append`/`merge`) always *overwrites*
`X-Forwarded-For` with Apache's own view of the connecting IP — the app
trusts this header for its login rate-limiter (`app/auth.py`), so it must
never be left settable by a client-supplied header.

`ProxyTimeout 180` matches the `proxy_read_timeout` this app needs regardless
of which web server sits in front of it:

- The Instagram auto-import feature (`POST /ui/ai/import`) downloads and
  transcribes a reel, capped at 120 seconds internally.
- The multi-place reel import (a reel listing several distinct places) can
  make up to 15 AI provider calls in one request (up to 5 running
  concurrently at a time — see `MAX_CONCURRENT_CATEGORIZE_CALLS` in
  `app/routers/ai_multi_categorize.py`), each place resolved independently
  and some involving a web search round trip. This is usually well under a
  minute, but a single slow call (each bounded to ~15s plus one automatic
  retry) can still push a real "10+ places" reel past a minute in the
  worst case, regardless of which provider (`AI_PROVIDER`) is active.

Also note: the **very first** Instagram import after a fresh deploy
additionally downloads the ~140MB Whisper speech-to-text model (cached
afterwards in the `/data` volume, so this only happens once, not on every
restart) — that first request can be noticeably slower than later ones.
Trigger one yourself right after deploying to warm the cache if you want
to avoid a slow/timed-out first real import.

At this point `http://reels.yourdomain.com` should already proxy to the app
(over plain HTTP) — confirm with `curl -I http://reels.yourdomain.com/health`
before moving on to TLS. Login won't work yet at this point (the session
cookie requires HTTPS) — that's expected until step 3 adds TLS.

## 3. Get a TLS certificate with certbot

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-apache
sudo certbot --apache -d reels.yourdomain.com
```

Certbot will ask for an email address, ask you to agree to Let's Encrypt's
terms, and ask whether to redirect HTTP to HTTPS — choose **redirect**.
It edits `/etc/apache2/sites-available/reelorganizer.conf` (adding a
`RewriteRule` redirect to the port-80 block) and creates a new
`reelorganizer-le-ssl.conf` file with a `<VirtualHost *:443>` block carrying
the certificate paths and an `SSLEngine on` directive. Your existing
WordPress virtual hosts are untouched.

## 4. Add security headers

Certbot doesn't add these. Edit `/etc/apache2/sites-available/reelorganizer-le-ssl.conf`
and inside its `<VirtualHost *:443>` block, add:

```apache
Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
Header always set X-Content-Type-Options "nosniff"
Header always set X-Frame-Options "DENY"
Header always set Referrer-Policy "strict-origin-when-cross-origin"
```

(`mod_headers` is already enabled from step 2.) Then:

```bash
sudo apache2ctl configtest
sudo systemctl reload apache2
```

## 5. Confirm auto-renewal works

```bash
sudo certbot renew --dry-run
```

Certbot installs its own systemd timer on Ubuntu/Debian — no cron job needed.
The Apache plugin's renewal hook reloads Apache automatically after a real
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
  Apache) times out or is refused — confirming the app isn't reachable
  except through Apache.

## Out of scope here

General VM/SSH hardening (e.g. `fail2ban` on SSH) is a VM-wide concern, not
specific to this app, and isn't covered by this guide.
