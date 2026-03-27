import { createFileRoute } from '@tanstack/react-router';
import React, { useState } from 'react';

import { useSettingsPage } from '../hooks/useSettingsPage';
import type {
  AppSettingType,
  SettingsCategoryType,
} from '../hooks/useSettingsPage';

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
});

function SettingsPage() {
  const {
    categories,
    loading,
    error,
    pendingKey,
    statusMessage,
    cookieContent,
    showCookieUpload,
    showSensitive,
    setCookieContent,
    setShowCookieUpload,
    handleToggleSensitive,
    handleUpdateSetting,
    handleResetSetting,
    handleUploadCookie,
    handleMigrateYaml,
  } = useSettingsPage();

  if (loading && categories.length === 0) {
    return (
      <div className='flex items-center justify-center py-12'>
        <div className='animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500' />
      </div>
    );
  }

  if (error) {
    return (
      <div className='p-4 bg-red-100 dark:bg-red-900/40 rounded-lg text-red-800 dark:text-red-200 border border-red-300 dark:border-red-700'>
        Failed to load settings: {error.message}
      </div>
    );
  }

  return (
    <div className='max-w-4xl mx-auto space-y-6'>
      <div className='flex items-center justify-between'>
        <h1 className='text-2xl font-bold text-gray-900 dark:text-white'>
          Settings
        </h1>
        <div className='flex items-center gap-3'>
          <button
            onClick={handleToggleSensitive}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              showSensitive
                ? 'bg-amber-100 dark:bg-amber-700 text-amber-800 dark:text-white'
                : 'bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
            }`}
          >
            {showSensitive ? 'Hide Secrets' : 'Show Secrets'}
          </button>
          <button
            onClick={() => setShowCookieUpload(!showCookieUpload)}
            className='px-3 py-1.5 text-sm rounded-md bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors'
          >
            Upload Cookies
          </button>
          <button
            onClick={handleMigrateYaml}
            className='px-3 py-1.5 text-sm rounded-md bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors'
          >
            Import from YAML
          </button>
        </div>
      </div>

      {statusMessage && (
        <div
          className={`p-3 rounded-lg text-sm font-medium border ${
            statusMessage.type === 'success'
              ? 'bg-green-100 dark:bg-green-700 text-green-800 dark:text-white border-green-300 dark:border-green-600'
              : 'bg-red-100 dark:bg-red-700 text-red-800 dark:text-white border-red-300 dark:border-red-600'
          }`}
        >
          {statusMessage.text}
        </div>
      )}

      {showCookieUpload && (
        <CookieUploadSection
          content={cookieContent}
          onChange={setCookieContent}
          onUpload={handleUploadCookie}
          onCancel={() => setShowCookieUpload(false)}
        />
      )}

      {categories.map(category => (
        <SettingsSection
          key={category.category}
          category={category}
          pendingKey={pendingKey}
          showSensitive={showSensitive}
          onUpdate={handleUpdateSetting}
          onReset={handleResetSetting}
        />
      ))}
    </div>
  );
}

function CookieUploadSection({
  content,
  onChange,
  onUpload,
  onCancel,
}: {
  content: string;
  onChange: (v: string) => void;
  onUpload: () => void;
  onCancel: () => void;
}) {
  return (
    <div className='bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-700 p-4 space-y-3'>
      <h3 className='font-medium text-gray-900 dark:text-white'>
        Upload YouTube Music Cookies
      </h3>
      <textarea
        value={content}
        onChange={e => onChange(e.target.value)}
        placeholder='Paste Netscape cookie file content here...'
        className='w-full h-32 px-3 py-2 text-sm font-mono bg-gray-50 dark:bg-slate-900 border border-gray-300 dark:border-slate-600 rounded-md text-gray-900 dark:text-gray-100 placeholder-gray-400 resize-y'
      />
      <div className='flex gap-2'>
        <button
          onClick={onUpload}
          disabled={!content.trim()}
          className='px-3 py-1.5 text-sm rounded-md bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
        >
          Save Cookie File
        </button>
        <button
          onClick={onCancel}
          className='px-3 py-1.5 text-sm rounded-md bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors'
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function SettingsSection({
  category,
  pendingKey,
  showSensitive,
  onUpdate,
  onReset,
}: {
  category: SettingsCategoryType;
  pendingKey: string | null;
  showSensitive: boolean;
  onUpdate: (key: string, value: string) => void;
  onReset: (key: string) => void;
}) {
  return (
    <div className='bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden'>
      <div className='px-4 py-3 bg-gray-50 dark:bg-slate-700/50 border-b border-gray-200 dark:border-slate-700'>
        <h2 className='text-lg font-semibold text-gray-900 dark:text-white'>
          {category.label}
        </h2>
      </div>
      <div className='divide-y divide-gray-100 dark:divide-slate-700'>
        {category.settings.map(setting => (
          <SettingRow
            key={setting.key}
            setting={setting}
            isPending={pendingKey === setting.key}
            showSensitive={showSensitive}
            onUpdate={onUpdate}
            onReset={onReset}
          />
        ))}
      </div>
    </div>
  );
}

function SettingRow({
  setting,
  isPending,
  showSensitive,
  onUpdate,
  onReset,
}: {
  setting: AppSettingType;
  isPending: boolean;
  showSensitive: boolean;
  onUpdate: (key: string, value: string) => void;
  onReset: (key: string) => void;
}) {
  return (
    <div className='px-4 py-3 flex flex-col sm:flex-row sm:items-start gap-2'>
      <div className='flex-1 min-w-0'>
        <div className='flex items-center gap-2'>
          <span className='text-sm font-medium text-gray-900 dark:text-white'>
            {setting.label}
          </span>
          {!setting.isDefault && (
            <span className='text-xs px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'>
              modified
            </span>
          )}
          {isPending && (
            <span className='animate-spin inline-block h-3 w-3 border-2 border-blue-500 border-t-transparent rounded-full' />
          )}
        </div>
        <p className='text-xs text-gray-500 dark:text-gray-400 mt-0.5'>
          {setting.description}
        </p>
      </div>
      <div className='flex items-center gap-2 shrink-0'>
        <SettingControl
          setting={setting}
          showSensitive={showSensitive}
          onUpdate={onUpdate}
        />
        {!setting.isDefault && (
          <button
            onClick={() => onReset(setting.key)}
            className='text-xs px-2 py-1 rounded text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors'
            title='Reset to default'
          >
            Reset
          </button>
        )}
      </div>
    </div>
  );
}

function SettingControl({
  setting,
  showSensitive,
  onUpdate,
}: {
  setting: AppSettingType;
  showSensitive: boolean;
  onUpdate: (key: string, value: string) => void;
}) {
  if (setting.type === 'bool') {
    return <BoolControl setting={setting} onUpdate={onUpdate} />;
  }
  if (
    setting.type === 'string' &&
    setting.options &&
    setting.options.length > 0
  ) {
    return <SelectControl setting={setting} onUpdate={onUpdate} />;
  }
  if (setting.type === 'int' || setting.type === 'float') {
    return <NumberControl setting={setting} onUpdate={onUpdate} />;
  }
  if (setting.type === 'list') {
    return (
      <ListControl
        setting={setting}
        showSensitive={showSensitive}
        onUpdate={onUpdate}
      />
    );
  }
  if (setting.type === 'secret') {
    return (
      <SecretControl
        setting={setting}
        showSensitive={showSensitive}
        onUpdate={onUpdate}
      />
    );
  }
  return <TextControl setting={setting} onUpdate={onUpdate} />;
}

function BoolControl({
  setting,
  onUpdate,
}: {
  setting: AppSettingType;
  onUpdate: (key: string, value: string) => void;
}) {
  const isOn = setting.value === 'true';
  return (
    <button
      onClick={() => onUpdate(setting.key, String(!isOn))}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
        isOn ? 'bg-[var(--color-accent)]' : 'bg-gray-300 dark:bg-slate-600'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          isOn ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );
}

function SelectControl({
  setting,
  onUpdate,
}: {
  setting: AppSettingType;
  onUpdate: (key: string, value: string) => void;
}) {
  return (
    <select
      value={setting.value}
      onChange={e => onUpdate(setting.key, e.target.value)}
      className='text-sm px-2 py-1 rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100'
    >
      {setting.options?.map(opt => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  );
}

function NumberControl({
  setting,
  onUpdate,
}: {
  setting: AppSettingType;
  onUpdate: (key: string, value: string) => void;
}) {
  const [localValue, setLocalValue] = useState(setting.value);
  return (
    <input
      type='number'
      value={localValue}
      onChange={e => setLocalValue(e.target.value)}
      onBlur={() => {
        if (localValue !== setting.value) {
          onUpdate(setting.key, localValue);
        }
      }}
      onKeyDown={e => {
        if (e.key === 'Enter') {
          onUpdate(setting.key, localValue);
        }
      }}
      className='w-24 text-sm px-2 py-1 rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100'
    />
  );
}

function TextControl({
  setting,
  onUpdate,
}: {
  setting: AppSettingType;
  onUpdate: (key: string, value: string) => void;
}) {
  const [localValue, setLocalValue] = useState(setting.value);
  return (
    <input
      type='text'
      value={localValue}
      onChange={e => setLocalValue(e.target.value)}
      onBlur={() => {
        if (localValue !== setting.value) {
          onUpdate(setting.key, localValue);
        }
      }}
      onKeyDown={e => {
        if (e.key === 'Enter') {
          onUpdate(setting.key, localValue);
        }
      }}
      className='w-48 text-sm px-2 py-1 rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100'
    />
  );
}

function SecretControl({
  setting,
  showSensitive,
  onUpdate,
}: {
  setting: AppSettingType;
  showSensitive: boolean;
  onUpdate: (key: string, value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [localValue, setLocalValue] = useState('');
  const hasValue = setting.value && !setting.isDefault;

  if (!editing) {
    return (
      <div className='flex items-center gap-2'>
        <span className='text-sm text-gray-500 dark:text-gray-400 font-mono max-w-xs truncate'>
          {hasValue
            ? showSensitive
              ? setting.value
              : '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022'
            : '(not set)'}
        </span>
        <button
          onClick={() => {
            setLocalValue(hasValue ? setting.value : '');
            setEditing(true);
          }}
          className='text-xs px-2 py-1 rounded text-[var(--color-accent)] dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors'
        >
          Change
        </button>
      </div>
    );
  }

  return (
    <div className='flex items-center gap-2'>
      <input
        type='password'
        value={localValue}
        onChange={e => setLocalValue(e.target.value)}
        placeholder='Enter new value...'
        className='w-48 text-sm px-2 py-1 rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100'
        autoFocus
      />
      <button
        onClick={() => {
          onUpdate(setting.key, localValue);
          setEditing(false);
          setLocalValue('');
        }}
        className='text-xs px-2 py-1 rounded bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] transition-colors'
      >
        Save
      </button>
      <button
        onClick={() => {
          setEditing(false);
          setLocalValue('');
        }}
        className='text-xs px-2 py-1 rounded text-gray-500 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors'
      >
        Cancel
      </button>
    </div>
  );
}

function ListControl({
  setting,
  showSensitive,
  onUpdate,
}: {
  setting: AppSettingType;
  showSensitive: boolean;
  onUpdate: (key: string, value: string) => void;
}) {
  let currentList: string[] = [];
  try {
    const parsed = JSON.parse(setting.value);
    if (Array.isArray(parsed)) currentList = parsed;
  } catch {
    currentList = setting.value
      ? setting.value.split(',').map(s => s.trim())
      : [];
  }

  const hasOptions = !!(setting.options && setting.options.length > 0);
  const isSensitive = setting.sensitive;

  const [localValue, setLocalValue] = useState(
    Array.isArray(currentList) ? currentList.join(', ') : setting.value
  );

  if (hasOptions) {
    return (
      <div className='flex flex-wrap gap-1.5'>
        {(setting.options ?? []).map(opt => {
          const isSelected = currentList.includes(opt);
          return (
            <button
              key={opt}
              onClick={() => {
                const next = isSelected
                  ? currentList.filter(v => v !== opt)
                  : [...currentList, opt];
                onUpdate(setting.key, JSON.stringify(next));
              }}
              className={`text-xs px-2 py-1 rounded-full border transition-colors ${
                isSelected
                  ? 'bg-blue-100 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300'
                  : 'bg-gray-50 dark:bg-slate-800 border-gray-300 dark:border-slate-600 text-gray-500 dark:text-gray-400'
              }`}
            >
              {opt}
            </button>
          );
        })}
      </div>
    );
  }

  if (isSensitive && !showSensitive && currentList.length > 0) {
    return (
      <span className='text-sm text-gray-500 dark:text-gray-400 font-mono'>
        {currentList.length} URL{currentList.length !== 1 ? 's' : ''} configured
      </span>
    );
  }

  return (
    <div className='flex flex-col gap-1'>
      <textarea
        value={localValue}
        onChange={e => setLocalValue(e.target.value)}
        onBlur={() => {
          const items = localValue
            .split(/[,\n]/)
            .map(s => s.trim())
            .filter(Boolean);
          onUpdate(setting.key, JSON.stringify(items));
        }}
        placeholder='One per line, or comma-separated'
        rows={Math.max(2, currentList.length)}
        className='w-64 text-sm px-2 py-1 rounded-md border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-gray-100 font-mono resize-y'
      />
    </div>
  );
}
