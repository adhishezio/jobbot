# Tailscale Access

This project is set up to keep app ports on `127.0.0.1`.
That means the app is not exposed to your local network by default.

To reach it from your own devices, use Tailscale Serve.

## Steps

1. Install Tailscale on the host PC.
2. Install Tailscale on the phone or laptop you want to use.
3. Sign in to the same tailnet on both devices.
4. Start the Docker stack.
5. On the host PC, run:

```powershell
tailscale serve --bg 8501
```

6. Open the Serve URL from the other device.

## Useful Commands

Check current Serve config:

```powershell
tailscale serve status
```

Stop the Serve config:

```powershell
tailscale serve reset
```

## Why this setup

- The app stays private to your tailnet.
- PostgreSQL and n8n are still not public.
- You do not need a domain or Cloudflare.
