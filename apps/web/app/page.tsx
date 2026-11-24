import Image from "next/image";
import Link from "next/link";
import { connection } from "next/server";

import { auth, isSignInConfigured } from "@/auth";
import { AuthButtons } from "@/components/auth-buttons";

export default async function HomePage() {
  await connection();
  const session = process.env.AUTH_SECRET ? await auth() : null;

  return (
    <main className="flex min-h-screen flex-col bg-[#f6f7f8] text-[#15191d]">
      <header className="flex h-20 items-center justify-between border-b border-[#dfe3e5] px-6 sm:px-10">
        <Link className="rounded-sm" href="/" aria-label="Ahoya home">
          <Image
            src="/ahoya-logo.png"
            alt=""
            width={254}
            height={130}
            priority
            unoptimized
            className="h-10 w-auto sm:h-12"
          />
        </Link>
        {session ? (
          <Link className="text-sm font-medium text-[#59636a] hover:text-[#a90000]" href="/profile">
            Your profile
          </Link>
        ) : null}
      </header>

      <section className="mx-auto flex w-full max-w-6xl flex-1 items-center px-6 py-16 sm:px-10 lg:py-24">
        <div className="grid w-full gap-14 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.6fr)] lg:items-end">
          <div>
            <p className="mb-6 text-sm font-medium text-[#a90000]">Welcome to Ahoya</p>
            <h1 className="max-w-3xl text-5xl font-semibold leading-[1.04] tracking-[-0.055em] sm:text-7xl">
              Your place starts with a profile.
            </h1>
            <p className="mt-7 max-w-xl text-lg leading-8 text-[#59636a]">
              Sign in securely and set up your Ahoya account. Your profile settings are saved to the live MongoDB database.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-4">
              {session ? (
                <Link
                  className="rounded-full bg-[#a90000] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[#850000]"
                  href="/profile"
                >
                  Open your profile
                </Link>
              ) : (
                <AuthButtons configured={isSignInConfigured} />
              )}
              {session ? <AuthButtons configured={isSignInConfigured} signedIn /> : null}
            </div>
          </div>

          <aside className="border-l-2 border-[#a90000] py-2 pl-5" aria-label="Account setup status">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-[#59636a]">Account setup</p>
            <p className="mt-2 text-lg font-medium">{session ? "Signed in" : "Google sign-in"}</p>
            {session ? (
              <p className="mt-2 text-sm leading-6 text-[#59636a]">
                Your application session is active. Continue to your private profile settings.
              </p>
            ) : isSignInConfigured ? (
              <p className="mt-2 text-sm leading-6 text-[#59636a]">
                Continue with Google to create or access your account.
              </p>
            ) : (
              <p className="mt-2 text-sm leading-6 text-[#59636a]">
                Sign-in setup is incomplete. Add the Google OAuth settings and API assertion keys to your ignored local .env file.
              </p>
            )}
          </aside>
        </div>
      </section>

      <footer className="border-t border-[#dfe3e5] px-6 py-5 text-sm text-[#59636a] sm:px-10">
        Ahoya account setup
      </footer>
    </main>
  );
}
