/**
 * W4-40: remark 插件 — 把文本里的文件路径转成自定义 filePath 节点
 *
 * MarkdownContent 用 components.filePath 渲染成 FilePathLink 组件.
 */
import { detectFilePaths } from './pathDetector';
import type { Plugin } from 'unified';
import type { Root, Text, PhrasingContent, Parent } from 'mdast';

export const FILE_PATH_NODE_TYPE = 'filePath';

export const remarkFilePaths: Plugin<[], Root> = () => {
  return (tree) => {
    walk(tree as Parent);
  };
};

function walk(node: Parent | PhrasingContent | Root): void {
  if (!('children' in node) || !Array.isArray((node as Parent).children)) return;
  const children = (node as Parent).children;
  const newChildren: typeof children = [];
  for (const child of children) {
    if (child.type === 'text') {
      const text = (child as Text).value;
      const paths = detectFilePaths(text);
      if (paths.length === 0) {
        newChildren.push(child);
        continue;
      }
      let cursor = 0;
      for (const p of paths) {
        if (p.start > cursor) {
          newChildren.push({ type: 'text', value: text.slice(cursor, p.start) } as Text);
        }
        newChildren.push({
          type: FILE_PATH_NODE_TYPE,
          value: p.path,
        } as unknown as PhrasingContent);
        cursor = p.end;
      }
      if (cursor < text.length) {
        newChildren.push({ type: 'text', value: text.slice(cursor) } as Text);
      }
    } else if ('children' in child) {
      // 不递归进 code 元素 — 里面的 text 留给 MarkdownContent 的 code 组件处理
      // 否则 code 组件会看到 children 是 filePath 元素, String(children) 变 '[object Object]'
      if (child.type === 'code' || child.type === 'inlineCode') {
        newChildren.push(child);
      } else {
        walk(child as Parent);
        newChildren.push(child);
      }
    } else {
      newChildren.push(child);
    }
  }
  (node as Parent).children = newChildren;
}
