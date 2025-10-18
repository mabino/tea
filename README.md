# Tiny Email App (TEA)

Tiny Email App (TEA) is a containerised email relay gateway that combines a FastAPI service, Playwright-ready Chromium runtime, and a noVNC-accessible desktop session. TEA makes it easy to broker OAuth-authenticated outbound and inbound email flows for programmatic clients while still providing browser-based remediation when interactive logins are required.

## Features

- OAuth-aware health reporting with browser intervention signalling
- Unauthenticated relay endpoints for sending and (optionally) listing messages
- Configurable dry-run mode and rich environment-driven settings
- Optional SMTP bridge for clients that expect raw SMTP submissions
- Playwright-enabled Chromium runtime exposed through noVNC for remote access
- Adaptive self-health monitor with automated email notifications
- File-backed token storage via bind mounts plus offline-friendly mock adapters
- Comprehensive test suite with GitHub Actions CI workflow

## Getting Started

```bash
# Build and run with docker-compose
TEA_OAUTH_CLIENT_ID=your-client-id \
TEA_OAUTH_TOKEN_ENDPOINT=https://provider.example.com/oauth/token \
TEA_SMTP_HOST=smtp.provider.example.com \
TEA_IMAP_HOST=imap.provider.example.com \
docker compose up --build
```

Once running:

- FastAPI service: http://localhost:8000
- OpenAPI docs: http://localhost:8000/docs
- noVNC desktop: http://localhost:6080 (password optional)

## Configuration Reference

| Environment Variable | Default | Description |
| --- | --- | --- |
| `TEA_APP_HOST` | `0.0.0.0` | FastAPI listen address inside the container. |
| `TEA_APP_PORT` | `8000` | FastAPI listen port inside the container. |
| `TEA_DEBUG` | `false` | Enable verbose JSON logs when `true`. |
| `TEA_DRY_RUN` | `false` | Skip outbound email delivery while still accepting requests. |
| `TEA_NOVNC_ENABLED` | `true` | Expose the noVNC desktop session. |
| `TEA_NOVNC_PASSWORD_ENABLED` | `false` | Require a password for noVNC when `true`. |
| `TEA_NOVNC_PASSWORD` | _empty_ | Password used when `TEA_NOVNC_PASSWORD_ENABLED=true`. |
| `TEA_RELAY_SEND_ENABLED` | `true` | Allow unauthenticated email submissions. |
| `TEA_RELAY_QUERY_ENABLED` | `false` | Allow unauthenticated inbox queries. |
| `TEA_MOCK_MODE` | `false` | Use in-memory token store and stub transports. |
| `TEA_SECRET_STORE_PATH` | `/secrets/tokens.json` | Location of the persisted token bundle. |
| `TEA_OAUTH_CLIENT_ID` | _empty_ | OAuth client identifier. |
| `TEA_OAUTH_CLIENT_SECRET` | _empty_ | OAuth client secret. |
| `TEA_OAUTH_TENANT` | _empty_ | Tenant, domain, or organisation hint for the provider. |
| `TEA_OAUTH_SCOPES` | _empty_ | Space-separated scopes requested during auth. |
| `TEA_OAUTH_AUTH_ENDPOINT` | _empty_ | Authorization endpoint for user sign-in. |
| `TEA_OAUTH_TOKEN_ENDPOINT` | _empty_ | Token endpoint used for refresh/exchange. |
| `TEA_OAUTH_REDIRECT_URI` | _empty_ | Redirect URI registered with the provider. |
| `TEA_OAUTH_REFRESH_TOKEN` | _empty_ | Seed refresh token written to the token store. |
| `TEA_OAUTH_ACCESS_TOKEN` | _empty_ | Seed access token written to the token store. |
| `TEA_SMTP_HOST` | `smtp.example.com` | SMTP host used for outbound email. |
| `TEA_SMTP_PORT` | `587` | SMTP port used for outbound email. |
| `TEA_SMTP_USE_TLS` | `true` | Enable STARTTLS for SMTP connection. |
| `TEA_SMTP_BRIDGE_ENABLED` | `false` | Expose a local SMTP listener that forwards traffic into TEA. |
| `TEA_SMTP_BRIDGE_HOST` | `127.0.0.1` | Hostname bound by the SMTP bridge listener. |
| `TEA_SMTP_BRIDGE_PORT` | `2525` | Port bound by the SMTP bridge listener. |
| `TEA_IMAP_HOST` | `imap.example.com` | IMAP host used for inbox polling. |
| `TEA_IMAP_PORT` | `993` | IMAP port used for inbox polling. |
| `TEA_IMAP_USE_SSL` | `true` | Enable SSL/TLS for IMAP connection. |
| `TEA_HEALTH_STATUS_CACHE_TTL` | `30` | Seconds to cache health snapshots. |
| `TEA_HEALTH_MONITOR_ENABLED` | `true` | Toggle the recurring self-health job. |
| `TEA_HEALTH_MONITOR_INTERVAL_SECONDS` | `900` | Base interval for self-health checks. |
| `TEA_HEALTH_MONITOR_MIN_INTERVAL_SECONDS` | `60` | Minimum interval when issues escalate. |
| `TEA_HEALTH_MONITOR_MAX_INTERVAL_SECONDS` | `3600` | Maximum interval when the system remains healthy. |
| `TEA_HEALTH_NOTIFICATION_ENABLED` | `true` | Deliver self-health results over email when configured. |
| `TEA_HEALTH_NOTIFICATION_SENDER` | _empty_ | Sender address used for self-health notifications. |
| `TEA_HEALTH_NOTIFICATION_RECIPIENT` | _empty_ | Recipient address for self-health notifications. |
| `NOVNC_PORT` | `6080` | External port exposed for noVNC websockify. |

### Chromium and Playwright

The container installs Playwright and Chromium during build time. Additional Playwright runtime flags can be supplied via command arguments when invoking the service, e.g. `docker compose run tea python -m playwright codegen ...`.

## Self-Health Monitor

TEA can continuously evaluate its own health. When `TEA_HEALTH_MONITOR_ENABLED=true` the service schedules a background task that calls the `/health` stack, adapts the cadence based on the results, and emits actionable guidance.

- **Adaptive cadence** – Healthy runs gradually stretch toward `TEA_HEALTH_MONITOR_MAX_INTERVAL_SECONDS`, while authentication or transport problems collapse the delay toward `TEA_HEALTH_MONITOR_MIN_INTERVAL_SECONDS`. Repeated failures tighten the loop still further so urgent issues are surfaced quickly.
- **Structured logging** – Every self-health run is logged under the `tea.health_monitor` logger with the computed advice and the next scheduled interval.
- **Email notifications** – When `TEA_HEALTH_NOTIFICATION_ENABLED=true` (default) and both `TEA_HEALTH_NOTIFICATION_SENDER` / `TEA_HEALTH_NOTIFICATION_RECIPIENT` are configured, TEA sends a summary email after each check with recommended next steps. Notifications are skipped gracefully in dry-run mode.

For unattended deployments, route the notification mailbox to your operations queue so token expirations or provider outages are caught before API clients are impacted.

## SMTP Bridge

If `TEA_SMTP_BRIDGE_ENABLED=true`, TEA launches a lightweight SMTP listener (default `127.0.0.1:2525`) that forwards inbound mail directly into the same relay logic used by the HTTP API. This is helpful when integrating legacy tooling that can only speak SMTP. For production, run the bridge behind your own TLS terminator or network proxy before exposing it outside the container.

### Quick Examples

#### Local testing

```bash
export TEA_SMTP_BRIDGE_ENABLED=true
export TEA_SMTP_BRIDGE_HOST=0.0.0.0
export TEA_SMTP_BRIDGE_PORT=2525
python -m tea
# point your client at localhost:2525 with plain SMTP (TEA still uses OAuth under the hood)
```

#### Docker Compose override

```yaml
override.yml:
services:
  tea:
    environment:
      TEA_SMTP_BRIDGE_ENABLED: "true"
      TEA_SMTP_BRIDGE_HOST: 0.0.0.0
      TEA_SMTP_BRIDGE_PORT: 2525
    ports:
      - "2525:2525"  # expose the bridge alongside the HTTP API
```

Launch with `docker compose -f docker-compose.yml -f override.yml up --build` and configure upstream systems to relay through the published port.

## Example Provider Configurations

Every provider expects you to register an OAuth client before TEA can authenticate on your behalf. The general flow is:

- Create a developer project in the provider portal.
- Enable IMAP/SMTP (and, when asked, add delegated mail scopes).
- Register an OAuth application, capture the client ID and client secret, and allow the refresh-token grant.
- Set the redirect URI to something you control (TEA does not host an OAuth callback; when you need to complete a sign-in flow you can use the bundled noVNC browser and paste the resulting code or token into the mounted secret store).

Use the provider-specific notes below to gather the exact values to place in your environment.

### Gmail / Google Workspace

1. Visit the [Google Cloud Console](https://console.cloud.google.com/), create a project, and enable the **Gmail API**.
2. Configure the OAuth consent screen (External works for testing; add the Gmail scopes you plan to request).
3. Create OAuth credentials of type **Desktop app** (simplest) or **Web application**. Record the `Client ID` and `Client secret`.
4. If you choose the Web application type, add a redirect URI such as `https://developers.google.com/oauthplayground`. For desktop clients Google handles the redirect automatically.
5. In the Google Workspace account, ensure IMAP is enabled for the mailbox you will automate.

```bash
export TEA_OAUTH_CLIENT_ID="your-google-client-id"
export TEA_OAUTH_CLIENT_SECRET="your-google-client-secret"
export TEA_OAUTH_AUTH_ENDPOINT="https://accounts.google.com/o/oauth2/v2/auth"
export TEA_OAUTH_TOKEN_ENDPOINT="https://oauth2.googleapis.com/token"
export TEA_OAUTH_SCOPES="https://mail.google.com/"
export TEA_SMTP_HOST="smtp.gmail.com"
export TEA_IMAP_HOST="imap.gmail.com"
docker compose up --build
```

### Microsoft 365 / Outlook

1. Open the [Azure Portal](https://portal.azure.com/), navigate to **Azure Active Directory → App registrations**, and create a new registration for TEA.
2. Choose the correct tenant scope (`Accounts in this organizational directory only` or `Multitenant`) and copy the generated **Application (client) ID**.
3. Under **Authentication**, add a redirect URI for public clients, e.g. `https://login.microsoftonline.com/common/oauth2/nativeclient`, and enable the **Allow public client flows** toggle if present.
4. Create a **Client secret** (Certificates & secrets) and record the value before leaving the blade.
5. Under **API permissions**, add the delegated permissions `SMTP.Send` and `IMAP.AccessAsUser.All`, then grant admin consent so the scopes can be used without additional prompts.
6. Make sure the target mailbox has IMAP enabled in Exchange Online and modern auth is allowed for SMTP (it is by default in M365 tenants).

```bash
export TEA_OAUTH_CLIENT_ID="your-azure-app-id"
export TEA_OAUTH_CLIENT_SECRET="your-azure-client-secret"
export TEA_OAUTH_TENANT="common"
export TEA_OAUTH_AUTH_ENDPOINT="https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
export TEA_OAUTH_TOKEN_ENDPOINT="https://login.microsoftonline.com/common/oauth2/v2.0/token"
export TEA_OAUTH_SCOPES="https://outlook.office.com/SMTP.Send https://outlook.office.com/IMAP.AccessAsUser.All"
export TEA_SMTP_HOST="smtp.office365.com"
export TEA_IMAP_HOST="outlook.office365.com"
docker compose up --build
```

### Yahoo Mail

1. Log in to the [Yahoo Developer Network](https://developer.yahoo.com/apps/) and create a new **Yahoo App**.
2. Choose the **Web application** flavour, add the optional company/project details, then enable the **Mail** API scope (`Read/Write`) to generate delegated access.
3. Provide a redirect URI; Yahoo accepts `oob` (out-of-band) or a custom HTTPS URI. Record the `Client ID` and `Client Secret` once the app is created.
4. In the Yahoo mailbox, confirm that access from third-party apps is enabled (Account Security → Allow apps that use OAuth).

```bash
export TEA_OAUTH_CLIENT_ID="your-yahoo-client-id"
export TEA_OAUTH_CLIENT_SECRET="your-yahoo-client-secret"
export TEA_OAUTH_AUTH_ENDPOINT="https://api.login.yahoo.com/oauth2/request_auth"
export TEA_OAUTH_TOKEN_ENDPOINT="https://api.login.yahoo.com/oauth2/get_token"
export TEA_OAUTH_SCOPES="mail-w"
export TEA_SMTP_HOST="smtp.mail.yahoo.com"
export TEA_IMAP_HOST="imap.mail.yahoo.com"
docker compose up --build
```

## Health and Relay Endpoints

- `GET /health` – Returns a comprehensive health snapshot including OAuth state.
- `GET /oauth/status` – Direct view into the OAuth authentication state.
- `POST /oauth/refresh` – Attempts a refresh token grant (if configured).
- `POST /relay/send` – Accepts JSON payload `{sender, recipient, subject, body}` and relays via the configured provider.
- `GET /relay/messages?limit=10` – Lists the newest inbox messages when enabled.

## Development & Testing

```bash
pip install -e '.[dev,playwright]'
pytest --cov=tea
```

To run the API locally without Docker:

```bash
export TEA_MOCK_MODE=true
python -m tea
```

Mocks keep tests fully offline and deterministic.

## Continuous Integration

GitHub Actions workflow `.github/workflows/ci.yml` runs linting and the test suite on every push and pull request.

## Security Considerations

Running TEA gives the host environment direct access to OAuth refresh tokens and browser sessions that can fully impersonate the connected mailbox. Operate it with the same care you would a jump-box that holds long-lived credentials.

- Store the `/secrets` mount on encrypted disk, protect the host filesystem permissions, and rotate refresh tokens whenever the container lifecycle changes.
- Treat the OAuth client registration as a privileged asset. If the client secret leaks, revoke it in the provider portal and generate a replacement before redeploying TEA.
- Restrict container network exposure. Only publish the FastAPI and noVNC ports to trusted networks and consider reverse proxies that enforce authentication, rate limiting, or IP allow-lists.
- Enable `TEA_NOVNC_PASSWORD_ENABLED=true` and set `TEA_NOVNC_PASSWORD`. For higher assurance, front noVNC with an identity-aware proxy or VPN so the desktop is never exposed publicly.
- Toggle `TEA_RELAY_SEND_ENABLED` / `TEA_RELAY_QUERY_ENABLED` to the minimum necessary surface area. In most cases you should disable inbox access unless automated polling is required.
- Keep dependencies patched. Rebuild the image regularly to pull updated base layers (Python, Chromium, system libraries) and re-run the Playwright installer so the bundled browser stays current.
- Monitor provider security alerts. OAuth consent screens, scopes, and app registrations can be audited or suspended if unusual traffic is detected; make sure a human reviews provider dashboards periodically.

## License

MIT

## TODO

