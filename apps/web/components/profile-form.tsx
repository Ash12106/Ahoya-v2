"use client";

import { useEffect, useState, type FormEvent } from "react";

type Profile = {
  username: string | null;
  display_name: string;
  date_of_birth: string | null;
  cover_alt_text: string;
  contact_email: string | null;
  phone_number: string | null;
  updated_at: string | null;
};

type ProfileResponse = {
  profile: Profile | null;
  contact_email_changes_remaining: number;
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
  const [contactEmail, setContactEmail] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [savedDateOfBirth, setSavedDateOfBirth] = useState("");
  const [coverAltText, setCoverAltText] = useState("");
  const [consent, setConsent] = useState(false);
  const [settings, setSettings] = useState<ProfileResponse | null>(null);
  const [status, setStatus] = useState("Loading your profile settings.");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);

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
          setContactEmail(data.profile.contact_email ?? "");
          setPhoneNumber(data.profile.phone_number ?? "");
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
          contact_email: contactEmail.trim() || null,
          phone_number: phoneNumber.trim() || null,
          ...(collectionEnabled && dateOfBirth.length > 0 && !savedDateOfBirth
            ? { date_of_birth: dateOfBirth }
            : {}),
          cover_alt_text: coverAltText,
        }),
      });
      if (!response.ok) {
        if (response.status === 409 || response.status === 429) {
          const apiError = (await response.json().catch(() => null)) as
            | { code?: string }
            | null;
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
          if (apiError?.code === "CONTACT_EMAIL_CHANGE_LIMIT") {
            setError("You can change your contact email twice in seven days. Try again later.");
            return;
          }
        }
        throw new Error("Your profile could not be saved. Check the fields and try again.");
      }
      const data = (await response.json()) as {
        profile: Profile;
        contact_email_changes_remaining: number;
      };
      setSettings((current) =>
        current
          ? {
              ...current,
              profile: data.profile,
              contact_email_changes_remaining: data.contact_email_changes_remaining,
            }
          : current,
      );
      setUsername(data.profile.username ?? "");
      setDisplayName(data.profile.display_name);
      setContactEmail(data.profile.contact_email ?? "");
      setPhoneNumber(data.profile.phone_number ?? "");
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

  async function downloadAccountExport() {
    setError(null);
    setStatus("Preparing your account data download.");
    setExporting(true);
    try {
      const response = await fetch("/api/account/export", { cache: "no-store" });
      if (!response.ok) throw new Error("Export unavailable");
      const blob = await response.blob();
      const exportedData: unknown = JSON.parse(await blob.text());
      if (typeof exportedData !== "object" || exportedData === null) {
        throw new Error("Invalid export");
      }
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = "ahoya-account-export.json";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      setStatus("Your account data download is ready.");
    } catch {
      setError("Your account data could not be exported. Try again later.");
      setStatus("Account data export failed.");
    } finally {
      setExporting(false);
    }
  }

  const collectionEnabled = settings?.date_of_birth_collection_enabled === true;
  const minimumAgeYears = settings?.minimum_age_years ?? 16;
  const notice = settings?.date_of_birth_consent_notice;

  return (
    <section
      aria-labelledby="profile-heading"
      className="profile-enter w-full max-w-3xl border border-[#d4d4d1] bg-[#f9f9f7] p-6 shadow-[0_24px_80px_-52px_rgba(0,0,0,0.45)] sm:p-10 lg:p-12"
    >
      <div className="mb-9 border-b border-[#d4d4d1] pb-8 sm:mb-11 sm:pb-10">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#a90000]">
          Your space <span className="mx-2 text-[#888986]">/</span> Profile settings
        </p>
        <h1
          className="mt-5 max-w-xl font-serif text-4xl font-medium leading-[1.02] tracking-[-0.045em] sm:text-6xl"
          id="profile-heading"
        >
          Make your profile yours.
        </h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-[#51534f] sm:text-lg sm:leading-8">
          Your profile settings are private and saved to Ahoya’s MongoDB database.
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
        <>
          <form className="space-y-8" onSubmit={saveProfile}>
          <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium" htmlFor="username">
              Username
            </label>
            <input
              autoCapitalize="none"
              autoComplete="username"
              className="w-full rounded-none border border-[#b9bbb7] bg-white px-4 py-3 text-base focus-visible:border-[#a90000]"
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
              className="w-full rounded-none border border-[#b9bbb7] bg-white px-4 py-3 text-base focus-visible:border-[#a90000]"
              id="display-name"
              maxLength={80}
              onChange={(event) => setDisplayName(event.target.value)}
              required
              value={displayName}
            />
          </div>
          </div>

          {collectionEnabled ? (
            <div>
              <label className="mb-2 block text-sm font-medium" htmlFor="date-of-birth">
                {savedDateOfBirth ? "Date of birth (locked)" : "Date of birth (required)"}
              </label>
              <input
                autoComplete="bday"
                className="w-full rounded-none border border-[#b9bbb7] bg-white px-4 py-3 text-base focus-visible:border-[#a90000]"
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
              className="w-full rounded-none border border-[#b9bbb7] bg-white px-4 py-3 text-base focus-visible:border-[#a90000]"
              id="cover-alt-text"
              maxLength={250}
              onChange={(event) => setCoverAltText(event.target.value)}
              value={coverAltText}
            />
            <p className="mt-2 text-sm leading-6 text-[#59636a]">
              You can add a cover image after media storage is configured.
            </p>
          </div>

          <div className="border-t border-[#d4d4d1] pt-7">
            <div className="mb-6 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#a90000]">
                  Private details
                </p>
                <h2 className="mt-2 font-serif text-2xl font-medium tracking-[-0.03em] sm:text-3xl">
                  Contact information
                </h2>
              </div>
              <p className="text-sm text-[#51534f]">
                {settings?.contact_email_changes_remaining ?? 2} of 2 email changes available
              </p>
            </div>
            <div className="grid gap-6 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium" htmlFor="contact-email">
                  Contact email
                </label>
                <input
                  autoComplete="email"
                  className="w-full rounded-none border border-[#b9bbb7] bg-white px-4 py-3 text-base focus-visible:border-[#a90000]"
                  id="contact-email"
                  maxLength={254}
                  onChange={(event) => setContactEmail(event.target.value)}
                  type="email"
                  value={contactEmail}
                />
                <p className="mt-2 text-sm leading-6 text-[#51534f]">
                  Private to you. No verification email is sent.
                </p>
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium" htmlFor="phone-number">
                  Phone number
                </label>
                <input
                  autoComplete="tel"
                  className="w-full rounded-none border border-[#b9bbb7] bg-white px-4 py-3 text-base focus-visible:border-[#a90000]"
                  id="phone-number"
                  inputMode="tel"
                  maxLength={32}
                  onChange={(event) => setPhoneNumber(event.target.value)}
                  type="tel"
                  value={phoneNumber}
                />
                <p className="mt-2 text-sm leading-6 text-[#51534f]">
                  Include + and your country code. It is private; no SMS is sent.
                </p>
              </div>
            </div>
            <p className="mt-5 text-xs leading-5 text-[#686a66]">
              Both fields are optional. Clear a field and save to remove it from your profile.
            </p>
            <p className="mt-5 border-l-2 border-[#a90000] pl-4 text-sm leading-6 text-[#51534f]">
              Ahoya uses Google sign-in. These contact details do not sign you in, link accounts,
              or recover a password.
            </p>
            <p className="mt-2 text-xs leading-5 text-[#686a66]">
              Contact email changes are limited to two in a rolling seven-day period.
            </p>
          </div>

          {collectionEnabled && notice ? (
            <div className="border border-[#d4d4d1] bg-white p-5">
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
            className="rounded-none bg-[#a90000] px-7 py-3.5 text-sm font-semibold text-white transition-colors hover:bg-[#850000] disabled:cursor-wait disabled:bg-[#8d9295]"
            disabled={saving || (dateOfBirth !== savedDateOfBirth && dateOfBirth.length > 0 && !consent)}
            type="submit"
          >
            {saving ? "Saving…" : "Save profile"}
          </button>
          </form>
          <section
            aria-labelledby="account-export-heading"
            className="mt-10 border-t border-[#d4d4d1] pt-8"
          >
            <div className="max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#a90000]">
                Your data
              </p>
              <h2
                className="mt-3 font-serif text-2xl font-medium tracking-[-0.03em] sm:text-3xl"
                id="account-export-heading"
              >
                Take a copy with you.
              </h2>
              <p
                className="mt-3 text-sm leading-6 text-[#51534f]"
                id="account-export-description"
              >
                Download the account, profile, and consent records Ahoya stores for you. Any saved
                date of birth and private contact details are included. Google account data is
                managed by Google and is not part of this export.
              </p>
            </div>
            <button
              aria-describedby="account-export-description"
              className="mt-5 rounded-none border border-[#151515] px-6 py-3 text-sm font-semibold text-[#151515] transition-colors hover:bg-[#151515] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a90000] disabled:cursor-wait disabled:opacity-60"
              disabled={exporting}
              onClick={() => void downloadAccountExport()}
              type="button"
            >
              {exporting ? "Preparing download…" : "Download account data (JSON)"}
            </button>
          </section>
        </>
      ) : null}
    </section>
  );
}
