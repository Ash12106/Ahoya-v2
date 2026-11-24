"use client";

import { signIn, signOut } from "next-auth/react";

type AuthButtonsProps = {
  configured: boolean;
  signedIn?: boolean;
};

export function AuthButtons({ configured, signedIn = false }: AuthButtonsProps) {
  if (signedIn) {
    return (
      <button
        className="rounded-full border border-[#cfd4d5] px-5 py-2.5 text-sm font-medium transition hover:border-[#a90000] hover:text-[#a90000]"
        onClick={() => signOut({ redirectTo: "/" })}
        type="button"
      >
        Sign out
      </button>
    );
  }

  return (
    <button
      className="rounded-full bg-[#a90000] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[#850000] disabled:cursor-not-allowed disabled:bg-[#8d9295]"
      disabled={!configured}
      onClick={() => signIn("google", { redirectTo: "/profile" })}
      type="button"
    >
      Continue with Google
    </button>
  );
}
