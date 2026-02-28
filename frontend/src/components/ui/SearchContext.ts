import { createContext } from 'react';

export interface SearchContextValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

export const SearchContext = createContext<SearchContextValue | null>(null);
