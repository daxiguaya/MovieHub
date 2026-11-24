import type { PublicConfig } from "./types";
import { appPath } from "./paths";

const fallback: PublicConfig = { xiaoyaSearchBaseUrl: "" };

export async function loadPublicConfig(): Promise<PublicConfig> {
  try {
    const response = await fetch(appPath("config.json"), { cache: "no-store" });
    if (!response.ok) return fallback;
    const config = (await response.json()) as Partial<PublicConfig>;
    return {
      xiaoyaSearchBaseUrl:
        typeof config.xiaoyaSearchBaseUrl === "string"
          ? config.xiaoyaSearchBaseUrl.trim()
          : ""
    };
  } catch {
    return fallback;
  }
}

export function openXiaoyaSearch(baseUrl: string, title: string): void {
  if (!baseUrl) return;
  try {
    const target = new URL(baseUrl);
    target.searchParams.set("box", title);
    window.open(target.toString(), "_blank", "noopener,noreferrer");
  } catch {
    window.alert("小雅搜索地址配置无效，请检查前端 config.json。");
  }
}
