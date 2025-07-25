// Enforce HTTPS: if the app was opened over http, redirect to https on the same host/path
if (window.location.protocol === 'http:') {
    try {
        const target = 'https://' + window.location.host + window.location.pathname + window.location.search + window.location.hash;
        window.location.replace(target);
    } catch (e) {
        // no-op
    }
}

let currentFqdn = '';
let hideErrorTimerId = null;

function applySuccessfulConnection(displayName) {
    const authContent = document.getElementById('auth-content');
    if (authContent) authContent.style.display = 'flex';

    const connText = document.getElementById('connection-text');
    if (connText) {
        connText.textContent = displayName ? `Connected to ${displayName}` : 'Connected';
    }
}

async function autoConnectToSameOrigin() {
    const connText = document.getElementById('connection-text');

    try {
        const res = await fetch('/api/v4/server');
        if (!res.ok) throw new Error('Bad status: ' + res.status);

        const json = await res.json();
        const displayName = json?.product?.display_name || '';
        currentFqdn = window.location.host;

        applySuccessfulConnection(displayName);

    } catch (e) {
        // Failed to connect — staying on the authorization screen
        if (connText) connText.textContent = 'Not connected';
        if (typeof showError === 'function') {
            showError('Failed to connect to server');
        } else {
            console.error(e);
        }
    }
}

// Инициализация при загрузке
document.addEventListener('DOMContentLoaded', () => {
    autoConnectToSameOrigin();
});

function signIn() {
    const fqdn = currentFqdn || document.getElementById("server-label")?.textContent || '';
    const login = document.getElementById("login").value.trim();
    const password = document.getElementById("password").value;

    if (!fqdn || !login || !password) {
        showError("Please fill in all fields.");
        return;
    }

    const url = `https://${fqdn}/bridge/api/client/v1/oauth/token`;
    const body = {
        client_id: "chat_bot",
        grant_type: "password",
        username: login,
        password: password
    };

    fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
    })
        .then(async response => {
            let data = null;
            try { data = await response.json(); } catch (_) { }

            if (!response.ok) {
                const msg = (data && (data.error_description || data.error || data.reason))
                    || (response.status === 401 ? 'Invalid username or password.' : `Authorization error (HTTP ${response.status}).`);
                const err = new Error(msg);
                err.isHttp = true;
                err.httpStatus = response.status;
                err.httpBody = data;
                throw err;
            }
            return data;
        })
        .then(data => {
            if (data && data.access_token) {
                const tokenInput = document.getElementById("access-token");
                tokenInput.value = data.access_token;
                document.getElementById("token-block").style.display = "block";
                document.getElementById("login").style.display = "none";
                document.getElementById("sign-in-button").style.display = "none";
                document.getElementById("password").style.display = "none";
                const loginLabel = document.querySelector('label[for="login"]');
                const passwordLabel = document.querySelector('label[for="password"]');
                if (loginLabel) loginLabel.style.display = "none";
                if (passwordLabel) passwordLabel.style.display = "none";
            } else {
                const msg = (data && (data.error_description || data.error || data.reason)) || 'Server did not return access_token.';
                showError(msg);
            }
        })
        .catch(err => {
            if (err && err.isHttp) {
                showError(err.message);
                console.error('Auth HTTP error:', err.httpStatus, err.httpBody);
                return;
            }
            showError(err?.message || 'Failed to sign in.');
            console.error(err);
        });
}

function showError(message) {
    const errorDiv = document.getElementById("error-message");
    if (!errorDiv) return;
    errorDiv.textContent = message;
    errorDiv.style.display = "block";
    // Clear previous timer if any
    if (hideErrorTimerId) {
        clearTimeout(hideErrorTimerId);
        hideErrorTimerId = null;
    }
    // Auto-hide after 6s, but keep long enough so user can read
    hideErrorTimerId = setTimeout(() => {
        errorDiv.style.display = "none";
    }, 6000);
    // Ensure visible to the user
    try {
        errorDiv.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (_) { }
}

function copyToken() {
    const tokenInput = document.getElementById("access-token");
    const value = tokenInput.value || '';
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).catch(() => {
            // fallback
            tokenInput.select();
            tokenInput.setSelectionRange(0, value.length);
            document.execCommand("copy");
        });
    } else {
        tokenInput.select();
        tokenInput.setSelectionRange(0, value.length);
        document.execCommand("copy");
    }
}

function downloadToken() {
    const token = document.getElementById("access-token").value;
    const username = document.getElementById("login").value.trim();
    const content = `username = "${username}"\naccess_token = "${token}"`;
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${username}.toml`;
    a.click();
    URL.revokeObjectURL(url);
}

// Глобальный обработчик Enter для перехода между этапами авторизации
document.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
        const authContent = document.getElementById("auth-content");
        if (authContent && authContent.style.display === "flex") {
            signIn();
        }
    }
});