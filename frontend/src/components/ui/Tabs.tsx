/**
 * Tabs - Reusable tab navigation component
 *
 * Provides consistent tabbed UI across the application with:
 * - Active/inactive state styling with underline indicator
 * - Optional count badges for each tab
 * - Keyboard accessible
 */

export interface Tab<T extends string> {
  id: T;
  label: string;
  count?: number;
}

interface TabsProps<T extends string> {
  /** Currently active tab ID */
  activeTab: T;
  /** Available tabs */
  tabs: Tab<T>[];
  /** Called when tab changes */
  onChange: (tabId: T) => void;
  /** Additional CSS classes for the container */
  className?: string;
}

export function Tabs<T extends string>({
  activeTab,
  tabs,
  onChange,
  className = '',
}: TabsProps<T>) {
  return (
    <div className={`border-b border-gray-200 ${className}`}>
      <nav className='-mb-px flex space-x-8' aria-label='Tabs'>
        {tabs.map(tab => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onChange(tab.id)}
              className={`group inline-flex items-center py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                isActive
                  ? 'border-indigo-500 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
              aria-current={isActive ? 'page' : undefined}
            >
              {tab.label}
              {tab.count !== undefined && (
                <span
                  className={`ml-2 py-0.5 px-2 rounded-full text-xs font-medium ${
                    isActive
                      ? 'bg-indigo-100 text-indigo-600'
                      : 'bg-gray-100 text-gray-900'
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
