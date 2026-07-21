import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import prettierConfig from 'eslint-config-prettier'

export default tseslint.config(
  // Base JS rules
  js.configs.recommended,

  // TypeScript
  ...tseslint.configs.recommended,

  // Vue (uses vue-eslint-parser for .vue files)
  ...pluginVue.configs['flat/recommended'],

  // Prettier (disables formatting rules that conflict)
  prettierConfig,

  // Global settings
  {
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
  },

  // Custom overrides
  {
    files: ['**/*.{ts,vue}'],
    rules: {
      // TypeScript
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/no-non-null-assertion': 'off',

      // Vue
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'off', // We use DOMPurify
      'vue/require-default-prop': 'off',
      'vue/max-attributes-per-line': 'off',
    },
  },

  // Ignore patterns
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      '*.d.ts',
      'src/museum/**', // Legacy Phaser code with @ts-nocheck
      'server/**',
      'public/**',
    ],
  },
)
