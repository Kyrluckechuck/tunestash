import { Link } from '@tanstack/react-router';
import { useTheme } from '../hooks/useTheme';
import { useDownloadModal } from './ui/useDownloadModal';
import { useSearch } from './ui/useSearch';

const themeIcons: Record<string, { icon: string; title: string }> = {
  system: { icon: '\u{1F5A5}', title: 'Theme: System' },
  light: { icon: '\u2600', title: 'Theme: Light' },
  dark: { icon: '\u{1F319}', title: 'Theme: Dark' },
};

const navLinks = [
  { to: '/', label: 'Home' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/artists', label: 'Artists' },
  { to: '/albums', label: 'Albums' },
  { to: '/playlists', label: 'Playlists' },
  { to: '/songs', label: 'Songs' },
  { to: '/tasks', label: 'Tasks' },
  { to: '/settings', label: 'Settings' },
];

export const Navbar = () => {
  const downloadModal = useDownloadModal();
  const search = useSearch();
  const { theme, cycle } = useTheme();
  const themeInfo = themeIcons[theme] ?? themeIcons.system;

  return (
    <nav className='bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-6 py-3 sticky top-0 z-10'>
      <div className='flex items-center justify-between w-full mx-auto'>
        <Link
          to='/'
          className='font-extrabold text-2xl tracking-tight text-slate-800 dark:text-slate-100 hover:text-[var(--color-accent)]'
          activeProps={{
            className:
              'font-extrabold text-2xl tracking-tight text-slate-800 dark:text-slate-100 hover:text-[var(--color-accent)]',
          }}
        >
          TuneStash
        </Link>
        <div className='flex items-center gap-1'>
          {navLinks.map(link => (
            <Link
              key={link.to}
              to={link.to}
              search={{} as Record<string, unknown>}
              className='px-3 py-1.5 rounded-md transition-colors text-sm font-medium text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800'
              activeProps={{
                className:
                  'px-3 py-1.5 rounded-md transition-colors text-sm font-medium text-[var(--color-accent)] bg-[var(--color-accent-light)] hover:text-[var(--color-accent)] hover:bg-[var(--color-accent-light)]',
              }}
              activeOptions={{ exact: true }}
            >
              {link.label}
            </Link>
          ))}
          <div className='w-px h-5 bg-slate-200 dark:bg-slate-700 mx-2' />
          <button
            onClick={cycle}
            className='px-2 py-1.5 text-slate-500 dark:text-slate-400 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 transition-colors text-base'
            title={themeInfo.title}
          >
            {themeInfo.icon}
          </button>
          <button
            onClick={search.open}
            className='px-3 py-1.5 border border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 rounded-md hover:border-slate-400 dark:hover:border-slate-500 hover:text-slate-700 dark:hover:text-slate-200 transition-colors flex items-center gap-2 text-sm'
            title='Search (Ctrl+K)'
          >
            <svg
              className='w-4 h-4'
              fill='none'
              stroke='currentColor'
              viewBox='0 0 24 24'
            >
              <path
                strokeLinecap='round'
                strokeLinejoin='round'
                strokeWidth={2}
                d='M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z'
              />
            </svg>
            <span className='hidden sm:inline'>Search</span>
            <kbd className='hidden md:inline-flex items-center gap-0.5 px-1.5 py-0.5 text-xs font-medium text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 rounded'>
              <span className='text-xs'>⌘</span>K
            </kbd>
          </button>
          <button
            onClick={downloadModal.open}
            className='px-4 py-1.5 bg-[var(--color-accent)] text-white rounded-md hover:bg-[var(--color-accent-hover)] transition-colors font-medium flex items-center gap-2 text-sm'
            title='Download music'
          >
            <svg
              className='w-4 h-4'
              fill='none'
              stroke='currentColor'
              viewBox='0 0 24 24'
            >
              <path
                strokeLinecap='round'
                strokeLinejoin='round'
                strokeWidth={2}
                d='M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z'
              />
            </svg>
            Download
          </button>
        </div>
      </div>
    </nav>
  );
};
