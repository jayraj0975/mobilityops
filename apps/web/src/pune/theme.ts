import { useCallback, useEffect, useState } from "react";

export type Theme = "auto" | "light" | "dark";
const KEY = "mobilityops.theme";

const read = (): Theme => {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "auto";
  } catch {
    return "auto"; // storage can be blocked; the page must still work
  }
};

/** Light, dark, or follow the system. The choice is remembered on this device only. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);
  const cycle = useCallback(() => {
    setTheme((t) => {
      const next: Theme = t === "auto" ? "dark" : t === "dark" ? "light" : "auto";
      try {
        if (next === "auto") window.localStorage.removeItem(KEY);
        else window.localStorage.setItem(KEY, next);
      } catch {
        /* not remembered; still applied */
      }
      return next;
    });
  }, []);
  return [theme, cycle];
}
