# Cloudflare origin protection setup

The production services require an origin token and trusted proxy CIDRs before the API starts. The web proxy rejects dynamic requests without the token. Keep the Render service URLs private until this setup is complete and verified.

## Configure Cloudflare

1. Generate one high-entropy secret with at least 32 bytes and store it in a password manager.
2. Set `CLOUDFLARE_ORIGIN_TOKEN` to that same secret on both Render services. Do not put it in source control, browser code, or a public build argument.
3. Add a Cloudflare request-header Transform Rule for each origin hostname. Set `x-ahoya-origin-token` to the secret with an unconditional overwrite so a visitor-supplied value cannot take precedence.
4. Confirm that requests through Cloudflare reach the web service and API only with the token, and that a direct request to each Render URL gets `403` for application routes.
5. Set `TRUSTED_PROXY_CIDRS` to the verified direct proxy peer ranges that connect to the API. Never use `0.0.0.0/0` or trust `CF-Connecting-IP` from arbitrary peers. Validate observed peer addresses against Render's current network behavior before enabling Krawl bans.
6. Set `CORS_ALLOWED_ORIGINS` to the exact public web origin, including scheme and hostname.

## Network restriction limit

The token check is an application-layer gate. It does not prevent direct TCP connections to the Render origin. Render documents native inbound IP allow rules as limited to Scale and Enterprise plans for web services. If the account remains on the free plan, keep the token gate and use Cloudflare as the public hostname, but do not describe the origin as network-isolated. Revisit native restrictions if the Render plan changes.

## Verification

Test each hostname after configuration:

- A request through the expected Cloudflare hostname succeeds.
- A request with a missing or wrong origin token receives `403` on a protected route.
- `/health` reports only liveness; `/health/db` reports a generic dependency status.
- API logs contain request IDs and route metadata, not the token, raw IP address, or database URI.
- Krawl records a keyed IP digest only when the direct peer belongs to a configured trusted range.
