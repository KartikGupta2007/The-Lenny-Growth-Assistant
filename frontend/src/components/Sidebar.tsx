import type { Session } from '../api/client';
import { IconClose, IconMoon, IconPanelLeft, IconPlus, IconSun } from './icons';
import { SessionList } from './SessionList';

interface SidebarProps {
  sessions: Session[];
  activeId: string | null;
  questions: Record<string, string>;
  loading: boolean;
  /** Drawer state on narrow screens. */
  open: boolean;
  /** Rail state on wide screens. */
  collapsed: boolean;
  theme: 'light' | 'dark';
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNewChat: () => void;
  onClose: () => void;
  onToggleCollapsed: () => void;
  onToggleTheme: () => void;
}

export function Sidebar({
  sessions,
  activeId,
  questions,
  loading,
  open,
  collapsed,
  theme,
  onSelect,
  onDelete,
  onNewChat,
  onClose,
  onToggleCollapsed,
  onToggleTheme,
}: SidebarProps) {
  return (
    <aside
      className="sidebar"
      data-open={open}
      data-collapsed={collapsed}
      aria-label="Conversations"
    >
      <div className="sidebar-head">
        <button
          type="button"
          className="icon-button sidebar-collapse"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <IconPanelLeft />
        </button>
        <span className="brand">Lenny</span>
        <button
          type="button"
          className="icon-button sidebar-close"
          onClick={onClose}
          aria-label="Close conversations"
        >
          <IconClose />
        </button>
      </div>

      <div className="sidebar-new">
        <button
          type="button"
          className="new-chat"
          onClick={onNewChat}
          aria-label="New chat"
        >
          <IconPlus />
          <span>New chat</span>
        </button>
      </div>

      <nav className="sidebar-body">
        <SessionList
          sessions={sessions}
          activeId={activeId}
          questions={questions}
          loading={loading}
          onSelect={onSelect}
          onDelete={onDelete}
        />
      </nav>

      <div className="sidebar-foot">
        <button
          type="button"
          className="icon-button theme-toggle"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
        >
          {theme === 'dark' ? <IconSun /> : <IconMoon />}
          <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
        </button>
      </div>
    </aside>
  );
}
