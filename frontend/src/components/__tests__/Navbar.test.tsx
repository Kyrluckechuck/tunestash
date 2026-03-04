import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Navbar } from '../Navbar';
import { DownloadModalProvider } from '../ui/DownloadModalProvider';
import { SearchProvider } from '../ui/SearchProvider';
import { ToastProvider } from '../ui/ToastProvider';

const renderNavbar = () => {
  return render(
    <ToastProvider>
      <SearchProvider>
        <DownloadModalProvider>
          <Navbar />
        </DownloadModalProvider>
      </SearchProvider>
    </ToastProvider>
  );
};

describe('Navbar', () => {
  it('renders the application title', () => {
    renderNavbar();

    expect(screen.getByText('TuneStash')).toBeInTheDocument();
  });

  it('renders all navigation links and download button', () => {
    renderNavbar();

    const expectedLinks = ['Home', 'Artists', 'Albums', 'Playlists', 'Tasks'];

    expectedLinks.forEach(linkText => {
      expect(screen.getByText(linkText)).toBeInTheDocument();
    });

    // Search and Download are buttons, not links
    expect(screen.getByText('Download')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /download/i })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument();
  });

  it('has proper navigation structure', () => {
    renderNavbar();

    const nav = screen.getByRole('navigation');
    expect(nav).toBeInTheDocument();

    // Check that nav links are anchor elements (6 links + 1 title link)
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(8); // Title + 7 nav links (Home, Dashboard, Artists, Albums, Songs, Playlists, Tasks)

    // Check that search and download buttons exist
    const searchButton = screen.getByRole('button', { name: /search/i });
    expect(searchButton).toBeInTheDocument();
    const downloadButton = screen.getByRole('button', { name: /download/i });
    expect(downloadButton).toBeInTheDocument();
  });

  it('applies correct CSS classes', () => {
    renderNavbar();

    const navbar = screen.getByRole('navigation');
    expect(navbar).toHaveClass('bg-white', 'border-b', 'border-gray-300');

    const title = screen.getByText('TuneStash');
    expect(title).toHaveClass('font-extrabold', 'text-2xl');
  });
});
