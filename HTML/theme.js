(() => {
  const STORAGE_KEY = 'udh-theme';
  const THEMES = ['light', 'dark', 'system'];

  const getStoredTheme = () => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return THEMES.includes(saved) ? saved : 'system';
  };

  const getEffectiveTheme = (theme) => {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return theme;
  };

  const applyTheme = (theme) => {
    const selected = THEMES.includes(theme) ? theme : 'system';
    const effective = getEffectiveTheme(selected);
    document.documentElement.dataset.theme = effective;
    document.documentElement.dataset.themePreference = selected;
  };

  // Apply the saved/system preference as early as possible to avoid a flash.
  applyTheme(getStoredTheme());

  const createThemeSwitcher = () => {
    if (document.getElementById('theme-switcher')) return;

    const switcher = document.createElement('div');
    switcher.id = 'theme-switcher';
    switcher.className = 'theme-switcher';
    switcher.setAttribute('role', 'group');
    switcher.setAttribute('aria-label', 'Theme selection');
    switcher.innerHTML = `
      <button type="button" data-theme-option="light" aria-label="Use light theme">☀️ <span>Light</span></button>
      <button type="button" data-theme-option="dark" aria-label="Use dark theme">🌙 <span>Dark</span></button>
      <button type="button" data-theme-option="system" aria-label="Follow system theme">💻 <span>System</span></button>
    `;

    const updateButtons = () => {
      const preference = document.documentElement.dataset.themePreference || getStoredTheme();
      switcher.querySelectorAll('[data-theme-option]').forEach((button) => {
        const active = button.dataset.themeOption === preference;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
      });
    };

    switcher.addEventListener('click', (event) => {
      const button = event.target.closest('[data-theme-option]');
      if (!button) return;
      const theme = button.dataset.themeOption;
      localStorage.setItem(STORAGE_KEY, theme);
      applyTheme(theme);
      updateButtons();
    });

    document.body.appendChild(switcher);
    updateButtons();

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleSystemChange = () => {
      if ((document.documentElement.dataset.themePreference || getStoredTheme()) === 'system') {
        applyTheme('system');
      }
    };

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleSystemChange);
    } else {
      mediaQuery.addListener(handleSystemChange);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createThemeSwitcher, { once: true });
  } else {
    createThemeSwitcher();
  }
})();
