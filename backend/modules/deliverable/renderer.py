"""modules.deliverable.renderer —— HTML(+CSS) → PDF（PyMuPDF Story）。

- 用 MuPDF 的 HTML 引擎（``fitz.Story``）排版：A4、给定页边距；中文由内置 CJK 字体自动回退；
- 样式走 MuPDF 的 CSS 子集：字体 / 字号 / 颜色 / 背景 / 边框 / 内外边距 / 对齐 / 列表 / 表格都支持；
  圆角、阴影、flex/grid、伪元素不支持（写了会被忽略，不影响排版）；
- ``DEFAULT_CSS`` 里的 ``__ACCENT__`` / ``__ACCENT_SOFT__`` / ``__ACCENT_DARK__`` 由模板的
  ``accent`` 替换；模板还可以用自己的 ``css`` 追加覆盖；
- 渲染完成后逐页盖页脚（文档标题 + 页码），中文用内置 CJK 字体（china-s）。
"""

from __future__ import annotations

import io

import fitz

from infra.util.logger import logger

# 品牌主色（与前端一致）；模板可用 accent 覆盖
ACCENT_DEFAULT = "#d4734e"

# ── 默认样式（MuPDF CSS 子集；__ACCENT__* 由模板 accent 替换）──
DEFAULT_CSS = """
body { font-family: sans-serif; font-size: 10px; line-height: 1.62; color: #2b2b2b; }

.hero {
  background-color: __ACCENT_SOFT__; border-left: 8px solid __ACCENT__;
  padding: 13px 15px 13px 15px; margin: 0 0 14px 0;
}
.hero .kicker { font-size: 8.5px; color: __ACCENT_DARK__; margin: 0 0 4px 0; }
h1 { font-size: 22px; color: #1a1714; margin: 0; }
.meta { font-size: 8.5px; color: #8a8179; margin: 6px 0 0 0; }

h2 {
  font-size: 13px; color: #1a1714; margin: 14px 0 5px 0;
  padding-left: 8px; border-left: 4px solid __ACCENT__; page-break-after: avoid;
}
h3 { font-size: 11px; color: __ACCENT_DARK__; margin: 10px 0 2px 0; page-break-after: avoid; }

p { margin: 3px 0 5px 0; }
ul, ol { margin: 3px 0 5px 18px; }
li { margin: 1px 0; }
strong { color: #1a1714; }
code { font-family: monospace; font-size: 9px; background-color: #f4f1ed; color: #8a4a2f; }
blockquote {
  margin: 7px 0; padding: 6px 11px 6px 11px;
  background-color: #faf7f4; border-left: 3px solid #ddd3c9; color: #4a4440;
}
hr { border: 0; border-top: 1px solid #e3ddd6; margin: 10px 0 10px 0; }

table { width: 100%; border-collapse: collapse; margin: 7px 0 10px 0; page-break-inside: avoid; }
th { background-color: __ACCENT_SOFT__; color: #1a1714; text-align: left; }
th, td { border: 1px solid #e3ddd6; padding: 4px 6px 4px 6px; font-size: 9px; vertical-align: top; }

.muted { color: #8a8179; font-size: 8.5px; }
.tag { color: __ACCENT_DARK__; font-size: 8.5px; }
"""


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """``#rrggbb`` / ``#rgb`` → ``(r, g, b)``。"""
    c = (color or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        c = ACCENT_DEFAULT.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(v))) for v in rgb))


def _mix(color: str, target: tuple[int, int, int], ratio: float) -> str:
    """把 ``color`` 按 ``ratio`` 比例混向 ``target``（0=原色，1=目标色）。"""
    r, g, b = _hex_to_rgb(color)
    return _rgb_to_hex((
        r + (target[0] - r) * ratio,
        g + (target[1] - g) * ratio,
        b + (target[2] - b) * ratio,
    ))


def theme_css(accent: str | None = None, extra: str = "") -> str:
    """生成最终样式：默认样式（替换主题色）+ 模板自定义 css。"""
    a = (accent or "").strip() or ACCENT_DEFAULT
    soft = _mix(a, (255, 255, 255), 0.90)   # 90% 白 → 浅底
    dark = _mix(a, (0, 0, 0), 0.28)         # 加深 28%
    # 先换长 token，避免 __ACCENT__ 前缀把 __ACCENT_SOFT__ 截断
    css = (
        DEFAULT_CSS
        .replace("__ACCENT_SOFT__", soft)
        .replace("__ACCENT_DARK__", dark)
        .replace("__ACCENT__", a)
    )
    return f"{css}\n{extra or ''}"


def _finalize(data: bytes, footer: str) -> bytes:
    """渲染后处理：去掉结尾空页 + 逐页盖页脚 + 压缩保存。"""
    try:
        doc = fitz.open("pdf", data)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"PDF 后处理打开失败（原样返回）: {e}")
        return data

    # Story 在内容刚好触底时可能多生成一页（只剩表格边框等无文字内容）→ 去掉无文字的结尾页
    while doc.page_count > 1:
        last = doc[doc.page_count - 1]
        if last.get_text().strip():
            break
        doc.delete_page(doc.page_count - 1)

    name = (footer or "").strip()
    if name:
        try:
            total = doc.page_count
            gray = (0.55, 0.51, 0.47)
            for i, page in enumerate(doc):
                w = page.rect.width
                y = page.rect.height - 34
                page.draw_line(fitz.Point(42, y), fitz.Point(w - 42, y), color=(0.89, 0.87, 0.84), width=0.6)
                page.insert_text(
                    fitz.Point(42, y + 12), name[:58],
                    fontsize=8, color=gray, fontname="china-s",
                )
                page.insert_textbox(
                    fitz.Rect(w - 42 - 170, y + 1, w - 42, y + 15), f"第 {i + 1} / {total} 页",
                    fontsize=8, color=gray, fontname="china-s", align=fitz.TEXT_ALIGN_RIGHT,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"页脚盖章失败（忽略，不影响正文）: {e}")

    try:
        return doc.tobytes(garbage=3, deflate=True)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"PDF 保存失败（原样返回）: {e}")
        return data


def render_html_to_pdf(html: str, css: str = "", accent: str | None = None, footer: str = "") -> bytes:
    """把 HTML 渲染为 A4 PDF 字节。

    Args:
        html: 完整 HTML 片段（模板渲染结果）。
        css: 模板自定义 CSS（追加在默认样式之后，可覆盖）。
        accent: 主题色（``#rrggbb``）；空则用品牌主色。
        footer: 页脚文字（通常为文档标题）；空则不盖页脚。

    Returns:
        bytes: PDF 文件内容。

    Raises:
        RuntimeError: 渲染失败。
    """
    try:
        story = fitz.Story(html=html or "<p></p>", user_css=theme_css(accent, css))
        out = io.BytesIO()
        writer = fitz.DocumentWriter(out)
        mediabox = fitz.paper_rect("a4")
        where = mediabox + (42, 46, -42, -44)   # 页边距（左/上/右/下）
        more = 1
        while more:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
        writer.close()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"PDF 渲染失败: {e}") from e
    return _finalize(out.getvalue(), footer)
