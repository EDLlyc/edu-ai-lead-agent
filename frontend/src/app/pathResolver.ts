export type ApplicationPath =
  | "console"
  | "ip-assets"
  | "ip-assets-create"
  | "ip-assets-login"
  | "not-found";

export function resolveApplicationPath(pathname: string): ApplicationPath {
  if (pathname === "/") return "console";
  if (pathname === "/ip-assets" || pathname === "/ip-assets/") {
    return "ip-assets";
  }
  if (pathname === "/ip-assets/create" || pathname === "/ip-assets/create/") {
    return "ip-assets-create";
  }
  if (pathname === "/ip-assets/login" || pathname === "/ip-assets/login/") {
    return "ip-assets-login";
  }
  return "not-found";
}
