import { describe, expect, it } from "vitest";
import { aboutDescription, pageScopeNotice, RELEASE_MATRIX } from "./about";

describe("About page release and connection copy", () => {
  it("shows the current deployed release matrix with companion versions labeled as references", () => {
    expect(RELEASE_MATRIX.map((release) => release.version)).toEqual([
      "v1.10.3",
      "v0.17.0",
      "v2.13.5",
    ]);
    expect(pageScopeNotice("host")).toContain("兼容参考");
    expect(pageScopeNotice("host")).toContain("不会实时查询");
  });

  it("describes the live host and demo modes accurately", () => {
    expect(aboutDescription("host")).toContain("已连接 AstrBot 宿主");
    expect(aboutDescription("host")).not.toContain("本地虚构演示数据");
    expect(pageScopeNotice("host")).toContain("当前页面连接到守灯插件");
    expect(aboutDescription("demo")).toContain("本地虚构演示数据");
    expect(pageScopeNotice("demo")).toContain("仅保存在内存中");
  });
});
