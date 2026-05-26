import { Link, useRouterState } from "@tanstack/react-router";
import {
  Search,
  Database,
  Bookmark,
  BarChart3,
  Calculator,
  Settings,
  Terminal,
  Car,
  Activity,
  HardDrive,
} from "lucide-react";


import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";

type NavItem = {
  title: string;
  url: string;
  icon: typeof Search;
  exact?: boolean;
};

const workItems: NavItem[] = [
  { title: "Szukaj", url: "/", icon: Search, exact: true },
  { title: "Aktywne joby", url: "/jobs", icon: Activity },
  { title: "Rekordy", url: "/records", icon: Database },
  { title: "Watchlist", url: "/watchlist", icon: Bookmark },
  { title: "Dashboard", url: "/dashboard", icon: BarChart3 },
];


const toolItems: NavItem[] = [
  { title: "Kalkulator", url: "/calculator", icon: Calculator },
  { title: "Ustawienia", url: "/settings", icon: Settings },
  { title: "Logi (dev)", url: "/dev/logs", icon: Terminal },
];

export function AppSidebar() {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const currentPath = useRouterState({
    select: (router) => router.location.pathname,
  });

  const isActive = (item: NavItem) =>
    item.exact ? currentPath === item.url : currentPath.startsWith(item.url);

  const renderItem = (item: NavItem) => {
    const active = isActive(item);
    return (
      <SidebarMenuItem key={item.url}>
        <SidebarMenuButton
          asChild
          isActive={active}
          tooltip={collapsed ? item.title : undefined}
        >
          <Link to={item.url} className="flex items-center gap-2">
            <item.icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="truncate">{item.title}</span>}
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  };

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <Link
          to="/"
          className="flex items-center gap-2 px-2 py-1.5 text-sm font-semibold tracking-tight"
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Car className="h-4 w-4" />
          </div>
          {!collapsed && <span>Car Auction Buddy</span>}
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Praca</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{workItems.map(renderItem)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Narzędzia</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{toolItems.map(renderItem)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
