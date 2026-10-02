import { beforeEach, describe, expect, it } from 'vitest';
import { renderSnapshot } from '../src/view';
import { errorMessage } from '../src/ipc';

beforeEach(() => {
  document.body.innerHTML = '<form><input id="server-url"><button id="connect"></button><button id="cancel"></button></form><div id="status"></div>';
});

describe('connection screen', () => {
  it('clears the launch token and allows cancellation while connecting', () => {
    document.querySelector<HTMLInputElement>('input')!.value = 'localhost:3000/?token=private';
    renderSnapshot({ phase: 'connecting', lastUrl: 'http://localhost:3000/', error: null, language: 'ru' });
    expect(document.querySelector<HTMLInputElement>('input')!.value).not.toContain('private');
    expect(document.querySelector<HTMLButtonElement>('#connect')!.disabled).toBe(true);
    expect(document.querySelector<HTMLButtonElement>('#cancel')!.hidden).toBe(false);
  });
  it('renders an error as text and enables retry', () => {
    renderSnapshot({ phase: 'error', lastUrl: 'http://localhost:3000/', error: 'network', language: 'en' });
    expect(document.querySelector('#status')!.textContent).toContain('container');
    expect(document.querySelector('#status script')).toBeNull();
    expect(document.querySelector<HTMLButtonElement>('#connect')!.disabled).toBe(false);
  });
  it('never reflects unexpected native errors containing secrets', () => {
    expect(errorMessage('request to http://localhost:3000/?token=private')).not.toContain('private');
    expect(errorMessage(new Error('private'))).not.toContain('private');
    expect(errorMessage('<script>private</script>')).not.toContain('private');
  });
  it('changes language without discarding an address still being typed', () => {
    const input = document.querySelector<HTMLInputElement>('input')!;
    input.value = 'localhost:3000/?token=not-submitted';
    renderSnapshot({ phase: 'idle', lastUrl: '', error: null, language: 'en' }, document, false);
    expect(input.value).toContain('not-submitted');
    expect(document.documentElement.lang).toBe('en');
    expect(document.querySelector('#connect')!.textContent).toBe('Connect');
  });
});
