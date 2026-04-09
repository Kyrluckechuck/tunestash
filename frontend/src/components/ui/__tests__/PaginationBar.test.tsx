import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PaginationBar } from '../PaginationBar';

describe('PaginationBar', () => {
  const defaultProps = {
    page: 1,
    totalPages: 10,
    totalCount: 500,
    pageSize: 50,
    onPageChange: vi.fn(),
  };

  it('shows correct range text', () => {
    render(<PaginationBar {...defaultProps} page={2} />);
    expect(screen.getByText('Showing 51–100 of 500')).toBeInTheDocument();
  });

  it('shows correct range on last partial page', () => {
    render(<PaginationBar {...defaultProps} page={10} totalCount={487} />);
    expect(screen.getByText('Showing 451–487 of 487')).toBeInTheDocument();
  });

  it('disables Prev on first page', () => {
    render(<PaginationBar {...defaultProps} page={1} />);
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
  });

  it('disables Next on last page', () => {
    render(<PaginationBar {...defaultProps} page={10} />);
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });

  it('calls onPageChange when clicking Next', () => {
    const onPageChange = vi.fn();
    render(
      <PaginationBar {...defaultProps} page={3} onPageChange={onPageChange} />
    );
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(onPageChange).toHaveBeenCalledWith(4);
  });

  it('calls onPageChange when clicking Prev', () => {
    const onPageChange = vi.fn();
    render(
      <PaginationBar {...defaultProps} page={3} onPageChange={onPageChange} />
    );
    fireEvent.click(screen.getByRole('button', { name: /prev/i }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it('calls onPageChange when clicking a page number', () => {
    const onPageChange = vi.fn();
    render(
      <PaginationBar {...defaultProps} page={1} onPageChange={onPageChange} />
    );
    fireEvent.click(screen.getByText('3'));
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it('shows first page, last page, and window around current', () => {
    render(
      <PaginationBar
        {...defaultProps}
        page={6}
        totalPages={33}
        totalCount={1645}
      />
    );
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.getByText('33')).toBeInTheDocument();
  });

  it('shows no ellipsis when pages fit in window', () => {
    render(
      <PaginationBar
        {...defaultProps}
        page={1}
        totalPages={3}
        totalCount={150}
      />
    );
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.queryByText('...')).not.toBeInTheDocument();
  });

  it('renders nothing when totalPages is 0', () => {
    const { container } = render(
      <PaginationBar {...defaultProps} totalPages={0} totalCount={0} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('disables buttons when loading', () => {
    render(<PaginationBar {...defaultProps} page={5} loading={true} />);
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });
});
