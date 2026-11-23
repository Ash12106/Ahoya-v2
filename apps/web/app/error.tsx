"use client";

export default function ErrorBoundary({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-16">
      <p className="text-sm font-medium text-[#176b4b]">Ahoya</p>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">This page could not load.</h1>
      <p className="mt-3 text-base leading-7 text-[#59636a]">
        Please try again. If the problem continues, come back in a little while.
      </p>
      <button
        className="mt-7 w-fit rounded-md bg-[#176b4b] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#10583d]"
        onClick={reset}
        type="button"
      >
        Try again
      </button>
    </main>
  );
}
