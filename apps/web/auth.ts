import { createPrivateKey, randomUUID, sign as signBytes } from "node:crypto";

import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

const sessionLifetimeSeconds = 7 * 24 * 60 * 60;

function base64UrlJson(value: Record<string, unknown>): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function createWebAssertion(googleSubject: string): string {
  const encodedKey = process.env.API_ASSERTION_PRIVATE_KEY;
  const keyId = process.env.API_ASSERTION_KEY_ID;
  if (
    !encodedKey ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(encodedKey) ||
    !keyId ||
    !/^[A-Za-z0-9._-]{1,64}$/.test(keyId)
  ) {
    throw new Error("Application session signing is not configured");
  }

  const privateKeyDer = Buffer.from(encodedKey, "base64");
  if (privateKeyDer.toString("base64") !== encodedKey) {
    throw new Error("Application session signing is not configured");
  }
  const privateKey = createPrivateKey({
    key: privateKeyDer,
    format: "der",
    type: "pkcs8",
  });
  const issuedAt = Math.floor(Date.now() / 1000);
  const header = base64UrlJson({ alg: "EdDSA", typ: "JWT", kid: keyId });
  const payload = base64UrlJson({
    iss: "ahoya-web",
    aud: "ahoya-api",
    sub: googleSubject,
    provider: "google",
    jti: randomUUID().replaceAll("-", "") + randomUUID().replaceAll("-", ""),
    iat: issuedAt,
    exp: issuedAt + 60,
  });
  const message = `${header}.${payload}`;
  const signature = signBytes(null, Buffer.from(message), privateKey).toString("base64url");
  return `${message}.${signature}`;
}

function apiOrigin(): string {
  const value = process.env.API_INTERNAL_ORIGIN;
  if (!value) {
    throw new Error("Application API is not configured");
  }
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("Application API is not configured");
  }
  return url.origin;
}

async function createApiSession(googleSubject: string): Promise<{
  apiSessionToken: string;
  apiSessionExpiresAt: number;
}> {
  const assertion = createWebAssertion(googleSubject);
  const response = await fetch(`${apiOrigin()}/v1/auth/sessions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${assertion}` },
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) {
    throw new Error("Could not establish the application session");
  }
  const body: unknown = await response.json();
  if (typeof body !== "object" || body === null) {
    throw new Error("Could not establish the application session");
  }
  const data = body as Record<string, unknown>;
  const expiresAt = typeof data.expires_at === "string" ? Date.parse(data.expires_at) : NaN;
  if (
    typeof data.session_token !== "string" ||
    !/^[A-Za-z0-9_-]{43,128}$/.test(data.session_token) ||
    !Number.isFinite(expiresAt) ||
    expiresAt <= Date.now() ||
    expiresAt > Date.now() + (sessionLifetimeSeconds + 120) * 1000
  ) {
    throw new Error("Could not establish the application session");
  }
  return {
    apiSessionToken: data.session_token,
    apiSessionExpiresAt: Math.floor(expiresAt / 1000),
  };
}

async function revokeApiSession(apiSessionToken: string): Promise<void> {
  try {
    const response = await fetch(`${apiOrigin()}/v1/auth/sessions/current`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${apiSessionToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) {
      console.error("api_session_revoke_failed", { status: response.status });
    }
  } catch (error) {
    console.error("api_session_revoke_failed", {
      errorType: error instanceof Error ? error.name : "UnknownError",
    });
  }
}

const googleConfigured = Boolean(process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: googleConfigured ? [Google] : [],
  secret: process.env.AUTH_SECRET,
  trustHost: true,
  session: { strategy: "jwt", maxAge: sessionLifetimeSeconds },
  jwt: { maxAge: sessionLifetimeSeconds },
  pages: { signIn: "/" },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        if (account.provider !== "google" || !account.providerAccountId) {
          throw new Error("Unsupported identity provider");
        }
        const apiSession = await createApiSession(account.providerAccountId);
        token.apiSessionToken = apiSession.apiSessionToken;
        token.apiSessionExpiresAt = apiSession.apiSessionExpiresAt;
        delete token.email;
        delete token.name;
        delete token.picture;
      }
      if (
        typeof token.apiSessionExpiresAt !== "number" ||
        token.apiSessionExpiresAt <= Math.floor(Date.now() / 1000) ||
        typeof token.apiSessionToken !== "string"
      ) {
        return null;
      }
      return token;
    },
    session({ session }) {
      if (session.user) {
        session.user.name = null;
        session.user.email = "";
        session.user.image = null;
      }
      return session;
    },
    redirect({ url, baseUrl }) {
      const configuredOrigin = process.env.AUTH_URL
        ? new URL(process.env.AUTH_URL).origin
        : new URL(baseUrl).origin;
      if (url.startsWith("/")) {
        return `${configuredOrigin}${url}`;
      }
      try {
        return new URL(url).origin === configuredOrigin ? url : configuredOrigin;
      } catch {
        return configuredOrigin;
      }
    },
  },
  events: {
    async signOut(message) {
      if ("token" in message && typeof message.token?.apiSessionToken === "string") {
        await revokeApiSession(message.token.apiSessionToken);
      }
    },
  },
});

export const isGoogleConfigured = googleConfigured;
export const isSignInConfigured = Boolean(
  googleConfigured &&
    process.env.AUTH_SECRET &&
    process.env.API_ASSERTION_PRIVATE_KEY &&
    process.env.API_ASSERTION_KEY_ID &&
    process.env.API_INTERNAL_ORIGIN,
);
