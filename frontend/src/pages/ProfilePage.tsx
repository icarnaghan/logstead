import { getUserProfile } from "../lib/auth";

/**
 * Profile & settings page.
 *
 * Shows the signed-in user's account information (read from the Cognito ID
 * token claims) and documents where integration settings live. Authentication
 * is delegated to Cognito, so account fields such as email and password are
 * managed in the identity provider, not here.
 */
export default function ProfilePage() {
  const profile = getUserProfile();

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold text-fg">
        Profile &amp; settings
      </h1>
      <p className="mt-1 text-sm text-fg-muted">
        Your account details and integration settings.
      </p>

      <section aria-labelledby="account-heading" className="mt-8">
        <h2 id="account-heading" className="text-lg font-medium text-fg">
          Account
        </h2>
        <dl className="mt-3 divide-y divide-border rounded-md border border-border">
          <div className="flex justify-between gap-4 px-4 py-3">
            <dt className="text-sm text-fg-subtle">Email</dt>
            <dd className="text-sm font-medium text-fg">
              {profile?.email ?? "Not available"}
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-xs text-fg-subtle">
          Sign-in and passwords are managed by the identity provider (Amazon
          Cognito), not in Logstead.
        </p>
      </section>

      <section aria-labelledby="integrations-heading" className="mt-8">
        <h2
          id="integrations-heading"
          className="text-lg font-medium text-fg"
        >
          Integrations
        </h2>
        <div className="mt-3 rounded-md border border-border px-4 py-3">
          <p className="text-sm font-medium text-fg">
            RentCast property enrichment
          </p>
          <p className="mt-1 text-sm text-fg-muted">
            Property data enrichment is powered by RentCast. Its API key is
            configured on the server as a deployment setting and is never stored
            in the browser or your account data. Enrichment is optional: adding
            a property always works even when it is unavailable.
          </p>
        </div>
        <div className="mt-3 rounded-md border border-border px-4 py-3">
          <p className="text-sm font-medium text-fg">
            Address autocomplete
          </p>
          <p className="mt-1 text-sm text-fg-muted">
            Address suggestions are provided by Amazon Location Service using the
            application&apos;s AWS permissions. No key configuration is required.
          </p>
        </div>
      </section>
    </div>
  );
}
