(() => {
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let choice;
  try { choice = localStorage.getItem('rundown-theme'); } catch { /* Storage may be disabled. */ }
  function apply(dark) {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.textContent = dark ? 'Light mode' : 'Dark mode';
      button.setAttribute('aria-pressed', String(dark));
    }
  }
  apply(choice === 'dark' || (choice !== 'light' && system.matches));
  system.addEventListener('change', event => { if (!choice) apply(event.matches); });
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme === 'dark');
    document.getElementById('theme-toggle').onclick = () => {
      choice = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('rundown-theme', choice); } catch { /* Still works this session. */ }
      apply(choice === 'dark');
    };
  });
})();
