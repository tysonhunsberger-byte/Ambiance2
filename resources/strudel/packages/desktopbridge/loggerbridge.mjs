import { listen } from '@tauri-apps/api/event';
import { logger } from '../core/logger.mjs';

// Listen for log events from the Tauri backend and log in the UI.
// Avoid top-level await so that the file works in older Chromium builds.
if (typeof listen === 'function') {
  try {
  Promise.resolve(
    listen('log-event', (e) => {
      if (!e || e.payload == null) {
        return;
      }
      const { message, message_type } = e.payload;
      logger(message, message_type);
    })
  ).catch(() => {
    // ignore registration failures
  });
} catch (error) {
  // ignore registration failures
}
}
