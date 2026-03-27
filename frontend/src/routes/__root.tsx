import { createRootRoute, Outlet } from '@tanstack/react-router';
import { ToastProvider } from '../components/ui/ToastProvider';
import { DownloadModalProvider } from '../components/ui/DownloadModalProvider';
import { SearchProvider } from '../components/ui/SearchProvider';
import { ErrorBoundary } from '../components/ui/ErrorBoundary';
import { Navbar } from '../components/Navbar';
import { AuthStatusBanner } from '../components/ui/AuthStatusBanner';

function RootComponent() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <SearchProvider>
          <DownloadModalProvider>
            <div className='min-h-screen bg-slate-50 dark:bg-slate-950'>
              <Navbar />
              <main className='max-w-7xl mx-auto px-6 py-8'>
                <AuthStatusBanner />
                <div className='bg-white dark:bg-slate-900/50 rounded-lg border border-slate-200 dark:border-slate-800 p-8 min-h-[400px]'>
                  <Outlet />
                </div>
              </main>
            </div>
          </DownloadModalProvider>
        </SearchProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}

export const Route = createRootRoute({
  component: RootComponent,
});
