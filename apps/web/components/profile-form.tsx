"use client";

import { useEffect, useState, type FormEvent } from "react";

type Profile = {
  username: string | null;
  display_name: string;
  date_of_birth: string | null;
  cover_alt_text: string;
  updated_at: string | null;
};

type ProfileResponse = {
  profile: Profile | null;
  date_of_birth_collection_enabled: boolean;
  minimum_age_years: number;
  date_of_birth_consent_notice: string | null;
  date_of_birth_consent_notice_version: string | null;
};

function latestEligibleBirthDate(minimumAgeYears: number): string {
  const now = new Date();
  const year = now.getUTCFullYear() - minimumAgeYears;
  const month = now.getUTCMonth();
  const cutoff = new Date(Date.UTC(year, month, now.getUTCDate()));
  if (cutoff.getUTCMonth() !== month) cutoff.setUTCDate(0);
  return cutoff.toISOString().slice(0, 10);
}

export function ProfileForm() {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [savedDateOfBirth, setSavedDateOfBirth] = useState("");
  const [coverAltText, setCoverAltText] = useState("");
  const [consent, setConsent] = useState(false);
  const [settings, setSettings] = useState<ProfileResponse | null>(null);
  const [status, setStatus] = useState("Loading your profile settings.");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    void fetch("/api/profile", { cache: "no-store" })
      .then(async (response) => {
        const data = (await response.json()) as ProfileResponse;
        if (!response.ok) throw new Error("Your profile could not be loaded. Try again later.");
        return data;
      })
      .then((data) => {
        if (!active) return;
        setSettings(data);
        if (data.profile) {
          setUsername(data.profile.username ?? "");
          setDisplayName(data.profile.display_name);
          const storedDate = data.profile.date_of_birth ?? "";
          setDateOfBirth(storedDate);
          setSavedDateOfBirth(storedDate);
          setCoverAltText(data.profile.cover_alt_text);
        }
        setStatus(
          data.date_of_birth_collection_enabled
            ? "Your profile settings are ready."
            : "The age check is unavailable while its privacy notice and encryption settings are pending.",
        );
      })
      .catch(() => {
        if (!active) return;
        setError("Your profile settings could not be loaded. Try again later.");
        setStatus("Profile settings unavailable.");
      });
    return () => {
      active = false;
    };
  }, []);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setStatus("");
    setSaving(true);
    try {
      const dateOfBirthChanged = dateOfBirth.length > 0 && dateOfBirth !== savedDateOfBirth;
      if (dateOfBirthChanged) {
        if (!collectionEnabled || !consent) {
          throw new Error("Review the date of birth notice and give consent before saving it.");
        }
        const consentResponse = await fetch("/api/consents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            purpose: "self_declared_date_of_birth",
            notice_version: settings?.date_of_birth_consent_notice_version,
            consented: true,
          }),
        });
        if (!consentResponse.ok) throw new Error("Consent could not be recorded.");
      }
      const response = await fetch("/api/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          display_name: displayName,
          ...(collectionEnabled && dateOfBirth.length > 0 && !savedDateOfBirth
            ? { date_of_birth: dateOfBirth }
            : {}),
          cover_alt_text: coverAltText,
        }),
      });
      if (!response.ok) {
        if (response.status === 409 || response.status === 429) {
          const apiError = (await response.json().catch(() => null)) as { code?: string } | null;
          if (apiError?.code === "USERNAME_UNAVAILABLE") {
            setError("That username is unavailable. Try another one.");
            return;
          }
          if (apiError?.code === "DATE_OF_BIRTH_LOCKED") {
            setError("Your date of birth is locked and cannot be changed.");
            return;
          }
          if (apiError?.code === "USERNAME_CHANGE_LIMIT") {
            setError("You can change your username twice in seven days. Try again later.");
            return;
          }
        }
        throw new Error("Your profile could not be saved. Check the fields and try again.");
      }
      const data = (await response.json()) as { profile: Profile };
      setUsername(data.profile.username ?? "");
      setDisplayName(data.profile.display_name);
      const storedDate = data.profile.date_of_birth ?? "";
      setDateOfBirth(storedDate);
      setSavedDateOfBirth(storedDate);
      setCoverAltText(data.profile.cover_alt_text);
      setStatus("Your profile was saved.");
    } catch {
      setError("Your profile could not be saved. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  const collectionEnabled = settings?.date_of_birth_collection_enabled === true;
  const minimumAgeYears = settings?.minimum_age_years ?? 16;
  const notice = settings?.date_of_birth_consent_notice;

  return (
    <section className="w-full max-w-2xl rounded-2xl border border-[#dfe3e5] bg-white p-6 shadow-sm sm:p-9">
      <div className="mb-8">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#a90000]">
          Profile
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">
          Set up your account
        </h1>
        <p className="mt-3 max-w-xl leading-7 text-[#59636a]">
          Your profile is saved to Ahoya’s MongoDB database and is visible only to you in this phase.
        </p>
      </div>

      <p aria-live="polite" className="sr-only" role="status">
        {status}
      </p>

      {!settings && !error ? (
        <p className="text-sm text-[#59636a]">Loading profile settings…</p>
      ) : null}

      {error ? (
        <p className="mb-6 rounded-lg bg-[#fff1f0] p-4 text-sm text-[#8a1212]" role="alert">
          {error}
        </p>
      ) : null}

      {settings && !collectionEnabled ? (
        <div className="rounded-xl border border-[#e3d4b2] bg-[#fffaf0] p-5 text-sm leading-6 text-[#574625]" role="status">
          The 16+ age check is currently disabled. You can save the rest of your profile now; date of birth will be enabled after its privacy notice and encryption settings are configured.
        </div>
      ) : null}

      {settings ? (
        <form className="mt-6 space-y-6" onSubmit={saveProfile}>
          <div>
            <label className="mb-2 block text-sm font-medium" htmlFor="username">
              Username
            </label>
            <input
              autoCapitalize="none"
              autoComplete="username"
              className="w-full rounded-lg border border-[#cfd4d5] px-4 py-3 text-base focus-visible:border-[#176b4b]"
              id="username"
              maxLength={24}
              minLength={3}
              onChange={(event) => setUsername(event.target.value)}
              pattern="[A-Za-z0-9_]{3,24}"
              required
              spellCheck={false}
              value={username}
            />
            <p className="mt-2 text-sm leading-6 text-[#59636a]">
              Choose 3–24 letters, numbers, or underscores. Usernames are case-insensitive and
              must be unique.
            </p>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium" htmlFor="display-name">
              Display name
            </label>
            <input
              autoComplete="name"
              className="w-full rounded-lg border border-[#cfd4d5] px-4 py-3 text-base focus-visible:border-[#176b4b]"
              id="display-name"
              maxLength={80}
              onChange={(event) => setDisplayName(event.target.value)}
              required
              value={displayName}
            />
          </div>

          {collectionEnabled ? (
            <div>
              <label className="mb-2 block text-sm font-medium" htmlFor="date-of-birth">
                {savedDateOfBirth ? "Date of birth (locked)" : "Date of birth (required)"}
              </label>
              <input
                autoComplete="bday"
                className="w-full rounded-lg border border-[#cfd4d5] px-4 py-3 text-base focus-visible:border-[#176b4b]"
                id="date-of-birth"
                max={latestEligibleBirthDate(minimumAgeYears)}
                onChange={(event) => setDateOfBirth(event.target.value)}
                disabled={savedDateOfBirth.length > 0}
                required
                type="date"
                value={dateOfBirth}
              />
              <p className="mt-2 text-sm leading-6 text-[#59636a]">
                {savedDateOfBirth
                  ? "Your date of birth is locked after the first successful profile save."
                  : `Ahoya accounts are for people aged ${minimumAgeYears} or older. This self-declared check does not independently verify your age and cannot be changed after saving.`}
              </p>
            </div>
          ) : null}

          <div>
            <label className="mb-2 block text-sm font-medium" htmlFor="cover-alt-text">
              Cover image description
            </label>
            <input
              className="w-full rounded-lg border border-[#cfd4d5] px-4 py-3 text-base focus-visible:border-[#176b4b]"
              id="cover-alt-text"
              maxLength={250}
              onChange={(event) => setCoverAltText(event.target.value)}
              value={coverAltText}
            />
            <p className="mt-2 text-sm leading-6 text-[#59636a]">
              You can add a cover image after media storage is configured.
            </p>
          </div>

          {collectionEnabled && notice ? (
            <div className="rounded-xl border border-[#dfe3e5] bg-[#f8f9f9] p-5">
              <h2 className="text-sm font-semibold">Date of birth privacy notice</h2>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#414a4f]">{notice}</p>
            </div>
          ) : null}

          {collectionEnabled && dateOfBirth.length > 0 && !savedDateOfBirth ? (
            <label className="flex items-start gap-3 text-sm leading-6 text-[#414a4f]">
              <input
                checked={consent}
                className="mt-1 size-4 accent-[#a90000]"
                onChange={(event) => setConsent(event.target.checked)}
                required={dateOfBirth !== savedDateOfBirth}
                type="checkbox"
              />
              <span>I have read this notice and consent to storing my date of birth for the purposes described above.</span>
            </label>
          ) : null}

          <button
            className="rounded-full bg-[#a90000] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[#850000] disabled:cursor-wait disabled:bg-[#8d9295]"
            disabled={saving || (dateOfBirth !== savedDateOfBirth && dateOfBirth.length > 0 && !consent)}
            type="submit"
          >
            {saving ? "Saving…" : "Save profile"}
          </button>
        </form>
      ) : null}
    </section>
  );
}
