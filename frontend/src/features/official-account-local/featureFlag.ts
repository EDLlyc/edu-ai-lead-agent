type OfficialAccountLocalEnvironment = Readonly<{
  DEV: boolean;
  VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED?: string;
}>;

export function isOfficialAccountLocalEnabled(
  environment: OfficialAccountLocalEnvironment = import.meta.env,
): boolean {
  return (
    environment.DEV &&
    environment.VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED === "true"
  );
}
