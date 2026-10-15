// Host names the app answers. The app listens on 127.0.0.1 only (scripts in package.json); this
// check also stops DNS rebinding, where a page whose name is rebound to 127.0.0.1 would
// otherwise be same-origin with the app.
export const LOCAL_HOSTS = ["localhost", "127.0.0.1"];

/** True when the Host header (with or without its port) names this machine. */
export function isAllowedHost(host: string | null, allowed: readonly string[] = LOCAL_HOSTS) {
  if (!host) return false;
  const name = host.startsWith("[") ? host.slice(0, host.indexOf("]") + 1) : host.split(":")[0];
  return allowed.includes(name.toLowerCase());
}
