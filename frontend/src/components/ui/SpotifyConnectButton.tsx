import { useMutation, useQuery } from '@apollo/client/react';
import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import {
  GetSystemStatusDocument,
  DisconnectSpotifyDocument,
} from '../../types/generated/graphql';

// Store modal state globally so it persists across component remounts
// This is necessary because the button is rendered in different DOM locations
// based on auth state, causing React to unmount/remount the component
let globalShowModal = false;
let globalModalAction: 'connected' | 'disconnected' = 'connected';
const modalListeners = new Set<() => void>();

function setGlobalModalState(
  show: boolean,
  action?: 'connected' | 'disconnected'
) {
  globalShowModal = show;
  if (action) globalModalAction = action;
  modalListeners.forEach(listener => listener());
}

function useGlobalModalState() {
  const [, forceUpdate] = useState({});

  useEffect(() => {
    const listener = () => forceUpdate({});
    modalListeners.add(listener);
    return () => {
      modalListeners.delete(listener);
    };
  }, []);

  return {
    showModal: globalShowModal,
    modalAction: globalModalAction,
    setShowModal: (show: boolean, action?: 'connected' | 'disconnected') =>
      setGlobalModalState(show, action),
  };
}

function RestartInstructions() {
  const isDev = import.meta.env.DEV;

  if (isDev) {
    return (
      <>
        <div className='bg-gray-100 rounded-md p-3 mb-6 font-mono text-sm text-gray-800'>
          make dev-container-down && make dev-container
        </div>
        <p className='text-sm text-gray-500 mb-6'>
          This ensures the worker processes pick up the new authentication
          state.
        </p>
      </>
    );
  }

  return (
    <>
      <p className='text-gray-600 mb-4'>
        Restart your containers using one of these methods:
      </p>
      <ul className='list-disc list-inside text-sm text-gray-600 mb-4 space-y-1'>
        <li>
          <strong>Docker Compose:</strong>
          <code className='ml-2 bg-gray-100 px-2 py-0.5 rounded text-xs'>
            docker compose down && docker compose up -d
          </code>
        </li>
        <li>
          <strong>Portainer/Dockge:</strong> Restart the stack from your
          dashboard
        </li>
      </ul>
      <p className='text-sm text-gray-500 mb-6'>
        This ensures the worker processes pick up the new authentication state.
      </p>
    </>
  );
}

// Singleton modal component that renders once at app level via portal
// This prevents the white flash caused by unmount/remount during auth state changes
function GlobalRestartModal() {
  const { showModal, modalAction, setShowModal } = useGlobalModalState();

  // Always render the portal container, just toggle visibility
  return createPortal(
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center transition-opacity duration-150 ${
        showModal ? 'opacity-100' : 'opacity-0 pointer-events-none'
      }`}
    >
      {/* Backdrop - no onClick to require explicit dismissal */}
      <div className='fixed inset-0 bg-black bg-opacity-50' />

      {/* Modal */}
      <div className='relative bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6'>
        <div className='flex items-center gap-3 mb-4'>
          <div className='flex-shrink-0 w-10 h-10 bg-amber-100 rounded-full flex items-center justify-center'>
            <svg
              className='w-6 h-6 text-amber-600'
              fill='none'
              stroke='currentColor'
              viewBox='0 0 24 24'
            >
              <path
                strokeLinecap='round'
                strokeLinejoin='round'
                strokeWidth={2}
                d='M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z'
              />
            </svg>
          </div>
          <h3 className='text-lg font-semibold text-gray-900'>
            Restart Required
          </h3>
        </div>

        <p className='text-gray-600 mb-6'>
          {modalAction === 'connected' ? (
            <>
              Your Spotify account has been linked successfully! To apply this
              change, please restart your Docker containers:
            </>
          ) : (
            <>
              Your Spotify account has been disconnected. To apply this change,
              please restart your Docker containers:
            </>
          )}
        </p>

        <RestartInstructions />

        <div className='flex justify-end'>
          <button
            onClick={() => setShowModal(false)}
            className='px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2'
          >
            Got it
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// Mount the global modal once when this module loads
let modalMounted = false;
function ensureGlobalModalMounted() {
  if (modalMounted || typeof document === 'undefined') return;
  modalMounted = true;

  // Create a dedicated container for the modal
  const container = document.createElement('div');
  container.id = 'spotify-restart-modal-root';
  document.body.appendChild(container);

  // Use React 18's createRoot for the singleton modal
  import('react-dom/client').then(({ createRoot }) => {
    const root = createRoot(container);
    root.render(<GlobalRestartModal />);
  });
}

export function SpotifyConnectButton() {
  const [isConnecting, setIsConnecting] = useState(false);
  const { setShowModal } = useGlobalModalState();
  const { data, loading, refetch } = useQuery(GetSystemStatusDocument);
  const [disconnectSpotify] = useMutation(DisconnectSpotifyDocument, {
    onCompleted: () => {
      refetch();
      setShowModal(true, 'disconnected');
    },
  });

  // Ensure the global modal is mounted once
  useEffect(() => {
    ensureGlobalModalMounted();
  }, []);

  const isConnected =
    data?.systemHealth.authentication.spotifyAuthMode === 'user-authenticated';

  const handleConnect = () => {
    setIsConnecting(true);

    // Open OAuth flow in a popup window
    const width = 600;
    const height = 700;
    const left = window.screen.width / 2 - width / 2;
    const top = window.screen.height / 2 - height / 2;

    const popup = window.open(
      '/auth/spotify/authorize',
      'spotify-oauth',
      `width=${width},height=${height},left=${left},top=${top}`
    );

    // Poll for popup closure (OAuth completion)
    const pollTimer = setInterval(() => {
      if (popup?.closed) {
        clearInterval(pollTimer);
        setIsConnecting(false);
        // Refresh to get updated status, then check if newly connected
        refetch().then(result => {
          const nowConnected =
            result.data?.systemHealth.authentication.spotifyAuthMode ===
            'user-authenticated';
          // Show modal if we just connected
          if (nowConnected) {
            setShowModal(true, 'connected');
          }
        });
      }
    }, 500);
  };

  const handleDisconnect = async () => {
    if (confirm('Are you sure you want to disconnect your Spotify account?')) {
      await disconnectSpotify();
    }
  };

  if (loading) {
    return (
      <button
        disabled
        className='px-4 py-2 text-sm font-medium text-gray-400 bg-gray-100 rounded-md cursor-not-allowed'
      >
        Loading...
      </button>
    );
  }

  if (isConnected) {
    return (
      <button
        onClick={handleDisconnect}
        className='px-4 py-2 text-sm font-medium text-red-700 bg-red-50 border border-red-200 rounded-md hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 transition-colors'
      >
        Disconnect
      </button>
    );
  }

  return (
    <button
      onClick={handleConnect}
      disabled={isConnecting}
      className='px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
    >
      {isConnecting ? 'Connecting...' : 'Connect Spotify'}
    </button>
  );
}
