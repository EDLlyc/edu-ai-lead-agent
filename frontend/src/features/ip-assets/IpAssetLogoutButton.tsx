import { currentIpAssetReturnTarget, leaveIpAssetDemo } from "./demoAccess";

type IpAssetLogoutButtonProps = {
  readonly className: string | undefined;
};

export function IpAssetLogoutButton({ className }: IpAssetLogoutButtonProps) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => leaveIpAssetDemo(currentIpAssetReturnTarget())}
    >
      退出登录
    </button>
  );
}
