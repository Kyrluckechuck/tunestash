import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ColumnToggle } from '../ColumnToggle';

const columns = [
  { key: 'lastSynced', label: 'Last Synced' },
  { key: 'lastDownloaded', label: 'Last Downloaded' },
  { key: 'addedAt', label: 'Added At' },
];

describe('ColumnToggle', () => {
  it('renders the Columns button', () => {
    render(
      <ColumnToggle
        columns={columns}
        visibleColumns={['lastSynced']}
        onToggle={vi.fn()}
      />
    );
    expect(
      screen.getByRole('button', { name: /toggle columns/i })
    ).toBeInTheDocument();
  });

  it('dropdown is closed by default', () => {
    render(
      <ColumnToggle
        columns={columns}
        visibleColumns={['lastSynced']}
        onToggle={vi.fn()}
      />
    );
    expect(screen.queryByText('Show Columns')).not.toBeInTheDocument();
  });

  it('opens dropdown when button is clicked', () => {
    render(
      <ColumnToggle
        columns={columns}
        visibleColumns={['lastSynced']}
        onToggle={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /toggle columns/i }));
    expect(screen.getByText('Show Columns')).toBeInTheDocument();
    expect(screen.getByLabelText('Last Synced')).toBeInTheDocument();
    expect(screen.getByLabelText('Last Downloaded')).toBeInTheDocument();
    expect(screen.getByLabelText('Added At')).toBeInTheDocument();
  });

  it('closes dropdown when button is clicked again', () => {
    render(
      <ColumnToggle
        columns={columns}
        visibleColumns={['lastSynced']}
        onToggle={vi.fn()}
      />
    );
    const btn = screen.getByRole('button', { name: /toggle columns/i });
    fireEvent.click(btn);
    expect(screen.getByText('Show Columns')).toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.queryByText('Show Columns')).not.toBeInTheDocument();
  });

  it('shows checked state for visible columns', () => {
    render(
      <ColumnToggle
        columns={columns}
        visibleColumns={['lastSynced', 'addedAt']}
        onToggle={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /toggle columns/i }));
    expect(screen.getByLabelText('Last Synced')).toBeChecked();
    expect(screen.getByLabelText('Added At')).toBeChecked();
    expect(screen.getByLabelText('Last Downloaded')).not.toBeChecked();
  });

  it('calls onToggle with correct key when checkbox is changed', () => {
    const onToggle = vi.fn();
    render(
      <ColumnToggle
        columns={columns}
        visibleColumns={['lastSynced']}
        onToggle={onToggle}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /toggle columns/i }));
    fireEvent.click(screen.getByLabelText('Last Downloaded'));
    expect(onToggle).toHaveBeenCalledWith('lastDownloaded');
  });

  it('closes dropdown when Escape is pressed', () => {
    render(
      <ColumnToggle
        columns={columns}
        visibleColumns={['lastSynced']}
        onToggle={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /toggle columns/i }));
    expect(screen.getByText('Show Columns')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByText('Show Columns')).not.toBeInTheDocument();
  });

  it('closes dropdown when clicking outside', () => {
    render(
      <div>
        <div data-testid='outside'>Outside</div>
        <ColumnToggle
          columns={columns}
          visibleColumns={['lastSynced']}
          onToggle={vi.fn()}
        />
      </div>
    );
    fireEvent.click(screen.getByRole('button', { name: /toggle columns/i }));
    expect(screen.getByText('Show Columns')).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId('outside'));
    expect(screen.queryByText('Show Columns')).not.toBeInTheDocument();
  });

  it('renders all column labels in the dropdown', () => {
    render(
      <ColumnToggle columns={columns} visibleColumns={[]} onToggle={vi.fn()} />
    );
    fireEvent.click(screen.getByRole('button', { name: /toggle columns/i }));
    for (const col of columns) {
      expect(screen.getByLabelText(col.label)).toBeInTheDocument();
    }
  });
});
