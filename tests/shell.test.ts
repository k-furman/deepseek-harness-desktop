import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import source from '../src-tauri/src/desktop_shell.js?raw';

const install = (origin = location.origin) =>
  new Function(source.replace('__DSH_ORIGIN__', JSON.stringify(origin)))();
const mutations = async () => { await Promise.resolve(); await Promise.resolve(); };

beforeEach(() => {
  document.documentElement.removeAttribute('style');
  document.body.removeAttribute('style');
  document.body.innerHTML = '<main id="other"><section></section></main>';
});
afterEach(async () => {
  // Disconnect any remaining real observer by satisfying its mount contract.
  document.body.innerHTML = '<div id="root"></div>';
  await mutations();
  vi.restoreAllMocks();
});

it('ignores other origins and nested lookalike mounts', async () => {
  install('https://other.example');
  document.body.innerHTML = '<div id="root"></div>';
  await mutations();
  expect(document.body.style.overflow).toBe('');
  document.body.innerHTML = '<main><div id="root"></div></main>';
  install();
  await mutations();
  expect(document.querySelector<HTMLElement>('#root')!.style.overflow).toBe('');
});

it('watches only body children, pins a delayed mount and disconnects afterwards', async () => {
  const observe = vi.spyOn(MutationObserver.prototype, 'observe');
  const disconnect = vi.spyOn(MutationObserver.prototype, 'disconnect');
  install();
  expect(observe).toHaveBeenLastCalledWith(document.body, { childList: true });
  const calls = observe.mock.calls.length;
  document.querySelector('section')!.append(document.createElement('span'));
  await mutations();
  expect(observe.mock.calls).toHaveLength(calls);
  const root = document.createElement('div');
  root.id = 'root';
  root.innerHTML = '<section style="overflow:auto"></section>';
  document.body.append(root);
  await mutations();
  for (const element of [document.documentElement, document.body, root]) {
    expect(element.style.overflow).toBe('clip');
  }
  expect(root.firstElementChild?.getAttribute('style')).toBe('overflow:auto');
  const stopped = disconnect.mock.calls.length;
  root.append(document.createElement('p'));
  await mutations();
  expect(disconnect.mock.calls).toHaveLength(stopped);
});

it('follows a replacement body while still waiting for the mount', async () => {
  install();
  const body = document.createElement('body');
  document.body.replaceWith(body);
  await mutations();
  body.innerHTML = '<div id="root"></div>';
  await mutations();
  expect(document.querySelector<HTMLElement>('#root')!.style.overflow).toBe('clip');
});
