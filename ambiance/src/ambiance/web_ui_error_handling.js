/**
 * Enhanced error handling utilities for the Noisetown web UI
 * 
 * This module provides consistent error handling and user feedback
 * for plugin rack operations, including:
 * - Better error message formatting
 * - Retry logic for transient failures
 * - User-friendly error explanations
 */

/**
 * Parse and format error messages from API responses
 * @param {Error|string} error - The error object or message
 * @param {Object} payload - Optional API response payload
 * @returns {string} - Formatted, user-friendly error message
 */
function formatApiError(error, payload = null) {
    // Extract the core error message
    let message = '';
    
    if (payload && payload.error) {
        message = payload.error;
    } else if (payload && payload.status && payload.status.last_error) {
        message = payload.status.last_error;
    } else if (error && error.message) {
        message = error.message;
    } else if (typeof error === 'string') {
        message = error;
    } else {
        message = 'An unknown error occurred';
    }
    
    // Add context for common error patterns
    const errorPatterns = [
        {
            pattern: /PyQt5|qt|QApplication/i,
            context: '\n\n💡 Tip: This is a Qt-related error. Make sure PyQt5 is installed with: pip install PyQt5'
        },
        {
            pattern: /display|DISPLAY|X11|headless/i,
            context: '\n\n💡 Tip: This appears to be a display server issue. Plugin UIs require a graphical environment.'
        },
        {
            pattern: /carla.*not.*found|libcarla/i,
            context: '\n\n💡 Tip: Carla library not found. Make sure Carla is built and the CARLA_ROOT environment variable is set.'
        },
        {
            pattern: /failed to load plugin|plugin.*not found/i,
            context: '\n\n💡 Tip: Check that the plugin file exists and is a valid VST/VST3/AU plugin.'
        },
        {
            pattern: /no plugin hosted/i,
            context: '\n\n💡 Tip: Load a plugin into the host before performing this operation.'
        },
        {
            pattern: /does not.*custom ui|does not.*editor/i,
            context: '\n\n💡 Tip: This plugin doesn\'t provide a native UI. You can still control it via parameters.'
        }
    ];
    
    for (const { pattern, context } of errorPatterns) {
        if (pattern.test(message)) {
            message += context;
            break;
        }
    }
    
    return message;
}

/**
 * Handle API errors with automatic retry for transient failures
 * @param {Function} apiCall - Async function that makes the API call
 * @param {Object} options - Configuration options
 * @returns {Promise} - Result of the API call
 */
async function withRetry(apiCall, options = {}) {
    const {
        maxRetries = 2,
        retryDelay = 1000,
        retryOnStatus = [502, 503, 504],
        onRetry = null,
        operation = 'Operation'
    } = options;
    
    let lastError = null;
    
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            const result = await apiCall();
            return result;
        } catch (error) {
            lastError = error;
            
            // Check if we should retry
            const shouldRetry = attempt < maxRetries && (
                (error.status && retryOnStatus.includes(error.status)) ||
                error.message.includes('Failed to fetch') ||
                error.message.includes('NetworkError')
            );
            
            if (shouldRetry) {
                const waitTime = retryDelay * Math.pow(2, attempt); // Exponential backoff
                if (onRetry) {
                    onRetry(attempt + 1, maxRetries, waitTime);
                }
                await new Promise(resolve => setTimeout(resolve, waitTime));
            } else {
                break;
            }
        }
    }
    
    throw lastError;
}

/**
 * Enhanced fetch wrapper with better error handling
 * @param {string} url - API endpoint
 * @param {Object} options - Fetch options
 * @returns {Promise<Object>} - Parsed JSON response
 */
async function apiFetch(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    };
    
    try {
        const response = await fetch(url, defaultOptions);
        
        // Try to parse JSON even for error responses
        let data;
        try {
            data = await response.json();
        } catch (parseError) {
            // If JSON parsing fails, create a basic error object
            data = {
                ok: false,
                error: `HTTP ${response.status}: ${response.statusText}`,
                status: null
            };
        }
        
        // Check response status
        if (!response.ok) {
            const error = new Error(formatApiError(null, data));
            error.status = response.status;
            error.response = data;
            throw error;
        }
        
        // Check if the API returned an error in the payload
        if (data && data.ok === false) {
            const error = new Error(formatApiError(data.error, data));
            error.response = data;
            throw error;
        }
        
        return data;
    } catch (error) {
        // Network errors or other fetch failures
        if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
            const enhancedError = new Error(
                'Failed to connect to the Ambiance server. ' +
                'Make sure the server is running on the correct port. ' +
                '\n\n💡 Tip: Start the server with: python -m ambiance.server'
            );
            enhancedError.originalError = error;
            throw enhancedError;
        }
        
        // Re-throw if already formatted
        throw error;
    }
}

/**
 * Show a user-friendly error notification
 * @param {string} message - Error message to display
 * @param {Function} log - Optional logging function
 */
function showErrorNotification(message, log = null) {
    // Log to console
    console.error('Plugin Rack Error:', message);
    
    // Log to UI if logger provided
    if (log) {
        log('❌ ' + message);
    }
    
    // Show browser notification if permitted
    if (window.Notification && Notification.permission === 'granted') {
        new Notification('Plugin Rack Error', {
            body: message.split('\n')[0], // Just the first line
            icon: '/static/icon-error.png'
        });
    }
}

/**
 * Validate plugin UI requirements before attempting to show UI
 * @param {Object} status - Host status object
 * @param {Object} plugin - Plugin object
 * @returns {Object} - Validation result with { valid, reason }
 */
function validatePluginUiRequirements(status, plugin) {
    if (!status || !plugin) {
        return {
            valid: false,
            reason: 'No plugin is currently loaded. Load a plugin from the library first.'
        };
    }
    
    if (!status.qt_available) {
        return {
            valid: false,
            reason: 'Qt is not available. Plugin UIs require PyQt5. Install with: pip install PyQt5'
        };
    }
    
    const statusCaps = status.capabilities || {};
    const pluginCaps = plugin.capabilities || {};
    const editorCapable = !!(pluginCaps.editor || statusCaps.editor);
    
    if (!editorCapable) {
        const pluginName = plugin.metadata && plugin.metadata.name ? plugin.metadata.name : 'This plugin';
        return {
            valid: false,
            reason: `${pluginName} does not provide a native UI editor. You can still control it using the parameter sliders below.`
        };
    }
    
    return { valid: true };
}

/**
 * Safe wrapper for operations that modify host state
 * @param {Function} operation - Async function to execute
 * @param {Object} state - State object to update (with .busy property)
 * @param {Function} render - Function to call to update UI
 * @param {Function} log - Logging function
 * @returns {Promise} - Result of the operation
 */
async function withHostStateLock(operation, state, render, log) {
    if (state.busy) {
        log('⏳ Another operation is in progress. Please wait...');
        return;
    }
    
    state.busy = true;
    render();
    
    try {
        const result = await operation();
        return result;
    } catch (error) {
        showErrorNotification(error.message, log);
        throw error;
    } finally {
        state.busy = false;
        render();
    }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        formatApiError,
        withRetry,
        apiFetch,
        showErrorNotification,
        validatePluginUiRequirements,
        withHostStateLock
    };
}

// Also expose globally for inline scripts
if (typeof window !== 'undefined') {
    window.PluginRackErrorHandling = {
        formatApiError,
        withRetry,
        apiFetch,
        showErrorNotification,
        validatePluginUiRequirements,
        withHostStateLock
    };
}
