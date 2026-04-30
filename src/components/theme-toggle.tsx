import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/components/theme-provider";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggle}
      className={className}
      title={isDark ? "Przełącz na jasny motyw" : "Przełącz na ciemny motyw"}
      aria-label="Przełącz motyw"
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
