import Image from "next/image";
import Link from "next/link";
import { redirect } from "next/navigation";
import { connection } from "next/server";

import { auth } from "@/auth";
import { AuthButtons } from "@/components/auth-buttons";
import { ProfileForm } from "@/components/profile-form";

export default async function ProfilePage() {
  await connection();
  const session = process.env.AUTH_SECRET ? await auth() : null;
  if (!session) redirect("/");

  return (
    <main className="flex min-h-screen flex-col bg-[#f6f7f8] text-[#15191d]">
      <header className="flex h-20 items-center justify-between border-b border-[#dfe3e5] px-6 sm:px-10">
        <Link className="rounded-sm" href="/" aria-label="Ahoya home">
          <Image
            src="/ahoya-logo.png"
            alt=""
            width={254}
            height={130}
            unoptimized
            className="h-10 w-auto sm:h-12"
          />
        </Link>
        <AuthButtons configured signedIn />
      </header>
      <div className="mx-auto flex w-full max-w-6xl flex-1 items-center justify-center px-5 py-10 sm:px-10">
        <ProfileForm />
      </div>
    </main>
  );
}
