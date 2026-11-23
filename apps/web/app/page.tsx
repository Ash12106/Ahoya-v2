import { connection } from "next/server";
import Link from "next/link";
import Image from "next/image";

export default async function HomePage() {
  await connection();

  return (
    <main className="flex min-h-screen flex-col bg-[#f6f7f8] text-[#15191d]">
      <header className="flex h-20 items-center justify-between border-b border-[#dfe3e5] px-6 sm:px-10">
        <Link
          className="rounded-sm text-xl font-semibold tracking-[-0.04em]"
          href="/"
          aria-label="Ahoya home"
        >
          <Image
            src="/ahoya-logo.png"
            alt=""
            width={254}
            height={130}
            priority
            className="h-10 w-auto sm:h-12"
          />
        </Link>
        <span className="text-xs font-medium uppercase tracking-[0.15em] text-[#59636a]">
          Phase 0 foundation
        </span>
      </header>

      <section className="mx-auto flex w-full max-w-6xl flex-1 items-center px-6 py-16 sm:px-10 lg:py-24">
        <div className="grid w-full gap-14 lg:grid-cols-[minmax(0,1.4fr)_minmax(250px,0.6fr)] lg:items-end">
          <div>
            <p className="mb-6 text-sm font-medium text-[#aa0000]">Ahoya</p>
            <h1 className="max-w-3xl text-5xl font-semibold leading-[1.04] tracking-[-0.055em] sm:text-7xl">
              A new foundation.
            </h1>
            <p className="mt-7 max-w-xl text-lg leading-8 text-[#59636a]">
              The Ahoya application is starting from a clean slate.
            </p>
          </div>

          <aside
            className="border-l-2 border-[#aa0000] py-2 pl-5"
            aria-label="Build status"
          >
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-[#59636a]">
              Project status
            </p>
            <p className="mt-2 text-lg font-medium">Foundation in progress</p>
            <p className="mt-2 text-sm leading-6 text-[#59636a]">
              Product data and features will be added after their requirements and database models are defined.
            </p>
          </aside>
        </div>
      </section>

      <footer className="border-t border-[#dfe3e5] px-6 py-5 text-sm text-[#59636a] sm:px-10">
        A new beginning for Ahoya.
      </footer>
    </main>
  );
}
