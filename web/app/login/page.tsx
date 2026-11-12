import { MARK_PATH } from "@/components/Mark";
import { safeNext, sessionSecrets } from "@/lib/session";

export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  wrong: "Wrong passphrase.",
  closed: "Sign-in is not set up on this server: the app stays closed.",
};

/** The sign-in page: a passphrase, sent to app/auth/login. A plain form, so it works before
 * any JavaScript runs. */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  const ready = (await sessionSecrets(process.env)) !== null;
  const message = ready ? ERRORS[error ?? ""] : ERRORS.closed;
  return (
    <div className="login">
      <svg viewBox="0 0 64 64" width={56} height={56} aria-hidden>
        <path fill="currentColor" d={MARK_PATH} />
      </svg>
      <h1>Lifter</h1>
      <form method="post" action="/auth/login" className="login-form">
        <input type="hidden" name="next" value={safeNext(next)} />
        <label htmlFor="passphrase" className="small muted">
          Passphrase
        </label>
        <input
          id="passphrase"
          name="passphrase"
          type="password"
          autoComplete="current-password"
          required
          autoFocus
          disabled={!ready}
          maxLength={512}
        />
        {message && (
          <p className="login-error" role="alert">
            {message}
          </p>
        )}
        <button type="submit" className="pill login-submit" disabled={!ready}>
          Sign in
        </button>
      </form>
    </div>
  );
}
