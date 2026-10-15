/** A hint for the person typing a password. It never blocks: the server alone refuses a password
 * (shorter than 8, the most common ones, the username itself). */
export type PasswordStrength = {
  readonly level: "weak" | "fair" | "strong";
  readonly label: string;
  readonly advice: string;
};

function hasRun(value: string): boolean {
  // Six or more characters in a row that step by one (123456, abcdef) or repeat (aaaaaa).
  let run = 1;
  for (let i = 1; i < value.length; i += 1) {
    const step = value.charCodeAt(i) - value.charCodeAt(i - 1);
    run = step === 1 || step === -1 || step === 0 ? run + 1 : 1;
    if (run >= 6) return true;
  }
  return false;
}

export function passwordStrength(
  password: string,
  username = "",
): PasswordStrength | null {
  if (password === "") return null;
  const lowered = password.toLowerCase();
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^a-zA-Z0-9]/].filter(
    (pattern) => pattern.test(password),
  ).length;
  const name = username.trim().toLowerCase();
  if (password.length < 8) {
    return { level: "weak", label: "弱", advice: "至少 8 位。" };
  }
  if (name.length >= 3 && lowered.includes(name)) {
    return { level: "weak", label: "弱", advice: "不要包含用户名。" };
  }
  if (classes === 1 && password.length < 14) {
    return {
      level: "weak",
      label: "弱",
      advice: /^[0-9]+$/.test(password)
        ? "只有数字很容易被猜到，建议加上字母。"
        : "只有一种字符，建议混合字母和数字。",
    };
  }
  if (hasRun(lowered)) {
    return { level: "weak", label: "弱", advice: "含有连续或重复的字符。" };
  }
  if (password.length >= 12 && classes >= 2) {
    return { level: "strong", label: "强", advice: "" };
  }
  return {
    level: "fair",
    label: "中",
    advice: "再长一些（12 位以上）会更安全。",
  };
}
