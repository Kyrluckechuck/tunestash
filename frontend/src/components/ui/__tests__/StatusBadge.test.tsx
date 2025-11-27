import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { StatusBadge } from '../StatusBadge';

describe('StatusBadge', () => {
  it('renders with label', () => {
    render(<StatusBadge label='Not Supported' color='amber' />);

    expect(screen.getByText('Not Supported')).toBeInTheDocument();
  });

  it('applies amber color classes', () => {
    render(<StatusBadge label='Not Supported' color='amber' />);

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-amber-100', 'text-amber-800');
  });

  it('applies red color classes', () => {
    render(<StatusBadge label='Not Found' color='red' />);

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-red-100', 'text-red-800');
  });

  it('applies green color classes', () => {
    render(<StatusBadge label='Active' color='green' />);

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-green-100', 'text-green-800');
  });

  it('applies gray color classes', () => {
    render(<StatusBadge label='Disabled' color='gray' />);

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-gray-100', 'text-gray-600');
  });

  it('renders tooltip when provided', () => {
    render(
      <StatusBadge
        label='Not Supported'
        color='amber'
        tooltip='Spotify-generated playlists cannot be accessed'
      />
    );

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveAttribute(
      'title',
      'Spotify-generated playlists cannot be accessed'
    );
  });

  it('renders default warning icon', () => {
    render(<StatusBadge label='Not Supported' color='amber' />);

    const svg = document.querySelector('svg');
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('renders custom icon when provided', () => {
    const customIcon = <span data-testid='custom-icon'>!</span>;
    render(<StatusBadge label='Custom' color='amber' icon={customIcon} />);

    expect(screen.getByTestId('custom-icon')).toBeInTheDocument();
  });

  it('has cursor-help class for tooltip indication', () => {
    render(<StatusBadge label='Not Supported' color='amber' />);

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('cursor-help');
  });

  it('has consistent width class for alignment', () => {
    render(<StatusBadge label='Not Supported' color='amber' />);

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('w-28');
  });
});
