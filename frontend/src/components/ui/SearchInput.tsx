import React, { useState, useEffect, useRef } from 'react';

interface SearchInputProps {
  placeholder?: string;
  onSearch: (query: string) => void;
  initialValue?: string;
  className?: string;
  debounceMs?: number;
}

export function SearchInput({
  placeholder = 'Search...',
  onSearch,
  initialValue = '',
  className = '',
  debounceMs = 500,
}: SearchInputProps) {
  const [searchTerm, setSearchTerm] = useState(initialValue);

  // Store the latest onSearch function in a ref to avoid dependency issues
  const onSearchRef = useRef(onSearch);

  // Keep ref up to date with latest onSearch
  useEffect(() => {
    onSearchRef.current = onSearch;
  }, [onSearch]);

  // Debounce the search term updates
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      onSearchRef.current(searchTerm);
    }, debounceMs);

    return () => clearTimeout(timeoutId);
  }, [searchTerm, debounceMs]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchTerm(e.target.value);
  };

  const handleClear = () => {
    setSearchTerm('');
  };

  return (
    <div className={`relative ${className}`}>
      <div className='absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none'>
        <svg
          className='h-5 w-5 text-gray-400 dark:text-slate-500'
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
      </div>
      <input
        type='text'
        value={searchTerm}
        onChange={handleChange}
        className='block w-full pl-10 pr-10 py-2 border border-gray-300 dark:border-slate-600 rounded-md leading-5 bg-white dark:bg-slate-800 placeholder-gray-500 dark:placeholder-slate-400 focus:outline-none focus:placeholder-gray-400 dark:focus:placeholder-slate-500 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm dark:text-slate-100'
        placeholder={placeholder}
      />
      {searchTerm && (
        <button
          onClick={handleClear}
          className='absolute inset-y-0 right-0 pr-3 flex items-center'
        >
          <svg
            className='h-5 w-5 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300'
            fill='none'
            stroke='currentColor'
            viewBox='0 0 24 24'
          >
            <path
              strokeLinecap='round'
              strokeLinejoin='round'
              strokeWidth={2}
              d='M6 18L18 6M6 6l12 12'
            />
          </svg>
        </button>
      )}
    </div>
  );
}
