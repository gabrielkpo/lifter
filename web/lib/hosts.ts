// Host names the app answers. Locally the app listens on 127.0.0.1 only (scripts in
// package.json); this check also stops DNS rebinding, where a page whose name is rebound to
// 127.0.0.1 would otherwise be same-origin with the app. On Vercel, the deployment's own host
// names (set by Vercel) are added, plus any custom domain listed in LIFTER_WEB_HOSTS.
export const LOCAL_HOSTS = ["localhost", "127.0.0.1"];

const VERCEL_HOST_VARIABLES = ["VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"];

/** The host names allowed in this environment (environment variables are trusted). */
export function allowedHosts(env: Record<string, string | undefined>): string[] {
  const extra = [
    ...VERCEL_HOST_VARIABLES.map((name) => env[name]),
    ...(env.LIFTER_WEB_HOSTS ?? "").split(","),
  ];
  return [
    ...LOCAL_HOSTS,
    ...extra.map((host) => host?.trim().toLowerCase()).filter((host): host is string => !!host),
  ];
}

/** True when the Host header (with or without its port) is one of the allowed names. */
export function isAllowedHost(host: string | null, allowed: readonly string[] = LOCAL_HOSTS) {
  if (!host) return false;
  const name = host.startsWith("[") ? host.slice(0, host.indexOf("]") + 1) : host.split(":")[0];
  return allowed.includes(name.toLowerCase());
}
