import { useEffect, useRef, useState } from "react";

import { useBootstrapIpAssetProfile } from "./hooks";
import {
  createLocalProfileToken,
  saveLocalIpAssetProfile,
  type LocalIpAssetProfile,
} from "./profile";

import styles from "./ProfileSetupDialog.module.css";

export function ProfileSetupDialog({
  onClose,
  onCreated,
}: Readonly<{
  onClose: () => void;
  onCreated: (profile: LocalIpAssetProfile) => void;
}>) {
  const mutation = useBootstrapIpAssetProfile();
  const [token] = useState(createLocalProfileToken);
  const panel = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  const bootstrapProfile = (displayName: string, department: string) => {
    mutation.mutate(
      { token, displayName, department },
      {
        onSuccess: (response) => {
          const profile: LocalIpAssetProfile = {
            token,
            profileRef: response.profile_ref,
            displayName: response.display_name,
            department: response.department,
          };
          saveLocalIpAssetProfile(profile);
          onCreated(profile);
        },
      },
    );
  };

  useEffect(() => {
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    closeButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || panel.current === null) return;
      const controls = Array.from(
        panel.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), [href]",
        ),
      );
      const first = controls[0];
      const last = controls.at(-1);
      if (first === undefined || last === undefined) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      previous?.focus();
    };
  }, [onClose]);

  return (
    <div className={styles.backdrop} onMouseDown={onClose}>
      <div
        ref={panel}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="local-profile-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button
          ref={closeButton}
          className={styles.close}
          type="button"
          onClick={onClose}
          aria-label="关闭个人资料设置"
        >
          ×
        </button>
        <p className={styles.kicker}>LOCAL MATERIAL PROFILE</p>
        <h2 id="local-profile-title">建立这台浏览器的素材名片</h2>
        <p className={styles.lead}>
          用于收藏、个人素材和 AI 创作结果归集。它没有密码，也不是员工身份认证。
        </p>
        <button
          className={styles.demoProfile}
          type="button"
          disabled={mutation.isPending}
          onClick={() => bootstrapProfile("演示用户", "品牌中心")}
        >
          {mutation.isPending ? "正在建立…" : "一键使用演示名片"}
        </button>
        <div className={styles.orDivider} aria-hidden="true">
          <span>或手动填写</span>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const displayName = formText(form, "displayName").trim();
            const department = formText(form, "department").trim();
            bootstrapProfile(displayName, department);
          }}
        >
          <label>
            <span>显示名称</span>
            <input
              name="displayName"
              required
              minLength={1}
              maxLength={80}
              autoComplete="name"
            />
          </label>
          <label>
            <span>部门</span>
            <input name="department" required minLength={1} maxLength={80} />
          </label>
          <div className={styles.boundary} role="note">
            <strong>请注意</strong>
            <span>
              这不是身份认证。资料只保存在当前浏览器；清除浏览器数据后无法找回，也不会跨设备同步。
            </span>
          </div>
          <button
            className={styles.submit}
            type="submit"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "正在建立…" : "进入个人素材仓库"}
          </button>
          {mutation.isError ? (
            <p className={styles.error} role="alert">
              建立失败，请保留本页并重试。
            </p>
          ) : null}
        </form>
      </div>
    </div>
  );
}

function formText(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === "string" ? value : "";
}
