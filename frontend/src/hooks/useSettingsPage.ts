import { useMutation, useQuery } from '@apollo/client/react';
import { useCallback, useState } from 'react';

import {
  GetAppSettingsDocument,
  MigrateSettingsFromYamlDocument,
  ResetAppSettingDocument,
  UpdateAppSettingDocument,
  UploadCookieFileDocument,
} from '../types/generated/graphql';
import type {
  AppSettingType,
  SettingsCategoryType,
} from '../types/generated/graphql';

export function useSettingsPage() {
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [cookieContent, setCookieContent] = useState('');
  const [showCookieUpload, setShowCookieUpload] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  const { data, loading, error, refetch } = useQuery(GetAppSettingsDocument, {
    fetchPolicy: 'cache-and-network',
  });

  const [updateSetting] = useMutation(UpdateAppSettingDocument);
  const [resetSetting] = useMutation(ResetAppSettingDocument);
  const [uploadCookieFile] = useMutation(UploadCookieFileDocument);
  const [migrateFromYaml] = useMutation(MigrateSettingsFromYamlDocument);

  const categories: SettingsCategoryType[] = data?.appSettings ?? [];

  const showStatus = useCallback((type: 'success' | 'error', text: string) => {
    setStatusMessage({ type, text });
    setTimeout(() => setStatusMessage(null), 6000);
  }, []);

  const handleUpdateSetting = useCallback(
    async (key: string, value: string) => {
      setPendingKey(key);
      try {
        const { data: result } = await updateSetting({
          variables: { key, value },
        });
        if (result?.updateAppSetting.success) {
          showStatus('success', `${key} updated`);
          await refetch();
        } else {
          showStatus(
            'error',
            result?.updateAppSetting.message ?? 'Update failed'
          );
        }
      } catch {
        showStatus('error', `Failed to update ${key}`);
      } finally {
        setPendingKey(null);
      }
    },
    [updateSetting, refetch, showStatus]
  );

  const handleResetSetting = useCallback(
    async (key: string) => {
      setPendingKey(key);
      try {
        const { data: result } = await resetSetting({
          variables: { key },
        });
        if (result?.resetAppSetting.success) {
          showStatus('success', `${key} reset to default`);
          await refetch();
        } else {
          showStatus(
            'error',
            result?.resetAppSetting.message ?? 'Reset failed'
          );
        }
      } catch {
        showStatus('error', `Failed to reset ${key}`);
      } finally {
        setPendingKey(null);
      }
    },
    [resetSetting, refetch, showStatus]
  );

  const handleUploadCookie = useCallback(async () => {
    if (!cookieContent.trim()) return;
    try {
      const { data: result } = await uploadCookieFile({
        variables: { content: cookieContent },
      });
      if (result?.uploadCookieFile.success) {
        showStatus('success', 'Cookie file uploaded');
        setCookieContent('');
        setShowCookieUpload(false);
      } else {
        showStatus(
          'error',
          result?.uploadCookieFile.message ?? 'Upload failed'
        );
      }
    } catch {
      showStatus('error', 'Failed to upload cookie file');
    }
  }, [cookieContent, uploadCookieFile, showStatus]);

  const handleMigrateYaml = useCallback(async () => {
    try {
      const { data: result } = await migrateFromYaml();
      if (result?.migrateSettingsFromYaml.success) {
        showStatus(
          'success',
          `Migration complete: ${result.migrateSettingsFromYaml.migrated} imported, ${result.migrateSettingsFromYaml.skipped} skipped`
        );
        await refetch();
      } else {
        showStatus(
          'error',
          result?.migrateSettingsFromYaml.message ?? 'Migration failed'
        );
      }
    } catch {
      showStatus('error', 'Failed to migrate settings');
    }
  }, [migrateFromYaml, refetch, showStatus]);

  return {
    categories,
    loading,
    error,
    pendingKey,
    statusMessage,
    cookieContent,
    showCookieUpload,
    setCookieContent,
    setShowCookieUpload,
    handleUpdateSetting,
    handleResetSetting,
    handleUploadCookie,
    handleMigrateYaml,
  };
}

export type { AppSettingType, SettingsCategoryType };
