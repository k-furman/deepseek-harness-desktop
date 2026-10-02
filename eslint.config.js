import js from '@eslint/js';
import ts from 'typescript-eslint';
import globals from 'globals';

export default ts.config(
  js.configs.recommended,
  ...ts.configs.recommended,
  { files: ['**/*.ts'], languageOptions: { globals: { ...globals.browser, ...globals.node } } },
  { ignores: ['dist/**', 'node_modules/**', '.tools/**', 'src-tauri/**', '.agents/**'] },
);
