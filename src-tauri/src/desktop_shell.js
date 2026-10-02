((origin) => {
  if (window.top !== window || window.location.origin !== origin) return;

  const pinShell = () => {
    const root = document.getElementById('root');
    const body = document.body;
    if (!body || root?.parentElement !== body) return false;

    // Harness owns scrolling inside its panels. Only its outer mount is pinned.
    // Property writes also work with a server CSP that forbids inline stylesheets.
    for (const element of [document.documentElement, body, root]) {
      for (const [property, value] of Object.entries({
        width: '100%',
        height: '100%',
        'min-width': '0',
        'min-height': '0',
        'box-sizing': 'border-box',
        margin: '0',
        padding: '0',
        overflow: 'clip',
        'overscroll-behavior': 'none',
      })) element.style.setProperty(property, value, 'important');
    }
    return true;
  };

  if (pinShell()) return;
  // At document start even <html> may not exist yet. Stop watching as soon as
  // the mount is present; chat mutations do not need a permanent observer.
  let watchedBody;
  const watchMount = () => {
    if (pinShell()) {
      observer.disconnect();
    } else if (document.body && document.body !== watchedBody) {
      watchedBody = document.body;
      observer.disconnect();
      // #root must be a direct body child. Do not inspect mutations in nested
      // panels on other same-origin pages that never create a Harness mount.
      observer.observe(document.documentElement, { childList: true });
      observer.observe(watchedBody, { childList: true });
    }
  };
  const observer = new MutationObserver(watchMount);
  observer.observe(document, { childList: true, subtree: true });
  watchMount();
})(__DSH_ORIGIN__);
