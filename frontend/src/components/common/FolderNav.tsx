/**
 * FolderNav — 平铺文字导航栏
 *
 * 每个 tab 一个简洁的文字按钮直接平铺在顶栏, 无图标无边框,
 * hover 浮现底色 / active 高亮, 点击切换。
 */

export interface FolderNavItem {
  key: string;
  label: string;
  emoji: string;
}

interface Props {
  items: FolderNavItem[];
  active: string;
  accent: string;
  onSelect: (key: string) => void;
}

export default function FolderNav({ items, active, onSelect }: Props) {
  return (
    <nav className="folder-nav" aria-label="主导航">
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          className={`folder-nav-item cursor-target ${active === it.key ? 'is-active' : ''}`}
          onClick={() => onSelect(it.key)}
          title={it.label}
          aria-pressed={active === it.key}
        >
          <span className="folder-nav-label">{it.label}</span>
        </button>
      ))}
    </nav>
  );
}
