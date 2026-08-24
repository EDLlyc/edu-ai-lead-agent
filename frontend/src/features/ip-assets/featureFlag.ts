type IpAssetEnvironment = Readonly<{
  VITE_IP_ASSET_HUB_ENABLED?: string;
}>;

export function isIpAssetHubEnabled(
  environment: IpAssetEnvironment = import.meta.env,
): boolean {
  return environment.VITE_IP_ASSET_HUB_ENABLED === "true";
}
