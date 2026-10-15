import styles from "../Admin.module.css";
import { passwordStrength } from "./passwordStrength";

/** Strength hint under a password field. Weak passwords are still allowed. */
export function PasswordHint({
  password,
  username,
}: {
  readonly password: string;
  readonly username?: string;
}) {
  const strength = passwordStrength(password, username);
  if (strength === null) return null;
  return (
    <p
      className={strength.level === "weak" ? styles.error : styles.hint}
      role="status"
      data-strength={strength.level}
    >
      密码强度：{strength.label}
      {strength.advice === "" ? "" : `。${strength.advice}`}
      {strength.level === "weak" && password.length >= 8
        ? "仍可以使用，但账号对公网开放，建议换一个更强的。"
        : ""}
    </p>
  );
}
