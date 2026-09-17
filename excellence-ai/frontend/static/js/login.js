/**
 * login.js — Login page form handling.
 */
(function () {
  const form = document.getElementById('login-form');
  const emailInput = document.getElementById('email');
  const passwordInput = document.getElementById('password');
  const errorMsg = document.getElementById('error-msg');
  const submitBtn = document.getElementById('submit-btn');
  const eyeBtn = document.getElementById('eye-btn');

  if (eyeBtn) {
    eyeBtn.addEventListener('click', () => {
      const isPassword = passwordInput.type === 'password';
      passwordInput.type = isPassword ? 'text' : 'password';
      eyeBtn.innerHTML = isPassword
        ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`
        : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
    });
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = emailInput.value.trim();
      const password = passwordInput.value;

      // Client-side validation
      if (!email) {
        showError('Please enter your email address.');
        return;
      }
      if (password.length < 4) {
        showError('Password must be at least 4 characters.');
        return;
      }

      hideError();
      submitBtn.textContent = 'Signing in...';
      submitBtn.disabled = true;

      try {
        const resp = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ email, password }),
        });

        const data = await resp.json();

        if (resp.ok && data.ok) {
          window.location.href = data.redirect || '/app';
        } else {
          showError(data.detail || 'Login failed. Please try again.');
          submitBtn.textContent = 'Sign In';
          submitBtn.disabled = false;
        }
      } catch (err) {
        showError('Network error. Please check your connection.');
        submitBtn.textContent = 'Sign In';
        submitBtn.disabled = false;
      }
    });
  }

  function showError(msg) {
    if (errorMsg) {
      errorMsg.textContent = msg;
      errorMsg.classList.add('show');
    }
  }

  function hideError() {
    if (errorMsg) errorMsg.classList.remove('show');
  }
})();
