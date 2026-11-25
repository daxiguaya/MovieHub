import type { PublicConfig } from "./types";
import { appPath } from "./paths";

const fallback: PublicConfig = { xiaoyaSearchUrlTemplate: "" };

export async function loadPublicConfig(): Promise<PublicConfig> {
  try {
    const response = await fetch(appPath("api/config"), { cache: "no-store" });
    if (!response.ok) return fallback;
    const config = (await response.json()) as Partial<PublicConfig>;
    return {
      xiaoyaSearchUrlTemplate:
        typeof config.xiaoyaSearchUrlTemplate === "string"
          ? config.xiaoyaSearchUrlTemplate.trim()
          : ""
    };
  } catch {
    return fallback;
  }
}

export function openXiaoyaSearch(template: string, title: string): void {
  if (!template) return;
  try {
    if (!template.includes("{query}")) throw new Error("missing query placeholder");
    const target = new URL(template.replaceAll("{query}", encodeURIComponent(title)));
    if (target.protocol !== "http:" && target.protocol !== "https:") throw new Error("unsupported protocol");
    window.open(target.toString(), "_blank", "noopener,noreferrer");
  } catch {
    window.alert("小雅搜索地址模板无效，请检查 MOVIEHUB_XIAOYA_SEARCH_URL_TEMPLATE。");
  }
}
