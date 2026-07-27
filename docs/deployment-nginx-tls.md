# Deploying ReelOrganizer behind nginx with TLS

This assumes: Ubuntu/Debian VM, nginx already installed and serving other
sites (e.g. WordPress) on their own domains, and a domain/subdomain you
control already pointing (DNS A record) at this VM's IP. Replace
`reels.yourdomain.com` below with your actual domain everywhere it appears.

This adds one new, isolated nginx server block for this app only — it does
not touch your existing sites' server blocks or `nginx.conf`.

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
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/reelorganizer /etc/nginx/sites-enabled/reelorganizer
sudo nginx -t
sudo systemctl reload nginx
```

At this point `http://reels.yourdomain.com` should already proxy to the app
(over plain HTTP) — confirm with `curl -I http://reels.yourdomain.com/health`
before moving on to TLS.

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
