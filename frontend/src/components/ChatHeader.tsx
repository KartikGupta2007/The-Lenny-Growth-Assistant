import { IconMenu } from './icons';

/** Minimal top bar: the drawer trigger on narrow screens, and the title. */
export function ChatHeader({
  title,
  onOpenSidebar,
}: {
  title: string;
  onOpenSidebar: () => void;
}) {
  return (
    <header className="chat-header">
      <button
        type="button"
        className="icon-button sidebar-open"
        onClick={onOpenSidebar}
        aria-label="Open conversations"
      >
        <IconMenu />
      </button>
      <h1 className="chat-title">{title}</h1>
    </header>
  );
}
