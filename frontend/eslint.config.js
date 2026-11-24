/**
 * ESLint configuration.
 *
 * `package.json` has declared a `lint` script since the project began, but no
 * config file existed, so `npm run lint` failed with "ESLint couldn't find an
 * eslint.config.js" rather than linting anything. A declared command that
 * errors is worse than no command: it reads as a broken project to anyone who
 * runs it.
 *
 * ESLint 9 uses flat config, which is why an `.eslintrc` would not have helped.
 * A legacy `.eslintrc.json` did exist here and was silently ignored by v9. It
 * was removed rather than left in place: a config file that looks
 * authoritative and changes nothing is worse than no config file, because
 * someone will edit it and conclude the linter is broken.
 *
 * The rule set is deliberately modest — correctness and hook-safety rules that
 * catch real bugs, not a style regime. Formatting is not enforced here; it
 * would produce a large diff that reviews as noise and hides anything real.
 */
import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['dist/**', 'coverage/**', 'node_modules/**'] },

  js.configs.recommended,

  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.es2021 },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    settings: { react: { version: '18.3' } },
    plugins: { react, 'react-hooks': reactHooks },
    rules: {
      ...react.configs.flat.recommended.rules,

      // This codebase uses the automatic JSX runtime, so neither of these
      // applies: React is not imported for JSX and the pragma is not in scope.
      'react/react-in-jsx-scope': 'off',
      'react/jsx-uses-react': 'off',

      // Prop types are not used anywhere in the project; enabling this would
      // report every component rather than finding a defect.
      'react/prop-types': 'off',

      // The two that matter. A missing dependency in an effect produces a
      // component that renders stale data with no error anywhere, which is
      // exactly the class of bug that is hard to find by reading.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      // An unused variable is usually a leftover from a change that was not
      // finished. Arguments are exempt: dropping an unused earlier parameter
      // would change a signature.
      'no-unused-vars': ['error', { args: 'none', ignoreRestSiblings: true }],

      // Caught a real defect in this codebase once already: an empty catch
      // that swallowed a failed mutation. Empty blocks must say why.
      'no-empty': ['error', { allowEmptyCatch: false }],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-var': 'error',
      'prefer-const': 'error',
    },
  },

  {
    // Tests read the filesystem and use Node globals.
    files: ['src/test/**/*.{js,jsx}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
]
