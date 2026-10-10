import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import remarkRehype from 'remark-rehype'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import rehypeStringify from 'rehype-stringify'
import { visit } from 'unist-util-visit'

const FENCE_RE = /^[ \t]{0,3}(?:```|~~~)/

/** 修补 LLM 常见的粗体/斜体/删除线孤立标记泄露 */
function sanitizeOrphanAsterisks(text) {
  const lines = text.split('\n')
  let inFenced = false
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (FENCE_RE.test(line)) { inFenced = !inFenced; continue }
    if (inFenced) continue
    if (/^[ \t]{4,}/.test(line)) continue
    // 跳过表格行（含 | 的 GFM 表格），避免误处理
    if (/^\|/.test(line.trim())) continue
    // 全局移除 ~~ 禁用删除线（LLM 中文输出中可能意外出现）
    lines[i] = line.replace(/~~/g, '')
    const clean = lines[i]
    if (!clean) continue
    for (const suffix of ['***', '**', '*']) {
      const escaped = suffix.replace(/\*/g, '\\*')
      const trailing = clean.match(RegExp(`${escaped}(\\s*)$`))
      if (!trailing) continue
      const rest = clean.slice(0, clean.length - trailing[0].length)
      let count = 0
      let inBacktick = false
      for (let j = 0; j < rest.length; j++) {
        if (rest[j] === '`') { inBacktick = !inBacktick; continue }
        if (inBacktick) continue
        if (rest.slice(j, j + suffix.length) === suffix) {
          count++
          j += suffix.length - 1
        }
      }
      if (count % 2 === 0) {
        lines[i] = rest + trailing[1]
        break
      }
    }
  }
  return lines.join('\n')
}

/** rehype 插件：删除删除线（~~）渲染 */
function rehypeRemoveDel() {
  return (tree) => {
    visit(tree, 'element', (node, index, parent) => {
      if (node.tagName === 'del' && parent && typeof index === 'number') {
        // 将 <del> 内容展开为纯文本，删除 <del> 标签
        parent.children.splice(index, 1, ...(node.children || []))
      }
    })
  }
}

/** rehype 插件：将 .katex-display 包裹在横向滚动的 div 中 */
function rehypeWrapKatex() {
  return (tree) => {
    visit(tree, 'element', (node, index, parent) => {
      if (
        node.tagName === 'span' &&
        node.properties?.className?.includes('katex-display') &&
        parent &&
        typeof index === 'number'
      ) {
        parent.children[index] = {
          type: 'element',
          tagName: 'div',
          properties: {
            class: 'katex-scroll-wrap',
            style: 'overflow-x:auto;max-width:100%;-webkit-overflow-scrolling:touch;',
          },
          children: [node],
        }
      }
    })
  }
}

const processor = unified()
  .use(remarkParse)
  .use(remarkMath)
  .use(remarkGfm)
  .use(remarkBreaks)
  .use(remarkRehype, { allowDangerousHtml: false })
  .use(rehypeKatex, { throwOnError: false, strict: false })
  .use(rehypeRemoveDel)   // 删除 ~...~ 渲染
  .use(rehypeWrapKatex)  // 在 KaTeX 之后包裹滚动容器
  .use(rehypeHighlight)
  .use(rehypeStringify)

export function renderMarkdown(text, token) {
  if (!text) return ''
  try {
    // 确保标题前有换行，避免 remarkBreaks 吃掉 heading 标记
    // 仅匹配行首的 #，不破坏表格单元格内的 #
    const withHeadingBreaks = text
      .replace(/(\n)(#{1,6}\s)/g, '\n\n$2')
      .replace(/^(#{1,6}\s)/gm, '\n\n$1')
    // 对图片 URL 中的空格进行 URL 编码，防止浏览器无法加载
    const encodedUrls = withHeadingBreaks.replace(
      /(!\[.*?\]\()(.*?)(\))/g,
      (match, prefix, url, suffix) => {
        const encoded = url.replace(/ /g, '%20')
        return prefix + encoded + suffix
      }
    )
    const normalized = sanitizeOrphanAsterisks(encodedUrls)
    const result = processor.processSync(normalized)
    let html = String(result)
    // 注入短时效 access token 到 <img> 标签（<img> 无法设 Authorization 头，媒体直链走 ?token=）
    if (token) {
      html = html.replace(
        /(<img\s[^>]*src=")([^"]+)(")/g,
        (match, prefix, src, suffix) => {
          if (src.includes('token=')) return match
          const sep = src.includes('?') ? '&' : '?'
          return prefix + src + sep + 'token=' + encodeURIComponent(token) + suffix
        }
      )
    }
    return html
  } catch (e) {
    console.error('[renderMarkdown] 渲染失败:', e)
    try {
      // 降级：直接返回原始文本（至少用户能看到内容）
      return text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
    } catch {
      return text || ''
    }
  }
}
