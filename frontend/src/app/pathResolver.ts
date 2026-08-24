export type ApplicationPath = "console" | "ip-assets" | "not-found";

export function resolveApplicationPath(pathname: string): ApplicationPath {
  if (pathname === "/") return "console";
  if (pathname === "/ip-assets" || pathname === "/ip-assets/") {
    return "ip-assets";
  }
  return "not-found";
}
